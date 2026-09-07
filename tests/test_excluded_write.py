"""excluded_sections.csv is written once, after the review merge, by main().

Run:  python tests/test_excluded_write.py
"""

import sys
import csv
import importlib.util
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

# This suite imports stage modules, which read config at import. Without a
# config of its own it would fall through to the operator's live study and
# then pass or fail on their data. See tests/_fixture.py.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _fixture import use_temp_study  # noqa: E402

STUDY = use_temp_study()

_spec = importlib.util.spec_from_file_location("rf", os.path.join(SCRIPTS, "04a_reformat.py"))
RF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RF)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


tmp = tempfile.mkdtemp(prefix="excl_")
try:
    paths = {"overrides": os.path.join(tmp, "rotation_overrides.csv"), "uid_col": "scene_uid",
             "excluded": os.path.join(tmp, "excluded_sections.csv")}
    with open(paths["overrides"], "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["scene_uid", "extra_rotation", "flip", "excluded",
                                           "rotation_source", "decision", "reason"])
        w.writeheader()
        w.writerow({"scene_uid": "A", "extra_rotation": "12", "flip": "0", "excluded": "0",
                    "rotation_source": "manual", "decision": "", "reason": ""})
        w.writerow({"scene_uid": "B", "extra_rotation": "0", "flip": "0", "excluded": "1",
                    "rotation_source": "", "decision": "manual", "reason": "torn"})

    overrides, excluded = RF.load_overrides(paths)
    chk("rotations still load", overrides, {"A": (12.0, False)})
    chk("exclusions still load", excluded, {"B": ("manual", "torn")})
    chk("load_overrides writes nothing by default", os.path.exists(paths["excluded"]), False)

    RF.write_excluded(paths["excluded"], {})
    # newline="" so the CRLF the csv writer emits is not translated away on read.
    with open(paths["excluded"], newline="", encoding="utf-8") as fh:
        chk("an empty list is a header-only file", fh.read(), "scene_uid,decision,reason\r\n")

    merged = dict(excluded)
    merged["C"] = ("manual", "excluded on review")
    RF.write_excluded(paths["excluded"], merged)
    rows = read(paths["excluded"])
    chk("the merged list is what lands", [r["scene_uid"] for r in rows], ["B", "C"])
    chk("...with its reasons", rows[1]["reason"], "excluded on review")

    # Which masks an excluded section gets: none, whatever the flags say.
    chk("kept section, both flags", RF.wants_masks(False, True, True, set(), "X"), (True, True))
    chk("kept section, rejected mask", RF.wants_masks(False, True, True, {"X"}, "X"), (False, True))
    chk("excluded section is rendered raw", RF.wants_masks(True, True, True, set(), "X"), (False, False))
    chk("no flags, no masks", RF.wants_masks(False, False, False, set(), "X"), (False, False))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
