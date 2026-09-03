"""Stage 4a - normalise sections and atlas plates into a common frame.

Adopted from BrainJ (Hammond, Cellular Imaging Platform), whose second pipeline
step centres each section, rotates it horizontal, and removes surrounding tissue
and debris *before* any analysis. See REFERENCES.md.

Why this comes first: `04b_atlas_match.py` was comparing raw hand-drawn scan
regions against arbitrarily cropped atlas plates. Position, scale, rotation and
debris were all free parameters, which is why it needed an eight-way orientation
search at all - and why the search returned nothing useful until the silhouettes
themselves were fixed. Normalising removes those parameters instead of searching
over them.

Each image is reduced to a tissue mask, then:

  1. **debris removed**    - components below a fraction of the largest are dropped,
                             so a fleck of tissue cannot drag the centroid or the axis
  2. **rotated horizontal** - by the principal axis of the mask, so the section's long
                             axis lies along x regardless of how it was mounted
  3. **centred and cropped** - to the tissue bounding box, then padded square
  4. **rescaled**           - to a fixed grid

Step 2 has a 180 degree ambiguity: the principal axis gives an orientation, not a
direction. That is resolved by making the heavier half consistently the same
side, which is stable for a shape with any dorsoventral asymmetry.

Left-right mirroring is *not* resolved here and deliberately so. Free-floating
sections land face up or face down, and a bilaterally near-symmetric section
carries almost no shape evidence of which. BrainJ makes flipping a separate
manual step for the same reason; here it is carried as an explicit per-section
hypothesis into matching (04b) and the curator.

Run:  python 04a_reformat.py
      python 04a_reformat.py --preview 12
"""

import argparse
import csv
import importlib.util
import json
import os

import numpy as np
from PIL import Image
from scipy import ndimage

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
PLATE_DIR = os.path.join(OUT_ROOT, "atlas", "plates")
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")

GRID = 256                  # normalised output is GRID x GRID
MIN_COMPONENT_FRACTION = 0.12   # debris threshold, relative to the largest component
WORK_SIZE = 400             # analysis resolution; output is resampled from the source


def otsu(values):
    hist, edges = np.histogram(values, bins=256)
    hist = hist.astype(np.float64)
    centres = (edges[:-1] + edges[1:]) / 2.0
    w1, w2 = np.cumsum(hist), np.cumsum(hist[::-1])[::-1]
    valid = (w1 > 0) & (w2 > 0)
    m1 = np.cumsum(hist * centres) / np.maximum(w1, 1e-9)
    m2 = (np.cumsum((hist * centres)[::-1]) / np.maximum(w2[::-1], 1e-9))[::-1]
    var = w1 * w2 * (m1 - m2) ** 2
    var[~valid] = -1
    return float(centres[int(np.argmax(var))])


def tissue_mask(v, light_background):
    """Binary tissue mask.

    Two polarities, two thresholds. Using one rule for both is what produced
    rim-only plates and speckle-only sections in the first attempt.

    **Atlas plates now arrive here already inverted** (see `reformat(invert=...)`),
    so they take the dark-background branch exactly like a section. The
    light-background branch is kept for any source that is genuinely dark tissue
    on light paper, but nothing in the pipeline uses it any more.
    """
    if light_background:
        mask = v < np.percentile(v, 90) * 0.92
    else:
        positive = v[v > 0]
        if positive.size < 200:
            return None
        mask = v > float(np.expm1(otsu(np.log1p(positive))))

    mask = ndimage.binary_closing(mask, np.ones((7, 7)))
    mask = ndimage.binary_fill_holes(mask)
    mask = ndimage.binary_opening(mask, np.ones((3, 3)))

    labels, n = ndimage.label(mask)
    if n == 0:
        return None
    sizes = np.array(ndimage.sum(mask, labels, range(1, n + 1)))
    keep = np.where(sizes >= MIN_COMPONENT_FRACTION * sizes.max())[0] + 1
    mask = np.isin(labels, keep)
    return mask if mask.sum() >= 200 else None


def principal_angle(mask):
    """Angle of the mask's long axis, in degrees.

    Second central moments give the orientation of the best-fitting ellipse.
    Rotating by its negative puts the long axis along x.
    """
    ys, xs = np.nonzero(mask)
    y, x = ys - ys.mean(), xs - xs.mean()
    cov = np.cov(np.vstack([x, y]))
    evals, evecs = np.linalg.eigh(cov)
    major = evecs[:, int(np.argmax(evals))]
    return float(np.degrees(np.arctan2(major[1], major[0])))


def resolve_180(mask):
    """Decide between an orientation and its 180 degree twin.

    The principal axis is an axis, not a direction. Fixing it by putting the
    heavier half consistently on the same side is stable for any shape with
    dorsoventral asymmetry, and harmless for one without.
    """
    h = mask.shape[0]
    return mask[: h // 2].sum() < mask[h // 2:].sum()


def load_censor(uid, shape):
    """04j's right-censored mask. Carried through the geometry, never blanked."""
    p = os.path.join(OUT_ROOT, "censor", uid + "_censor.png")
    if not os.path.exists(p):
        return None
    return np.asarray(Image.open(p).resize(shape, Image.NEAREST)) > 127


def load_artifact(uid, shape):
    """04g's artifact mask, resized to the analysis grid. None when absent."""
    p = os.path.join(OUT_ROOT, "artifacts", uid + "_artifact.png")
    if not os.path.exists(p):
        return None
    a = Image.open(p).resize(shape, Image.NEAREST)
    return np.asarray(a) > 0


def _stretch_to_grid(pi, pm, pa, grid=GRID):
    """Robust in-tissue stretch, then resize to GRID. See the note below.

    Pulled out of `reformat` so a companion channel is stretched by exactly the
    same rule as the geometry channel rather than a second copy of it that can
    drift.
    """
    # Stretch on a ROBUST range of in-tissue pixels: median +/- multiples of the
    # MAD, not min/max and not percentiles.
    #
    # Two earlier attempts failed here. min/max let one saturated pixel set the
    # top. Switching to the 1st/99th percentile was not enough either: debris
    # flecks routinely exceed 1% of the mask, so p99 still landed on them and
    # tissue rendered at an in-mask mean of 8 out of 255 - which is why sections
    # containing perfectly good tissue looked blank. Measured on the same
    # sections, this gives ~80.
    #
    # MAD is outlier-resistant by construction, so it does not care what
    # fraction of the mask the specks occupy.
    # Artifact pixels are excluded from the stretch statistics as well as being
    # blanked. They are the brightest pixels in the section by construction, so
    # leaving them in the median and MAD would darken the real tissue - which is
    # the same failure that made sections look blank three attempts ago.
    inside = pi[pm & ~pa]
    if inside.size > 50:
        med = float(np.median(inside))
        mad = float(np.median(np.abs(inside - med))) * 1.4826
        if mad <= 0:
            mad = max(float(inside.std()), 1.0)
        lo, hi = med - mad, med + 4.0 * mad
    else:
        lo, hi = float(pi.min()), float(pi.max())
    norm = np.clip((pi - lo) / max(hi - lo, 1e-6), 0, 1) * 255.0
    norm[~pm] = 0
    norm[pa] = 0
    return np.asarray(Image.fromarray(norm.astype(np.uint8)).resize((grid, grid), Image.BILINEAR))


def reformat(path, light_background, extra_angle=0.0, flip=False, artifact=None,
             censor=None, invert=False, companion=None, render_scale=1,
             report=None):
    """Return (normalised grayscale, normalised mask, angle applied).

    `companion` is a second image - the marker channel - carried through the
    *same* rotation, flip, crop, pad and resize as `path`. It takes no part in
    deciding the geometry: the mask and the angle come from `path` alone, which
    is DAPI for a section, because the marker channel is a sparse signal and a
    poor silhouette. Passing it appends a sixth element to the return; omitting
    it leaves the return exactly five long, as every existing caller expects.

    `report`, if given a dict, is filled with the geometry this call applied:
    source size, working grid, angle, flip, crop origin, pad offsets and output
    grid. That is everything needed to map a point in the normalised output back
    to a pixel of the source overview, which is how an ROI drawn on the 256 grid
    becomes a rectangle in the CZI (see 05a_roi_geometry.py).

    It is an OUT parameter rather than an extra return value because the return
    is already 5 or 6 elements depending on `companion`, and every caller unpacks
    it positionally; making the length depend on two independent flags is how
    that starts going wrong. Callers that pass nothing see no change.

    The numbers must come from the run that produced the image the operator
    annotated. The mask decides the angle, the angle decides the crop, so
    recomputing any of them separately would move every ROI on the section.

    `extra_angle` is the curator's manual correction, in degrees. It is folded
    into the automatic angle and applied in the SAME rotation, for two reasons.

    Interpolating twice would blur the image for no gain; more importantly, the
    curator allows any angle, and rotating an already-cropped square frame by,
    say, 40 degrees pushes the corners of the tissue outside it. Rotating before
    the crop means the bounding box is recomputed afterwards and nothing is ever
    clipped. The manual angle is added *after* the 180 degree resolution below,
    so a manual 180 is not silently cancelled by the automatic one.
    """
    try:
        img = Image.open(path).convert("L")
    except OSError:
        return None
    src_w, src_h = img.size
    work = np.asarray(img.resize((WORK_SIZE, WORK_SIZE), Image.BILINEAR)).astype(np.float32)
    comp = None
    if companion is not None:
        try:
            cim = Image.open(companion).convert("L")
        except OSError:
            return None
        comp = np.asarray(cim.resize((WORK_SIZE, WORK_SIZE), Image.BILINEAR)).astype(np.float32)
    # Invert BEFORE anything else, so an atlas plate ends up in the same polarity
    # as a DAPI section: cell-dense bright, fibre tracts and ventricles dark,
    # background black. Doing it afterwards is not equivalent - the intensity
    # stretch below is asymmetric (median - MAD to median + 4 MAD), so applied to
    # the wrong polarity it clips away exactly the cell-density detail that makes
    # the plate comparable to a section.
    if invert:
        work = 255.0 - work

    mask = tissue_mask(work, light_background)
    if mask is None:
        return None

    angle = principal_angle(mask)
    # The 180 decision needs the rotated mask, so rotate the mask alone first -
    # order=0 on a binary array is cheap. The image is rotated once, afterwards,
    # by the final combined angle.
    probe = ndimage.rotate(mask.astype(np.uint8), angle, order=0, reshape=True) > 0
    if probe.sum() < 100:
        return None
    if resolve_180(probe):
        angle += 180.0
    angle += extra_angle

    # `render_scale` changes only how finely this frame is SAMPLED. The mask, the
    # angle and therefore the crop are all decided above at WORK_SIZE and are not
    # recomputed, so the output is the same picture at a higher resolution rather
    # than a slightly different one - which matters because a landmark placed on
    # it has to mean the same thing. Raising WORK_SIZE instead would change the
    # mask, and with it the angle and the bounding box.
    S = int(render_scale)
    work_size = WORK_SIZE * S
    if S > 1:
        big = WORK_SIZE * S
        work = np.asarray(img.resize((big, big), Image.BILINEAR)).astype(np.float32)
        if invert:
            work = 255.0 - work
        if comp is not None:
            comp = np.asarray(cim.resize((big, big), Image.BILINEAR)).astype(np.float32)
        def _up(a):
            return np.asarray(Image.fromarray(a.astype(np.uint8) * 255)
                              .resize((big, big), Image.NEAREST)) > 127
        mask = _up(mask)
        if artifact is not None:
            artifact = _up(artifact)
        if censor is not None:
            censor = _up(censor)

    rot_mask = ndimage.rotate(mask.astype(np.uint8), angle, order=0, reshape=True) > 0
    rot_img = ndimage.rotate(work, angle, order=1, reshape=True)
    rot_comp = (ndimage.rotate(comp, angle, order=1, reshape=True)
                if comp is not None else None)
    if rot_mask.sum() < 100:
        return None
    # The artifact mask rides the SAME geometry, so it stays registered to the
    # image through rotation, crop and resize.
    rot_art = (ndimage.rotate(artifact.astype(np.uint8), angle, order=0, reshape=True) > 0
               if artifact is not None else None)
    # Censored pixels ride the same geometry but are NEVER blanked: a clipped
    # pixel is real signal whose value is lost, not an artifact to remove. See
    # 04j_censor_clipped.py.
    rot_cen = (ndimage.rotate(censor.astype(np.uint8), angle, order=0, reshape=True) > 0
               if censor is not None else None)
    if flip:
        rot_mask, rot_img = rot_mask[:, ::-1], rot_img[:, ::-1]
        if rot_comp is not None:
            rot_comp = rot_comp[:, ::-1]
        if rot_art is not None:
            rot_art = rot_art[:, ::-1]
        if rot_cen is not None:
            rot_cen = rot_cen[:, ::-1]

    ys, xs = np.nonzero(rot_mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop_m = rot_mask[y0:y1, x0:x1]
    crop_i = np.where(rot_mask, rot_img, 0.0)[y0:y1, x0:x1]
    crop_p = (np.where(rot_mask, rot_comp, 0.0)[y0:y1, x0:x1]
              if rot_comp is not None else None)
    crop_a = rot_art[y0:y1, x0:x1] if rot_art is not None else None
    crop_c = rot_cen[y0:y1, x0:x1] if rot_cen is not None else None

    # Square-pad rather than stretch, so aspect - which is real shape
    # information - survives the resize.
    h, w = crop_m.shape
    side = max(h, w)
    pm = np.zeros((side, side), bool)
    pi = np.zeros((side, side), np.float32)
    pa = np.zeros((side, side), bool)
    pc = np.zeros((side, side), bool)
    oy, ox = (side - h) // 2, (side - w) // 2
    pm[oy:oy + h, ox:ox + w] = crop_m
    pi[oy:oy + h, ox:ox + w] = crop_i
    pp = None
    if crop_p is not None:
        pp = np.zeros((side, side), np.float32)
        pp[oy:oy + h, ox:ox + w] = crop_p
    if crop_a is not None:
        pa[oy:oy + h, ox:ox + w] = crop_a
    if crop_c is not None:
        pc[oy:oy + h, ox:ox + w] = crop_c

    grid = GRID * S
    if report is not None:
        # The forward chain, in order. Composed and inverted by 05a.
        #
        # Note src_w/src_h separately: the resize to a SQUARE working grid is
        # anisotropic whenever the scan box is not square, which it rarely is.
        # A circle drawn on the output is therefore an ellipse on the slide, and
        # anything that carries a single radius forward is wrong.
        report.update({
            "src_w": int(src_w), "src_h": int(src_h),
            "work_size": int(work_size),
            "angle": float(angle % 360.0),
            "flip": bool(flip),
            "rot_h": int(rot_mask.shape[0]), "rot_w": int(rot_mask.shape[1]),
            "x0": int(x0), "y0": int(y0),
            "crop_w": int(w), "crop_h": int(h),
            "side": int(side), "ox": int(ox), "oy": int(oy),
            "grid": int(grid),
        })
    out_m = np.asarray(Image.fromarray(pm.astype(np.uint8) * 255).resize((grid, grid), Image.BILINEAR)) > 127

    out_i = _stretch_to_grid(pi, pm, pa, grid)
    out_p = _stretch_to_grid(pp, pm, pa, grid) if pp is not None else None
    # The tissue mask is deliberately NOT reduced by the artifact mask. It is the
    # section's silhouette, used for orientation and matching, and punching holes
    # in it would change the shape those depend on. What is masked is the
    # measurement and the picture, not the outline.
    out_a = np.asarray(Image.fromarray(pa.astype(np.uint8) * 255)
                       .resize((grid, grid), Image.NEAREST)) > 127
    # Blank AFTER the resize as well as before it. The image is downsampled
    # bilinearly, which smears bright neighbours back into the hole - measured at
    # up to full intensity on a 190 px artifact. Zeroing before the resize alone
    # leaves the artifact faintly visible in exactly the place it was removed.
    out_i = np.where(out_a, 0, out_i).astype(np.uint8)
    out_c = np.asarray(Image.fromarray(pc.astype(np.uint8) * 255)
                       .resize((grid, grid), Image.NEAREST)) > 127
    if out_p is None:
        return out_i, out_m, angle % 360.0, out_a, out_c
    # Same post-resize blanking as the geometry channel, for the same reason:
    # the bilinear downsample smears a bright artifact back into the hole.
    out_p = np.where(out_a, 0, out_p).astype(np.uint8)
    return out_i, out_m, angle % 360.0, out_a, out_c, out_p


def marker_paths(marker):
    """Per-marker output paths and override source.

    The two markers are separate acquisitions of the same sections, so they get
    separate index files and separate section directories. Scene uids differ
    anyway (`..._s03b_...` vs `..._s03a_...`), but sharing an index would let one
    run silently overwrite the other's.
    """
    if marker == "AF488":
        return {"overrides": os.path.join(REFORMAT_DIR, "rotation_overrides.csv"),
                "uid_col": "scene_uid",
                "sections": os.path.join(REFORMAT_DIR, "sections"),
                "index": os.path.join(REFORMAT_DIR, "reformat_index.csv"),
                "excluded": os.path.join(REFORMAT_DIR, "excluded_sections.csv"),
                "lost": os.path.join(REFORMAT_DIR, "lost_sections.csv")}
    return {"overrides": os.path.join(REFORMAT_DIR, f"perk_overrides.csv"),
            # 04i writes the pERK scene under its own column name.
            "uid_col": "perk_scene_uid",
            "sections": os.path.join(REFORMAT_DIR, f"sections_{marker}"),
            "index": os.path.join(REFORMAT_DIR, f"reformat_index_{marker}.csv"),
            "excluded": os.path.join(REFORMAT_DIR, f"excluded_sections_{marker}.csv"),
            "lost": os.path.join(REFORMAT_DIR, f"lost_sections_{marker}.csv")}


REVIEW_CSV = os.path.join(REFORMAT_DIR, "section_review.csv")


def apply_review(excluded, marker):
    """Merge `section_review.csv` - the Review mode's decisions - over the
    exclusion list, and collect the sections whose artifact mask was rejected.

    **A separate file, MERGED, rather than a rewritten override file.** The
    Review mode runs in a browser and can only download; having it write
    `perk_overrides.csv` directly would mean a page that knows about the handful
    of sections someone reviewed overwriting a file that carries hand-entered
    rotations for 1,134. One bad export would destroy work that cannot be
    recovered. So it writes only its own decisions and this merges them.

    Reinstating is not a new concept: `load_overrides` already reads and counts
    `decision="restored"`. This applies the same idea from the other file.

    Returns (excluded, mask_rejected). `excluded` is a new dict; the caller's is
    not mutated.
    """
    if not os.path.exists(REVIEW_CSV):
        return excluded, set()
    out, rejected = dict(excluded), set()
    restored = dropped = 0
    with open(REVIEW_CSV, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            uid = r.get("scene_uid", "")
            # Rows for the other marker belong to the other run's index and
            # would never match a section here; skipping them keeps the counts
            # honest rather than reporting decisions this run did not apply.
            if not uid or (r.get("marker") and r["marker"] != marker):
                continue
            if r.get("mask_rejected") == "1":
                rejected.add(uid)
            if (r.get("decision") or "") == "restored":
                if out.pop(uid, None) is not None:
                    restored += 1
            elif r.get("excluded") == "1":
                out[uid] = ("manual", r.get("reason") or "excluded on review")
                dropped += 1
    if restored or dropped or rejected:
        print(f"section_review.csv: {restored} reinstated, {dropped} dropped, "
              f"{len(rejected)} mask(s) rejected")
    return out, rejected


def load_overrides(paths=None, write=False):
    """Manual rotation corrections from 04d_rotation_curator.py.

    Stored as a correction *on top of* the automatic angle rather than as an
    absolute orientation, so improving the auto-rotation later does not
    invalidate the manual work.
    """
    paths = paths or marker_paths("AF488")
    path, uid_col = paths["overrides"], paths["uid_col"]
    if not os.path.exists(path):
        return {}, {}
    out, excluded = {}, {}
    for r in csv.DictReader(open(path, newline="", encoding="utf-8")):
        if r.get("excluded") == "1":
            excluded[r[uid_col]] = (r.get("decision") or "manual",
                                        r.get("reason") or "too damaged to measure")
            continue
        # float, not int: the curator rotates freely to 1 degree, and an earlier
        # version of this loader floored everything to a multiple of 90 - which
        # would have thrown away the manual work silently.
        rot, flip = float(r["extra_rotation"] or 0), r["flip"] == "1"
        if rot or flip:
            out[r[uid_col]] = (rot, flip)

    n_auto = sum(1 for d, _ in excluded.values() if d == "auto")
    n_manual = len(excluded) - n_auto
    print(f"loaded {len(out)} rotation override(s), {len(excluded)} exclusion(s) "
          f"({n_auto} auto-accepted, {n_manual} manual)")

    # How often the 04f proposal was overruled. This is the honest measure of
    # whether the automatic rule is set in the right place, and it costs nothing
    # to report - so it gets reported rather than assumed.
    restored = sum(1 for r in csv.DictReader(open(path, newline="", encoding="utf-8"))
                   if (r.get("decision") or "") == "restored")
    if restored:
        prop = n_auto + restored
        print(f"  {restored} of {prop} automatic proposals were overruled "
              f"({100 * restored / prop:.0f}%) - see LOGS.md if that rate is high")

    # The canonical list is written by main(), AFTER apply_review() has merged
    # section_review.csv over this - writing it here published a list that
    # never carried a Review-mode drop or reinstatement, and every caller of
    # this loader (04o builds composites) rewrote it. `write=True` is for a
    # caller that has no review to merge and wants the old behaviour.
    if write:
        write_excluded(paths["excluded"], excluded)
    return out, excluded


def write_excluded(path, excluded):
    """`excluded_sections*.csv`: the canonical exclusion list, one row per
    section, so any stage can honour it without parsing a curator export.
    Header-only when there is nothing to exclude: an absent file reads as
    "never computed", which is a different fact."""
    rows = [{"scene_uid": uid, "decision": excluded[uid][0], "reason": excluded[uid][1]}
            for uid in sorted(excluded)]
    IO.atomic_write_csv(path, rows, ["scene_uid", "decision", "reason"])


def wants_masks(is_excl, mask_artifacts, censor, mask_rejected, uid):
    """(use artifact mask, use censor mask) for one section.

    An excluded section is rendered RAW whatever the flags say. 04o builds its
    composite unmasked - the blue plane has to equal this picture - and a
    section on screen so somebody can decide whether to reinstate it cannot
    be judged with the artifact already painted black.
    """
    if is_excl:
        return False, False
    return (mask_artifacts and uid not in mask_rejected), censor


def select_only(spec, excluded):
    """The uids a `--only` run may touch, or raise.

    A PARTIAL RUN REPAIRS PICTURES AND NOTHING ELSE. The index is written from
    the rows a full pass builds, so `--only` writes none - and this guard is
    what makes that safe rather than merely true. Re-rendering an INDEXED
    section without rewriting its row would leave the analysis pointing at an
    image that no longer matches the angle and fill recorded for it, and nothing
    downstream could detect that. An excluded section has no row to disagree
    with, so those are the only ones this can touch.

    `spec` is a comma-separated list, or "@path" for one uid per line.
    """
    if spec.startswith("@"):
        with open(spec[1:], encoding="utf-8") as fh:
            want = {ln.strip() for ln in fh if ln.strip()}
    else:
        want = {u.strip() for u in spec.split(",") if u.strip()}
    if not want:
        raise SystemExit("--only was given no scene_uids")
    indexed = want - set(excluded)
    if indexed:
        raise SystemExit(
            "--only refuses %d section(s) that are not excluded, because a "
            "partial run writes no index and their rows would go stale: %s"
            % (len(indexed), ", ".join(sorted(indexed)[:10])))
    return want


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=int, default=8)
    ap.add_argument("--marker", default="AF488", choices=["AF488", "AF568"],
                    help="AF488 = PCNA (default), AF568 = pERK")
    ap.add_argument("--censor", action="store_true",
                    help="carry 04j clipped-pixel censor masks through the geometry")
    ap.add_argument("--mask-artifacts", action="store_true",
                    help="blank 04g artifact pixels in the reformatted output")
    ap.add_argument("--apply-overrides", action="store_true",
                    help="apply manual rotations from rotation_overrides.csv")
    ap.add_argument("--render-excluded", action="store_true",
                    help="also render excluded sections, so they can be LOOKED at "
                         "in the ROI curator's Review mode. They are never added "
                         "to the index, so nothing downstream can pick them up.")
    ap.add_argument("--only", metavar="UIDS",
                    help="re-render just these scene_uids (comma-separated, or @file "
                         "for one per line) and write NO index. Every uid must be an "
                         "excluded one: a partial run cannot produce a complete "
                         "index, and re-rendering an INDEXED section without "
                         "rewriting the index would leave the analysis pointing at "
                         "an image that no longer matches its row. Repairs the "
                         "look-at-only PNGs, nothing else")
    args = ap.parse_args()
    paths = marker_paths(args.marker)
    overrides, excluded = load_overrides(paths) if args.apply_overrides else ({}, {})
    mask_rejected = set()
    if args.apply_overrides:
        excluded, mask_rejected = apply_review(excluded, args.marker)
        # After the merge, unconditionally: header-only means "nothing excluded".
        write_excluded(paths["excluded"], excluded)

    sec_dir = paths["sections"]
    plate_dir = os.path.join(REFORMAT_DIR, "plates")
    os.makedirs(sec_dir, exist_ok=True)
    os.makedirs(plate_dir, exist_ok=True)

    rows = []

    with open(os.path.join(PLATE_DIR, "plates.csv"), newline="", encoding="utf-8") as fh:
        plates = list(csv.DictReader(fh))
    ok = 0
    # A --only run repairs section pictures; the plates are not sections and
    # rewriting them would be a side effect nobody asked for, even though the
    # bytes would come out the same.
    if args.only:
        plates = []
    for p in plates:
        # Plates are Nissl - cell bodies DARK on white paper - so they are
        # inverted into DAPI polarity and then treated by the dark-background
        # branch, exactly like a section.
        out = reformat(os.path.join(PLATE_DIR, p["image_file"]),
                       light_background=False, invert=True)
        if out is None:
            continue
        img, mask, angle, _, _ = out
        Image.fromarray(img).save(os.path.join(plate_dir, p["plate_id"] + ".png"))
        np.save(os.path.join(plate_dir, p["plate_id"] + "_mask.npy"), mask)
        rows.append({"kind": "plate", "id": p["plate_id"], "angle": round(angle, 1),
                     "fill": round(float(mask.mean()), 4), "regions": p["regions"]})
        ok += 1
    print(f"plates reformatted: {ok}/{len(plates)}")

    with open(QC_CSV, newline="", encoding="utf-8") as fh:
        secs = [r for r in csv.DictReader(fh) if r["marker_channel"] == args.marker]

    # A PARTIAL RUN REPAIRS PICTURES AND NOTHING ELSE.
    #
    # The index is written from `rows`, which a partial run only half fills, so
    # --only must not reach it - and the guard below is what makes that safe
    # rather than merely true. Re-rendering an INDEXED section without rewriting
    # its row would leave the analysis pointing at an image that no longer
    # matches the angle and fill recorded for it, which nothing downstream could
    # detect. Excluded sections have no row to disagree with, so they are the
    # only ones this can touch.
    if args.only:
        want = select_only(args.only, excluded)
        secs = [r for r in secs if r["scene_uid"] in want]
        gone = want - {r["scene_uid"] for r in secs}
        if gone:
            print("--only: %d uid(s) not in %s for this marker, skipped: %s"
                  % (len(gone), os.path.basename(QC_CSV), ", ".join(sorted(gone)[:5])))
        print(f"--only: re-rendering {len(secs)} excluded section(s), no index write")
        args.render_excluded = True
    ok = 0
    n_excluded = 0
    n_rendered = 0
    lost = []
    no_mask = []
    for i, r in enumerate(secs):
        # Excluded sections are kept out of the INDEX rather than filtered
        # later, so nothing downstream can accidentally pick them up.
        #
        # Whether their image is rendered at all is a separate question, and it
        # used to be answered by accident. PCNA was reformatted and excluded
        # afterwards, so all 1,381 have a PNG; pERK exclusions were applied
        # first, so 473 have none - which left the Review mode able to show an
        # excluded PCNA section in the analysis frame and an excluded pERK one
        # only as the original scan. Same pipeline, different order, and the
        # asymmetry fell entirely on one channel.
        #
        # --render-excluded renders them too. It never adds an index row, so
        # nothing downstream can pick them up either way: the image exists to be
        # LOOKED AT, and being in reformatted/ has never been what puts a
        # section into the analysis.
        is_excl = r["scene_uid"] in excluded
        if is_excl:
            n_excluded += 1
            if not args.render_excluded:
                continue
        src = os.path.join(OVERVIEW_DIR, r["animal"], r["marker_channel"],
                           r["scene_uid"] + "_DAPI.png")
        # A section that was NOT excluded must survive, or it must be reported.
        # Both of these used to be silent `continue`s, so a missing overview or a
        # failed mask removed a section from the analysis with no record at all -
        # indistinguishable from a deliberate exclusion.
        if not os.path.exists(src):
            lost.append((r["scene_uid"], "overview PNG missing"))
            continue
        extra, flip = overrides.get(r["scene_uid"], (0.0, False))
        # A rejected mask means this section reformats UNMASKED even with
        # --mask-artifacts on. The mask file is left alone, so the decision is
        # reversible by deleting one row of section_review.csv.
        use_art, use_cen = wants_masks(is_excl, args.mask_artifacts, args.censor,
                                       mask_rejected, r["scene_uid"])
        art = load_artifact(r["scene_uid"], (WORK_SIZE, WORK_SIZE)) if use_art else None
        cen = load_censor(r["scene_uid"], (WORK_SIZE, WORK_SIZE)) if use_cen else None
        # "no mask was built for this section" and "its mask was rejected on
        # review" are different facts, and reporting the second as the first
        # would read as a gap in 04g rather than as a decision someone made.
        if (args.mask_artifacts and art is None and not is_excl
                and r["scene_uid"] not in mask_rejected):
            no_mask.append(r["scene_uid"])
        out = reformat(src, light_background=False, extra_angle=extra, flip=flip,
                       artifact=art, censor=cen)
        if out is None:
            lost.append((r["scene_uid"], "no tissue mask could be formed"))
            continue
        img, mask, angle, amask, cmask = out
        Image.fromarray(img).save(os.path.join(sec_dir, r["scene_uid"] + ".png"))
        np.save(os.path.join(sec_dir, r["scene_uid"] + "_mask.npy"), mask)
        # No mask products for an excluded section: it is a picture to look at,
        # and 05c reads these .npy files as "this section is in the analysis".
        if use_art:
            np.save(os.path.join(sec_dir, r["scene_uid"] + "_artifact.npy"), amask)
        if use_cen:
            np.save(os.path.join(sec_dir, r["scene_uid"] + "_censor.npy"), cmask)
        # THE INDEX IS WHAT PUTS A SECTION INTO THE ANALYSIS, and an excluded
        # one must never enter it - however good its picture looks.
        if is_excl:
            n_rendered += 1
            continue
        rows.append({"kind": "section", "id": r["scene_uid"], "angle": round(angle, 1),
                     "fill": round(float(mask.mean()), 4),
                     "animal": r["animal"], "section_order": r["section_order"],
                     "manual_rotation": extra, "manual_flip": int(flip)})
        ok += 1
        if (i + 1) % 200 == 0:
            print(f"\r  sections {i + 1}/{len(secs)}  ok {ok}", end="")
    print(f"\rsections reformatted: {ok}/{len(secs)}"
          + (f"  ({n_excluded} manually excluded)" if n_excluded else "") + "          ")

    # Full accounting, every run. The operator's standing requirement is that
    # everything not explicitly excluded is kept, and `lost` only catches
    # sections that reached the loop and failed - this catches anything else.
    universe = {r["scene_uid"] for r in secs}
    kept_ids = {r["id"] for r in rows if r["kind"] == "section"}
    excl_ids = set(excluded)          # `excluded` maps uid -> (decision, reason)
    unaccounted = universe - kept_ids - excl_ids
    print()
    print(f"accounting: {len(universe)} sections = {len(kept_ids)} kept "
          f"+ {len(excl_ids & universe)} excluded + {len(unaccounted)} unaccounted")
    if unaccounted:
        print("!" * 74)
        print(f"{len(unaccounted)} section(s) are neither kept nor excluded:")
        for uid in sorted(unaccounted)[:20]:
            print(f"    {uid}")
        print("!" * 74)

    if args.only:
        print()
        print("=" * 72)
        print(f"--only: rendered {n_rendered} excluded section(s); index left alone")
        return

    out_csv = paths["index"]
    keys = ["kind", "id", "angle", "fill", "animal", "section_order", "regions",
            "manual_rotation", "manual_flip"]
    IO.atomic_write_csv(out_csv, rows, keys)

    if args.preview:
        preview(rows, sec_dir, plate_dir, args.preview)

    fills = [r["fill"] for r in rows if r["kind"] == "section"]
    pfills = [r["fill"] for r in rows if r["kind"] == "plate"]
    print()
    print("=" * 72)
    print(f"wrote {out_csv}")
    if fills and pfills:
        print(f"tissue fill  sections median {np.median(fills):.3f} | plates median {np.median(pfills):.3f}")
        print("  these should now be comparable - they were not before reformatting")
    if no_mask:
        print(f"WARNING: {len(no_mask)} section(s) had no 04g artifact mask and were "
              f"left unmasked - run 04g_artifact_mask.py first")
        for u in no_mask[:5]:
            print(f"    {u}")
    if lost:
        # Loud, and written out, because these are sections the operator chose to
        # KEEP that did not make it through anyway.
        path = paths["lost"]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(["scene_uid", "reason"]); w.writerows(lost)
        print()
        print("!" * 74)
        print(f"{len(lost)} section(s) were NOT excluded but still did not survive:")
        for uid, why in lost[:15]:
            print(f"    {uid:<24} {why}")
        if len(lost) > 15:
            print(f"    ... and {len(lost) - 15} more")
        print(f"  full list: {path}")
        print("!" * 74)
    if n_excluded:
        print(f"excluded {n_excluded} section(s) marked as too damaged in the curator;")
        print(f"  the list is in {paths['excluded']}")
        print(f"  they are absent from {os.path.basename(paths['index'])}, "
              f"so no later stage can pick them up")
    print("NEXT: 04c_atlas_match.py")
    print("=" * 72)


def preview(rows, sec_dir, plate_dir, n):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plates = [r for r in rows if r["kind"] == "plate"][:n]
    secs = [r for r in rows if r["kind"] == "section"]
    secs = secs[:: max(1, len(secs) // n)][:n]
    # squeeze=False: with n == 1 the axes array comes back 1-D and every
    # ax[row, col] below raises.
    fig, ax = plt.subplots(2, n, figsize=(2.1 * n, 4.6), squeeze=False)
    for k, p in enumerate(plates):
        ax[0, k].imshow(np.asarray(Image.open(os.path.join(plate_dir, p["id"] + ".png"))), cmap="gray")
        ax[0, k].set_title(f"{p['id']}\n{p['angle']:.0f} deg", fontsize=7)
    for k, s in enumerate(secs):
        ax[1, k].imshow(np.asarray(Image.open(os.path.join(sec_dir, s["id"] + ".png"))), cmap="gray")
        ax[1, k].set_title(f"{s['id']}\n{s['angle']:.0f} deg", fontsize=7)
    for a in ax.ravel():
        a.axis("off")
    fig.suptitle("Reformatted: centred, rotated horizontal, debris removed  "
                 "(TOP plates, BOTTOM sections)", fontsize=11)
    fig.tight_layout()
    out = os.path.join(REFORMAT_DIR, "reformat_preview.png")
    fig.savefig(out, dpi=100)
    plt.close(fig)
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
