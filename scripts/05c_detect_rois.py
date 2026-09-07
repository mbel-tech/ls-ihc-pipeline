"""Stage 5c - count nuclei in every placed ROI, and measure the marker in them.

Reads the CZI at native 0.65 um/px over the boxes `05a` computed, segments
nuclei on DAPI, and measures the marker channel inside each nuclear mask.

**Segment on DAPI, never on the marker.** Detecting on the marker channel would
define "number of pERK+ cells" by the threshold twice over: once to find the
object and again to call it positive, so the count and the cut could never be
varied independently. Nuclei come from the counterstain; the marker is measured
afterwards; positivity is decided last and can be changed without re-reading a
single CZI. The rest of the pipeline already leans on DAPI for the same reason -
`04a_reformat` decides all its geometry there because "the marker channel is a
sparse signal and a poor silhouette".

**StarDist, not threshold-and-watershed.** Not a general preference: watershed
under-segments where nuclei touch, and Vv, Vd and POA are periventricular. The
error would be worst in exactly those ROIs and mild in Dm and Dl, and a
region-correlated counting bias survives into the results looking like an
anatomical finding.

**What a background disc is for.** It is measured by this stage identically to a
real ROI - same read, same segmentation, same statistics, distinguished only by
`roi_kind`. Two things come out of that: a per-section reference level measured
rather than inferred, and a false-positive rate, since the same detector runs
over tissue the operator called empty. It is NOT a negative control: the primary
antibody is on that tissue too, so it measures non-specific binding plus
autofluorescence, not zero.

Writes `results/roi_nuclei.csv`, one row per nucleus. That is the artefact that
matters - with per-nucleus intensities on disk the positivity cut becomes a
decision about a table rather than a reason to re-read 130 CZI scenes.

Run:  python 05c_detect_rois.py
      python 05c_detect_rois.py --limit 5
      python 05c_detect_rois.py --qc            # also write overlay crops to
                                                # qc/roi_detections/ - green =
                                                # counted, red = outside the disc
"""

import argparse
import csv
import importlib.util
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_g5", os.path.join(_HERE, "05a_roi_geometry.py"))
G5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G5)

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_naming as NM  # noqa: E402
OUT_ROOT = G5.OUT_ROOT
REFORMAT_DIR = G5.REFORMAT_DIR
RESULTS = os.path.join(OUT_ROOT, "results")
NUCLEI_CSV = os.path.join(RESULTS, "roi_nuclei.csv")
QC_DIR = os.path.join(OUT_ROOT, "qc", "roi_detections")

BASE_PX_UM = CONFIG["pixel_size_um"]
DAPI_C = CONFIG["channels"]["dapi_index"]
MARK_C = CONFIG["channels"]["marker_index"]
NUC_UM = CONFIG["detection"]["nucleus_diameter_um"]

COLUMNS = ["scene_uid", "animal", "marker", "roi_kind", "region", "seed_n",
           "roi_index", "nucleus_id",
           "czi_x", "czi_y", "sec_x", "sec_y",
           "area_um2", "equiv_diam_um",
           "dapi_mean", "marker_mean", "marker_median", "marker_p90",
           "censored", "artifact", "off_tissue"]


def point_in_poly(px, py, v):
    """Is (px, py) inside the ring `v`, an (N, 2) array of canonical-grid points?

    Even-odd ray cast, in plain Python. It is called once per detected nucleus
    over a ring of a dozen or so vertices, which is nothing beside the
    segmentation that produced the nucleus, and keeping it here means the
    membership rule is one readable function rather than a matplotlib Path whose
    boundary convention would have to be looked up to be trusted.

    A nucleus exactly on the boundary is not worth a rule of its own: the ROI is
    drawn at 25 um per pixel and a nucleus is 7 um, so the boundary is thicker
    than the question.
    """
    inside = False
    n = len(v)
    j = n - 1
    for i in range(n):
        xi, yi = v[i][0], v[i][1]
        xj, yj = v[j][0], v[j][1]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def check_header(path, columns):
    """Refuse to append to a roi_nuclei.csv whose header is not `columns`.

    This stage appends positionally, and the file is shared across runs and
    both markers. COLUMNS gained `off_tissue` on 2026-09-02; a resume against a
    file written before that appended 21-field rows under a 20-field header,
    and nothing failed: csv.DictReader maps the extra field to key None, so in
    06a every NEW nucleus read `off_tissue` as None - the same as absent - and
    06g_flag_off_tissue.py cannot backfill a file that is half old and half
    new. Order is checked too, not just the set: a permuted header would take
    every appended row scrambled.
    """
    with open(path, newline="", encoding="utf-8") as rf:
        header = next(csv.reader(rf), None) or []
    if header == list(columns):
        return
    missing = [c for c in columns if c not in header]
    extra = [c for c in header if c not in columns]
    why = (f"missing {missing}" if missing else "") + \
          (f" extra {extra}" if extra else "") or "same columns, different order"
    raise SystemExit(
        f"!! {path} has a different header from the one this stage writes "
        f"({why}). Appending to it would give the new rows a different layout "
        f"from the old ones. If `off_tissue` is what is missing, run "
        f"06g_flag_off_tissue.py to backfill it first; otherwise re-run "
        f"05c_detect_rois.py --force to rewrite the file.")


def drop_rows(path, marker, uids):
    """Rewrite `path` without the rows of `marker` whose scene_uid is in `uids`.

    THE ONLY PATH IN THE PIPELINE THAT DELETES MEASURED DATA, so it is exact:
    other markers' rows and this marker's other sections are kept as they are.
    `--force --limit N` used to drop EVERY row of the marker and then
    re-measure N sections, silently discarding the rest; the caller now passes
    its todo list and nothing outside it is touched.

    Through a temp file and one atomic replace, because this stage runs against
    a drive that has dropped writes and a half-written roi_nuclei.csv is the
    whole dataset. Returns (dropped, kept).
    """
    uids = set(uids)
    tmp = path + ".tmp"
    dropped = kept = 0
    with open(path, newline="", encoding="utf-8") as rf, \
            open(tmp, "w", newline="", encoding="utf-8") as tf:
        rd, tw = csv.reader(rf), csv.writer(tf)
        header = next(rd, None)
        if not header or "marker" not in header or "scene_uid" not in header:
            tf.close()
            os.remove(tmp)
            raise SystemExit(f"!! {path} has no marker/scene_uid column - "
                             f"cannot tell whose rows to drop")
        tw.writerow(header)
        mi, ui = header.index("marker"), header.index("scene_uid")
        for row in rd:
            if row and row[mi] == marker and row[ui] in uids:
                dropped += 1
                continue
            tw.writerow(row)
            kept += 1
    os.replace(tmp, path)
    return dropped, kept


def load_model():
    """StarDist's pretrained fluorescence model.

    Downloaded on first use, so the first run needs network access.

    `from_pretrained` finishes by creating a SYMLINK next to the extracted
    weights, and Windows refuses that without Developer Mode or elevation -
    WinError 1314, "a required privilege is not held by the client". The
    download and extraction have already succeeded by then, so the fallback
    below opens the extracted folder directly and needs no privilege at all.
    Same weights, same thresholds; only the convenience link is missing.
    """
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    from stardist.models import StarDist2D
    print("loading StarDist 2D_versatile_fluo (downloads on first use)...")
    try:
        return StarDist2D.from_pretrained("2D_versatile_fluo")
    except OSError as exc:
        base = os.path.expanduser("~/.keras/models/StarDist2D/2D_versatile_fluo")
        extracted = os.path.join(base, "2D_versatile_fluo_extracted")
        if not os.path.exists(os.path.join(extracted, "weights_best.h5")):
            raise
        print(f"  ({exc.__class__.__name__}: {exc.strerror or exc}) "
              f"- loading the extracted weights directly")
        return StarDist2D(None, name="2D_versatile_fluo_extracted", basedir=base)


def balanced_order(uids, done=()):
    """Alternate treatment and control, one section at a time.

    This is the same idea as `04n_roi_worklist.py` - an order chosen so that ANY
    PREFIX is a usable dataset - carried one step further. That stage balances
    across animals; this balances across groups too, so a run stopped half way
    has both arms measured to about the same depth rather than five control
    animals finished and every exercise animal untouched.

    Within a group it round-robins the animals, and within an animal it walks
    the sections in order, so the depth stays even at every level at once.

    **THIS READS THE GROUP KEY, and config.blinding says no stage before 06b
    may.** The exemption is narrow and worth stating: the group decides only the
    ORDER sections are measured in. Nothing downstream of it - not the
    segmentation, not the per-section threshold, not a single number in the
    output - depends on when a section was processed, and the finished dataset
    is identical whichever order was used. It is `--order uid` away from being
    blind again, and the run prints which order it used.
    """
    groups = CONFIG.get("groups") or {}
    by_animal = groups.get("by_animal") or {}
    if not by_animal:
        print("  no group key in config - falling back to plain uid order")
        return uids

    # animal -> its sections, in order
    per = {}
    for u in uids:
        per.setdefault(NM.subject_of(u), []).append(u)
    for v in per.values():
        v.sort()

    order = [g for g in (groups.get("order") or []) if g] or sorted(
        {by_animal.get(a, "") for a in per} - {""})
    arms = {g: [a for a in sorted(per, key=NM.natural_key)
                if by_animal.get(a) == g] for g in order}
    unknown = [a for a in per if by_animal.get(a) not in order]
    if unknown:
        print(f"  animals with no group: {unknown} - appended at the end")

    have = {g: sum(len(per[a]) for a in arms[g]) for g in order}

    # Count what a previous run already measured, so a RESUME corrects an
    # imbalance rather than preserving it. Strict alternation would only keep
    # the remainder even; taking from whichever arm is furthest behind keeps the
    # CUMULATIVE totals even, which is the property that actually matters when
    # the operator stops half way and looks at the numbers.
    cum = dict.fromkeys(order, 0)
    for u in (done or ()):
        g = by_animal.get(NM.subject_of(u))
        if g in cum:
            cum[g] += 1
    if any(cum.values()):
        print(f"  already measured: " + ", ".join(f"{g} {cum[g]}" for g in order))

    out = []
    cursor = {g: 0 for g in order}
    while any(per[a] for g in order for a in arms[g]):
        live_arms = [g for g in order if any(per[a] for a in arms[g])]
        g = min(live_arms, key=lambda x: (cum[x], order.index(x)))
        live = [a for a in arms[g] if per[a]]
        a = live[cursor[g] % len(live)]        # round-robin the animals within it
        cursor[g] += 1
        out.append(per[a].pop(0))
        cum[g] += 1
    for a in unknown:
        out.extend(per[a])
    print("  order: balanced - "
          + ", ".join(f"{g} {have[g]} to do ({len(arms[g])} animals)"
                      for g in order))
    return out


def mask_at(uid, kind):
    """The 256-frame artifact or censor mask, or None."""
    p = os.path.join(REFORMAT_DIR, "sections_AF568", f"{uid}_{kind}.npy")
    if not os.path.exists(p):
        p = os.path.join(REFORMAT_DIR, "sections", f"{uid}_{kind}.npy")
    return np.load(p) if os.path.exists(p) else None


def write_overlay(uid, bi, b, dapi, labels, kept):
    """One PNG per ROI: the DAPI crop with the segmentation drawn on it.

    What this is for. The nucleus-diameter check in the docs says the
    segmentation is finding objects of about the right SIZE; it cannot say they
    are in the right PLACES, that touching nuclei were split rather than merged,
    or that a disc landed where the operator meant it to. Those are visual
    facts, and until now the only way to see one was to re-read the box in a
    notebook - so in practice nobody looked.

    Boundaries, not filled labels: a filled overlay hides the very thing being
    judged, which is whether the outline follows the nucleus.

    GREEN is a nucleus that was COUNTED. RED is one StarDist found inside the
    bounding box but outside the ROI itself, so it was dropped. Drawing the
    rejects is the point - a box that is mostly red means the shape is small or
    misplaced relative to what was segmented, and that is invisible in any
    table. It is the direct check on a drawn region too: a polygon traced off
    the anatomy shows as a crescent of red down one side.
    """
    from PIL import Image

    lo, hi = np.percentile(dapi, (1, 99.8))
    g = np.clip((dapi - lo) / max(hi - lo, 1e-6), 0, 1)
    rgb = np.repeat((g * 255).astype(np.uint8)[:, :, None], 3, axis=2)

    # A boundary pixel is one whose label differs from a neighbour. Computed
    # with shifts rather than skimage.find_boundaries so this adds no import
    # that the frozen build would have to carry.
    lab = labels
    edge = np.zeros(lab.shape, bool)
    edge[:-1, :] |= lab[:-1, :] != lab[1:, :]
    edge[1:, :] |= lab[1:, :] != lab[:-1, :]
    edge[:, :-1] |= lab[:, :-1] != lab[:, 1:]
    edge[:, 1:] |= lab[:, 1:] != lab[:, :-1]
    edge &= lab > 0

    keep_mask = np.isin(lab, list(kept)) if kept else np.zeros(lab.shape, bool)
    rgb[edge & keep_mask] = (0, 255, 0)
    rgb[edge & ~keep_mask] = (255, 0, 0)

    os.makedirs(QC_DIR, exist_ok=True)
    name = f"{uid}_roi{bi:02d}_{b['roi_kind']}_{b['region'] or 'na'}.png"
    name = name.replace(" ", "_").replace("/", "_")
    Image.fromarray(rgb).save(os.path.join(QC_DIR, name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only the first N sections")
    ap.add_argument("--order", choices=("balanced", "uid"), default="balanced",
                    help="balanced alternates treatment and control, one section "
                         "at a time, so a partial run is still a comparison; "
                         "uid is plain scene_uid order")
    ap.add_argument("--qc", action="store_true",
                    help="write one overlay PNG per ROI to qc/roi_detections: "
                         "DAPI with nucleus boundaries, green counted, red "
                         "found but outside the disc")
    ap.add_argument("--marker", choices=G5.MARKERS, default="AF568",
                    help="which marker's boxes to measure (default AF568). "
                         "Appends to the same roi_nuclei.csv - the two markers "
                         "have disjoint sections.")
    ap.add_argument("--force", action="store_true", help="redo finished sections")
    args = ap.parse_args()

    G5.use_marker(args.marker)
    if not os.path.exists(G5.BOX_CSV):
        print(f"no {G5.BOX_CSV} - run 05a_roi_geometry.py --marker {args.marker} first")
        return 1
    print(f"marker: {args.marker}  ({os.path.basename(G5.BOX_CSV)})")
    boxes = G5.load_csv(G5.BOX_CSV)
    geom = {g["scene_uid"]: g for g in G5.load_csv(G5.GEOM_CSV)}
    os.makedirs(RESULTS, exist_ok=True)
    if args.qc:
        os.makedirs(QC_DIR, exist_ok=True)

    # Resume by section, because a section is the unit that costs something:
    # one CZI open and a model call per ROI in it.
    by_sec = {}
    for b in boxes:
        by_sec.setdefault(b["scene_uid"], []).append(b)

    # Resume by section, scoped to THIS MARKER. roi_nuclei.csv holds both once
    # the PCNA pass has run, and while scene uids are disjoint - so a raw
    # `done` set would still skip the right sections - the balanced-order
    # counter below counts what each arm has already had, and the other
    # marker's sections would inflate both arms and misdirect the ordering.
    exists = os.path.exists(NUCLEI_CSV)
    if exists:
        # Before anything else: appending to a file with a different header
        # corrupts it quietly (see check_header), and the check is one line.
        check_header(NUCLEI_CSV, COLUMNS)
    done = set()
    if exists and not args.force:
        # Streamed with csv.reader, not load_csv: this needs one column and
        # load_csv would build a dict per row - about five million of them once
        # PCNA is in the file, on the resume of the run this stage exists to
        # make resumable. 06c reads the same file the same way for the same
        # reason.
        with open(NUCLEI_CSV, newline="", encoding="utf-8") as rf:
            rd = csv.reader(rf)
            next(rd, None)
            for row in rd:
                if row and row[0] in by_sec:
                    done.add(row[0])
        print(f"resuming: {len(done)} {args.marker} sections already measured")
    todo = [u for u in sorted(by_sec) if u not in done]
    if args.order == "balanced":
        todo = balanced_order(todo, done)
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("nothing to do")
        return 0
    print(f"{len(todo)} sections, {sum(len(by_sec[u]) for u in todo)} ROIs")

    model = load_model()
    from csbdeep.utils import normalize
    from pylibCZIrw import czi as pyczi
    from skimage.measure import regionprops

    # --force MUST NOT TRUNCATE THE OTHER MARKER'S ROWS, NOR THE SECTIONS IT
    # IS NOT ABOUT TO REDO.
    #
    # roi_nuclei.csv is shared: the two markers have disjoint sections and
    # append to one file. Opening it "w" to redo one marker would discard the
    # other's entirely - `--marker AF488 --force` deleting ~895,000 pERK rows,
    # or a forced pERK re-run deleting the PCNA ones. Nothing would error; 06a
    # and 06c would just report the missing marker at 0 coverage. That is the
    # same hazard Phase 3.1 removed from 05a's box files, one stage later, and
    # here the cost is hours of irrecoverable detection.
    #
    # The same applied within the marker: `--force --limit 5` dropped every
    # section of the marker and re-measured five. So the drop is scoped to
    # `todo` - exactly the sections whose rows are about to be replaced - and
    # done after load_model(), so a model that fails to load leaves the file
    # as it was.
    if exists and args.force:
        dropped, kept = drop_rows(NUCLEI_CSV, args.marker, todo)
        print(f"  --force: dropped {dropped} {args.marker} rows over {len(todo)} "
              f"sections, kept {kept}")

    fh = open(NUCLEI_CSV, "a" if exists else "w", newline="", encoding="utf-8")
    w = csv.writer(fh)
    if not exists:
        w.writerow(COLUMNS)

    px_area = BASE_PX_UM ** 2
    total_nuc = 0
    no_tissue_mask = []
    for n, uid in enumerate(todo, 1):
        g = geom[uid]
        M = np.array([[float(g["m00"]), float(g["m01"]), float(g["m02"])],
                      [float(g["m10"]), float(g["m11"]), float(g["m12"])]])
        Minv = G5.invert_affine(M)              # CZI px -> 256 grid
        art = mask_at(uid, "artifact")
        cen = mask_at(uid, "censor")
        # The DAPI tissue silhouette 04a_reformat.py carried into this same 256
        # frame - the tissue definition every other stage and the curator use.
        # Without it there is no way to tell a nucleus on the section from one
        # on the glass, so a section with no mask is skipped rather than
        # measured: silently calling every nucleus on-tissue is the failure this
        # check exists to stop.
        tis = mask_at(uid, "mask")
        if tis is None:
            no_tissue_mask.append(uid)
            continue
        path = os.path.join(CONFIG["source_dir"], g["czi_file"])
        rows = []
        with pyczi.open_czi(path) as doc:
            for bi, b in enumerate(by_sec[uid], 1):
                x0, y0 = int(b["czi_x0"]), int(b["czi_y0"])
                bw, bh = int(b["czi_w"]), int(b["czi_h"])
                if bw < 8 or bh < 8:
                    continue
                roi = (x0, y0, bw, bh)
                dapi = np.squeeze(doc.read(roi=roi, plane={"C": DAPI_C})).astype(np.float32)
                mark = np.squeeze(doc.read(roi=roi, plane={"C": MARK_C})).astype(np.float32)
                if dapi.ndim != 2 or dapi.shape != mark.shape:
                    continue
                # ALWAYS TILE. Untiled, StarDist takes 121 s on a 1.22 Mpx ROI;
                # at n_tiles=(2,2) it takes 4.1 s and returns the identical 1177
                # nuclei. The cost is wildly non-linear in image size - a
                # quarter of the pixels ran in 0.7 s - so this is 30x on a
                # typical ROI and the difference between a 75-minute run and a
                # 62-hour one. Nothing about the answer changes.
                #
                # Tiles of roughly 300k px, never fewer than 2x2. More tiles
                # than that is slower again (5.1 s at 4x4, 11.1 s at 8x8): the
                # per-tile overhead takes over.
                nt = max(2, int(np.ceil(np.sqrt(dapi.size / 300_000))))
                labels, _ = model.predict_instances(
                    normalize(dapi, 1, 99.8), n_tiles=(nt, nt),
                    verbose=False, show_tile_progress=False)
                if labels.max() == 0:
                    continue

                # Which nuclei are actually IN the ROI. The shape is drawn on
                # the 256 grid and is something else here - a circle becomes an
                # ellipse, a polygon a differently-proportioned polygon - so
                # membership is decided by mapping the centroid BACK to the grid
                # and testing it there, never against a radius in CZI px.
                #
                # That is why a drawn region needs no new machinery: the test
                # changes from "inside this circle" to "inside this ring", and
                # everything either side of it stays as it was.
                sx, sy = float(b["sec_x"]), float(b["sec_y"])
                sr = float(b["sec_r"] or 0)
                poly = G5.parse_poly(b.get("sec_poly", ""))
                inside = ((lambda gx, gy: point_in_poly(gx, gy, poly))
                          if poly is not None else
                          (lambda gx, gy: (gx - sx) ** 2 + (gy - sy) ** 2 <= sr * sr))
                props = regionprops(labels, intensity_image=mark)
                dprops = {p.label: p for p in regionprops(labels, intensity_image=dapi)}
                kept = set()
                for p in props:
                    cy, cx = p.centroid
                    gx, gy = G5.apply_affine(Minv, x0 + cx, y0 + cy)
                    if not inside(gx, gy):
                        continue
                    kept.add(p.label)
                    vals = p.image_intensity[p.image]
                    ix, iy = int(round(gx)), int(round(gy))
                    inb = lambda m: (m is not None and 0 <= iy < m.shape[0]
                                     and 0 <= ix < m.shape[1] and bool(m[iy, ix]))
                    # Outside the silhouette, or off the frame entirely, means
                    # the nucleus is not on the section - glass, mounting
                    # medium, or a neighbouring scene. `inb` is False for an
                    # out-of-bounds index, so both cases land here. Recorded
                    # rather than dropped, the way `artifact` is: 06a decides,
                    # and the QC overlay can still show what was found.
                    off_tis = int(not inb(tis))
                    rows.append([
                        uid, b["animal"], b["marker"], b["roi_kind"], b["region"],
                        b["seed_n"], bi, p.label,
                        round(x0 + cx, 1), round(y0 + cy, 1),
                        round(float(gx), 2), round(float(gy), 2),
                        round(p.area * px_area, 2),
                        round(2 * np.sqrt(p.area * px_area / np.pi), 2),
                        round(float(dprops[p.label].image_intensity[
                            dprops[p.label].image].mean()), 1),
                        round(float(vals.mean()), 1),
                        round(float(np.median(vals)), 1),
                        round(float(np.percentile(vals, 90)), 1),
                        int(inb(cen)), int(inb(art)), off_tis])
                if args.qc:
                    write_overlay(uid, bi, b, dapi, labels, kept)
        w.writerows(rows)
        fh.flush()
        total_nuc += len(rows)
        print(f"\r  {n}/{len(todo)}  {uid}  {len(rows)} nuclei  "
              f"({total_nuc} total)          ", end="")
    fh.close()
    print(f"\n{total_nuc} nuclei -> {NUCLEI_CSV}")
    if no_tissue_mask:
        print(f"!! {len(no_tissue_mask)} sections SKIPPED for want of a tissue "
              f"mask in reformatted/: {no_tissue_mask[:5]}")
        print("   Run 04a_reformat.py for them before trusting any count.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
