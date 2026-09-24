"""The curator's plate array: its order, and what a missing image does to it.

Both defects here are silent. A string sort is right only for a zero-padded
atlas; `plate_1 .. plate_100` scrambles, and every stored index then means a
different plate. And skipping a plate whose image is absent shifts every later
index by one, which renumbers the back half of the atlas with nothing said.

Run:  work/appenv/Scripts/python.exe tests/test_roi_curator_plates.py
"""

import os
import sys

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

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
