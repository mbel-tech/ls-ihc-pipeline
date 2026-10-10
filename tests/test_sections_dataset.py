"""`04m_sections_dataset` and `04n_roi_worklist` under a study that is not LS.

Both stages named their inputs with a fluorophore in the string:

    04m:121  rel("reformat_index_AF568.csv")
    04n:69   perk_sections_dataset.csv / reformat_index_AF568.csv

Neither imported `ls_channels` at all, so for any other study those files do
not exist and `main()` died on its first line with FileNotFoundError. That is
the loud half. The quiet half is `04n`'s `num(r, k)` helper, which read the
partner columns through `.get(k, "")`: a renamed column and a genuinely empty
cell produce the same character in the same cell, so the worklist would still
have its 454 rows, still have its columns, and carry no numbers at all.

The rename that goes with the fix is checked here too - `pcna_*` -> `partner_*`
for the partner's facts, unprefixed for the row's own - along with the one
asymmetry that must NOT be tidied away: `manual` belongs to the partner (a
human entered it in 04d) and `derived` belongs to the row (04i re-derived it
from silhouette alignment). They disagree on 420 of 424 paired analysis-set
rows on the live study, and a column set that spelled them the same way would
be claiming they are one number.

Run:  python tests/test_sections_dataset.py
"""

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from _fixture import temp_study, load_stage                      # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


def write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        return list(rd.fieldnames or []), list(rd)


MAN_COLS = ["animal", "slide", "variant", "file", "scene_uid", "scene_index",
            "slide_serial", "section_order", "marker_channel"]
IDX_COLS = ["id", "kind", "animal", "angle", "manual_rotation", "manual_flip"]
EXC_COLS = ["scene_uid", "reason", "decision"]
ASET_COLS = ["scene_uid", "animal", "section_order", "censored_fraction",
             "censored_fraction_in_tissue", "recorded_saturated_fraction",
             "in_analysis_set", "gate", "reason"]
CAND_COLS = ["uid", "focus_score", "largest_mm2", "total_mm2", "n_pieces",
             "proposed"]

# U1..U4 are the measured marker's sections; P1..P4 their partners in the
# geometry-source pass. U3 has no override row, so it is the unpaired case;
# U4 was excluded because its partner P4 was.
FOCUS_REASON = "no resolvable nuclear detail (focus 0.061, threshold 0.1)"


def lay_out(reformat_dir, manifest_dir, uid_col, partner_col):
    """Every input 04m reads, under the names a Mk1/Mk2 study would use."""
    man = []
    for i, u in enumerate(["U1", "U2", "U3", "U4"], 1):
        man.append({"animal": "AB12", "slide": 1, "variant": "a",
                    "file": "AB12_1a.czi", "scene_uid": u, "scene_index": i,
                    "slide_serial": i, "section_order": i,
                    "marker_channel": "Mk1"})
    for i, p in enumerate(["P1", "P2", "P3", "P4"], 1):
        man.append({"animal": "AB12", "slide": 1, "variant": "b",
                    "file": "AB12_1b.czi", "scene_uid": p, "scene_index": i,
                    "slide_serial": i, "section_order": i,
                    "marker_channel": "Mk2"})
    write_csv(os.path.join(manifest_dir, "manifest_scenes.csv"), MAN_COLS, man)

    # The row's own angles: 04i DERIVED these, so `manual_rotation` here is not
    # a human's number even though the column it lands in is called that.
    write_csv(os.path.join(reformat_dir, "reformat_index_Mk1.csv"), IDX_COLS,
              [{"id": "U1", "kind": "section", "animal": "AB12", "angle": "11",
                "manual_rotation": "3", "manual_flip": "0"},
               {"id": "U2", "kind": "section", "animal": "AB12", "angle": "12",
                "manual_rotation": "", "manual_flip": ""},
               {"id": "U3", "kind": "section", "animal": "AB12", "angle": "13",
                "manual_rotation": "5", "manual_flip": "1"}])
    # The partner's angles: entered by hand in 04d.
    write_csv(os.path.join(reformat_dir, "reformat_index.csv"), IDX_COLS,
              [{"id": "P1", "kind": "section", "animal": "AB12", "angle": "90",
                "manual_rotation": "88", "manual_flip": "1"},
               {"id": "P2", "kind": "section", "animal": "AB12", "angle": "91",
                "manual_rotation": "89", "manual_flip": "0"}])

    write_csv(os.path.join(reformat_dir, "excluded_sections_Mk1.csv"), EXC_COLS,
              [{"scene_uid": "U4", "reason": "partner excluded by the operator",
                "decision": "excluded"}])
    write_csv(os.path.join(reformat_dir, "excluded_sections.csv"), EXC_COLS,
              [{"scene_uid": "P4", "reason": FOCUS_REASON,
                "decision": "excluded"}])

    write_csv(os.path.join(reformat_dir, "rotation_overrides_Mk1.csv"),
              [uid_col, partner_col, "animal", "align_iou", "flip_margin",
               "confidence"],
              [{uid_col: "U1", partner_col: "P1", "animal": "AB12",
                "align_iou": "0.81", "flip_margin": "0.2", "confidence": "high"},
               {uid_col: "U2", partner_col: "P2", "animal": "AB12",
                "align_iou": "0.62", "flip_margin": "0.1", "confidence": "low"},
               {uid_col: "U4", partner_col: "P4", "animal": "AB12",
                "align_iou": "0.55", "flip_margin": "0.1", "confidence": "low"}])

    write_csv(os.path.join(reformat_dir, "Mk1_analysis_set.csv"), ASET_COLS,
              [{"scene_uid": u, "animal": "AB12", "section_order": i,
                "censored_fraction": "0.001",
                "censored_fraction_in_tissue": "0.002",
                "recorded_saturated_fraction": "0.003",
                "in_analysis_set": "1", "gate": "tissue", "reason": ""}
               for i, u in enumerate(["U1", "U2", "U3"], 1)])

    write_csv(os.path.join(reformat_dir, "exclusion_candidates.csv"), CAND_COLS,
              [{"uid": "P1", "focus_score": "0.44", "largest_mm2": "0.91",
                "total_mm2": "1.20", "n_pieces": "2", "proposed": "0"}])


EXPECT_COLUMNS = [
    "scene_uid", "animal", "slide", "variant", "scene_index", "section_order",
    "status", "exclusion_class", "disposition_reason",
    "partner_scene_uid", "paired", "partner_kept", "pair_align_iou",
    "pair_flip_margin", "pair_confidence",
    "partner_manual_rotation_deg", "partner_manual_flip",
    "partner_final_angle_deg",
    "derived_rotation_deg", "manual_flip", "final_angle_deg",
    "censored_fraction", "censored_fraction_in_tissue",
    "recorded_saturated_fraction",
    "qc_source", "partner_focus_score", "partner_largest_piece_mm2",
    "partner_total_tissue_mm2", "partner_n_pieces"]


print("--- 04m under a study whose markers are Mk1/Mk2 ---")
with temp_study(acquisition={"layout": "paired",
                             "markers": ["Mk1", "Mk2"]}) as study:
    M = load_stage("04m_sections_dataset.py", name="lsstage_04m_mk")

    # The legacy header first: this is the operator's 82,893-byte
    # perk_overrides.csv, and a reader that stopped resolving it would drop
    # every pairing with no error at all.
    lay_out(M.REFORMAT_DIR, os.path.dirname(M.MANIFEST_CSV),
            "perk_scene_uid", "pcna_scene_uid")

    raised = ""
    try:
        M.main()
    except BaseException as exc:            # noqa: BLE001 - report, do not mask
        raised = f"{type(exc).__name__}: {exc}"
    chk("04m.main() runs at all", raised, "")

    chk("its output is named after the marker",
        os.path.basename(M.OUT_CSV), "sections_dataset_Mk1.csv")

    header, rows = read_csv(M.OUT_CSV)
    chk("the columns carry no antibody names", header, EXPECT_COLUMNS)
    chk("every section of the universe is a row",
        [r["scene_uid"] for r in rows], ["U1", "U2", "U3", "U4"])

    by_uid = {r["scene_uid"]: r for r in rows}
    chk("a legacy-header overrides file still joins",
        [by_uid[u]["partner_scene_uid"] for u in ("U1", "U2", "U3", "U4")],
        ["P1", "P2", "", "P4"])
    chk("...and the pairing columns come with it",
        by_uid["U1"]["pair_align_iou"], "0.81")

    # THE ASYMMETRY. `manual` is the partner's - a human entered it in 04d -
    # and `derived` is the row's, re-derived by 04i from silhouette alignment.
    chk("manual stays on the partner",
        by_uid["U1"]["partner_manual_rotation_deg"], "88")
    chk("derived stays on the row",
        by_uid["U1"]["derived_rotation_deg"], "3")
    chk("...and they are not the same number",
        by_uid["U1"]["partner_manual_rotation_deg"]
        == by_uid["U1"]["derived_rotation_deg"], False)
    chk("the row's own flip and angle lose the prefix, not the meaning",
        [by_uid["U1"]["manual_flip"], by_uid["U1"]["final_angle_deg"]],
        ["0", "11"])

    chk("paired and partner_kept stay two questions",
        [(by_uid[u]["paired"], by_uid[u]["partner_kept"])
         for u in ("U1", "U3", "U4")],
        [("1", "1"), ("0", "0"), ("1", "0")])
    chk("the exclusion reason is followed to the partner's side",
        [by_uid["U4"]["status"], by_uid["U4"]["exclusion_class"]],
        ["excluded", "out_of_focus"])
    chk("the partner's QC numbers land under partner_*",
        [by_uid["U1"]["partner_focus_score"], by_uid["U1"]["partner_n_pieces"]],
        ["0.44", "2"])

    print()
    print("--- 04n, on what 04m just wrote ---")
    N = load_stage("04n_roi_worklist.py", name="lsstage_04n_mk")
    saved_argv = sys.argv
    sys.argv = ["04n_roi_worklist.py", "--min-sections", "0"]
    raised = ""
    try:
        N.main()
    except BaseException as exc:            # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    finally:
        sys.argv = saved_argv
    chk("04n.main() runs at all", raised, "")

    wl_header, wl = read_csv(N.OUT_CSV)
    chk("the worklist columns carry no antibody names", wl_header,
        ["rank", "tier", "tier_reason", "scene_uid", "partner_scene_uid",
         "animal", "section_order", "rotation_unchecked", "pair_confidence",
         "pair_align_iou", "partner_focus_score", "partner_n_pieces",
         "partner_largest_piece_mm2"])
    chk("every analysis-set section is queued",
        sorted(r["scene_uid"] for r in wl), ["U1", "U2", "U3"])

    wl_by = {r["scene_uid"]: r for r in wl}
    chk("the unpaired section is its own tier",
        wl_by["U3"]["tier"], "unpaired_unchecked")
    chk("...and its reason names no antibody",
        wl_by["U3"]["tier_reason"],
        "no partner in the geometry-source pass; rotation never checked "
        "against anything")
    # THE SILENT HALF. num(r, k) used .get(), so a moved column and an empty
    # cell were the same character. These numbers came out of 04m's renamed
    # columns; a blank here means the read fell through, not that the section
    # has no focus score.
    chk("the partner's numbers actually arrived",
        [wl_by["U1"]["partner_focus_score"], wl_by["U1"]["partner_n_pieces"],
         wl_by["U1"]["partner_largest_piece_mm2"]],
        ["0.44", "2", "0.91"])
    chk("...and a section whose partner had none is blank, as before",
        wl_by["U3"]["partner_focus_score"], "")

    print()
    print("--- the same overrides file under the generic header ---")
    # `pick_column` is asked once against the header, so BOTH spellings read.
    # Neither is a default: a third name is a stop, not a blank.
    lay_out(M.REFORMAT_DIR, os.path.dirname(M.MANIFEST_CSV),
            "scene_uid", "source_scene_uid")
    M.main()
    _, rows2 = read_csv(M.OUT_CSV)
    chk("a generic-header overrides file joins the same way",
        [r["partner_scene_uid"] for r in rows2], ["P1", "P2", "", "P4"])

    print()
    print("--- a header with neither spelling refuses ---")
    lay_out(M.REFORMAT_DIR, os.path.dirname(M.MANIFEST_CSV),
            "left_uid", "right_uid")
    got = "accepted"
    try:
        M.main()
    except SystemExit as exc:
        got = "refused" if "scene_uid" in str(exc) else f"exit: {exc}"
    except KeyError as exc:
        got = f"KeyError {exc}"
    chk("a renamed key column is a stop, not a blank", got, "refused")


print()
print("--- 04m is paired-only ---")
import ls_layouts as LY                                          # noqa: E402

chk("04m_sections_dataset.py applies to paired only",
    LY.layouts_for("04m_sections_dataset.py"), ("paired",))
chk("...and 04n is not restricted with it - it reads a table, not a join",
    LY.layouts_for("04n_roi_worklist.py"), ("multiplex", "paired"))


print()
print("--- the LS shape, unchanged ---")
with temp_study(acquisition={"layout": "paired",
                             "markers": ["AF568", "AF488"]}) as study:
    M2 = load_stage("04m_sections_dataset.py", name="lsstage_04m_ls")
    ref = M2.REFORMAT_DIR
    # WRITES the new name; READS whatever is on the drive. The operator's
    # files are all under the old names, and every one of them must still be
    # found - see ls_paths.Names.read.
    chk("the output takes the derived name",
        os.path.basename(M2.OUT_CSV), "sections_dataset_AF568.csv")
    os.makedirs(ref, exist_ok=True)
    for name in ("perk_sections_dataset.csv", "perk_overrides.csv",
                 "perk_analysis_set.csv"):
        open(os.path.join(ref, name), "w", encoding="utf-8").close()
    chk("...but the legacy overrides file is what is read",
        os.path.basename(M2.overrides_csv()), "perk_overrides.csv")
    chk("...and the legacy analysis set too",
        os.path.basename(M2.analysis_set_csv()), "perk_analysis_set.csv")
    chk("the index files are the operator's",
        [os.path.basename(M2.index_csv(m)) for m in ("AF568", "AF488")],
        ["reformat_index_AF568.csv", "reformat_index.csv"])
    chk("...and so are the exclusion lists",
        [os.path.basename(M2.excluded_csv(m)) for m in ("AF568", "AF488")],
        ["excluded_sections_AF568.csv", "excluded_sections.csv"])

    N2 = load_stage("04n_roi_worklist.py", name="lsstage_04n_ls")
    chk("04n reads the dataset 04m would have written before the rename",
        os.path.basename(N2.dataset_csv()), "perk_sections_dataset.csv")
    chk("...and the measured marker's index",
        os.path.basename(N2.index_csv()), "reformat_index_AF568.csv")

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
