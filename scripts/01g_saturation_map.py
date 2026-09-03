"""Stage 1c - locate the AF568 saturation and decide how much it costs.

35% of AF568 sections have >2% of pixels clipped at 65535, up to 47%, and the
pattern is animal-specific (LS53 100%, LS85 86%, LS138 71%, against LS120/LS22/
LS61 at 0%). Clipped pixels are unrecoverable, so the only useful question is
what the clipping actually covers:

  edges, folds, debris     -> cosmetic; the biology is untouched
  parenchyma / germinal zones -> serious; intensity is dead and, if AF568 is
                                 PCNA, dense nuclei merge and undercount

Four measurements separate those cases:

  in-tissue fraction   how much of the clipping is inside the DAPI mask at all.
                       Clipping outside tissue is mounting medium or debris.

  edge affinity        median distance from a clipped pixel to the tissue
                       boundary, over the tissue half-width. Folds and rim
                       artifacts score low; parenchymal signal scores high.

  blob size            at 5.2 um/px a 7 um nucleus is under one pixel, so any
                       large connected clipped region CANNOT be nuclei - it is
                       a fold, a bubble, or a genuinely over-exposed field.

  tissue coverage      what fraction of the tissue itself is clipped, which is
                       what actually bounds how much of a section is usable.

Works off the exported 8-bit overviews rather than the CZIs, so it costs
minutes rather than hours. The tissue and background intensities still come from
those PNGs, which is correct - they are display-ranged comparisons.

**The clipped set no longer does, and the old hedge understated the problem.**
This module used to call `_MARK.png >= 254` a "close proxy for clipping". It was
not close: the PNG is written after `apply_tile_field()`, and dividing by a gain
above 1 lifts a pixel off the 16-bit ceiling so it stops reading as clipped,
while its value is exactly as lost. `tilefield_c1` runs 0.812-1.097 and exceeds
1.0 over 54% of its area, so the proxy held roughly 46% of the clipped pixels and
every figure this module printed was about half the truth. The clipped set now
comes from `qc/censor_raw/<uid>_clipped.png`, measured on the raw 16-bit plane by
`01k_saturation_raw.py`; run that first.

Run:  python 01g_saturation_map.py
      python 01g_saturation_map.py --figures 12
"""

import argparse
import csv
import json
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from scipy import ndimage

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "saturation")

# 8-bit proxy for a clipped 16-bit pixel.
SAT_LEVEL = 254          # fallback only; see raw_clip_mask()
RAW_MASK_DIR = os.path.join(OUT_ROOT, "qc", "censor_raw")
_fallbacks = []
# --proxy reproduces the pre-2026-09-02 measurement with TODAY'S code, so a
# before/after comparison isolates the mask change instead of mixing it with
# three weeks of drift in this file. Debugging affordance only; never the
# default, and it writes to its own output.
_force_proxy = [False]
# Only sections with at least this much clipping are worth characterising.
MIN_SAT_FRACTION = 0.005
# A clipped region larger than this cannot be a nucleus at overview resolution.
BIG_BLOB_UM2 = 2000.0


def otsu(values):
    hist, edges = np.histogram(values, bins=256)
    hist = hist.astype(float)
    centres = (edges[:-1] + edges[1:]) / 2.0
    w1, w2 = np.cumsum(hist), np.cumsum(hist[::-1])[::-1]
    valid = (w1 > 0) & (w2 > 0)
    m1 = np.cumsum(hist * centres) / np.maximum(w1, 1e-9)
    m2 = (np.cumsum((hist * centres)[::-1]) / np.maximum(w2[::-1], 1e-9))[::-1]
    var = w1 * w2 * (m1 - m2) ** 2
    var[~valid] = -1
    return centres[int(np.argmax(var))]


def tissue_mask(dapi):
    """Tissue from DAPI, in log space and cleaned up.

    The naive version of this - a percentile threshold on the raw 8-bit image -
    is what made the channel-identity masks trace the mounting halo instead of
    the brain. Log-Otsu plus a closing and hole fill gives the actual section.
    """
    positive = dapi[dapi > 0].astype(np.float64)
    if positive.size < 500:
        return np.zeros_like(dapi, dtype=bool)
    thr = float(np.expm1(otsu(np.log1p(positive))))
    mask = ndimage.gaussian_filter(dapi.astype(np.float32), 2.0) > thr
    mask = ndimage.binary_closing(mask, np.ones((7, 7)))
    mask = ndimage.binary_fill_holes(mask)
    mask = ndimage.binary_opening(mask, np.ones((5, 5)))

    # Keep only the largest few components: the section, not dust.
    labels, n = ndimage.label(mask)
    if n > 1:
        sizes = ndimage.sum(mask, labels, range(1, n + 1))
        keep = np.where(sizes >= 0.05 * sizes.max())[0] + 1
        mask = np.isin(labels, keep)
    return mask


def raw_clip_mask(uid, shape):
    """Clipping as measured on the RAW 16-bit plane by 01k_saturation_raw.py.

    This module used to take `_MARK.png >= 254` as the clipped set, on the
    grounds that the AF568 display high is 65535. The arithmetic is right and
    the input was wrong: the PNG is written AFTER `apply_tile_field()`, and
    dividing by a gain above 1 lifts a pixel off the ceiling so it stops reading
    as clipped. `tilefield_c1` exceeds 1.0 over 54% of its area, so every
    clipping figure this module printed before today was roughly half the truth.
    """
    p = os.path.join(RAW_MASK_DIR, uid + "_clipped.png")
    if not os.path.exists(p):
        return None
    m = np.asarray(Image.open(p).convert("L")) > 0
    return m if m.shape == shape else None


def analyse(row, um_px):
    base = os.path.join(OVERVIEW_DIR, row["animal"], row["marker_channel"], row["scene_uid"])
    mark_path, dapi_path = base + "_MARK.png", base + "_DAPI.png"
    if not (os.path.exists(mark_path) and os.path.exists(dapi_path)):
        return None

    # The 8-bit overview still supplies the tissue/background intensities below -
    # those are display-ranged comparisons and belong on it. Only the clipped set
    # moves to the raw plane.
    mark = np.asarray(Image.open(mark_path).convert("L"))
    dapi = np.asarray(Image.open(dapi_path).convert("L"))
    sat = None if _force_proxy[0] else raw_clip_mask(row["scene_uid"], mark.shape)
    if sat is None and not _force_proxy[0]:
        _fallbacks.append(row["scene_uid"])
    if sat is None:
        sat = mark >= SAT_LEVEL
    sat_fraction = float(sat.mean())

    result = {
        "scene_uid": row["scene_uid"], "animal": row["animal"], "slide": row["slide"],
        "marker_channel": row["marker_channel"], "section_order": row["section_order"],
        "sat_fraction_frame": round(sat_fraction, 5),
    }

    tissue = tissue_mask(dapi)
    tissue_px = int(tissue.sum())
    if tissue_px < 2000:
        result["verdict"] = "no tissue mask"
        return result, None

    # Tissue against background, measured on every section whether it clips or
    # not. This is the measurement the first version of this module lacked: it
    # asked only where the clipping sat, so it called a section "cosmetic" while
    # the background was ten times brighter than the brain. Unscanned corners
    # are exactly zero in both channels and must not count as background.
    scanned = (mark > 0) | (dapi > 0)
    background = (~tissue) & scanned
    tissue_med = float(np.median(mark[tissue]))
    bg_med = float(np.median(mark[background])) if background.sum() > 500 else float("nan")
    result["tissue_median"] = round(tissue_med, 1)
    result["background_median"] = round(bg_med, 1)
    result["contrast"] = round(tissue_med / max(bg_med, 1.0), 3) if np.isfinite(bg_med) else ""
    result["inverted"] = int(np.isfinite(bg_med) and tissue_med < bg_med)

    if sat_fraction < MIN_SAT_FRACTION:
        result["verdict"] = "inverted contrast" if result["inverted"] else "negligible"
        return result, None

    sat_in = sat & tissue
    n_sat = int(sat.sum())
    result["in_tissue_fraction"] = round(float(sat_in.sum()) / max(n_sat, 1), 4)
    result["tissue_coverage"] = round(float(sat_in.sum()) / tissue_px, 4)

    # How deep inside the tissue the clipping sits.
    distance = ndimage.distance_transform_edt(tissue)
    half_width = float(distance.max())
    if half_width > 0 and sat_in.any():
        result["edge_affinity"] = round(float(np.median(distance[sat_in]) / half_width), 4)
        result["tissue_edge_affinity"] = round(float(np.median(distance[tissue]) / half_width), 4)
    else:
        result["edge_affinity"] = ""
        result["tissue_edge_affinity"] = ""

    # Blob sizes: at 5.2 um/px a nucleus is sub-pixel, so anything large is not one.
    labels, n = ndimage.label(sat_in)
    px_um2 = um_px * um_px
    if n:
        sizes = np.array(ndimage.sum(sat_in, labels, range(1, n + 1))) * px_um2
        result["n_blobs"] = int(n)
        result["median_blob_um2"] = round(float(np.median(sizes)), 1)
        result["max_blob_um2"] = round(float(sizes.max()), 1)
        result["frac_area_in_big_blobs"] = round(
            float(sizes[sizes >= BIG_BLOB_UM2].sum() / max(sizes.sum(), 1e-9)), 4)
    else:
        result.update({"n_blobs": 0, "median_blob_um2": "", "max_blob_um2": "",
                       "frac_area_in_big_blobs": ""})

    result["verdict"] = classify(result)
    return result, (mark, dapi, tissue, sat_in)


def classify(r):
    """Cosmetic, or biologically costly?

    Contrast is checked first. A section whose background outshines its tissue
    is broken regardless of where the clipping happens to sit, and calling that
    "mostly outside tissue" is how the first version of this got it wrong.
    """
    if r.get("inverted"):
        return "inverted contrast"
    if isinstance(r.get("contrast"), float) and r["contrast"] < 1.5:
        return "weak contrast"
    if r.get("in_tissue_fraction", 0) < 0.5:
        return "mostly outside tissue"
    if r.get("frac_area_in_big_blobs", 0) >= 0.8:
        # One or a few large clipped regions - a fold, a bubble, an over-exposed
        # field - rather than signal spread through the parenchyma.
        return "large contiguous regions"
    if r.get("tissue_coverage", 0) >= 0.10:
        return "widespread in tissue"
    return "scattered in tissue"


def figure(samples, path):
    n = len(samples)
    fig, axes = plt.subplots(n, 3, figsize=(12, 3.6 * n), squeeze=False)
    for i, (res, imgs) in enumerate(samples):
        mark, dapi, tissue, sat_in = imgs
        axes[i][0].imshow(dapi, cmap="gray"); axes[i][0].set_title(f"{res['scene_uid']} DAPI", fontsize=9)
        axes[i][1].imshow(mark, cmap="gray"); axes[i][1].set_title("marker", fontsize=9)
        axes[i][2].imshow(mark, cmap="gray")
        axes[i][2].contour(tissue, levels=[0.5], colors="#40a0ff", linewidths=0.7)
        overlay = np.zeros(mark.shape + (4,))
        overlay[sat_in] = [1, 0, 0, 0.75]
        axes[i][2].imshow(overlay)
        axes[i][2].set_title(
            f"clipped {100 * res['sat_fraction_frame']:.1f}% of frame, "
            f"{100 * res.get('tissue_coverage', 0):.1f}% of tissue\n{res['verdict']}", fontsize=9)
        for a in axes[i]:
            a.axis("off")
    fig.suptitle("Where the clipping falls - red = clipped, blue = tissue outline", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--figures", type=int, default=8)
    ap.add_argument("--marker", default="AF568")
    ap.add_argument("--proxy", action="store_true",
                    help="measure clipping with the OLD 8-bit >=254 proxy instead "
                         "of the raw masks, writing saturation_<marker>_proxy.csv. "
                         "For reproducing the pre-fix census with current code.")
    args = ap.parse_args()
    _force_proxy[0] = args.proxy
    suffix = "_proxy" if args.proxy else ""
    if args.proxy:
        print("PROXY MODE: measuring clipping the old, wrong way, on purpose.")
    os.makedirs(REPORT_DIR, exist_ok=True)

    with open(QC_CSV, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["marker_channel"] == args.marker]
    print(f"{len(rows)} {args.marker} sections\n")

    results, samples = [], []
    worst = sorted(rows, key=lambda r: -float(r.get("saturated_fraction_raw")
                                               or r["saturated_fraction"] or 0))
    want = {r["scene_uid"] for r in worst[: args.figures]}

    for i, row in enumerate(rows):
        um_px = float(row["um_px"] or 5.2)
        out = analyse(row, um_px)
        if out is None:
            continue
        res, imgs = out
        results.append(res)
        if imgs and res["scene_uid"] in want and len(samples) < args.figures:
            samples.append((res, imgs))
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(rows)}")

    path = os.path.join(REPORT_DIR, f"saturation_{args.marker}{suffix}.csv")
    keys = sorted({k for r in results for k in r})
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(results)
    print(f"\nwrote {path}")

    if samples:
        fig_path = os.path.join(REPORT_DIR, f"saturation_{args.marker}{suffix}.png")
        figure(samples, fig_path)
        print(f"wrote {fig_path}")

    report(results, args.marker)


def report(results, marker):
    print()
    print("=" * 72)

    # Contrast first - it applies to every section, clipped or not.
    contrasts = [r["contrast"] for r in results if isinstance(r.get("contrast"), float)]
    inverted = [r for r in results if r.get("inverted")]
    print(f"{marker}: {len(results)} sections measured")
    if contrasts:
        c = np.array(contrasts)
        print(f"\ntissue / background contrast: median {np.median(c):.2f}  "
              f"p10 {np.percentile(c, 10):.2f}  p90 {np.percentile(c, 90):.2f}")
        print(f"  sections where background is BRIGHTER than tissue: "
              f"{len(inverted)} ({100 * len(inverted) / len(results):.0f}%)")
        print(f"  sections with contrast < 1.5: {int((c < 1.5).sum())} "
              f"({100 * (c < 1.5).mean():.0f}%)")
        if len(inverted) > len(results) * 0.1:
            print("  -> a bright non-tissue field is swamping the signal on a large share of")
            print("     sections. That is an acquisition problem, not a processing one.")

        by_animal = defaultdict(list)
        for r in results:
            if isinstance(r.get("contrast"), float):
                by_animal[r["animal"]].append(r["contrast"])
        print("\ncontrast by animal (median, and % inverted):")
        for a in sorted(by_animal, key=lambda k: np.median(by_animal[k])):
            v = np.array(by_animal[a])
            print(f"  {a:<7} {np.median(v):>6.2f}   {100 * (v < 1).mean():>5.0f}% inverted   (n={len(v)})")

    affected = [r for r in results if r.get("verdict") not in (None, "negligible", "no tissue mask")]
    print(f"\n{len(affected)} sections with a non-negligible verdict")
    if _fallbacks:
        print(f"\n!! {len(_fallbacks)} sections had no raw clipping mask and fell "
              f"back to the 8-bit proxy, which UNDERCOUNTS by roughly 2x.")
        print(f"   Run 01k_saturation_raw.py. First few: {_fallbacks[:5]}")
    print(f"verdicts: {dict(sorted(defaultdict_count(results, 'verdict').items(), key=lambda kv: -kv[1]))}")
    if not affected:
        print("=" * 72)
        return

    print(f"\nverdicts: {dict(sorted(defaultdict_count(affected, 'verdict').items(), key=lambda kv: -kv[1]))}")

    def med(key):
        vals = [r[key] for r in affected if isinstance(r.get(key), (int, float))]
        return float(np.median(vals)) if vals else float("nan")

    print(f"\nof the clipped pixels, median {100 * med('in_tissue_fraction'):.0f}% fall inside tissue")
    print(f"clipping covers a median {100 * med('tissue_coverage'):.1f}% of the tissue area")
    print(f"edge affinity: clipped {med('edge_affinity'):.3f} vs tissue overall {med('tissue_edge_affinity'):.3f}")
    print(f"  (lower than tissue = hugging the rim; similar or higher = inside the parenchyma)")
    print(f"median blob {med('median_blob_um2'):.0f} um2, largest {med('max_blob_um2'):.0f} um2")
    print(f"median share of clipped area sitting in blobs >{BIG_BLOB_UM2:.0f} um2: "
          f"{100 * med('frac_area_in_big_blobs'):.0f}%")

    print("\nby animal:")
    by = defaultdict(list)
    for r in affected:
        by[r["animal"]].append(r)
    for a in sorted(by, key=lambda k: -len(by[k])):
        g = by[a]
        cov = [r["tissue_coverage"] for r in g if isinstance(r.get("tissue_coverage"), (int, float))]
        print(f"  {a:<7} {len(g):>3} sections, median {100 * np.median(cov):.1f}% of tissue clipped, "
              f"top verdict {max(defaultdict_count(g, 'verdict').items(), key=lambda kv: kv[1])[0]}")

    print()
    big = med("frac_area_in_big_blobs")
    depth = med("edge_affinity")
    tissue_depth = med("tissue_edge_affinity")
    # Contrast is judged before clipping location, matching classify(). The two
    # disagreed until now: per-section verdicts said "inverted contrast" while
    # this summary still concluded "largely cosmetic" off the clipping location
    # alone. A summary that contradicts its own rows is worse than no summary.
    if len(inverted) > len(results) * 0.25:
        print("READING: the background outshines the tissue on most sections. Whatever the")
        print("         clipping does, the signal is sitting under a brighter non-tissue")
        print("         field - an acquisition problem that masking cannot undo.")
    elif med("in_tissue_fraction") < 0.5:
        print("READING: most clipping is outside the tissue - debris and mounting medium.")
        print("         Largely cosmetic; mask to tissue and it stops mattering.")
    elif big >= 0.8 and depth < tissue_depth:
        print("READING: clipping is a few large regions hugging the tissue rim - folds and")
        print("         edge artifacts rather than signal. Excludable with a quality mask.")
    elif big >= 0.8:
        print("READING: clipping forms large contiguous regions inside the tissue - whole")
        print("         over-exposed fields. Intensity is unusable there; counts survive only")
        print("         where objects stay separable, which they will not inside those regions.")
    else:
        print("READING: clipping is distributed through the parenchyma. Intensity measures on")
        print("         these sections are dead, and dense nuclei will merge and undercount.")
        print("         Re-scanning the affected slides at lower exposure is the only real fix.")
    print("=" * 72)


def defaultdict_count(rows, key):
    out = defaultdict(int)
    for r in rows:
        out[r.get(key, "")] += 1
    return dict(out)


if __name__ == "__main__":
    main()
