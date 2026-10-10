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
print("--- 04g takes its default and its filenames from 04a, not from AF488 ---")

# 04g masks ONE marker's pass per run, so its --marker default selects which
# sections get written. A silent flip processes the wrong pass and says nothing
# - a reviewer changed it to MARKERS[0] and the whole suite stayed green, which
# is why this reads `action.default` off the BUILT PARSER rather than the help
# text, the way 04a's default is pinned above.
G4G = load_stage("04g_artifact_mask.py")


def marker_default(mod):
    ap = mod.build_parser()
    return next(a.default for a in ap._actions if a.dest == "marker")


chk("04g's --marker default is the SECOND declared marker",
    marker_default(G4G), "AF488")
chk("...which is the same marker 04a calls its default",
    marker_default(G4G), RF.DEFAULT_MARKER)
chk("04g's summary is unsuffixed for that default marker",
    os.path.basename(G4G.summary_csv("AF488")), "artifact_summary.csv")
chk("...and suffixed for the other",
    os.path.basename(G4G.summary_csv("AF568")), "artifact_summary_AF568.csv")

# AND UNDER MARKERS THAT ARE NOT FLUOROPHORES. 04g used to rebuild the reformat
# filenames against the literal "AF488", which agrees with 04a only because
# this study's second marker happens to be called AF488. Declare two markers
# with other names and the two disagree: 04a writes Mk2's index unsuffixed
# while 04g would look for reformat_index_Mk2.csv. A nested study, because
# that is the only way to ask what these stages do for a marker list they were
# not imported under.
from _fixture import temp_study                                # noqa: E402

with temp_study(acquisition={"layout": "paired",
                             "markers": ["Mk1", "Mk2"]}) as _s:
    _rf = load_stage("04a_reformat.py", name="lsstage_04a_alt")
    _4g = load_stage("04g_artifact_mask.py", name="lsstage_04g_alt")
    chk("a two-marker study still defaults 04g to the second",
        marker_default(_4g), "Mk2")
    for _m in ("Mk1", "Mk2"):
        chk(f"04g reads the reformat index 04a WRITES for {_m}",
            os.path.basename(_4g._RF.marker_paths(_m)["index"]),
            os.path.basename(_rf.marker_paths(_m)["index"]))
        chk(f"...and the excluded list 04a writes for {_m}",
            os.path.basename(_4g._RF.marker_paths(_m)["excluded"]),
            os.path.basename(_rf.marker_paths(_m)["excluded"]))
    chk("Mk2's index is the UNSUFFIXED one, as 04a writes it",
        os.path.basename(_rf.marker_paths("Mk2")["index"]), "reformat_index.csv")
    chk("04g's own summary follows the same rule, not the literal AF488",
        os.path.basename(_4g.summary_csv("Mk2")), "artifact_summary.csv")
    chk("...leaving the first marker suffixed",
        os.path.basename(_4g.summary_csv("Mk1")), "artifact_summary_Mk1.csv")

    # 04l builds the page's <img> srcs from its own marker_paths, which used to
    # be `if marker == "AF568"` under a docstring claiming it mirrored 04a. It
    # mirrors 04a only for a study whose second marker is called AF488; for any
    # other pair it sent BOTH markers to `sections`, so one marker's grid
    # showed the other marker's sections and the rest showed nothing. A broken
    # <img> is silent.
    _4l = load_stage("04l_roi_curator.py", name="lsstage_04l_alt")
    for _m in ("Mk1", "Mk2"):
        chk(f"04l reads the reformat index 04a WRITES for {_m}",
            os.path.basename(_4l.marker_paths(_m)[0]),
            os.path.basename(_rf.marker_paths(_m)["index"]))
        chk(f"...and shows the section directory 04a writes for {_m}",
            _4l.marker_paths(_m)[1],
            os.path.basename(_rf.marker_paths(_m)["sections"]))
    chk("...so the two markers do not share one directory",
        _4l.marker_paths("Mk1")[1] != _4l.marker_paths("Mk2")[1], True)
    # What the page is handed, as data. Both JS sites read this map now; a
    # literal in a generated page is invisible to every Python suite.
    chk("the page's SECDIRS covers every marker, with 04a's names",
        _4l.section_dirs(), {"Mk1": "sections_Mk1", "Mk2": "sections"})

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
