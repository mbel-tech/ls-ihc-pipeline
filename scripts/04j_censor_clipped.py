"""Stage 4j - censor clipped pERK pixels and fix the pERK analysis set.

AF568 clipping is information loss, not miscalibration: a pixel pinned at the
16-bit ceiling has lost its value and no normalisation recovers it. See LOGS.md -
restricted to clip-free sections the two apparent "staining batches" turn out to
be identical, so the whole 1.86x background gap is produced by the clipping
itself.

Two mechanisms, and they are deliberately separate because they mean different
things:

**Section level - a 1% tolerance.** Sections with 1% or more of pixels at the
ceiling are set aside. Not deleted: recorded in `perk_analysis_set.csv` with
`in_analysis_set = 0`, so the decision is visible and reversible.

**Pixel level - censoring, not masking.** Within the sections that stay, clipped
pixels are marked as **right-censored**: their true value is unknown but at least
the ceiling.

*That is not the same as the artifact mask and must not be treated as it.* An
artifact pixel is not tissue and should leave the analysis entirely. A censored
pixel is real signal that happens to be unmeasurable, so:

  * it MUST be excluded from any intensity statistic - mean, median, the negative
    peak UniFORM aligns on - because including a floor value biases every one of
    them downward;
  * it MUST NOT be excluded from detection or from positivity, because a pixel at
    the ceiling is unambiguously positive. Dropping it would bias positive counts
    *down* in exactly the animals with the brightest staining.

Getting that backwards would turn a data-quality problem into a group difference.

Where the mask comes from
-------------------------

The AF568 display range recorded in `qc/display_ranges.json` is `lo 1070,
hi 65535` - the display high **is** the 16-bit ceiling. So in the exported 8-bit
marker overview, value 255 corresponds to 16-bit >= 65535, which is exactly the
clipped set. Verified against `saturated_fraction` in `focus.csv`, computed
independently on the 16-bit data at export: median absolute difference over 12
random sections is **0.00000**.

This does not generalise. DAPI (hi 27993) and AF488 (hi 37263) have display highs
below the ceiling, so 255 there means "at or above the display high", not
"clipped". The trick works for AF568 and only because its display high saturated.

Run:  python 04j_censor_clipped.py
      python 04j_censor_clipped.py --tolerance 0.005
"""

import argparse
import csv
import json
import os

import numpy as np
from PIL import Image

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
CENSOR_DIR = os.path.join(OUT_ROOT, "censor")
OUT_CSV = os.path.join(REFORMAT_DIR, "perk_analysis_set.csv")

MARKER = "AF568"
CEILING_8BIT = 255       # only valid because the AF568 display high is 65535
TOLERANCE = 0.01         # section-level: 1% of pixels at the ceiling


def censor_mask(png_path):
    """Right-censored pixels: at the 16-bit ceiling, value unknown but >= it."""
    try:
        m = np.asarray(Image.open(png_path).convert("L"))
    except OSError:
        return None
    return m >= CEILING_8BIT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tolerance", type=float, default=TOLERANCE,
                    help="section is set aside at or above this clipped fraction")
    args = ap.parse_args()
    os.makedirs(CENSOR_DIR, exist_ok=True)

    foc = {r["scene_uid"]: r for r in csv.DictReader(open(QC_CSV, encoding="utf-8"))}
    with open(os.path.join(REFORMAT_DIR, f"reformat_index_{MARKER}.csv"),
              newline="", encoding="utf-8") as fh:
        kept = [r for r in csv.DictReader(fh) if r["kind"] == "section"]

    rows = []
    for i, r in enumerate(kept, 1):
        uid, animal = r["id"], r["animal"]
        mark = os.path.join(OVERVIEW_DIR, animal, MARKER, uid + "_MARK.png")
        dapi = os.path.join(OVERVIEW_DIR, animal, MARKER, uid + "_DAPI.png")
        cen = censor_mask(mark)
        if cen is None:
            continue
        tis = np.asarray(Image.open(dapi).convert("L")) > 0 if os.path.exists(dapi) else None

        frac_frame = float(cen.mean())
        frac_tissue = float(cen[tis].mean()) if tis is not None and tis.any() else float("nan")
        recorded = float(foc.get(uid, {}).get("saturated_fraction", "nan") or "nan")

        # Written for every section, including the ones set aside - a later stage
        # may want to know what it is missing.
        Image.fromarray((cen * 255).astype(np.uint8)).save(
            os.path.join(CENSOR_DIR, uid + "_censor.png"))

        rows.append({
            "scene_uid": uid, "animal": animal, "section_order": r["section_order"],
            "censored_fraction": round(frac_frame, 6),
            "censored_fraction_in_tissue": round(frac_tissue, 6),
            "recorded_saturated_fraction": recorded,
            "in_analysis_set": int(frac_frame < args.tolerance),
            "reason": "" if frac_frame < args.tolerance
                      else f"{100 * frac_frame:.1f}% of pixels at the 16-bit ceiling "
                           f"(tolerance {100 * args.tolerance:.0f}%)",
        })
        if i % 100 == 0:
            print(f"\r  {i}/{len(kept)}", end="")
    print(f"\r  measured {len(rows)} pERK sections        ")

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    keep = [r for r in rows if r["in_analysis_set"]]
    drop = [r for r in rows if not r["in_analysis_set"]]
    cf = np.array([r["censored_fraction"] for r in keep])
    print()
    print("=" * 74)
    print(f"{len(rows)} pERK sections -> {OUT_CSV}")
    print(f"  in the analysis set (< {100 * args.tolerance:.0f}% clipped) : "
          f"{len(keep)} ({100 * len(keep) / len(rows):.0f}%)")
    print(f"  set aside                                : {len(drop)}")
    print(f"  censor masks written to {CENSOR_DIR}/<uid>_censor.png")
    if len(cf):
        print()
        print(f"  within the analysis set, censored fraction: median {np.median(cf):.5f}, "
              f"p95 {np.percentile(cf, 95):.5f}, max {cf.max():.5f}")
        print(f"  sections with NO censored pixels at all   : {int((cf == 0).sum())}")

    per = {}
    for r in rows:
        d = per.setdefault(r["animal"], [0, 0])
        d[0] += 1
        d[1] += r["in_analysis_set"]
    print()
    print(f"  {'animal':<8}{'pERK':>7}{'in set':>8}{'%':>6}")
    for a in sorted(per, key=lambda x: int(x[2:])):
        t, k = per[a]
        print(f"  {a:<8}{t:>7}{k:>8}{100 * k / t:>5.0f}%")
    lost = [a for a, (t, k) in per.items() if k == 0]
    if lost:
        print(f"\n  ANIMALS WITH NOTHING LEFT: {', '.join(sorted(lost))}")
        print("  They cannot contribute to the pERK analysis at any tolerance that")
        print("  excludes them; that is a decision about n, not about thresholds.")
    print()
    print("Censored != masked. A clipped pixel is real signal whose value is lost:")
    print("  exclude it from intensity statistics, KEEP it for detection and")
    print("  positivity. Dropping it from counts would bias positive rates DOWN in")
    print("  exactly the animals with the brightest staining.")
    print("=" * 74)


if __name__ == "__main__":
    main()
