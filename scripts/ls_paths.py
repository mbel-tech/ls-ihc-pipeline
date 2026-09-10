"""Where a marker's artifacts live. One rule, one place.

Under `paired`, each marker is a separate physical scan of the same sections,
so each gets its own section directory, its own reformat index and its own
exclusion lists. One of them - the pass that was curated first - owns the
UNSUFFIXED names, because those files were written before the pipeline had a
second marker and 130 curated sections still point at them.

That single sentence is currently written out eight times across the codebase,
and several of the copies have it backwards. An inverted copy is not loud.
`04q_import_curation` looked in `sections/` for a marker whose page had been
drawn from `sections_AF568_rgb/`, failed to find the 768-px image, fell back to
a scale factor of 1.0 where the curator had drawn at K=3, and imported every
disc, landmark and polygon vertex a third of the way towards the origin.
Nothing raised. This module exists so there is exactly one place to be wrong.

THE TRAP, stated once so a reader meets it before writing a ninth copy: the
marker with the unsuffixed outputs is the **second** declared. `04a` has always
defaulted to `MARKERS[1]` (AF488 = PCNA on the LS study) because that is the
pass that was curated first. Code that assumes "first declared = unsuffixed" is
inverted, and for a two-marker study it is inverted in a way that still
produces perfectly plausible filenames.

Under `multiplex` one scan carries every marker, so the reformat is decided
once per SCENE and every marker answers with the same unsuffixed names. Both
layouts are handled here; neither is handled anywhere else.

Deliberately imports no stage module. `04a_reformat.py` is 900 lines of image
processing that pulls in numpy and PIL, and this table needs to be readable by
a test, by the app and by `--migrate` without any of that. The dependency runs
the other way: stages delegate TO this, never the reverse.

    python scripts/ls_paths.py --migrate     # lists legacy files, moves none
"""

import os
import re
import time

import ls_channels as CH

#: An artifact's name, as a rule rather than as a string.
#:
#:   key -> (subdir, stem, ext, suffix_ruled)
#:
#: `suffix_ruled` True means the suffix rule above applies: the geometry source
#: gets `<stem><ext>`, every other marker gets `<stem>_<marker><ext>`. `None`
#: means the stem is a template carrying `{marker}` and the suffix rule does
#: NOT apply - the marker's name is in the filename for every marker, geometry
#: source included.
#:
#: An empty `ext` is a directory, not a file with no extension.
ARTIFACTS = {
    # key                subdir         stem                     ext     ruled
    "sections":         ("reformatted", "sections",              "",     True),
    "index":            ("reformatted", "reformat_index",        ".csv", True),
    "excluded":         ("reformatted", "excluded_sections",     ".csv", True),
    "lost":             ("reformatted", "lost_sections",         ".csv", True),
    "overrides":        ("reformatted", "rotation_overrides",    ".csv", True),
    "sections_dataset": ("reformatted", "sections_dataset",      ".csv", True),
    "artifact_summary": ("artifacts",   "artifact_summary",      ".csv", True),
    # NOT suffix-ruled. 04j names EVERY marker's file after the marker,
    # including the geometry source (pcna_analysis_set.csv). That is what is on
    # disk, and a reader who assumed the suffix rule everywhere would go
    # looking for analysis_set.csv and find nothing. 05a does the same for its
    # two geometry files, and for a stated reason: the markers of a paired
    # study have disjoint scene_uids, so one export must never overwrite the
    # other's boxes - roi_nuclei.csv joins to that file by (scene_uid,
    # roi_index) and 883,000 measured rows would quietly lose the geometry they
    # were measured against.
    "analysis_set":     ("reformatted", "{marker}_analysis_set", ".csv", None),
    "roi_geometry":     ("reformatted", "roi_geometry_{marker}", ".csv", None),
    "roi_boxes":        ("reformatted", "roi_boxes_{marker}",    ".csv", None),
}

#: Basenames that EXIST ON ONE OPERATOR'S DRIVE. Not a naming convention.
#:
#: Keyed on (artifact, MARKER NAME) rather than on a role, because a study
#: whose markers are ["Mk1", "Mk2"] must get `Mk1_analysis_set.csv` and never
#: `perk_analysis_set.csv` - the antibody names in these values mean nothing
#: outside the LS study, and a role key would carry them into every study that
#: has a first marker.
#:
#: `os.path.exists` is what decides whether any of these is used, so the claim
#: this table makes is "these files are in THIS out_root", not "AF568 means
#: pERK". A fresh study that happens to reuse the fluorophore name AF568 in an
#: empty out_root never reaches one of these names: nothing is there to find.
#:
#: Nothing is ever WRITTEN under a legacy name - see Names.path.
LEGACY = {
    ("overrides",        "AF568"): "perk_overrides.csv",
    ("sections_dataset", "AF568"): "perk_sections_dataset.csv",
    ("analysis_set",     "AF568"): "perk_analysis_set.csv",
    ("analysis_set",     "AF488"): "pcna_analysis_set.csv",
    ("roi_geometry",     "AF568"): "roi_geometry.csv",
    ("roi_boxes",        "AF568"): "roi_boxes.csv",
}

#: Artifacts that are adopted together or not at all.
#:
#: 05a.resolve_paths (scripts/05a_roi_geometry.py:128-155) already refuses to
#: adopt `roi_geometry.csv` on the strength of `roi_boxes.csv` alone: deciding
#: on one file would hand back a legacy path for a repo that has already
#: written the suffixed one, and that path may not exist. The rule is preserved
#: exactly - every member's legacy file must be present AND no member's current
#: file may be, or none of them is adopted.
LEGACY_GROUPS = [("roi_geometry", "roi_boxes")]

_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def slug(name):
    """A marker name as it appears inside a derived COLUMN name.

    `slug("AF568") == "af568"`, which is what `02_pair_passes.py` already
    writes into pairs.csv: `af568_file`, `af568_scene`, `af568_scene_uid`,
    `n_af568`. Deriving those from here rather than from a literal therefore
    leaves the live pairs.csv header byte-identical - checked, not assumed;
    tests/test_ls_paths.py pins it.

    Not `ls_config.slugify`, which separates with `-`. These become CSV column
    names and parts of R variable names, where a hyphen is an operator.
    """
    return _SLUG_RE.sub("_", str(name)).strip("_").lower()


def slug_collisions(markers):
    """{slug: [markers]} for any slug two markers would share.

    "Mk 1" and "Mk-1" both slug to `mk_1`, so they would share every derived
    column in pairs.csv and one marker's values would silently land in the
    other's cells. Findable here rather than discovered as a column that holds
    the right numbers some of the time.
    """
    seen = {}
    for m in markers:
        seen.setdefault(slug(m), []).append(m)
    return {s: ms for s, ms in seen.items() if len(ms) > 1}


def geometry_source(markers, layout):
    """The marker whose artifacts carry the unsuffixed names, or None.

    Under `paired` this is `markers[1]` - the SECOND declared - matching
    `04a.DEFAULT_MARKER`. It is the pass that was curated first, and its files
    were written before there was anything to suffix against. Taking the first
    declared instead would silently rename 130 curated sections' worth of
    outputs, which is the whole reason 04a's comment says not to.

    Under `multiplex` there is one scan per section carrying every marker, so
    no pass is distinguished and every marker answers with the unsuffixed
    names. There is no source to return, so this returns None and `suffix()`
    is `""` for everybody.
    """
    markers = list(markers or [])
    if layout != CH.LAYOUT_PAIRED or not markers:
        return None
    return markers[1] if len(markers) > 1 else markers[0]


class Names:
    """Every artifact path for one study.

    Built from three facts - where the outputs go, which markers there are and
    in what order, and which layout was acquired - and nothing else. No config
    object is held, so a caller can construct one for a directory that is not
    a study at all, which is what makes this testable in a temp tree.
    """

    def __init__(self, out_root, markers, layout):
        self.out_root = out_root
        self.markers = list(markers or [])
        self.layout = layout
        self.geometry_source_marker = geometry_source(self.markers, layout)

    def _check(self, marker):
        # A marker this study did not declare is a caller bug, and it has to be
        # loud: silently deriving `sections_Mk9` would create a directory that
        # nothing else ever looks in, and the stage would report zero sections
        # rather than an error. Markers are only checked when there are any -
        # a Names built for a bare directory has no list to check against.
        if self.markers and marker not in self.markers:
            raise ValueError(
                f"unknown marker {marker!r}; this study declares {self.markers}")

    def suffix(self, marker):
        """`""` for the geometry source, `"_<marker>"` for everyone else."""
        self._check(marker)
        if self.geometry_source_marker is None:
            # multiplex, or a study with no markers: one set of names.
            return ""
        return "" if marker == self.geometry_source_marker else f"_{marker}"

    def path(self, artifact, marker):
        """Where a WRITER writes this marker's artifact. Never a legacy name.

        This is the half of the module that must stay pure. A writer that
        resolved to a legacy name would keep writing `perk_overrides.csv`
        forever, the branch that writes the derived name would never execute,
        and the first study that is not LS would inherit an antibody name it
        does not measure - while every test kept passing, because the file it
        asserted on would still be there. Both of this codebase's last two
        silent bugs survived on exactly that shape: a fallback that was never
        observed to be a fallback.

        `read()` is the only method allowed to answer with a legacy name, and
        only for a file that is demonstrably on the drive.
        """
        self._check(marker)
        subdir, stem, ext, ruled = ARTIFACTS[artifact]
        name = (stem.format(marker=marker) if ruled is None
                else stem + self.suffix(marker))
        return os.path.join(self.out_root, subdir, name + ext)

    def legacy_path(self, artifact, marker):
        """The pre-rename basename for this pair, or None. Existence unchecked."""
        basename = LEGACY.get((artifact, marker))
        if basename is None:
            return None
        subdir = ARTIFACTS[artifact][0]
        return os.path.join(self.out_root, subdir, basename)

    def _adoptable(self, artifact, marker):
        """True when this artifact alone would take its legacy name."""
        legacy = self.legacy_path(artifact, marker)
        return (legacy is not None and os.path.exists(legacy)
                and not os.path.exists(self.path(artifact, marker)))

    def read(self, artifact, marker, announce=print):
        """Which file to READ for this marker: the current name unless only the
        legacy one is there.

        Existence decides, rather than a version number or a config flag,
        because the question being asked is "which of these files did this
        out_root actually get written". A flag can be wrong about a drive; a
        drive cannot be wrong about itself.

        When BOTH exist the current name wins and the fact is PRINTED:

            Two files that mean the same thing and disagree in age is how a
            stale number survives a rename; a reader that silently prefers one
            of them is the same bug as a reader that silently prefers the
            other.

        so the announcement names the file being ignored and when it was last
        written, which is the one piece of evidence that tells an operator
        whether the ignored copy mattered.
        """
        current = self.path(artifact, marker)
        legacy = self.legacy_path(artifact, marker)
        if legacy is None:
            return current

        if os.path.exists(legacy) and os.path.exists(current):
            older = min((legacy, current), key=os.path.getmtime)
            stamp = time.strftime("%Y-%m-%d %H:%M",
                                  time.localtime(os.path.getmtime(older)))
            announce(
                f"  note: both {os.path.basename(legacy)} and "
                f"{os.path.basename(current)} exist; reading "
                f"{os.path.basename(current)}. The older of the two, "
                f"{os.path.basename(older)}, was last written {stamp} and is "
                f"being ignored.")
            return current

        if not self._adoptable(artifact, marker):
            return current

        # Group members are adopted together or not at all - see LEGACY_GROUPS.
        for group in LEGACY_GROUPS:
            if artifact in group and not all(self._adoptable(other, marker)
                                             for other in group):
                return current
        return legacy

    def all_paths(self, artifact):
        """{marker: path} for every marker this study declares."""
        return {m: self.path(artifact, m) for m in self.markers}


def migrate_report(names):
    """Every legacy file present under this study's out_root, and its new name.

    A report, not a migration. Nothing is moved, copied or deleted: the files
    this finds are read by 04l, 04m and 04p and by the app's stage table, and a
    rename that half-succeeded on a drive that goes away mid-write (see
    ls_io) would leave the operator with neither name. Deciding to move them is
    the operator's, once they can see the list.
    """
    rows = []
    for (artifact, marker), basename in sorted(LEGACY.items()):
        if marker not in names.markers:
            # A legacy entry for a marker this study never declared. The file
            # may well be sitting there - the drive does not know which study
            # is asking - but renaming it into this study's namespace would be
            # inventing a marker.
            continue
        legacy = names.legacy_path(artifact, marker)
        if not os.path.exists(legacy):
            continue
        current = names.path(artifact, marker)
        rows.append({"artifact": artifact, "marker": marker,
                     "legacy": legacy, "current": current,
                     "current_exists": os.path.exists(current),
                     "bytes": os.path.getsize(legacy)})
    return rows


_CACHE = {}


def for_config(cfg):
    """The `Names` for a config, memoised on (out_root, markers, layout).

    Memoised because most callers are module-level stage constants evaluated at
    import, and there are 46 of them; the key is the three facts a Names is
    built from, so two configs that differ anywhere else share one instance and
    two studies never do.
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    out_root = cfg.get("out_root")
    markers = tuple(CH.marker_names(cfg))
    layout = (cfg.get("acquisition") or {}).get("layout", CH.LAYOUT_MULTIPLEX)
    key = (out_root, markers, layout)
    if key not in _CACHE:
        _CACHE[key] = Names(out_root, list(markers), layout)
    return _CACHE[key]


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog="ls_paths.py",
        description=("Report where this study's artifacts are named, and which "
                     "pre-rename files are still on the drive."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("--migrate MOVES NOTHING. It lists every legacy file found\n"
                "under out_root and the current name it maps to, so the\n"
                "operator can decide. Renaming these by machine would touch\n"
                "files that 04l, 04m and 04p read while a curation session is\n"
                "open, and a half-finished rename on a drive that goes away\n"
                "mid-write leaves neither name."))
    parser.add_argument("--migrate", action="store_true",
                        help="list the legacy files on the drive. Moves nothing.")
    parser.add_argument("--table", action="store_true",
                        help="print every artifact path, per marker.")
    args = parser.parse_args(argv)

    from ls_config import CONFIG, CONFIG_PATH
    names = for_config(CONFIG)
    print(f"config   {CONFIG_PATH}")
    print(f"out_root {names.out_root}")
    print(f"layout   {names.layout}")
    print(f"markers  {names.markers}"
          f"   (geometry source: {names.geometry_source_marker})")
    collisions = slug_collisions(names.markers)
    if collisions:
        print(f"  !! markers share a derived column name: {collisions}")

    if args.table:
        print()
        for artifact in sorted(ARTIFACTS):
            for marker in names.markers:
                print(f"  {artifact:<17} {marker:<8} "
                      f"{os.path.basename(names.path(artifact, marker))}")

    if args.migrate:
        print()
        print("--- legacy files present (NOTHING IS MOVED) ---")
        rows = migrate_report(names)
        if not rows:
            print("  none")
        for r in rows:
            flag = "  <-- current name also present" if r["current_exists"] else ""
            print(f"  {os.path.basename(r['legacy']):<28} -> "
                  f"{os.path.basename(r['current']):<30} "
                  f"({r['bytes']} bytes, {r['artifact']}/{r['marker']}){flag}")
        print()
        print(f"  {len(rows)} legacy file(s). Nothing was moved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
