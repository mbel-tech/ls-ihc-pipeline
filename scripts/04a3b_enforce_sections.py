"""Stage 4a3b - force the plate boxes to agree with how many sections a figure holds.

`04a2` proposes boxes from the tissue bands in a merged figure. That works for 42
of the 47 figures and fails on five, in two distinct ways that a band detector
cannot see past:

  **Under-split (34, 35).** Two sections that *touch*. The upper section's
  pituitary hangs into the notch between the lower section's two dorsal humps, so
  they are one connected component - and the legend text runs horizontally across
  the contact zone, so no row is empty either. One band, two sections.

  **Over-split (45, 46, 47).** One section crossed by an internal white band -
  stained brainstem above, pale cerebellum below - read as two bands. Figure 46
  has this on both of its sections, giving four boxes for two.

Neither is recoverable from the image, so the count comes from `config.json`
(`atlas_figure_sections`), where it is recorded as operator knowledge with the
date and the reason. **The declared count is the authority and the detector is
not**; this script only decides *where* to cut, never *how many* times.

Merging is unambiguous - take the boxes in y order and union the pair separated
by the smallest gap, repeatedly, until the count is right.

Splitting is not, so it is done the way the neighbouring figures already are:
**the two boxes overlap.** Figures 31-44 as drawn overlap by 0.005-0.015 of their
height. A single cut line through touching sections would slice the pituitary off
one plate or the humps off the other; an overlap gives each box its whole section
and costs only a sliver of the neighbour at the edge. The split figures are
flagged `review=1` on export so they can be nudged in `04a3`.

Nothing is done in place. The previous `plate_boxes.csv` is kept as
`plate_boxes.prev.csv`, and figures with no declared count are copied through
untouched - a figure the operator drew by hand stays exactly as drawn.

Run:  python 04a3b_enforce_sections.py            # report only
      python 04a3b_enforce_sections.py --apply    # rewrite plate_boxes.csv
"""

import argparse
import csv
import json
import os
import shutil
from collections import defaultdict

import numpy as np
from PIL import Image
from scipy import ndimage

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
ATLAS_DIR = os.path.join(OUT_ROOT, "atlas")
MERGED_DIR = os.path.join(ATLAS_DIR, "plates_merged")
BOXES_CSV = os.path.join(ATLAS_DIR, "plate_boxes.csv")
PREV_CSV = os.path.join(ATLAS_DIR, "plate_boxes.prev.csv")

# How far the two boxes of a split figure are allowed to overlap, as a fraction
# of figure height. Matched to what figures 31-44 already do rather than tuned.
OVERLAP = 0.045


def declared_counts():
    """Figure id -> number of sections, expanded from the config range."""
    spec = CONFIG.get("atlas_figure_sections", {})
    out = {}
    rng = spec.get("two_sections")
    if rng:
        a, b = (int(v) for v in rng.split("-"))
        for n in range(a, b + 1):
            out[f"mplate_{n:03d}"] = 2
    return out


def tissue_waist(path):
    """Row where the tissue is narrowest, ignoring the legend.

    The legend is not part of the largest connected component, so taking that
    component alone removes the text that otherwise bridges the two sections.
    The waist is the narrowest row of what remains - the stalk between them.
    """
    a = np.asarray(Image.open(path).convert("L"), float)
    h, w = a.shape
    ink = ndimage.binary_closing(a < 200, np.ones((5, 5)))
    lab, k = ndimage.label(ink)
    if k == 0:
        return 0.5
    sz = ndimage.sum(ink, lab, range(1, k + 1))
    prof = (lab == (int(np.argmax(sz)) + 1)).sum(axis=1) / w
    lo, hi = int(0.35 * h), int(0.65 * h)
    return (lo + int(np.argmin(prof[lo:hi]))) / h


def merge_to(boxes, want):
    """Union the closest pair, repeatedly, until `want` boxes remain."""
    b = [list(map(float, x)) for x in boxes]
    b.sort(key=lambda r: r[1])
    while len(b) > want:
        gaps = [b[i + 1][1] - b[i][3] for i in range(len(b) - 1)]
        i = int(np.argmin(gaps))
        b[i] = [min(b[i][0], b[i + 1][0]), min(b[i][1], b[i + 1][1]),
                max(b[i][2], b[i + 1][2]), max(b[i][3], b[i + 1][3])]
        del b[i + 1]
    return b


def split_to_two(box, waist):
    """Two overlapping boxes from one, cut at the waist. See the module docstring."""
    x0, y0, x1, y1 = (float(v) for v in box)
    cut = y0 + waist * (y1 - y0) if (y1 - y0) < 1.0 else waist
    return [[x0, y0, x1, min(y1, cut + OVERLAP)],
            [x0, max(y0, cut - 0.01), x1, y1]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="rewrite plate_boxes.csv")
    args = ap.parse_args()

    if not os.path.exists(BOXES_CSV):
        raise SystemExit(f"{BOXES_CSV} not found - export from 04a3_plate_reframe.py first")

    with open(os.path.join(MERGED_DIR, "plates.csv"), newline="", encoding="utf-8") as fh:
        figs = {r["plate_id"]: r for r in csv.DictReader(fh)}
    with open(BOXES_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    per = defaultdict(list)
    for r in rows:
        per[r["figure_id"]].append(r)

    want = declared_counts()
    drop = CONFIG.get("atlas_figure_sections", {}).get("drop_inset_boxes", {})

    out, changed, review = [], [], []
    for fid in sorted(per, key=lambda k: int(k.split("_")[1])):
        cur = sorted(per[fid], key=lambda r: float(r["y0_frac"]))
        page = cur[0]["page"]
        boxes = [[float(r["x0_frac"]), float(r["y0_frac"]),
                  float(r["x1_frac"]), float(r["y1_frac"])] for r in cur]
        note = ""

        if fid in drop:
            i = int(drop[fid]) - 1
            if 0 <= i < len(boxes):
                boxes.pop(i)
                note = f"dropped inset box {i + 1}"
        elif fid in want:
            n = want[fid]
            if len(boxes) > n:
                boxes = merge_to(boxes, n)
                note = f"merged {len(cur)} -> {n}"
            elif len(boxes) < n and len(boxes) == 1:
                w = tissue_waist(os.path.join(MERGED_DIR, figs[fid]["image_file"]))
                boxes = split_to_two(boxes[0], w)
                note = f"split 1 -> 2 at waist {w:.3f}, overlapping"
                review.append(fid)

        if note:
            changed.append((fid, len(cur), len(boxes), note))
        for i, b in enumerate(boxes):
            out.append({"figure_id": fid, "page": page, "box": i + 1,
                        "x0_frac": f"{b[0]:.5f}", "y0_frac": f"{b[1]:.5f}",
                        "x1_frac": f"{b[2]:.5f}", "y1_frac": f"{b[3]:.5f}",
                        "edited": cur[0].get("edited", "0"),
                        "review": 1 if fid in review else 0})

    print("=" * 74)
    for fid, a, b, note in changed:
        print(f"  {fid}  {a} -> {b} box(es)   {note}")
    if not changed:
        print("  nothing to change - every declared figure already agrees")
    print()
    print(f"  {len(rows)} boxes -> {len(out)}; {len(changed)} figures touched, "
          f"{len(per) - len(changed)} left exactly as drawn")

    if not args.apply:
        print()
        print("  report only - re-run with --apply to write it")
        print("=" * 74)
        return

    shutil.copyfile(BOXES_CSV, PREV_CSV)
    with open(BOXES_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print()
    print(f"  wrote {BOXES_CSV}   (previous kept as {os.path.basename(PREV_CSV)})")
    if review:
        print(f"  {', '.join(review)} were SPLIT and are flagged review=1 - the cut is")
        print("  an estimate through touching tissue. Check them in 04a3 before trusting.")
    print()
    print("  then: python 04a4_plate_rebuild.py --dpi 300")
    print("=" * 74)


if __name__ == "__main__":
    main()
