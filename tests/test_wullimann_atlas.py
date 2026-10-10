"""The Wullimann atlas as an alternative to the salmon one.

Covers the pieces that are not a page: choosing the atlas from config, the
plate-set builder (04w), the outline-to-polygon extractor (04x) and the shared
polygon contract (atlas_polygons.py). Everything is built from synthetic images
in a temp folder - no atlas, no PDF, no tesseract needed.

Run:  python tests/test_wullimann_atlas.py
"""

import csv
import importlib.util
import os
import shutil
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")


sys.path.insert(0, HERE)
from _fixture import use_temp_study  # noqa: E402
use_temp_study(atlas_source="wullimann1996")   # 04w/04x read config on import, like every stage


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AP = load("ap", "atlas_polygons.py")
W04 = load("w04", "04w_wullimann_plates.py")
X04 = load("x04", "04x_wullimann_polygons.py")

fails = 0


def chk(label, got, want=True):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(60) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


def raises(fn):
    try:
        fn()
    except (SystemExit, ValueError):
        return True
    return False


# ---- choosing the atlas --------------------------------------------------------
sys.path.insert(0, SCRIPTS)
import ls_atlas as AT  # noqa: E402

chk("default source is salmon", AT.source({}), "salmon")
chk("salmon keeps the configured plate set",
    AT.set_name({"atlas_plate_set": {"dir": "plates_final"}}), "plates_final")
chk("salmon default plate set", AT.set_name({}), "plates")
chk("wullimann ignores atlas_plate_set",
    AT.set_name({"atlas_source": "wullimann1996", "atlas_plate_set": {"dir": "plates_final"}}),
    "plates_wullimann")
chk("plate_dir follows the source",
    AT.plate_dir({"out_root": "/o", "atlas_source": "wullimann1996"}).replace("\\", "/"),
    "/o/atlas/plates_wullimann")
chk("unknown source is an error, not a silent salmon",
    raises(lambda: AT.source({"atlas_source": "zebra"})))
chk("salmon reformatted plates folder unchanged", AT.reformatted_dir({}), "plates")
chk("wullimann has its own reformatted folder",
    AT.reformatted_dir({"atlas_source": "wullimann1996"}), "plates_wullimann")
chk("wullimann ids sort the way the sections run",
    [r["plate_id"] for r in AT.plate_order([{"plate_id": "wplate_100"}, {"plate_id": "wplate_023"},
                                              {"plate_id": "wplate_050"}])],
    ["wplate_023", "wplate_050", "wplate_100"])


# ---- synthetic plate -------------------------------------------------------------
def make_plate(path, w=400, h=300):
    """Gray panel; white drawing half with three outlined regions; stipple right.

    A: large, touching the midline (like Dm). B: small, inside A's neighbour.
    C: separate, lower left. All outlined in black, 2 px.
    """
    im = np.full((h, w), 190, np.uint8)
    mid = w // 2
    im[20:h - 20, 20:mid] = 255                       # drawing half, white
    rng = np.random.RandomState(0)
    im[20:h - 20, mid:w - 20] = rng.randint(60, 200, (h - 40, w - 20 - mid))   # micrograph
    def box(x0, y0, x1, y1):
        im[y0:y1, x0:x1] = 255
        im[y0:y0 + 2, x0:x1] = 0
        im[y1 - 2:y1, x0:x1] = 0
        im[y0:y1, x0:x0 + 2] = 0
        im[y0:y1, x1 - 2:x1] = 0
    # the outer outline of the drawing, so regions are enclosed
    im[20:22, 20:mid] = 0
    im[h - 22:h - 20, 20:mid] = 0
    im[20:h - 20, 20:22] = 0
    im[20:h - 20, mid - 2:mid] = 0
    box(120, 40, mid, 150)        # A touches the midline wall
    box(40, 40, 110, 120)         # B
    box(40, 160, 180, 270)        # C
    Image.fromarray(im).save(path)


tmp = tempfile.mkdtemp()
try:
    src = os.path.join(tmp, "src")
    os.makedirs(src)
    make_plate(os.path.join(src, "p03_cross_100.png"))
    make_plate(os.path.join(src, "p04_cross_23.png"))
    with open(os.path.join(src, "legends.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["cross_section", "pdf_page", "abbreviation", "definition"])
        for sec, pg in ((23, 4), (100, 3)):
            for ab in ("Dm", "Dl", "V"):
                w.writerow([sec, pg, ab, "x"])
    out = os.path.join(tmp, "plates_wullimann")
    rows, bad_mid, missing = W04.build(src, out)

    # ---- 04w ----------------------------------------------------------------
    ids = [r["plate_id"] for r in rows]
    chk("ids are zero-padded section numbers", ids, ["wplate_023", "wplate_100"])
    chk("sorting ids sorts the sections", sorted(ids), ids)
    chk("section_level keeps the real number", [r["section_level"] for r in rows], [23, 100])
    chk("midline found near the middle", all(0.46 < r["midline_frac"] < 0.54 for r in rows))
    chk("no plate fell back on the default midline", bad_mid, [])
    chk("regions come from the legend", rows[0]["regions"], "Dl|Dm|V")
    with open(os.path.join(out, "seeds.csv"), newline="") as fh:
        chk("seeds.csv exists with a header and no rows",
            (len(fh.readline().split(",")) > 3, fh.read()), (True, ""))
    mg = Image.open(os.path.join(out, "wplate_023_micrograph.png"))
    chk("micrograph crop is the right half", abs(mg.width - 200) <= 3)

    # ---- 04x ----------------------------------------------------------------
    polys = X04.extract_plate(os.path.join(out, "wplate_100.png"),
                              rows[1]["midline_frac"], ["Dm", "Dl", "V"], ocr=False)
    chk("three outlined boxes plus the enclosed ground give four polygons", len(polys), 4)
    chk("without OCR every cell is unassigned",
        {p["status"] for p in polys}, {"unassigned"})
    chk("polygon touching the midline is kept", any(
        max(x for x, _ in p["v"]) > 0.45 for p in polys))
    chk("numbers are 1..n, once each", sorted(p["roi_number"] for p in polys), [1, 2, 3, 4])
    first = min(polys, key=lambda p: p["roi_number"])
    chk("numbering starts at the left column, top",
        min(x for x, _ in first["v"]) < 0.15 and min(y for _, y in first["v"]) < 0.2)

    # similarity gate: a wrong reading must not be accepted as a name
    name, _ = X04.match_name("Xq", ["Dm", "Dl", "V"], set())
    chk("a poor reading names nothing", name, None)
    name, _ = X04.match_name("DI", ["Dm", "Dl", "V"], set())
    chk("I/l confusion still reads Dl", name, "Dl")
    name, _ = X04.match_name("Dl", ["Dm", "Dl"], {"Dl"})
    chk("a name already used is not offered twice", name != "Dl")

    # ---- polygon file and the view 04l gets ---------------------------------
    polys.sort(key=lambda p: p["roi_number"])
    for p, (reg, st) in zip(polys, (("Dm", "reviewed"), ("V", "reviewed"),
                                    ("Dl", "auto"), ("", "unassigned"))):
        p["region"], p["status"] = reg, st
    path = os.path.join(out, "polygons.csv")
    AP.write_polygons(path, {"wplate_100": polys})
    back = AP.read_polygons(path)["wplate_100"]
    chk("polygons survive a round trip", [(p["region"], p["status"], len(p["v"])) for p in back],
        [(p["region"], p["status"], len(p["v"])) for p in polys])
    seeds, hulls = AP.plate_view(back)
    chk("only reviewed polygons reach the curator by default", len(hulls), 2)
    seeds, hulls = AP.plate_view(back, statuses=("reviewed", "auto"))
    chk("auto polygons appear when asked for, unassigned never", len(hulls), 3)
    chk("each hull has exactly one seed", all(len(h["seeds"]) == 1 for h in hulls))
    chk("ROI numbers are 1..n", sorted(h["roi"] for h in hulls), [1, 2, 3])
    chk("the seed lies inside its polygon", all(
        AP._inside(s["xf"], s["yf"], h["v"]) for s, h in zip(seeds, hulls)))
    chk("no ambiguity group on a polygon plate", {h["amb"] for h in hulls}, {""})
    chk("a region keeps one colour", AP.region_colour("Dm"), AP.region_colour("Dm"))
    seeds, hulls = AP.plate_view(back, midline=0.5)
    chk("mirroring doubles the reviewed polygons", len(hulls), 4)
    chk("mirrored copies are parts of their region", sorted(h["n_parts"] for h in hulls), [2, 2, 2, 2])
    mir = [h for h in hulls if h["part"] == 2 and h["region"] == "Dm"][0]
    orig = [h for h in hulls if h["part"] == 1 and h["region"] == "Dm"][0]
    chk("mirror reflects about the midline",
        abs(min(x for x, _ in mir["v"]) - (1.0 - max(x for x, _ in orig["v"]))) < 0.002)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n%s" % ("all passed" if not fails else "%d FAILED" % fails))
raise SystemExit(1 if fails else 0)
