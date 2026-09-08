"""Under multiplex, the reformat is per SCENE, not per marker.

The pixels are the same pixels - one scan carries every marker - so rotation,
cropping, the artifact mask and the censor mask are decided once. Deciding them
twice would let two markers of one section disagree about where the section is.

SYNTHETIC ONLY. No multiplex study exists yet, so the multiplex half of this
suite is the only thing that has ever exercised that branch.
"""

import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

# A study of our own, and a PAIRED one: load_stage imports under whatever
# config is currently named, so without this the suite would read the
# operator's live study and pass or fail on their data. config.example.json is
# multiplex, so the paired half has to be asked for explicitly.
from _fixture import use_temp_study, load_stage             # noqa: E402

STUDY = use_temp_study(acquisition={"layout": "paired",
                                    "markers": ["AF568", "AF488"]})
RF = load_stage("04a_reformat.py")

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


print("--- paired: one set of paths per marker, as today ---")
chk("the module read the paired layout", RF.LAYOUT, "paired")
a = RF.marker_paths("AF568")
b = RF.marker_paths("AF488")
chk("the two markers get different section dirs",
    a["sections"] != b["sections"], True)
chk("...and different indexes", a["index"] != b["index"], True)
chk("the section dir still carries the marker name",
    os.path.basename(a["sections"]), "sections_AF568")
# The unsuffixed set belongs to the DEFAULT marker - the pass that was curated
# first - not to a fluorophore named in the source.
chk("the default marker keeps the unsuffixed names",
    os.path.basename(b["sections"]), "sections")
chk("...and the default marker is the second declared",
    RF.DEFAULT_MARKER, "AF488")

print()
print("--- paired: one frame per SCAN, as today ---")
_rows = [{"scene_uid": "u1", "marker_channel": "AF568"},
         {"scene_uid": "u2", "marker_channel": "AF488"},
         {"scene_uid": "u3", "marker_channel": "AF568"}]
chk("a paired run takes only its own scan's rows",
    [r["scene_uid"] for r in RF.frames_for(_rows, "AF568")], ["u1", "u3"])

print()
print("--- multiplex: one set of paths for every marker ---")
# marker_paths reads the module-level LAYOUT, so flipping it is the whole
# difference. Restored in `finally` because the module is process-global and a
# later assertion would otherwise inherit it.
_was = RF.LAYOUT
try:
    RF.LAYOUT = "multiplex"
    m1 = RF.marker_paths("pERK")
    m2 = RF.marker_paths("PCNA")
    chk("every marker shares one section dir", m1["sections"], m2["sections"])
    chk("...and one index", m1["index"], m2["index"])
    chk("...and one excluded list", m1["excluded"], m2["excluded"])
    chk("...and one lost list", m1["lost"], m2["lost"])
    chk("...and one rotation override file", m1["overrides"], m2["overrides"])
    chk("...read under one uid column", m1["uid_col"], m2["uid_col"])
    chk("the shared dir carries no marker name",
        os.path.basename(m1["sections"]), "sections")
    # A KeyError here is a caller crashing on a key the paired branch has and
    # the multiplex branch forgot.
    chk("the multiplex branch answers every key the paired one does",
        sorted(m1), sorted(a))

    print()
    print("--- multiplex: one frame per SCENE ---")
    # marker_channel is 00_manifest's SECOND channel name, so under multiplex
    # it names at most one of the declared markers. Filtering by it would
    # reformat nothing for every other marker.
    mx = [{"scene_uid": "u1", "marker_channel": "pERK"},
          {"scene_uid": "u2", "marker_channel": "pERK"}]
    chk("every scene is reformatted once, whatever marker was asked for",
        [r["scene_uid"] for r in RF.frames_for(mx, "PCNA")], ["u1", "u2"])
    print()
    print("--- multiplex: the review is about the FRAME, not the marker ---")
    # The mirror image of tests/test_section_review.py, which pins the paired
    # rule. One frame per scene means a decision applies to that frame whatever
    # marker the reviewer had on screen; filtering it out would let two markers
    # of one section disagree about whether it is excluded.
    _tmp = tempfile.mkdtemp(prefix="lsrevmx_")
    _keep = RF.REVIEW_CSV
    try:
        RF.REVIEW_CSV = os.path.join(_tmp, "section_review.csv")
        with open(RF.REVIEW_CSV, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["scene_uid", "marker", "excluded",
                                               "decision", "mask_rejected",
                                               "reason"])
            w.writeheader()
            w.writerow({"scene_uid": "S1", "marker": "pERK", "excluded": "0",
                        "decision": "restored", "mask_rejected": "1",
                        "reason": "reviewed on the pERK channel"})
        out, rejected = RF.apply_review({"S1": ("auto", "no tissue")}, "PCNA")
        chk("a decision made on one marker reinstates the frame",
            "S1" in out, False)
        chk("...and its mask rejection is collected too",
            "S1" in rejected, True)
    finally:
        RF.REVIEW_CSV = _keep
        try:
            os.remove(os.path.join(_tmp, "section_review.csv"))
            os.rmdir(_tmp)
        except OSError:
            pass
finally:
    RF.LAYOUT = _was

chk("the layout was put back", RF.LAYOUT, "paired")

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
