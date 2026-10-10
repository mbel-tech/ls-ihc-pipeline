"""Stage 4w - build the Wullimann 1996 plate set the curators can read.

The salmon atlas reaches the pipeline through 04a (extract the plates and their
colour-coded seeds from the PDF). The Wullimann 1996 zebrafish atlas has no
seeds, and its plates were already cut out of the PDF into

    atlas/wullimann1996/   pNN_cross_<level>.png   one image per cross section
                           legends.csv             abbreviation + definition
                           index.csv               page and size per image

so this stage only arranges them into the layout every later stage reads:

    <out_root>/atlas/plates_wullimann/
        plates.csv        plate_id, page, image_file, px_w, px_h, n_seeds,
                          regions, section_level, midline_frac
        seeds.csv         header only - 04l loads it, and the regions come from
                          polygons.csv (04x) instead
        wplate_023.png ...  the plate as printed
        wplate_023_micrograph.png ...  the right half, for inspection (04e crops the
                          plate itself, from midline_frac)

Plate ids are zero-padded section numbers (wplate_023 ... wplate_363). The
curators order plates by sorting `plate_id` and store that position, so ids must
sort the way the sections run, rostral to caudal; "cross_100" would sort before
"cross_23". `section_level` keeps the real number, because Wullimann's sections
are not evenly spaced (steps of 8 to 21) and a position in a list says nothing
about distance.

Each plate is a gray panel: the outline drawing of one hemisphere on the left,
the stippled micrograph of the other on the right. `midline_frac` is where they
meet, as a fraction of the width; 04x reads the drawing to its left and 04l mirrors
polygons about it.

The plates are not ours to redistribute, so nothing here goes in git - the
`atlas/` folder is ignored.

Run:  python 04w_wullimann_plates.py [--src DIR] [--out DIR]
"""

import argparse
import csv
import importlib.util
import json
import os
import re
import shutil

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
_lsio = importlib.util.spec_from_file_location("_lsio", os.path.join(HERE, "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

PLATE_KEYS = ["plate_id", "page", "image_file", "px_w", "px_h", "n_seeds",
              "regions", "section_level", "midline_frac"]
SEED_KEYS = ["plate_id", "page", "plate_seq", "region", "region_raw", "is_unknown",
             "colour_hex", "from_raster", "x_px", "y_px", "x_frac", "y_frac"]
CROSS_RE = re.compile(r"^p(\d+)_cross_(\d+)\.png$")

# The drawing's white interior ends at the midline; the micrograph beyond it is
# gray stipple. White = above this, and a column counts as drawing when more than
# WHITE_COL of its rows are white. Measured on the real plates: the edge sits at
# 0.50-0.52 of the width.
WHITE = 240
WHITE_COL = 0.08
MID_RANGE = (0.40, 0.62)


def midline_frac(path):
    """Where the drawing half ends, as a fraction of the image width.

    Falls back to 0.5 and says so when the measurement lands outside any
    plausible range - a wrong midline would mirror polygons onto the wrong place
    without any error to show it.
    """
    im = np.asarray(Image.open(path).convert("L"))
    h, w = im.shape
    colw = (im[int(h * 0.1):int(h * 0.9)] > WHITE).mean(axis=0)
    xs = np.where(colw[:int(w * 0.7)] > WHITE_COL)[0]
    if len(xs) == 0:
        return 0.5, False
    f = (xs.max() + 1) / float(w)
    if not (MID_RANGE[0] <= f <= MID_RANGE[1]):
        return 0.5, False
    return round(f, 4), True


def load_legends(path):
    """{section: [abbreviation, ...]} in legend order."""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(int(r["cross_section"]), []).append(r["abbreviation"])
    return out


def build(src, out_dir):
    legends = load_legends(os.path.join(src, "legends.csv"))
    plates = []
    for name in sorted(os.listdir(src)):
        m = CROSS_RE.match(name)
        if m:
            plates.append((int(m.group(2)), int(m.group(1)), name))
    if not plates:
        raise SystemExit("no pNN_cross_<level>.png plates in %s" % src)
    plates.sort()
    levels = [p[0] for p in plates]
    if len(set(levels)) != len(levels):
        raise SystemExit("two plates carry the same section number: %s"
                         % sorted(l for l in set(levels) if levels.count(l) > 1))
    os.makedirs(out_dir, exist_ok=True)
    rows, bad_mid = [], []
    for level, page, name in plates:
        pid = "wplate_%03d" % level
        img = "%s.png" % pid
        shutil.copyfile(os.path.join(src, name), os.path.join(out_dir, img))
        mid, ok = midline_frac(os.path.join(src, name))
        if not ok:
            bad_mid.append(pid)
        im = Image.open(os.path.join(src, name))
        w, h = im.size
        im.crop((int(round(mid * w)), 0, w, h)).save(
            os.path.join(out_dir, "%s_micrograph.png" % pid))
        regs = legends.get(level, [])
        rows.append({"plate_id": pid, "page": page, "image_file": img, "px_w": w,
                     "px_h": h, "n_seeds": 0,
                     "regions": "|".join(sorted(set(regs))),
                     "section_level": level, "midline_frac": mid})
    IO.atomic_write_csv(os.path.join(out_dir, "plates.csv"), rows, PLATE_KEYS)
    IO.atomic_write_csv(os.path.join(out_dir, "seeds.csv"), [], SEED_KEYS)
    missing = [r["plate_id"] for r in rows if not r["regions"]]
    return rows, bad_mid, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", help="folder holding the extracted plates "
                    "(default: <repo>/atlas/wullimann1996)")
    ap.add_argument("--out", help="output plate-set folder "
                    "(default: <out_root>/atlas/plates_wullimann)")
    args = ap.parse_args()
    src = args.src or os.path.join(os.path.dirname(HERE), "atlas", "wullimann1996")
    out_dir = args.out
    if not out_dir:
        cfg_path = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(HERE), "config.json")
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        out_dir = os.path.join(cfg["out_root"], "atlas", IO.WULLIMANN_SET)
    rows, bad_mid, missing = build(src, out_dir)
    print("%d plates -> %s" % (len(rows), out_dir))
    print("sections %d .. %d" % (rows[0]["section_level"], rows[-1]["section_level"]))
    if bad_mid:
        print("midline not measurable on %d plates, 0.5 used: %s" % (len(bad_mid), ", ".join(bad_mid)))
    if missing:
        print("no legend for: %s" % ", ".join(missing))


if __name__ == "__main__":
    main()
