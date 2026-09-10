"""`04p_section_provenance` - the directory each section's picture is in.

Every thumbnail in the ROI curator's Review pane is an <img> whose src comes
out of `section_provenance.csv`, and 04p builds the directory half of that
path. It used to build it from a literal:

    sec_dir = "sections" if mk == "AF488" else f"sections_{mk}"

which is not merely LS-specific - it is EXACTLY INVERTED for any other pair.
The unsuffixed directory belongs to the geometry source, and the geometry
source is the SECOND declared marker, not a fluorophore called AF488. So for a
study whose markers are ["Mk1", "Mk2"], Mk2 - the default marker, the one whose
sections really are in `sections/` - was sent to `sections_Mk2`, a directory
04a never wrote; and Mk1 was sent to `sections`, which holds Mk2's sections.
The grid then renders blank, or renders the wrong marker's section under the
right marker's row. A broken <img> in that page is silent.

This suite is deliberately NOT in `tests/test_backfill_provenance.py`: that
file is uncommitted work belonging to another session. See the plan's Task 6,
which owns the rest of 04p.

Run:  python tests/test_section_provenance.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from _fixture import temp_study, load_stage                    # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


print("--- a study whose markers are not AF568/AF488 ---")
with temp_study(acquisition={"layout": "paired",
                             "markers": ["Mk1", "Mk2"]}):
    P4 = load_stage("04p_section_provenance.py", name="lsstage_04p_dirs")
    RF = load_stage("04a_reformat.py", name="lsstage_04a_04p")

    chk("the geometry source keeps the unsuffixed directory",
        P4.section_dir("Mk2"), "sections")
    chk("...and the other marker gets its own",
        P4.section_dir("Mk1"), "sections_Mk1")
    # The assertion that stops this drifting from the stage that writes those
    # directories: 04a is the writer, and this must be its basename.
    for m in ("Mk1", "Mk2"):
        chk(f"{m} agrees with 04a, the stage that wrote the directory",
            P4.section_dir(m),
            os.path.basename(RF.marker_paths(m)["sections"]))
    chk("it is a NAME, not a path - the page resolves it relatively",
        os.sep in P4.section_dir("Mk1"), False)

    # `mk` is the manifest's marker_channel column, which can name a channel
    # this config never declared as a marker. One such row must not take down
    # a table that has 1,500 good ones.
    chk("a channel the config does not declare still gets a directory",
        P4.section_dir("Mk9"), "sections_Mk9")

print()
print("--- the LS shape, unchanged ---")
with temp_study(acquisition={"layout": "paired",
                             "markers": ["AF568", "AF488"]}):
    P4 = load_stage("04p_section_provenance.py", name="lsstage_04p_ls")
    chk("AF488, the geometry source, is still `sections`",
        P4.section_dir("AF488"), "sections")
    chk("AF568 is still `sections_AF568`",
        P4.section_dir("AF568"), "sections_AF568")

print()
print("--- multiplex: one frame per scene, so one directory ---")
with temp_study(acquisition={"layout": "multiplex", "channels": [
        {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
        {"name": "Mk1", "role": "marker", "czi_name": "AF568", "index": 1,
         "segment": "nuclear"},
        {"name": "Mk2", "role": "marker", "czi_name": "AF647", "index": 2,
         "segment": "nuclear"}]}):
    P4 = load_stage("04p_section_provenance.py", name="lsstage_04p_mx")
    chk("every marker answers with the same directory",
        [P4.section_dir(m) for m in ("Mk1", "Mk2")], ["sections", "sections"])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
