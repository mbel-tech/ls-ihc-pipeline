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

The rest of the stage had three more of the same shape, and every one of them
fails SILENTLY because `load()` returns [] for a file that is not there:

  * the literal tuple of index / exclusion / artifact-summary filenames, so
    for any other study none of the six files is found and every section of
    both markers reads `not_reformatted` - even the ones 04a reformatted.
  * `perk_analysis_set.csv` and `perk_overrides.csv` by name, so
    `in_analysis_set` is blank on every row and neither the exclusion-reason
    follow-through nor the QC one ever fires.
  * `count_rois` probing `roi_boxes_AF568.csv` / `roi_boxes_AF488.csv`, while
    05a writes `roi_boxes_<marker>.csv` - so `n_rois` is 0 everywhere and no
    section ever reaches `status = "curated"`.

This suite is deliberately NOT in `tests/test_backfill_provenance.py`: that
file is uncommitted work belonging to another session. See the plan's Task 6,
which owns the rest of 04p.

Run:  python tests/test_section_provenance.py
"""

import csv
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
print("--- the rest of the table, for a study that is not LS ---")

MAN_COLS = ["animal", "slide", "variant", "file", "scene_uid", "scene_index",
            "slide_serial", "section_order", "marker_channel"]
IDX_COLS = ["id", "kind", "animal", "angle", "manual_rotation", "manual_flip"]
EXC_COLS = ["scene_uid", "reason", "decision"]
ART_COLS = ["scene_uid", "n_compact", "n_elongated", "artifact_pct_of_tissue"]
ASET_COLS = ["scene_uid", "in_analysis_set", "censored_fraction_in_tissue",
             "reason"]
CAND_COLS = ["uid", "focus_score", "largest_mm2", "total_mm2", "n_pieces",
             "proposed"]
BOX_COLS = ["scene_uid", "roi_index", "x", "y"]
FOCUS_REASON = "no resolvable nuclear detail (focus 0.061, threshold 0.1)"


def write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def lay_out(P4):
    """Every input 04p reads, under the names a Mk1/Mk2 study would use.

    U1/U2/U3 are Mk1 (the measured pass), P1/P2/P3 are Mk2 (the geometry
    source). U3 was excluded because its partner P3 was; U1 has discs on it.
    """
    ref, art_dir = P4.REFORMAT_DIR, P4.MASK_DIR
    man = ([{"animal": "AB12", "slide": 1, "variant": "a", "file": "AB12_1a.czi",
             "scene_uid": u, "scene_index": i, "slide_serial": i,
             "section_order": i, "marker_channel": "Mk1"}
            for i, u in enumerate(["U1", "U2", "U3"], 1)]
           + [{"animal": "AB12", "slide": 1, "variant": "b",
               "file": "AB12_1b.czi", "scene_uid": p, "scene_index": i,
               "slide_serial": i, "section_order": i, "marker_channel": "Mk2"}
              for i, p in enumerate(["P1", "P2", "P3"], 1)])
    write_csv(P4.MANIFEST_CSV, MAN_COLS, man)

    write_csv(os.path.join(ref, "reformat_index_Mk1.csv"), IDX_COLS,
              [{"id": u, "kind": "section", "animal": "AB12", "angle": "10",
                "manual_rotation": "1", "manual_flip": "0"}
               for u in ("U1", "U2")])
    write_csv(os.path.join(ref, "reformat_index.csv"), IDX_COLS,
              [{"id": p, "kind": "section", "animal": "AB12", "angle": "90",
                "manual_rotation": "88", "manual_flip": "1"}
               for p in ("P1", "P2")])

    write_csv(os.path.join(ref, "excluded_sections_Mk1.csv"), EXC_COLS,
              [{"scene_uid": "U3", "reason": "partner excluded by the operator",
                "decision": "excluded"}])
    write_csv(os.path.join(ref, "excluded_sections.csv"), EXC_COLS,
              [{"scene_uid": "P3", "reason": FOCUS_REASON,
                "decision": "excluded"}])

    write_csv(os.path.join(art_dir, "artifact_summary_Mk1.csv"), ART_COLS,
              [{"scene_uid": "U1", "n_compact": "2", "n_elongated": "1",
                "artifact_pct_of_tissue": "0.4"}])
    write_csv(os.path.join(art_dir, "artifact_summary.csv"), ART_COLS,
              [{"scene_uid": "P1", "n_compact": "3", "n_elongated": "0",
                "artifact_pct_of_tissue": "0.7"}])

    write_csv(os.path.join(ref, "Mk1_analysis_set.csv"), ASET_COLS,
              [{"scene_uid": "U1", "in_analysis_set": "1",
                "censored_fraction_in_tissue": "0.002", "reason": ""},
               {"scene_uid": "U2", "in_analysis_set": "0",
                "censored_fraction_in_tissue": "0.31",
                "reason": "31% of pixels at the 16-bit ceiling"}])

    write_csv(os.path.join(ref, "rotation_overrides_Mk1.csv"),
              ["perk_scene_uid", "pcna_scene_uid", "animal"],
              [{"perk_scene_uid": u, "pcna_scene_uid": p, "animal": "AB12"}
               for u, p in (("U1", "P1"), ("U2", "P2"), ("U3", "P3"))])

    write_csv(os.path.join(ref, "exclusion_candidates.csv"), CAND_COLS,
              [{"uid": "P1", "focus_score": "0.44", "largest_mm2": "0.91",
                "total_mm2": "1.20", "n_pieces": "2", "proposed": "0"}])

    # 05a's name for the box file. The literals this replaces probed
    # roi_boxes_AF568.csv and roi_boxes_AF488.csv and would find neither.
    write_csv(os.path.join(ref, "roi_boxes_Mk1.csv"), BOX_COLS,
              [{"scene_uid": "U1", "roi_index": i, "x": 1, "y": 2}
               for i in (0, 1, 2)])


with temp_study(acquisition={"layout": "paired",
                             "markers": ["Mk1", "Mk2"]}) as study:
    P4 = load_stage("04p_section_provenance.py", name="lsstage_04p_full")
    lay_out(P4)

    saved_argv = sys.argv
    sys.argv = ["04p_section_provenance.py"]
    raised = ""
    try:
        P4.main()
    except BaseException as exc:                # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    finally:
        sys.argv = saved_argv
    chk("04p.main() runs at all", raised, "")

    with open(P4.OUT_CSV, newline="", encoding="utf-8") as fh:
        prov = {r["scene_uid"]: r for r in csv.DictReader(fh)}
    chk("every scanned section is a row", sorted(prov),
        ["P1", "P2", "P3", "U1", "U2", "U3"])

    # The literal tuple held only AF488 and AF568 filenames, so nothing was
    # found and every one of these read "not_reformatted".
    chk("both passes' reformat indexes are read",
        [prov[u]["reformatted"] for u in ("U1", "U2", "P1", "P2")],
        ["1", "1", "1", "1"])
    chk("...and both exclusion lists",
        [prov[u]["decision"] for u in ("U3", "P3")], ["excluded", "excluded"])
    chk("...and both artifact summaries",
        [prov[u]["n_artifact_objects"] for u in ("U1", "P1")], ["3", "3"])

    # 04j's columns, from the measured pass's own analysis set.
    chk("the analysis set is found under the study's own name",
        [prov[u]["in_analysis_set"] for u in ("U1", "U2")], ["1", "0"])
    chk("...so a censored section is not reported as merely reformatted",
        prov["U2"]["status"], "censored_out")

    # The exclusion-reason follow-through: the measured pass's reason is
    # always "partner excluded", and the real one is on the partner's side.
    chk("the exclusion reason is followed through the pairing",
        prov["U3"]["decision_reason"], FOCUS_REASON)
    chk("...and classified from it", prov["U3"]["exclusion_class"],
        "out_of_focus")
    # The QC follow-through, same pairing, different table.
    chk("the partner's QC numbers reach the measured section",
        [prov["U1"]["largest_mm2"], prov["U1"]["qc_source"]],
        ["0.91", "exclusion_candidates"])

    # count_rois asked for roi_boxes_AF568.csv / roi_boxes_AF488.csv, so
    # n_rois was 0 for every section of every other study and nothing could
    # ever reach "curated".
    chk("the discs 05a wrote are counted", prov["U1"]["n_rois"], "3")
    chk("...so a curated section says so", prov["U1"]["status"], "curated")

    print()
    print("--- absent is not empty ---")
    # `load()` returning [] for a missing file is how all four of the bugs
    # above stayed silent. A header with no rows under it is a real answer;
    # a file that is not there is not.
    empty = os.path.join(P4.REFORMAT_DIR, "an_empty_one.csv")
    write_csv(empty, ["scene_uid"], [])
    missing = os.path.join(P4.REFORMAT_DIR, "not_here_at_all.csv")

    P4.MISSING.clear()
    chk("an empty file reads as no rows", P4.load(empty), [])
    chk("...and is not reported missing", list(P4.MISSING), [])
    chk("a file that is not there also reads as no rows",
        P4.load(missing), [])
    chk("...but is recorded, so the miss is visible",
        [os.path.basename(p) for p in P4.MISSING], ["not_here_at_all.csv"])

    got = "accepted"
    try:
        P4.load(missing, required=True)
    except SystemExit as exc:
        got = "refused" if "not_here_at_all.csv" in str(exc) else str(exc)
    chk("a required file that is absent is a stop", got, "refused")
    chk("...and an empty required file is not",
        P4.load(empty, required=True), [])

print()
print("--- multiplex: no partner pass, so nothing to follow ---")
# There is no pairing file under multiplex, and `rotation_overrides.csv` has no
# partner column in it at all - so a follow-through that ran anyway would
# refuse at the header. `MEASURED` is None here and no manifest row can equal
# it, which is what keeps both guards shut.
with temp_study(acquisition={"layout": "multiplex", "channels": [
        {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
        {"name": "Mk1", "role": "marker", "czi_name": "AF568", "index": 1,
         "segment": "nuclear"},
        {"name": "Mk2", "role": "marker", "czi_name": "AF647", "index": 2,
         "segment": "nuclear"}]}) as study:
    P4 = load_stage("04p_section_provenance.py", name="lsstage_04p_mxmain")
    chk("no partner pass is declared", [P4.PARTNER, P4.MEASURED], [None, None])
    write_csv(P4.MANIFEST_CSV, MAN_COLS,
              [{"animal": "AB12", "slide": 1, "variant": "a",
                "file": "AB12_1a.czi", "scene_uid": "S1", "scene_index": 1,
                "slide_serial": 1, "section_order": 1, "marker_channel": "Mk1"}])
    saved_argv = sys.argv
    sys.argv = ["04p_section_provenance.py"]
    raised = ""
    try:
        P4.main()
    except BaseException as exc:                # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    finally:
        sys.argv = saved_argv
    chk("04p.main() runs for a multiplex study", raised, "")
    chk("...and every declared marker's analysis set applies",
        P4.ANALYSIS_MARKERS, ["Mk1", "Mk2"])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
