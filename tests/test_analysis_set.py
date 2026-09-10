"""Unmeasured is not censored.

Run:  python tests/test_analysis_set.py
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


J = load("j", "04j_censor_clipped.py")
M = load("m", "04m_sections_dataset.py")

# THESE TWO FILENAMES NAME FILES THAT EXIST ON THE OPERATOR'S DRIVE.
#
# They are not a naming convention and nothing derives them:
# ls_paths.LEGACY maps AF568 -> perk_analysis_set.csv and AF488 ->
# pcna_analysis_set.csv because both files were already written under those
# names, and `Names.analysis_set_path` - which 04j calls, and which is asked
# for below - hands them back unconditionally rather than on sight. FIVE other
# places read them - 04l, 04m, 04p, app/stages.py (three sites) and this
# suite's own temp path below - so swapping or renaming either one moves live
# paths, and until this check existed nothing noticed: a reviewer exchanged the
# two values and the entire suite stayed green.
#
# Called with the marker names spelled out, not with whatever the configured
# study declares. This suite runs under a throwaway study whose marker list is
# ["Marker1"], and the mapping is a module constant that does not depend on it.
chk("AF568's analysis set is still perk_analysis_set.csv",
    os.path.basename(J.analysis_set_path("AF568")), "perk_analysis_set.csv")
chk("AF488's analysis set is still pcna_analysis_set.csv",
    os.path.basename(J.analysis_set_path("AF488")), "pcna_analysis_set.csv")
chk("...and any other marker gets a name derived from itself",
    os.path.basename(J.analysis_set_path("Mk9")), "Mk9_analysis_set.csv")

row = J.unmeasured_row("U1", "LS1", "7")
chk("an unmeasured row is blank, not zero", row["in_analysis_set"], "")
chk("...and says why", row["reason"], "no raw clipping mask - run 01k_saturation_raw.py")
chk("...under the same columns", list(row.keys()), J.ANALYSIS_KEYS)

full = [{"scene_uid": "A", "in_analysis_set": 1}, {"scene_uid": "B", "in_analysis_set": 0}]
part = [{"scene_uid": "A", "in_analysis_set": 1}, {"scene_uid": "B", "in_analysis_set": ""}]
chk("complete means every row measured", J.is_complete(full), True)
chk("a blank makes it partial", J.is_complete(part), False)

tmp = tempfile.mkdtemp(prefix="aset_")
try:
    out = os.path.join(tmp, "perk_analysis_set.csv")
    chk("no file on disk: partial is allowed", J.guard_partial(out, part, False), None)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["scene_uid", "in_analysis_set"])
        w.writeheader(); w.writerows(full)
    msg = ""
    try:
        J.guard_partial(out, part, False)
    except SystemExit as exc:
        msg = str(exc)
    chk("a complete file is not replaced by a partial one", "--allow-partial" in msg, True)
    chk("...unless asked", J.guard_partial(out, part, True), None)
    chk("a complete result always writes", J.guard_partial(out, full, False), None)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

chk("04m: curator default reason", M.classify("too damaged to measure"), ("tissue_damaged", None))
chk("04m: review-mode reason", M.classify("excluded on review"), ("tissue_damaged", None))
chk("04m: curator export reason", M.classify("manually excluded: tissue too damaged to measure"), ("tissue_damaged", None))
chk("04m: focus reason still parses", M.classify("no resolvable nuclear detail (focus 0.061, threshold 0.1)"), ("out_of_focus", 0.061))

chk("04m: in set", M.fate({"in_analysis_set": "1", "reason": ""}), ("analysis_set", ""))
chk("04m: set aside", M.fate({"in_analysis_set": "0", "reason": "12% clipped"}), ("censored_out", "12% clipped"))
chk("04m: blank row is unmeasured", M.fate({"in_analysis_set": "", "reason": "no raw clipping mask"}),
    ("unmeasured", "no raw clipping mask"))
chk("04m: no row is unmeasured, not censored", M.fate(None),
    ("unmeasured", "no analysis-set row - 04j has not measured this section"))

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
