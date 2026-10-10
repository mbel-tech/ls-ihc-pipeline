"""The curator's plate array: its order, and what a missing image does to it.

Both defects here are silent. A string sort is right only for a zero-padded
atlas; `plate_1 .. plate_100` scrambles, and every stored index then means a
different plate. And skipping a plate whose image is absent shifts every later
index by one, which renumbers the back half of the atlas with nothing said.

Run:  work/appenv/Scripts/python.exe tests/test_roi_curator_plates.py
"""

import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from _fixture import load_stage, use_temp_study               # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


# `atlas_plate_set.dir` is validated by ls_config against a fixed choice list
# (plates / plates_merged / plates_final - see scripts/ls_config.py:460), so
# the plan's literal `atlas_plate_set={"dir": "before"}` is refused before
# 04l ever loads ("`atlas_plate_set.dir` must be one of plates, plates_merged,
# plates_final"). plate_rows() takes an explicit `plate_dir` override for
# exactly this reason, so the fixture directory is passed directly instead of
# smuggled through the validated config; the declared set only has to be SOME
# valid choice.
study = use_temp_study(atlas_plate_set={"dir": "plates_final"})
sys.path.insert(0, os.path.join(REPO, "scripts"))
import _atlas_fixture as FIX                                  # noqa: E402

atlas_root = os.path.join(study.out_root, "atlas")
os.makedirs(atlas_root, exist_ok=True)
before, after = FIX.build(atlas_root)

C = load_stage("04l_roi_curator.py")

rows = C.plate_rows(before)
chk("every plate in the table is in the array", len(rows), 4)
chk("...in atlas order", [r["id"] for r in rows],
    ["plate_001", "plate_002", "plate_003", "plate_004"])
chk("each carries its fingerprint", all(r.get("fp") for r in rows), True)
chk("...and its pixel size", rows[0]["w"], FIX.PLATE_W)
chk("...and its filename", rows[0]["image_file"], "plate_001_p01.png")
# `img` has to be built from the DIRECTORY plate_rows() was actually given,
# not from the module-level PLATE_SET constant - a caller that passed an
# override otherwise gets rows whose img points into the wrong set entirely.
chk("...and img points into the given directory, not PLATE_SET",
    rows[0]["img"], "../atlas/before/plate_001_p01.png")

# Remove one image. The plate must KEEP its slot.
# NOTE: the fixture's image filenames are `plate_%03d_p%02d.png`, not
# `<plate_id>.png` (tests/_atlas_fixture.py:build) - plate_002's image is
# plate_002_p02.png.
os.remove(os.path.join(before, "plate_002_p02.png"))
rows = C.plate_rows(before)
chk("a plate whose image is gone keeps its position", len(rows), 4)
chk("...and the ones after it do not shift",
    [r["id"] for r in rows],
    ["plate_001", "plate_002", "plate_003", "plate_004"])
chk("...and it is marked rather than dropped", rows[1]["missing"], 1)

# The fixture above uses ids plate_001..plate_004, where string and numeric
# order happen to COINCIDE - so nothing checked so far can tell a numeric
# sort from a string one; putting the string sort back would still pass
# every assertion above. plate_order()'s numeric-vs-text behaviour is
# already pinned directly in tests/test_ls_atlas.py:75-100 - what is NOT
# pinned anywhere is that plate_rows() actually CALLS it rather than sorting
# on its own. A minimal plates.csv whose ids diverge under the two orderings
# closes that gap.
numeric_dir = tempfile.mkdtemp()
with open(os.path.join(numeric_dir, "plates.csv"), "w", newline="",
          encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["plate_id", "page", "image_file", "px_w", "px_h"])
    for n in (1, 2, 10, 100):
        w.writerow([f"plate_{n}", n, f"plate_{n}.png", 10, 10])
# No images and nothing labelled is needed for an ordering check; an empty
# seeds.csv is enough for load_seeds() not to error.
open(os.path.join(numeric_dir, "seeds.csv"), "w", encoding="utf-8").close()

rows = C.plate_rows(numeric_dir)
chk("numeric order, not string order "
    "(plate_2 before plate_10 before plate_100)",
    [r["id"] for r in rows],
    ["plate_1", "plate_2", "plate_10", "plate_100"])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
