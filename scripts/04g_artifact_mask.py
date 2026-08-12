"""Stage 4g - detect and mask bright artifacts inside the tissue.

Section-level exclusion (`04f`) throws away whole sections that cannot be
measured. This is the other half: sections that are fine overall but carry
bubbles, antibody aggregates or fibres *inside* otherwise good tissue. Those
cannot be dropped, only masked.

Measured on this dataset before building anything: in 139 random sections,
**86% carry at least one bright artifact strictly inside the tissue**, median 4
objects per section, up to 23.

**Be clear about how much this changes.** The masked area is small - median
**0.13%** of tissue, p95 0.48%, worst 1.13%. For a density per mm2 that is
negligible. It is not negligible for anything driven by *intensity*, because
these are by construction the brightest pixels in the section, and Andhari et
al. 2024 showed artifact-inflated intensities skewing normalisation so badly
that cell labels changed **outside** the artifact regions. This project's
primary readouts are DAPI-normalised, so the mask must be applied *before*
normalising, not after.

Where the parameters come from
------------------------------

**Resolution: the overviews, 5.20 um/px.** DIAGNijmegen's pathology artifact
detector runs at **4.0 um/px** - essentially this scale. That is the useful fact
from that repository: artifact detection does not need full resolution, so this
runs on PNGs that already exist instead of re-reading 730,000 tiles from the
CZIs. The model itself is not transferable (DeepLabV3+/EfficientNet-B2 trained
on brightfield H&E and chromogenic IHC, and it needs an 11 GB GPU).

**Two shape classes, not one.** QUALIFAI and DIAGNijmegen both separate air
bubbles from external artifacts/dust, and they have different origins -
coverslipping versus sample preparation. Splitting them here costs nothing and
keeps the counts interpretable.

**Detected on DAPI.** Following QUALIFAI's channel-agnostic/channel-specific
split: bubbles, fibres and folds affect every channel identically and are
annotated on DAPI; antibody aggregates are channel-specific and are not. This
mask is therefore the channel-agnostic one. A per-channel aggregate mask would
have to be built on the marker channel and would break the blinding, so it is
deliberately left out.

**The tissue rim is eroded away before deciding.** The edge of a section is
genuinely DAPI-bright - pial surface, ventricular lining - and a brightness rule
without this step masks real anatomy. Eroding 6 px (31 um) clears it.

Not detected here: **tissue folds**. Named by all three sources, and a fold in
fluorescence is doubled tissue - brighter, but with normal granularity, so the
smoothness test that finds bubbles will not find it. Left as a manual judgement
rather than guessed at.

Run:  python 04g_artifact_mask.py --preview 8     # look before committing
      python 04g_artifact_mask.py
"""

import argparse
import csv
import importlib.util
import json
import os

import numpy as np
from PIL import Image
from scipy import ndimage

_SPEC = importlib.util.spec_from_file_location(
    "reformat_mod", os.path.join(os.path.dirname(os.path.abspath(__file__)), "04a_reformat.py"))
_RF = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RF)
tissue_mask, WORK = _RF.tissue_mask, _RF.WORK_SIZE

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
MASK_DIR = os.path.join(OUT_ROOT, "artifacts")
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "artifacts")

UM_PX = 5.20e-3

# Label values written into the mask PNG. 0 is clean.
LBL_COMPACT = 1     # air bubble / antibody aggregate
LBL_ELONGATED = 2   # fibre / hair / external debris

RIM_ERODE_PX = 6            # 31 um - clears the genuinely bright tissue edge
BRIGHT_PCTL = 99.0          # seed: of in-tissue intensity
SMOOTH_FRAC = 0.35          # seed: texture below this fraction of median in-tissue texture
GROW_PCTL = 95.0            # grow: the artifact's halo is bright but not flat
GROW_ITERS = 25             # 130 um - bounds growth so it cannot flood the tissue rim
MIN_OBJ_PX = 15             # ~0.0004 mm2; below this it is noise
MAX_OBJ_MM2 = 1.2           # above this it is not an artifact, it is anatomy
ELONGATION_SPLIT = 3.0      # bbox aspect ratio dividing compact from elongated
FILL_SPLIT = 0.55           # area / bbox area; a curved fibre is low, a disc is high


def texture(im):
    """Local high-frequency energy.

    At 5.20 um/px a nucleus is 1-2 px, so real tissue is granular at the pixel
    scale while a bubble or an aggregate is a smooth dome. The median filter
    removes that granularity; what is left is how granular the neighbourhood was.
    """
    return ndimage.uniform_filter(np.abs(im - ndimage.median_filter(im, size=3)), size=9)


def detect(im, tis):
    """Return (label image, per-object records)."""
    core = ndimage.binary_erosion(tis, np.ones((2 * RIM_ERODE_PX + 1,) * 2))
    if core.sum() < 500:
        return np.zeros(im.shape, np.uint8), []

    tex = texture(im)
    t_med = float(np.median(tex[tis]))
    if t_med <= 0:
        return np.zeros(im.shape, np.uint8), []

    # Hysteresis, and it is not a refinement - without it the mask is wrong.
    #
    # The smoothness test finds the flat interior of a bubble but fails at its
    # edge, where the intensity gradient is steep and the texture measure is
    # therefore high. Thresholding on smoothness alone masks the core of each
    # artifact and leaves its bright halo behind - which defeats the purpose,
    # since the halo is still among the brightest pixels in the section and
    # still skews normalisation.
    #
    # So: seed on bright AND smooth AND away from the rim, then grow into the
    # merely-bright region. Growth is capped at GROW_ITERS dilations because the
    # tissue rim is bright and connected all the way round a section; unbounded
    # propagation from a seed touching it would flood the entire outline.
    seed = (im > np.percentile(im[tis], BRIGHT_PCTL)) & (tex < SMOOTH_FRAC * t_med) & core
    seed = ndimage.binary_opening(seed, np.ones((3, 3)))
    if not seed.any():
        return np.zeros(im.shape, np.uint8), []
    halo = ndimage.binary_fill_holes(im > np.percentile(im[tis], GROW_PCTL))
    hot = ndimage.binary_dilation(seed, np.ones((3, 3)), iterations=GROW_ITERS, mask=halo)
    hot = ndimage.binary_fill_holes(hot)

    out = np.zeros(im.shape, np.uint8)
    labels, n = ndimage.label(hot)
    records = []
    if n == 0:
        return out, records
    for i, sl in enumerate(ndimage.find_objects(labels), 1):
        m = labels[sl] == i
        area = int(m.sum())
        if area * UM_PX ** 2 > MAX_OBJ_MM2:
            # Growth escaped - almost certainly along the bright tissue rim.
            # Fall back to the seed for this object rather than dropping it,
            # so a real artifact is still partly masked and the rim is not.
            m = m & seed[sl]
            area = int(m.sum())
        if area < MIN_OBJ_PX:
            continue
        h, w = m.shape
        elong = max(h, w) / max(min(h, w), 1)
        # Bounding-box aspect alone calls a curved fibre "compact", because a
        # C-shape has a near-square box. Fill separates them: a disc packs its
        # box, a worm does not.
        fill = area / float(h * w)
        lbl = LBL_ELONGATED if (elong >= ELONGATION_SPLIT or fill < FILL_SPLIT) else LBL_COMPACT
        region = out[sl]
        region[m] = lbl
        records.append({"label": lbl, "area_mm2": area * UM_PX ** 2,
                        "elongation": round(float(elong), 2), "fill": round(float(fill), 2)})
    return out, records


def load_artifact_mask(scene_uid, shape=None):
    """Load one section's artifact mask. The public entry point for later stages.

    **Frame:** the same pixel grid as `overviews/<animal>/<channel>/<uid>_DAPI.png`,
    i.e. the section as scanned, at 5.20 um/px - *not* the reformatted frame,
    which is rotated, cropped and rescaled for atlas matching. Stages 3 and 5
    work at native CZI resolution in the scanned frame, so this is the frame they
    need; pass `shape` to nearest-neighbour resize onto a finer grid.

    Values: 0 clean, 1 compact (bubble/aggregate), 2 elongated (fibre/debris).
    Returns None when no mask has been computed for that section.
    """
    path = os.path.join(MASK_DIR, scene_uid + "_artifact.png")
    if not os.path.exists(path):
        return None
    m = Image.open(path)
    if shape is not None and (m.size[1], m.size[0]) != tuple(shape):
        m = m.resize((shape[1], shape[0]), Image.NEAREST)
    return np.asarray(m)


def measurable(scene_uid, tissue, shape=None):
    """Tissue with artifacts removed - the mask to measure inside, and the one
    whose area belongs in the denominator of any density."""
    art = load_artifact_mask(scene_uid, shape=tissue.shape)
    return tissue if art is None else (tissue & (art == 0))


def load_tissue(im):
    small = np.asarray(Image.fromarray(im).resize((WORK, WORK), Image.BILINEAR)).astype(np.float32)
    t = tissue_mask(small, light_background=False)
    if t is None:
        return None
    return np.asarray(Image.fromarray(t.astype(np.uint8) * 255).resize(
        (im.shape[1], im.shape[0]), Image.NEAREST)) > 127


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=int, default=0, help="render N overlays and stop")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    os.makedirs(MASK_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    chan, satur = {}, {}
    with open(QC_CSV, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            chan[r["scene_uid"]] = r["marker_channel"]
            try:
                satur[r["scene_uid"]] = float(r["saturated_fraction"])
            except (KeyError, ValueError):
                pass

    with open(os.path.join(REFORMAT_DIR, "reformat_index.csv"), newline="", encoding="utf-8") as fh:
        index = [r for r in csv.DictReader(fh) if r["kind"] == "section"]
    if args.limit:
        index = index[: args.limit]

    rows, previews = [], []
    for i, r in enumerate(index):
        uid = r["id"]
        src = os.path.join(OVERVIEW_DIR, r["animal"], chan.get(uid, "AF488"), uid + "_DAPI.png")
        if not os.path.exists(src):
            continue
        im = np.asarray(Image.open(src).convert("L")).astype(np.float32)
        tis = load_tissue(im)
        if tis is None:
            continue
        mask, recs = detect(im, tis)

        # Written per section rather than batched: this drive has dropped writes
        # mid-run before, and a partial run should cost minutes, not the lot.
        Image.fromarray(mask).save(os.path.join(MASK_DIR, uid + "_artifact.png"))

        tissue_mm2 = float(tis.sum()) * UM_PX ** 2
        a_c = sum(x["area_mm2"] for x in recs if x["label"] == LBL_COMPACT)
        a_e = sum(x["area_mm2"] for x in recs if x["label"] == LBL_ELONGATED)
        rows.append({
            "scene_uid": uid, "animal": r["animal"], "section_order": r["section_order"],
            "tissue_mm2": round(tissue_mm2, 3),
            "n_compact": sum(1 for x in recs if x["label"] == LBL_COMPACT),
            "n_elongated": sum(1 for x in recs if x["label"] == LBL_ELONGATED),
            "compact_mm2": round(a_c, 4), "elongated_mm2": round(a_e, 4),
            "artifact_mm2": round(a_c + a_e, 4),
            "artifact_pct_of_tissue": round(100 * (a_c + a_e) / max(tissue_mm2, 1e-9), 3),
            # Tissue that survives masking - the denominator any later density
            # should use.
            "measurable_mm2": round(tissue_mm2 - a_c - a_e, 3),
            # Channel-specific and NOT masked here; carried so the two can be
            # joined later without recomputing.
            "saturated_fraction": satur.get(uid, ""),
        })
        if args.preview and len(previews) < args.preview and recs:
            previews.append((uid, im, tis, mask))
        if (i + 1) % 100 == 0:
            print(f"\r  {i + 1}/{len(index)}", end="")
    print(f"\r  masked {len(rows)}/{len(index)} sections        ")
    if not rows:
        raise SystemExit("nothing masked - run 04a_reformat.py first")

    if previews:
        overlay(previews)
        if args.preview:
            return

    out = os.path.join(MASK_DIR, "artifact_summary.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    pct = np.array([r["artifact_pct_of_tissue"] for r in rows])
    aff = sum(1 for r in rows if r["n_compact"] or r["n_elongated"])
    print()
    print("=" * 74)
    print(f"{len(rows)} sections -> {out}")
    print(f"  masks written to {MASK_DIR}/<uid>_artifact.png  "
          f"(0 clean, {LBL_COMPACT} compact, {LBL_ELONGATED} elongated)")
    print(f"  sections with >=1 artifact : {aff} ({100 * aff / len(rows):.0f}%)")
    print(f"  compact objects total      : {sum(r['n_compact'] for r in rows)}")
    print(f"  elongated objects total    : {sum(r['n_elongated'] for r in rows)}")
    print(f"  % of tissue masked         : median {np.median(pct):.3f}  "
          f"p95 {np.percentile(pct, 95):.3f}  max {pct.max():.2f}")
    print()
    print("The masked FRACTION is small, so densities per mm2 barely move. The")
    print("point is intensity: these are the brightest pixels in the section, and")
    print("an unmasked artifact skews normalisation for the WHOLE section, not")
    print("just its own area (Andhari et al. 2024). Apply the mask before")
    print("normalising, and use measurable_mm2 as the density denominator.")
    print()
    print("NOT masked here: tissue folds (no reliable signature at this")
    print("resolution) and channel-specific antibody aggregates (would need the")
    print("marker channel, which would break the blinding).")
    print("=" * 74)


def overlay(previews):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(previews)
    fig, ax = plt.subplots(1, n, figsize=(4.0 * n, 4.4))
    ax = np.atleast_1d(ax)
    for k, (uid, im, tis, mask) in enumerate(previews):
        v = im[tis]
        med = float(np.median(v))
        mad = float(np.median(np.abs(v - med))) * 1.4826 or max(float(v.std()), 1.0)
        disp = np.clip((im - (med - mad)) / max(5 * mad, 1e-6), 0, 1)
        rgb = np.dstack([disp] * 3)
        rgb[mask == LBL_COMPACT] = [1.0, 0.15, 0.10]
        rgb[mask == LBL_ELONGATED] = [0.20, 0.60, 1.00]
        ax[k].imshow(rgb)
        ax[k].set_title(f"{uid}\nred compact {int((mask == LBL_COMPACT).any() and (mask == LBL_COMPACT).sum())} px"
                        f" | blue elongated {int((mask == LBL_ELONGATED).sum())} px", fontsize=7)
        ax[k].axis("off")
    fig.suptitle("artifact mask - red = bubble/aggregate, blue = fibre/debris", fontsize=12)
    fig.tight_layout()
    path = os.path.join(REPORT_DIR, "overlay.png")
    fig.savefig(path, dpi=112)
    plt.close(fig)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
