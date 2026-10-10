"""Stage 4a4 - render final atlas plates from the reframed boxes.

Consumes `atlas/plate_boxes.csv` from `04a3_plate_reframe.py` and produces the
plate set everything downstream should use: `atlas/plates_final/`.

Each box is a fraction of a merged figure, and each merged figure has a known
rectangle in PDF page coordinates, so a box maps to a page rectangle exactly and
the crop is **rendered from the PDF** rather than resampled from an already-lossy
JPEG.

Seeds carry across the same way: a seed is a fraction of its figure, which gives
a point in the figure, which falls inside exactly one box and becomes a fraction
of that box. A seed inside no box is **reported, not silently dropped** - it
usually means a box was drawn too tight.

Run:  python 04a4_plate_rebuild.py --dpi 300
"""

import sys
import argparse
import csv
import json
import os
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402

OUT_ROOT = CONFIG["out_root"]
ATLAS_PDF = CONFIG["atlas_pdf"]
ATLAS_DIR = os.path.join(OUT_ROOT, "atlas")
MERGED_DIR = os.path.join(ATLAS_DIR, "plates_merged")
BOXES_CSV = os.path.join(ATLAS_DIR, "plate_boxes.csv")
OUT_DIR = os.path.join(ATLAS_DIR, "plates_final")


def main():
    import fitz
    ap = argparse.ArgumentParser()
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args()

    if not os.path.exists(BOXES_CSV):
        raise SystemExit(f"{BOXES_CSV} not found - export from 04a3_plate_reframe.py first")

    with open(os.path.join(MERGED_DIR, "plates.csv"), newline="", encoding="utf-8") as fh:
        figs = {r["plate_id"]: r for r in csv.DictReader(fh)}
    with open(BOXES_CSV, newline="", encoding="utf-8") as fh:
        boxes = list(csv.DictReader(fh))
    seeds = []
    sp = os.path.join(MERGED_DIR, "seeds.csv")
    if os.path.exists(sp):
        with open(sp, newline="", encoding="utf-8") as fh:
            seeds = list(csv.DictReader(fh))
    by_fig = defaultdict(list)
    for s in seeds:
        by_fig[s["plate_id"]].append(s)

    os.makedirs(OUT_DIR, exist_ok=True)
    doc = fitz.open(ATLAS_PDF)

    plates, new_seeds, orphan = [], [], []
    n = 0
    for b in sorted(boxes, key=lambda r: (r["figure_id"], int(r["box"]))):
        f = figs.get(b["figure_id"])
        if f is None:
            continue
        fx0, fy0 = float(f["x0"]), float(f["y0"])
        fw, fh = float(f["x1"]) - fx0, float(f["y1"]) - fy0
        bx0, by0 = float(b["x0_frac"]), float(b["y0_frac"])
        bx1, by1 = float(b["x1_frac"]), float(b["y1_frac"])
        rect = fitz.Rect(fx0 + bx0 * fw, fy0 + by0 * fh,
                         fx0 + bx1 * fw, fy0 + by1 * fh)
        n += 1
        pid = f"plate_{n:03d}"
        name = f"{pid}_p{int(f['page']):02d}.png"
        pm = doc[int(f["page"]) - 1].get_pixmap(clip=rect, dpi=args.dpi)
        pm.save(os.path.join(OUT_DIR, name))
        plates.append({"plate_id": pid, "page": int(f["page"]),
                       "source_figure": b["figure_id"], "box": int(b["box"]),
                       "image_file": name, "px_w": pm.width, "px_h": pm.height,
                       "x0": round(rect.x0, 2), "y0": round(rect.y0, 2),
                       "x1": round(rect.x1, 2), "y1": round(rect.y1, 2)})

        for s in by_fig.get(b["figure_id"], []):
            sx, sy = float(s["x_frac"]), float(s["y_frac"])
            if not (bx0 <= sx <= bx1 and by0 <= sy <= by1):
                continue
            new_seeds.append({**s, "plate_id": pid,
                              "x_frac": round((sx - bx0) / (bx1 - bx0), 6),
                              "y_frac": round((sy - by0) / (by1 - by0), 6)})

    placed = {(s["page"], s["region"], s["x_px"], s["y_px"]) for s in new_seeds}
    for s in seeds:
        if (s["page"], s["region"], s["x_px"], s["y_px"]) not in placed:
            orphan.append(s)

    with open(os.path.join(OUT_DIR, "plates.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(plates[0].keys()))
        w.writeheader()
        w.writerows(plates)
    if new_seeds:
        with open(os.path.join(OUT_DIR, "seeds.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(new_seeds[0].keys()))
            w.writeheader()
            w.writerows(new_seeds)

    seeded = len({s["plate_id"] for s in new_seeds})
    print("=" * 74)
    print(f"{len(plates)} plates -> {OUT_DIR}")
    print(f"  seeds carried : {len(new_seeds)} onto {seeded} plates")
    if orphan:
        print()
        print(f"  {len(orphan)} seed(s) fell inside NO box and were left behind:")
        for k, v in Counter((s['plate_id'], s['region']) for s in orphan).most_common(10):
            print(f"      {k[0]} {k[1]} x{v}")
        print("  That usually means a box was drawn too tight. Widen it in 04a3 and")
        print("  re-run - the seeds are not lost, they are just outside every crop.")
    print()
    print("Point the ROI curator at this set by pointing PLATE_DIR in")
    print("04l_roi_curator.py at plates_final. Nothing is overwritten.")
    print("=" * 74)


if __name__ == "__main__":
    main()
