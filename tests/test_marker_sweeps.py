"""The marker literals argparse could not catch, and the sweeps around them.

Every check here is a study whose markers are NOT called AF568 and AF488. That
is the whole point: each of these sites was correct for exactly one study, and
under any other one it did not raise - it filtered to nothing, named a
directory that does not exist, or wrote another lab's antibody names into the
operator's config. A suite run against the live study cannot tell a fixed
implementation from the hardcoded one, so none of these run against it.

The two argparse defaults are the reason `tests/test_marker_choices.py` was
widened: `01g` and `04b` declared `--marker` with a bare string default and no
`choices=` at all, so argparse accepted any string and the stage ran to
completion on an empty filter.

Run:  python tests/test_marker_sweeps.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from _fixture import temp_study, load_stage                 # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(62) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


def marker_action(ap):
    """The --marker action off a built parser, so choices and default are read
    from the object argparse will actually use rather than from the help text.
    A reviewer flipping a default and the suite staying green is the failure
    tests/test_reformat_layout.py already guards against for 04a."""
    return next(a for a in ap._actions if a.dest == "marker")


# Two studies. `OTHER` is any second lab: two markers, neither named after a
# fluorophore this pipeline has ever seen. `LS` is the live study, used only to
# assert that the derived answer is the literal it replaces.
OTHER = {"layout": "paired", "markers": ["Mk1", "Mk2"]}
LS = {"layout": "paired", "markers": ["AF568", "AF488"]}


print("--- 01g_saturation_map: a --marker with no choices at all ---")
#
# The default selected the filter AND the output filename: an unrecognised
# value gave `0 <marker> sections` and an empty saturation_<marker>.csv, which
# app/stages.py declares as this stage's output - so the app would show the
# stage as done, holding a file with a header and no rows.
for study, want_choices, want_default in ((OTHER, ["Mk1", "Mk2"], "Mk1"),
                                          (LS, ["AF568", "AF488"], "AF568")):
    with temp_study(acquisition=study):
        mod = load_stage("01g_saturation_map.py")
        act = marker_action(mod.build_parser())
        name = study["markers"][0]
        chk(f"01g offers this study's markers ({name} study)",
            list(act.choices or []), want_choices)
        chk(f"01g defaults to the first declared marker ({name} study)",
            act.default, want_default)

print()
print("--- 04b_atlas_match: the same, on the pass whose DAPI is registered ---")
#
# 04b defaulted to "AF488", the SECOND declared marker - the trap this whole
# migration keeps meeting. Derived, it has to stay the second, not become the
# first.
for study, want_choices, want_default in ((OTHER, ["Mk1", "Mk2"], "Mk2"),
                                          (LS, ["AF568", "AF488"], "AF488")):
    with temp_study(acquisition=study):
        mod = load_stage("04b_atlas_match.py")
        act = marker_action(mod.build_parser())
        name = study["markers"][0]
        chk(f"04b offers this study's markers ({name} study)",
            list(act.choices or []), want_choices)
        chk(f"04b defaults to the SECOND declared marker ({name} study)",
            act.default, want_default)

print()
print("--- 01k_saturation_raw: the resolution-dilution pool ---")
#
# `native_sample` sampled `marker_channel == "AF568"`. Under any other study
# the pool is empty, the ratio has no denominator, and the stage reports "no
# data" - a measured constant quietly replaced by an assumption.
SCENES = [{"marker_channel": "Mk1", "file": "a.czi"},
          {"marker_channel": "Mk2", "file": "b.czi"},
          {"marker_channel": "Mk1", "file": "c.czi"}]
with temp_study(acquisition=OTHER):
    mod = load_stage("01k_saturation_raw.py")
    chk("01k pools the first declared marker, not a literal",
        [r["file"] for r in mod.clip_pool(SCENES)], ["a.czi", "c.czi"])
    chk("...and an unrelated marker contributes nothing",
        mod.clip_pool([{"marker_channel": "AF568", "file": "x.czi"}]), [])
with temp_study(acquisition=LS):
    mod = load_stage("01k_saturation_raw.py")
    rows = [{"marker_channel": "AF568", "file": "a.czi"},
            {"marker_channel": "AF488", "file": "b.czi"}]
    chk("01k on the live study still pools AF568",
        [r["file"] for r in mod.clip_pool(rows)], ["a.czi"])

print()
print("--- 04o_section_rgb: which worklist column carries this marker's uid ---")
#
# `if args.marker == "AF488"` chose between the partner column and the row's
# own. For another study every marker took the `else` branch and both passes
# were built from the same uids.
FIELDS = ["scene_uid", "partner_scene_uid", "tier", "rank"]
with temp_study(acquisition=OTHER):
    mod = load_stage("04o_section_rgb.py")
    chk("04o: the partner column belongs to the DEFAULT marker",
        mod.worklist_uid_column("Mk2", FIELDS), "partner_scene_uid")
    chk("04o: the other marker reads the row's own uid",
        mod.worklist_uid_column("Mk1", FIELDS), "scene_uid")
with temp_study(acquisition=LS):
    mod = load_stage("04o_section_rgb.py")
    chk("04o on the live study: AF488 still takes the partner column",
        mod.worklist_uid_column("AF488", FIELDS), "partner_scene_uid")
    chk("04o on the live study: AF568 still takes scene_uid",
        mod.worklist_uid_column("AF568", FIELDS), "scene_uid")
    chk("04o still follows 04n's rename back to pcna_scene_uid",
        mod.worklist_uid_column("AF488", ["scene_uid", "pcna_scene_uid"]),
        "pcna_scene_uid")

print()
print("--- 04f_exclusion_candidates: the overview directory a section is read from ---")
#
# `chan.get(r["id"], "AF488")` named a directory that does not exist for any
# other study, `measure()` returned None on the missing file, and the section
# dropped out of the candidate list with nothing said.
with temp_study(acquisition=OTHER):
    mod = load_stage("04f_exclusion_candidates.py")
    known = mod.source_png("LS1", "u1", {"u1": "Mk1"})
    guessed = mod.source_png("LS1", "u2", {})
    chk("04f uses the channel the manifest recorded",
        os.path.basename(os.path.dirname(known)), "Mk1")
    chk("04f falls back to the DEFAULT marker, not a literal",
        os.path.basename(os.path.dirname(guessed)), "Mk2")
with temp_study(acquisition=LS):
    mod = load_stage("04f_exclusion_candidates.py")
    chk("04f on the live study still falls back to AF488",
        os.path.basename(os.path.dirname(mod.source_png("LS1", "u2", {}))),
        "AF488")

print()
print("--- 00c_channel_identity: the two antibody names it may write ---")
#
# `call = {clustered: "PCNA", other: "pERK"}`, and `--accept` wrote those two
# names into the operator's config.json `marker_identity` block. For a study
# that measures neither antibody that is a false record the operator is then
# asked to confirm.
CLUSTERED_SECOND = {"Mk1": {"clustering_index": 0.9, "edge_affinity": 0.8},
                    "Mk2": {"clustering_index": 0.4, "edge_affinity": 0.2}}
DISAGREE = {"Mk1": {"clustering_index": 0.4, "edge_affinity": 0.8},
            "Mk2": {"clustering_index": 0.9, "edge_affinity": 0.2}}
with temp_study(acquisition=OTHER):
    mod = load_stage("00c_channel_identity.py")
    chk("00c reads the measured pattern, both statistics agreeing",
        mod.pattern(CLUSTERED_SECOND), ("Mk2", "Mk1"))
    chk("...and makes none when they disagree",
        mod.pattern(DISAGREE), None)

    call, lines = mod.make_call(CLUSTERED_SECOND, {})
    chk("00c invents NO antibody name for an undeclared study", call, None)
    said = " ".join(lines)
    chk("...and does not so much as mention PCNA", "PCNA" in said, False)
    chk("...or pERK", "pERK" in said, False)
    chk("...and says which channel is the clustered one anyway",
        "Mk2" in said and "Mk1" in said, True)

    call, lines = mod.make_call(CLUSTERED_SECOND,
                                {"Mk1": "cFos", "Mk2": "Ki67"})
    chk("00c names the channels the STUDY declared",
        call, {"Mk1": "cFos", "Mk2": "Ki67"})

    call, _ = mod.make_call(CLUSTERED_SECOND, {"Mk1": "cFos"})
    chk("a half-declared study is not half-named", call, None)
    call, _ = mod.make_call(DISAGREE, {"Mk1": "cFos", "Mk2": "Ki67"})
    chk("no pattern, no call, however well declared", call, None)

with temp_study(acquisition=LS, marker_identity={"AF568": "pERK",
                                                 "AF488": "PCNA"}):
    mod = load_stage("00c_channel_identity.py")
    chk("00c reads the live study's declaration off config",
        mod.declared_names(), {"AF568": "pERK", "AF488": "PCNA"})
    live = {"AF568": {"clustering_index": 0.9, "edge_affinity": 0.8},
            "AF488": {"clustering_index": 0.4, "edge_affinity": 0.2}}
    call, _ = mod.make_call(live, mod.declared_names())
    chk("00c on the live study writes exactly what the literal wrote",
        call, {"AF488": "PCNA", "AF568": "pERK"})
with temp_study(acquisition=LS):
    mod = load_stage("00c_channel_identity.py")
    chk("a study that declared nothing has nothing to read",
        mod.declared_names(), {})

print()
print("--- 04l_roi_curator: the counterstain's NAME, and the flag help ---")
#
# The Review pane's header already took the counterstain's colour and lift from
# the config; its NAME was the literal "DAPI". And --analysis-set/--worklist
# still described their subsets as pERK and PCNA, which are this study's
# antibodies, not a rule.
HOECHST = {"layout": "multiplex",
           "channels": [{"name": "Hoechst", "role": "nuclear",
                         "czi_name": "DAPI", "index": 0},
                        {"name": "Ki67", "role": "marker",
                         "czi_name": "AF568", "index": 1}]}
with temp_study(acquisition=HOECHST):
    mod = load_stage("04l_roi_curator.py")
    chk("04l names the counterstain the study's channel table names",
        mod.NUCLEAR_NAME, "Hoechst")
    filters = mod.review_filters(mod.MARKERS, mod.MARKER_COLOURS,
                                 mod.NUCLEAR_COLOUR)
    chk("...and hands that name to the pane beside its colour",
        filters["nuclearLabel"], "Hoechst")
with temp_study(acquisition=LS):
    mod = load_stage("04l_roi_curator.py")
    chk("a paired study declares no table, so the counterstain is DAPI",
        mod.NUCLEAR_NAME, "DAPI")
    filters = mod.review_filters(mod.MARKERS, mod.MARKER_COLOURS,
                                 mod.NUCLEAR_COLOUR)
    chk("...and the live pane header is unchanged",
        (filters["nuclearLabel"], filters["nuclearName"], filters["lift"]),
        ("DAPI", "blue", 4))

with temp_study(acquisition=OTHER):
    mod = load_stage("04l_roi_curator.py")
    helps = {}
    for act in mod.build_parser()._actions:
        helps[act.dest] = act.help or ""
    for dest in ("analysis_set", "worklist"):
        text = helps.get(dest, "")
        chk(f"--{dest.replace('_', '-')} does not name another study's antibodies",
            [w for w in ("pERK", "PCNA") if w in text], [])
        # Both flags narrow the FIRST declared marker and leave every other
        # marker on its own full set, so that marker is the one the help has
        # to name.
        chk(f"--{dest.replace('_', '-')} names THIS study's first marker instead",
            "Mk1" in text, True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
