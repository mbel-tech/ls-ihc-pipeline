"""One naming rule, in one place - and it must agree with 04a's.

`scripts/ls_paths.py` exists because the rule "is this marker's output
directory `sections/` or `sections_<marker>/`?" is currently written out eight
times across the codebase and INVERTED in several of those copies. An inverted
copy is not loud: `04q_import_curation` read the wrong directory, failed to
find the 768-px page image, fell back to k=1.0 while the curator had drawn at
K=3, and imported every disc, landmark and polygon vertex a third of the way
towards the origin. Nothing errored.

The single most important thing in this suite is therefore the consistency
block: for the live study's marker list, `Names.path()` must return what
`04a.marker_paths()` returns today, key for key and marker for marker. That is
what stops the new module and the old one drifting apart between now and the
point where the copies are deleted.

THE TRAP: the marker with the UNSUFFIXED outputs is the SECOND declared
(`04a.DEFAULT_MARKER = MARKERS[1]`). Any code - or any test - that assumes
"first = unsuffixed" is inverted, and for the live study it is inverted in a
way that still produces plausible filenames.

Run:  python tests/test_ls_paths.py
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

# A study of our own, shaped like the live one: paired, two fluorophores, the
# second of which owns the unsuffixed names. load_stage imports 04a under
# whatever config is currently named, so without this the suite would read the
# operator's config.json and assert against their drive.
from _fixture import use_temp_study, load_stage, temp_study   # noqa: E402

STUDY = use_temp_study(acquisition={"layout": "paired",
                                    "markers": ["AF568", "AF488"]})
RF = load_stage("04a_reformat.py")

import ls_paths as P                                          # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(62) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


def base(path):
    return os.path.basename(path)


print("--- slug() ---")
# 02_pair_passes.py already writes `af568_file`, `af568_scene`,
# `af568_scene_uid`, `n_af568` and `n_af488` into pairs.csv. Task 4 replaces
# those literals with f"{slug(m)}_file" and friends, so if slug() disagreed
# with what is on the drive by even one character the live pairs.csv would be
# rewritten with different headers - and every reader of it joins by name.
chk("slug('AF568')", P.slug("AF568"), "af568")
chk("slug('AF488')", P.slug("AF488"), "af488")
chk("...so pairs.csv's existing scene-uid column is derivable",
    f"{P.slug('AF568')}_scene_uid", "af568_scene_uid")
chk("...and its existing count column", f"n_{P.slug('AF488')}", "n_af488")
chk("slug('Marker 1')", P.slug("Marker 1"), "marker_1")
chk("slug strips punctuation runs to one separator",
    P.slug("Mk--1 "), "mk_1")

# Two markers whose slugs collide would share every derived column in
# pairs.csv, so the collision has to be findable rather than discovered as a
# column that holds one marker's values some of the time.
chk("colliding slugs are detectable",
    P.slug_collisions(["Mk 1", "Mk-1", "AF568"]), {"mk_1": ["Mk 1", "Mk-1"]})
chk("...and a clean marker list reports nothing",
    P.slug_collisions(["AF568", "AF488"]), {})

print()
print("--- geometry_source(): the SECOND declared marker, under paired ---")
chk("the live study's geometry source is the second declared",
    P.geometry_source(["AF568", "AF488"], "paired"), "AF488")
chk("...and it is 04a's DEFAULT_MARKER, not a fluorophore this module names",
    P.geometry_source(["AF568", "AF488"], "paired"), RF.DEFAULT_MARKER)
chk("a one-marker paired study is its own source",
    P.geometry_source(["Mk1"], "paired"), "Mk1")
chk("a three-marker paired study still points at the second",
    P.geometry_source(["A", "B", "C"], "paired"), "B")
chk("no markers, no source", P.geometry_source([], "paired"), None)
# Under multiplex one scan carries every marker, so there is no pass that was
# curated first and nothing to suffix against.
chk("multiplex has no distinguished source",
    P.geometry_source(["AF568", "AF488"], "multiplex"), None)

print()
print("--- Names.suffix() ---")
paired = P.Names("/out", ["AF568", "AF488"], "paired")
chk("the geometry source gets no suffix", paired.suffix("AF488"), "")
chk("every other marker gets its own name", paired.suffix("AF568"), "_AF568")

multi = P.Names("/out", ["AF568", "AF488"], "multiplex")
chk("multiplex: no suffix for the first", multi.suffix("AF568"), "")
chk("multiplex: no suffix for the second", multi.suffix("AF488"), "")

print()
print("--- Names.path(): the basenames 04a writes ---")
live = P.for_config(STUDY.config)
chk("index for the suffixed marker",
    base(live.path("index", "AF568")), "reformat_index_AF568.csv")
chk("index for the geometry source",
    base(live.path("index", "AF488")), "reformat_index.csv")
chk("sections is a directory, no extension",
    base(live.path("sections", "AF568")), "sections_AF568")
chk("...unsuffixed for the geometry source",
    base(live.path("sections", "AF488")), "sections")
# The two entries that are NOT suffix-ruled: 04j names every marker's analysis
# set after the marker, the geometry source included, and 05a suffixes both
# geometry files for every marker. A reader who applied the suffix rule here
# would look for analysis_set.csv and roi_boxes.csv and find nothing.
chk("analysis_set is marker-named even for the geometry source",
    base(live.path("analysis_set", "AF488")), "AF488_analysis_set.csv")
chk("roi_boxes is marker-named even for the geometry source",
    base(live.path("roi_boxes", "AF488")), "roi_boxes_AF488.csv")
chk("artifact_summary lives beside the masks, not in reformatted/",
    os.path.basename(os.path.dirname(live.path("artifact_summary", "AF568"))),
    "artifacts")
try:
    live.path("no_such_artifact", "AF568")
    chk("an unknown artifact key raises", "returned a path", "KeyError")
except KeyError:
    chk("an unknown artifact key raises", "KeyError", "KeyError")

try:
    live.path("index", "Mk9")
    chk("a marker this study did not declare raises", "returned", "ValueError")
except ValueError:
    chk("a marker this study did not declare raises", "ValueError", "ValueError")

print()
print("--- all_paths() ---")
chk("all_paths covers every declared marker",
    sorted(live.all_paths("index")), ["AF488", "AF568"])
chk("...with the same values path() gives",
    live.all_paths("index")["AF568"], live.path("index", "AF568"))

print()
print("--- basename() and including() ---")
chk("basename is path()'s last component",
    live.basename("sections", "AF568"), "sections_AF568")
chk("...unsuffixed for the geometry source",
    live.basename("sections", "AF488"), "sections")
chk("...and it is a NAME, never a path",
    os.sep in live.basename("index", "AF568"), False)
# A marker that arrives from data rather than from config - the manifest's
# marker_channel column, or a `marker` cell in an exported CSV. path() refuses
# it, which is right for a writer; a reader has to answer.
try:
    live.basename("sections", "Mk9")
    chk("path() alone refuses an undeclared marker", "returned", "ValueError")
except ValueError:
    chk("path() alone refuses an undeclared marker", "ValueError", "ValueError")
wide = live.including("Mk9")
chk("including() answers for it", wide.basename("sections", "Mk9"), "sections_Mk9")
chk("...without moving the geometry source",
    (wide.geometry_source_marker, wide.basename("sections", "AF488")),
    ("AF488", "sections"))
chk("...and a marker already declared gets the same Names back",
    live.including("AF568") is live, True)

print()
print("--- CONSISTENCY WITH 04a.marker_paths: the anti-drift assertion ---")
# 04a.marker_paths returns SIX keys. Four are pure paths under the suffix rule
# and must be identical. The remaining two are handled below, explicitly,
# because they are NOT identical and pretending otherwise is how the rule got
# copied wrong eight times in the first place.
for m in ("AF568", "AF488"):
    for key in ("sections", "index", "excluded", "lost"):
        chk(f"{key} for {m} is byte-identical to 04a's",
            live.path(key, m), RF.marker_paths(m)[key])

# `overrides` - the key the rule was WRONGEST in, and now the fifth path that
# has to be byte-identical. 04a used to hand back the literal
# `perk_overrides.csv` for every marker that is not the geometry source: no
# marker in it, so a three-marker study named two different markers' rotation
# files after the same antibody and whichever ran second overwrote the first.
# It is the same expression as the other four now, so the two cannot drift.
chk("overrides for AF568 is derived from the marker, not from an antibody",
    base(RF.marker_paths("AF568")["overrides"]), "rotation_overrides_AF568.csv")
chk("...and is exactly what ls_paths resolves for a READER",
    RF.marker_paths("AF568")["overrides"],
    live.read("overrides", "AF568", announce=lambda _m: None))
chk("the geometry source's overrides file agrees with 04a exactly",
    live.path("overrides", "AF488"), RF.marker_paths("AF488")["overrides"])
chk("legacy_path still names the operator's own basename",
    base(live.legacy_path("overrides", "AF568")), "perk_overrides.csv")

# THE LIVE STUDY, which must keep working. 82,893 bytes of hand-entered
# rotations and exclusions for 130 curated sections are in
# `perk_overrides.csv` on the operator's drive, and `04a.load_overrides`
# returns ({}, {}) for a file that is not there - a missed fallback drops all
# of it with no error at all. So with the legacy file present and the derived
# one absent, 04a must still resolve to the legacy one. Laid down in a temp
# tree: a suite never writes to the operator's drive.
with temp_study(acquisition={"layout": "paired",
                             "markers": ["AF568", "AF488"]}) as legacy_study:
    os.makedirs(os.path.join(legacy_study.out_root, "reformatted"), exist_ok=True)
    open(os.path.join(legacy_study.out_root, "reformatted",
                      "perk_overrides.csv"), "w").close()
    legacy_rf = load_stage("04a_reformat.py", name="lsstage_04a_legacy")
    chk("with perk_overrides.csv on the drive, 04a still reads it",
        base(legacy_rf.marker_paths("AF568")["overrides"]), "perk_overrides.csv")
    chk("...and the geometry source is untouched by the fallback",
        base(legacy_rf.marker_paths("AF488")["overrides"]),
        "rotation_overrides.csv")

# DIFFERENCE 2 - `uid_col`. This key is NOT a path. It is a CSV COLUMN NAME
# ("perk_scene_uid" / "scene_uid") that 04i writes into the overrides file, so
# it has no place in a table of files and ARTIFACTS deliberately does not carry
# it. Pinned here rather than left unmentioned, so that the count of keys this
# module does and does not own is stated where somebody comparing the two will
# read it. (The plan for this task describes all six keys as paths. They are
# not: five of the six are, and the sixth is a column name.)
chk("uid_col is not an artifact this module names",
    "uid_col" in P.ARTIFACTS, False)
chk("04a's uid_col for the geometry source, pinned",
    RF.marker_paths("AF488")["uid_col"], "scene_uid")
chk("04a's uid_col for the other marker, pinned (a legacy column name)",
    RF.marker_paths("AF568")["uid_col"], "perk_scene_uid")
chk("marker_paths really does return six keys",
    len(RF.marker_paths("AF568")), 6)

print()
print("--- read(): existence decides, all four combinations ---")


def combo(legacy_there, current_there):
    """read('overrides', 'AF568') in a temp tree with those two files."""
    tmp = tempfile.mkdtemp(prefix="lspaths_")
    n = P.Names(tmp, ["AF568", "AF488"], "paired")
    os.makedirs(os.path.join(tmp, "reformatted"), exist_ok=True)
    if legacy_there:
        open(n.legacy_path("overrides", "AF568"), "w").close()
    if current_there:
        # The current file is written second, so it is the NEWER of the two
        # whenever both exist - which is the case the announcement is about.
        time.sleep(0.01)
        open(n.path("overrides", "AF568"), "w").close()
    said = []
    got = n.read("overrides", "AF568", announce=said.append)
    return base(got), said


got, said = combo(False, False)
chk("neither on disk -> the current name", got, "rotation_overrides_AF568.csv")
chk("...and nothing is announced", said, [])

got, said = combo(True, False)
chk("legacy only -> the legacy name", got, "perk_overrides.csv")
chk("...and nothing is announced", said, [])

got, said = combo(False, True)
chk("current only -> the current name", got, "rotation_overrides_AF568.csv")
chk("...and nothing is announced", said, [])

got, said = combo(True, True)
chk("both -> the current name wins", got, "rotation_overrides_AF568.csv")
chk("...and the fact is ANNOUNCED, not silently resolved", len(said), 1)
chk("...naming the file that is being ignored",
    "perk_overrides.csv" in (said[0] if said else ""), True)
chk("...and when it was last written",
    any(c.isdigit() for c in (said[0] if said else "")), True)

print()
print("--- a fresh study that happens to call a marker AF568 ---")
# The legacy table is keyed on (artifact, MARKER NAME) and gated on
# os.path.exists, so it is a claim about one out_root rather than a claim about
# what "AF568" means anywhere. A new lab that reuses the fluorophore name in an
# empty out_root must never be handed perk_overrides.csv.
with tempfile.TemporaryDirectory(prefix="lspaths_fresh_") as tmp:
    fresh = P.Names(tmp, ["AF568", "AF488"], "paired")
    os.makedirs(os.path.join(tmp, "reformatted"), exist_ok=True)
    for key in sorted(P.ARTIFACTS):
        for m in ("AF568", "AF488"):
            got = fresh.read(key, m, announce=lambda _m: None)
            if got != fresh.path(key, m):
                chk(f"empty out_root: {key}/{m} stayed on the current name",
                    base(got), base(fresh.path(key, m)))
    chk("no artifact in an empty out_root resolves to a legacy name",
        sorted({k for k in P.ARTIFACTS for m in ("AF568", "AF488")
                if fresh.read(k, m, announce=lambda _m: None)
                != fresh.path(k, m)}), [])
    chk("...and path() never even offers one",
        sorted({k for k in P.ARTIFACTS for m in ("AF568", "AF488")
                if fresh.path(k, m) == fresh.legacy_path(k, m)}), [])

print()
print("--- LEGACY_GROUPS: roi_geometry and roi_boxes, together or not at all ---")
# 05a.resolve_paths (scripts/05a_roi_geometry.py:128-155) refuses to adopt
# roi_geometry.csv on its own: deciding on one file alone would hand back a
# legacy path for a repo that already has the suffixed one, and that path may
# not exist. Preserved here exactly.
chk("the group is declared", P.LEGACY_GROUPS, [("roi_geometry", "roi_boxes")])


def group_case(geom_legacy, box_legacy, geom_cur=False, box_cur=False):
    tmp = tempfile.mkdtemp(prefix="lspaths_grp_")
    n = P.Names(tmp, ["AF568", "AF488"], "paired")
    os.makedirs(os.path.join(tmp, "reformatted"), exist_ok=True)
    for flag, key in ((geom_legacy, "roi_geometry"), (box_legacy, "roi_boxes")):
        if flag:
            open(n.legacy_path(key, "AF568"), "w").close()
    for flag, key in ((geom_cur, "roi_geometry"), (box_cur, "roi_boxes")):
        if flag:
            open(n.path(key, "AF568"), "w").close()
    quiet = lambda _m: None                                   # noqa: E731
    return (base(n.read("roi_geometry", "AF568", announce=quiet)),
            base(n.read("roi_boxes", "AF568", announce=quiet)))

chk("both legacy present -> both adopted",
    group_case(True, True), ("roi_geometry.csv", "roi_boxes.csv"))
chk("geometry present, boxes absent -> NEITHER adopted",
    group_case(True, False),
    ("roi_geometry_AF568.csv", "roi_boxes_AF568.csv"))
chk("boxes present, geometry absent -> NEITHER adopted",
    group_case(False, True),
    ("roi_geometry_AF568.csv", "roi_boxes_AF568.csv"))
chk("neither present -> the current pair",
    group_case(False, False),
    ("roi_geometry_AF568.csv", "roi_boxes_AF568.csv"))
# The half-migrated repo 05a's comment is about: both legacy files still there,
# but one suffixed file already written. Adopting the legacy pair would read
# stale geometry against fresh boxes.
chk("both legacy present but one current file written -> NEITHER adopted",
    group_case(True, True, box_cur=True),
    ("roi_geometry_AF568.csv", "roi_boxes_AF568.csv"))

print()
print("--- migrate_report(): finds legacy files, moves nothing ---")
with tempfile.TemporaryDirectory(prefix="lspaths_mig_") as tmp:
    n = P.Names(tmp, ["AF568", "AF488"], "paired")
    os.makedirs(os.path.join(tmp, "reformatted"), exist_ok=True)
    legacy = n.legacy_path("analysis_set", "AF568")
    open(legacy, "w").close()
    rows = P.migrate_report(n)
    chk("the legacy file is reported",
        [(r["artifact"], r["marker"], base(r["legacy"]), base(r["current"]))
         for r in rows],
        [("analysis_set", "AF568", "perk_analysis_set.csv",
          "AF568_analysis_set.csv")])
    chk("...and it is still exactly where it was", os.path.exists(legacy), True)
    chk("...and nothing was created under the current name",
        os.path.exists(n.path("analysis_set", "AF568")), False)

print()
print("--- for_config() ---")
chk("for_config is memoised on (out_root, markers, layout)",
    P.for_config(STUDY.config) is P.for_config(STUDY.config), True)
chk("...and reads the markers ls_channels reports",
    P.for_config(STUDY.config).markers, ["AF568", "AF488"])
chk("...and the layout the study declared",
    P.for_config(STUDY.config).layout, "paired")

# A different study must not be handed the first study's Names.
with temp_study(acquisition={"layout": "paired",
                             "markers": ["Mk1", "Mk2"]}) as other:
    alt = P.for_config(other.config)
    chk("a second study gets its own Names", alt is live, False)
    chk("...whose geometry source is ITS second marker",
        alt.geometry_source_marker, "Mk2")
    chk("...so Mk2 owns the unsuffixed sections dir",
        base(alt.path("sections", "Mk2")), "sections")
    chk("...and Mk1 is the suffixed one",
        base(alt.path("sections", "Mk1")), "sections_Mk1")
    # The whole point of the module: a study whose markers are not
    # fluorophores must never see one of the operator's basenames, even with
    # those files present.
    os.makedirs(os.path.join(other.out_root, "reformatted"), exist_ok=True)
    open(os.path.join(other.out_root, "reformatted",
                      "perk_overrides.csv"), "w").close()
    chk("a foreign perk_overrides.csv is not adopted by Mk1",
        base(alt.read("overrides", "Mk1", announce=lambda _m: None)),
        "rotation_overrides_Mk1.csv")
    # ...and 04a, imported under THAT study, agrees with it key for key.
    alt_rf = load_stage("04a_reformat.py", name="lsstage_04a_alt")
    for m in ("Mk1", "Mk2"):
        for key in ("sections", "index", "excluded", "lost"):
            chk(f"Mk study: {key} for {m} agrees with 04a",
                alt.path(key, m), alt_rf.marker_paths(m)[key])
    # ...`overrides` included, and this one is the whole point. 04a used to
    # return the LITERAL perk_overrides.csv for every non-source marker, so a
    # study whose markers are Mk1/Mk2 was told to keep its rotations in a file
    # named after an antibody it does not measure - and the file laid down
    # above is proof that being on the drive is not enough to be adopted: the
    # legacy table is keyed on the MARKER NAME, and Mk1 is not AF568.
    chk("Mk study: overrides for Mk1 agrees with 04a",
        alt.path("overrides", "Mk1"), alt_rf.marker_paths("Mk1")["overrides"])
    chk("...and names the marker, not the operator's antibody",
        base(alt_rf.marker_paths("Mk1")["overrides"]),
        "rotation_overrides_Mk1.csv")
    chk("Mk study: overrides for the geometry source agrees with 04a",
        alt.path("overrides", "Mk2"), alt_rf.marker_paths("Mk2")["overrides"])

print()
print("--- three markers, three override files ---")
# The collision the literal caused, stated as a test. With `perk_overrides.csv`
# hardcoded for every non-source marker, Mk1 and Mk3 were handed the SAME file
# and whichever ran second overwrote the first's curation. Two markers, one
# file, no error.
with temp_study(acquisition={"layout": "paired",
                             "markers": ["Mk1", "Mk2", "Mk3"]}) as three:
    tri = load_stage("04a_reformat.py", name="lsstage_04a_three")
    tri_ov = [base(tri.marker_paths(m)["overrides"]) for m in ("Mk1", "Mk2", "Mk3")]
    chk("three markers get three distinct override files", len(set(tri_ov)), 3)
    chk("...each named after itself, the geometry source unsuffixed", tri_ov,
        ["rotation_overrides_Mk1.csv", "rotation_overrides.csv",
         "rotation_overrides_Mk3.csv"])
    chk("...and the geometry source really is the SECOND declared",
        tri.DEFAULT_MARKER, "Mk2")

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
