"""Stage 4a2 - rebuild the atlas plates, merging PDF image strips into whole plates.

`04a_atlas_extract.py` treated every image XObject in the PDF as one plate. PDFs
routinely store a single large bitmap as several horizontal **strips**, each its
own XObject, and this atlas does exactly that. The extraction therefore produced
half-sections and quarter-sections as if they were plates.

Measured on the source PDF: **101 XObjects, but only 47 actual plates.** More than
half the reference set was a fragment of another plate. Detected exactly rather
than heuristically - strips of one image share their x-range to within 2 pt and
abut in y with a gap of **0.00 pt**:

    page 8:  x 106.0-507.4  y 424.1-587.2   px 1226x498
             x 106.0-507.4  y 587.2-750.1   px 1226x498     <- same image

That explains more than it first appears. `04c` was scoring sections against a
reference set in which over half the entries were partial sections, which is a
large part of why the level signal never appeared.

Images are produced by **rendering the page region**, not by stitching the
extracted strips: rendering composites whatever transform the PDF applies, so the
result is what the plate actually looks like on the page.

Region seeds are remapped exactly. A seed is stored as a fraction of its old
strip; that fraction times the old strip bbox gives a point in PDF page
coordinates, which is then expressed as a fraction of the merged plate. No
approximation anywhere.

Nothing is overwritten. Output goes to `atlas/plates_merged/`, alongside the
originals, so the merge can be reviewed before anything is pointed at it.

Run:  python 04a2_atlas_remerge.py --dry-run
      python 04a2_atlas_remerge.py --dpi 300
"""

import argparse
import csv
import json
import os
from collections import Counter

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
ATLAS_PDF = CONFIG["atlas_pdf"]
PLATE_DIR = os.path.join(OUT_ROOT, "atlas", "plates")
OUT_DIR = os.path.join(OUT_ROOT, "atlas", "plates_merged")

ABUT_TOL = 2.0      # pt - strips of one image abut at 0.00 in this PDF
X_TOL = 2.0         # pt - and share their x-range exactly


def page_groups(page):
    """Image XObjects on a page, grouped into whole plates.

    A group is a run of boxes sharing an x-range and abutting vertically.
    Returned top to bottom, which is how the plates read on the page.
    """
    boxes = []
    for it in page.get_images(full=True):
        try:
            b = page.get_image_bbox(it)
        except Exception:                                        # noqa: BLE001
            continue
        if b.is_empty or b.width <= 0 or b.height <= 0:
            continue
        boxes.append({"bbox": b, "px_w": it[2], "px_h": it[3]})
    boxes.sort(key=lambda t: (round(t["bbox"].x0, 1), round(t["bbox"].y0, 1)))

    used = [False] * len(boxes)
    groups = []
    for i, bi in enumerate(boxes):
        if used[i]:
            continue
        grp = [bi]
        used[i] = True
        cur = bi["bbox"]
        while True:
            nxt = None
            for j, bj in enumerate(boxes):
                if used[j]:
                    continue
                b = bj["bbox"]
                if (abs(b.x0 - cur.x0) < X_TOL and abs(b.x1 - cur.x1) < X_TOL
                        and abs(b.y0 - cur.y1) < ABUT_TOL):
                    nxt = j
                    break
            if nxt is None:
                break
            grp.append(boxes[nxt])
            used[nxt] = True
            cur = boxes[nxt]["bbox"]
        groups.append(grp)
    groups.sort(key=lambda g: (round(g[0]["bbox"].y0, 1), round(g[0]["bbox"].x0, 1)))
    return groups


def main():
    import fitz
    ap = argparse.ArgumentParser()
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    doc = fitz.open(ATLAS_PDF)
    with open(os.path.join(PLATE_DIR, "plates.csv"), newline="", encoding="utf-8") as fh:
        old_rows = list(csv.DictReader(fh))
    old = {}
    for r in old_rows:
        old.setdefault(int(r["page"]), []).append(r)

    if not args.dry_run:
        os.makedirs(OUT_DIR, exist_ok=True)

    plates, mapping = [], {}
    n = 0
    for pno in range(doc.page_count):
        page = doc[pno]
        groups = page_groups(page)
        if not groups:
            continue
        olds = sorted(old.get(pno + 1, []), key=lambda r: int(r["index_on_page"]))
        oi = 0
        for gi, grp in enumerate(groups):
            x0 = min(g["bbox"].x0 for g in grp)
            x1 = max(g["bbox"].x1 for g in grp)
            y0 = min(g["bbox"].y0 for g in grp)
            y1 = max(g["bbox"].y1 for g in grp)
            n += 1
            pid = f"mplate_{n:03d}"
            name = f"{pid}_p{pno + 1:02d}_{gi}.png"
            if args.dry_run:
                sc = args.dpi / 72.0
                pw, ph = int((x1 - x0) * sc), int((y1 - y0) * sc)
            else:
                pm = page.get_pixmap(clip=fitz.Rect(x0, y0, x1, y1), dpi=args.dpi)
                pm.save(os.path.join(OUT_DIR, name))
                pw, ph = pm.width, pm.height
            plates.append({"plate_id": pid, "page": pno + 1, "index_on_page": gi,
                           "image_file": name, "px_w": pw, "px_h": ph,
                           "n_strips": len(grp),
                           "x0": round(x0, 2), "y0": round(y0, 2),
                           "x1": round(x1, 2), "y1": round(y1, 2)})
            for g in grp:
                if oi < len(olds):
                    b = g["bbox"]
                    mapping[olds[oi]["plate_id"]] = {
                        "new": pid,
                        "ob": (b.x0, b.y0, b.x1, b.y1),
                        "nb": (x0, y0, x1, y1)}
                    oi += 1

    print(f"{len(old_rows)} extracted XObjects -> {len(plates)} merged plates")
    multi = [p for p in plates if p["n_strips"] > 1]
    print(f"  plates assembled from more than one strip: {len(multi)}")
    c = Counter(p["n_strips"] for p in plates)
    print("  strips per plate: " + ", ".join(f"{k} -> {v}" for k, v in sorted(c.items())))
    if args.dry_run:
        print("\n(dry run - nothing written)")
        return

    with open(os.path.join(OUT_DIR, "plates.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(plates[0].keys()))
        w.writeheader()
        w.writerows(plates)

    sp = os.path.join(PLATE_DIR, "seeds.csv")
    moved, lost = [], 0
    if os.path.exists(sp):
        with open(sp, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                m = mapping.get(r["plate_id"])
                if not m:
                    lost += 1
                    continue
                ox0, oy0, ox1, oy1 = m["ob"]
                nx0, ny0, nx1, ny1 = m["nb"]
                px = ox0 + float(r["x_frac"]) * (ox1 - ox0)
                py = oy0 + float(r["y_frac"]) * (oy1 - oy0)
                moved.append({**r, "plate_id": m["new"],
                              "x_frac": round((px - nx0) / (nx1 - nx0), 6),
                              "y_frac": round((py - ny0) / (ny1 - ny0), 6)})
        if moved:
            with open(os.path.join(OUT_DIR, "seeds.csv"), "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(moved[0].keys()))
                w.writeheader()
                w.writerows(moved)

    seeded = len({r["plate_id"] for r in moved})
    print(f"\n  seeds remapped: {len(moved)} onto {seeded} plates ({lost} unmapped)")
    print(f"  wrote {OUT_DIR}")
    print()
    print("Seeds carry exactly: a fraction of the old strip becomes a point in PDF")
    print("page coordinates, then a fraction of the merged plate.")
    print()
    print("NOTHING is overwritten - the originals stay in atlas/plates/. Review the")
    print("merged plates before pointing anything at them.")


if __name__ == "__main__":
    main()
