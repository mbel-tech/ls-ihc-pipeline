"""Workbook columns by name, groups checked against the unblinding, 12 shapes.

Run:  python tests/test_join_metadata.py
"""

import csv
import importlib.util
import os
import re
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


B = load("b", "06b_join_sampling.py")
# The live header, typos and double space included.
LIVE = {0: "Fish ID", 1: "timepoint", 2: "enviroment", 3: "brackish Tank", 4: "sea water  tank",
        5: "treatment", 6: "freshwater to brackish trasfer date", 7: "brackish to sea trasfer date",
        8: "Heart ID", 9: "Body weight(g)", 10: "Fork Length (cm)", 11: "Sex", 12: "Hearts in PFA",
        13: "Brain for", 14: "Stress test", 15: "notes", 16: "date", 17: "slicing IHC July 2025",
        18: "slicing MD MARCH 2026"}
col = B.resolve_columns(LIVE)
chk("live header resolves to the old indices",
    col, {"fish": 0, "timepoint": 1, "environment": 2, "brackish_tank": 3, "sea_tank": 4,
          "treatment": 5, "body_weight_g": 9, "fork_length_cm": 10, "sex": 11, "brain_for": 13,
          "sliced_july_2025": 17})
shifted = {0: "Fish ID", 1: "new column", **{k + 1: v for k, v in LIVE.items() if k > 0}}
chk("an inserted column moves every index", B.resolve_columns(shifted)["treatment"], 6)
msg = ""
try:
    B.resolve_columns({k: v for k, v in LIVE.items() if k != 5})
except SystemExit as exc:
    msg = str(exc)
chk("a missing column stops and is named", "treatment" in msg, True)

C = load("c", "06c_excel_dataset.py")
tmp = tempfile.mkdtemp(prefix="meta_")
try:
    meta = os.path.join(tmp, "animal_metadata.csv")
    chk("no metadata yet: config stands", C.resolve_groups({"LS1": "control"}, meta), {"LS1": "control"})
    with open(meta, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["animal", "treatment"])
        w.writeheader()
        w.writerows([{"animal": "LS1", "treatment": "control"}, {"animal": "LS2", "treatment": "exercise"}])
    chk("agreement: metadata fills what config lacks",
        C.resolve_groups({"LS1": "control"}, meta), {"LS1": "control", "LS2": "exercise"})
    msg = ""
    try:
        C.resolve_groups({"LS1": "exercise"}, meta)
    except SystemExit as exc:
        msg = str(exc)
    chk("disagreement fails and names the animal", "LS1" in msg and "06b" in msg, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

with open(os.path.join(REPO, "analysis", "plot_roi_figures.R"), encoding="utf-8") as fh:
    r_src = fh.read()
shapes = re.search(r"^SHAPES <- c\(([^)]*)\)", r_src, re.M).group(1)
chk("twelve distinct shapes", len(set(s.strip() for s in shapes.split(","))), 12)
fn = re.search(r"animal_shapes <- function\(levels_all\) \{(.*?)\n\}", r_src, re.S).group(1)
chk("animal_shapes stops on overflow", "stop(" in fn, True)
chk("...and no longer recycles", "rep_len" in fn, False)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
