"""Stage 6h: appending the provenance columns to an existing roi_nuclei.csv.

The file this rewrites is the dataset - 130 curated sections, hundreds of
thousands of rows, hours of StarDist that cannot be re-run cheaply. So the ways
of ruining it are pinned here rather than discovered on the operator's drive:

  * A PARTIAL WRITE. The volume this runs against does not merely drop writes,
    it goes away (see scripts/ls_io.py). A rewrite that lands half a file
    destroys the dataset, so the new bytes go to a temp file beside the target
    and one `os.replace` swaps them in. The real file is never opened for
    writing.
  * A FILE OF TWO WIDTHS. The whole point is that EVERY row gains the three
    columns. csv.DictReader hands back None - not an error - for a field the
    header does not name, None is falsy, and 06a would then withhold the
    Abercrombie correction from every correctly-nuclear row.
  * FILLING IN A HEADER THIS DOES NOT UNDERSTAND. The values it writes are true
    of a file written before the provenance columns existed and of nothing
    else. A header that is not exactly those 21 columns has to be refused, not
    guessed at - including one that is those columns in a different order,
    since the rows are then not what their positions say.

Idempotence is not a nicety here either: the operator re-runs stages, and a
second run must not append `segmented_on` twice.

Synthetic CSVs in a temp dir throughout. This suite never reads or writes
out_root.

Run:  python tests/test_backfill_provenance.py
"""

import csv
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# This suite imports stage modules, which read config at import. Without a
# config of its own it would fall through to the operator's live study and
# then pass or fail on their data. See tests/_fixture.py.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _fixture import load_stage, temp_study, use_temp_study  # noqa: E402

STUDY = use_temp_study()

G5C = load_stage("05c_detect_rois.py")
MOD = load_stage("06h_backfill_provenance.py")

fails = 0


def chk(label, got, want):
    global fails
    ok = str(got) == str(want)
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + str(got)
          + ("" if ok else "   want " + str(want)))


def row(n, marker, kind):
    """One row that looks like the operator's, under the 21-column header.

    The values are arbitrary except that they are all different, so a rewrite
    that shifts a field by one shows up instead of passing.
    """
    return [f"LS{n:02d}_s01a_sc01", f"LS{n:02d}", marker, kind, "Dm", "3",
            "0", str(n), "1000", "2000", "100.5", "200.5",
            "42.0", "7.3", "812.0", "301.0", "295.0", "410.0",
            "0", "0", "0"]


ROWS = [row(1, "AF568", "roi"), row(2, "AF488", "background"),
        row(3, "AF568", "roi")]


def write_csv(path, cols, rows, terminator="\r\n"):
    """Lay down a synthetic file and return its bytes, for comparing after."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator=terminator)
        w.writerow(cols)
        w.writerows(rows)
    with open(path, "rb") as fh:
        return fh.read()


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        return next(rd), [r for r in rd if r]


def raw(path):
    with open(path, "rb") as fh:
        return fh.read()


def tmp_left(path):
    return os.path.exists(path + ".tmp")


# ---------------------------------------------------------------------------

def constants_check():
    """What gets filled in is 05c's answer and the study's - not this stage's."""
    chk("the header this accepts is 05c's pre-provenance one",
        len(G5C.LEGACY_COLUMNS), 21)
    chk("...taken from 05c, not restated here",
        MOD.LEGACY_COLUMNS == G5C.LEGACY_COLUMNS, True)
    chk("the fill values are 05c's LEGACY_PROVENANCE, not a copy",
        MOD.PROVENANCE == G5C.LEGACY_PROVENANCE, True)
    chk("backend='stardist'", MOD.PROVENANCE["backend"], "stardist")
    chk("nucleus_shaped='1'", MOD.PROVENANCE["nucleus_shaped"], "1")
    # `segmented_on` is the counterstain's name AS THE STUDY DECLARES IT, so
    # that a backfilled row and a row 05c appends afterwards say the same
    # thing rather than two spellings of it. This fixture study is the example
    # config - multiplex, with a declared nuclear channel.
    chk("a declared nuclear channel is what segmented_on records",
        MOD.PROVENANCE["segmented_on"], G5C.NUCLEAR_NAME)
    chk("...which for this study is its channel table's name",
        MOD.PROVENANCE["segmented_on"], "DAPI")


def paired_study_fallback():
    """The live study's branch: no channel table, so no name to record.

    A `paired` study declares no channels by definition - each of its scans
    carries the counterstain plus one marker - so its counterstain has no
    declared name. Writing an empty cell would leave a reader unable to tell
    "segmented on the counterstain" from "this column was never filled in", so
    the literal "nuclear" goes in. This is what the operator's file gets, so it
    is checked against a study shaped like theirs rather than assumed.
    """
    with temp_study(acquisition={"layout": "paired", "channels": [],
                                 "markers": ["AF568", "AF488"]}):
        paired = load_stage("06h_backfill_provenance.py", name="lsstage_06h_paired")
        chk("a study with no channel table falls back to 'nuclear'",
            paired.PROVENANCE["segmented_on"], "nuclear")
        chk("...and the other two are unchanged",
            (paired.PROVENANCE["backend"], paired.PROVENANCE["nucleus_shaped"]),
            ("stardist", "1"))


def happy_path(tmp):
    """A 21-column file gains three columns on every row, and nothing else."""
    path = os.path.join(tmp, "roi_nuclei.csv")
    before = write_csv(path, G5C.LEGACY_COLUMNS, ROWS)

    got = MOD.migrate(path, backup_dir=os.path.join(tmp, "_backup"))
    chk("it reports a backfill", got["action"], "backfilled")
    chk("...of every row", got["rows"], len(ROWS))

    header, rows = read_csv(path)
    chk("the header is now exactly 05c's COLUMNS", header == G5C.COLUMNS, True)
    chk("every row is one width", sorted({len(r) for r in rows}),
        [len(G5C.COLUMNS)])
    chk("no row was lost or duplicated", len(rows), len(ROWS))
    chk("the 21 columns that were there are untouched",
        [r[:21] for r in rows] == ROWS, True)
    for col in ("segmented_on", "backend", "nucleus_shaped"):
        chk(f"{col} is filled in on every row",
            sorted({r[header.index(col)] for r in rows}),
            [MOD.PROVENANCE[col]])
    chk("the temp file is gone", tmp_left(path), False)

    backup = os.path.join(tmp, "_backup", "roi_nuclei.csv")
    chk("the file it replaced was backed up first", os.path.exists(backup), True)
    chk("...byte for byte", raw(backup) == before, True)


def default_backup(tmp):
    """The backup lands beside the file being migrated, not beside the study's.

    `--path` exists so this can be rehearsed on a copy. If the default backup
    directory came from the config instead of from the file, rehearsing on a
    copy would write into the operator's real results/ - the one thing a
    rehearsal must not do.
    """
    here = os.path.join(tmp, "elsewhere")
    os.makedirs(here, exist_ok=True)
    path = os.path.join(here, "roi_nuclei.csv")
    write_csv(path, G5C.LEGACY_COLUMNS, ROWS)

    MOD.migrate(path)
    chk("the backup is beside the file, not under the study's results/",
        os.path.exists(os.path.join(here, "_pre_06h_backup", "roi_nuclei.csv")),
        True)
    chk("...and nothing was written under the study's out_root",
        os.path.exists(MOD.BACKUP_DIR), False)


def already_migrated(tmp):
    """A second run is a no-op, not a second set of columns."""
    path = os.path.join(tmp, "roi_nuclei.csv")
    write_csv(path, G5C.LEGACY_COLUMNS, ROWS)
    MOD.migrate(path, backup=False)
    once = raw(path)

    got = MOD.migrate(path, backup=False)
    chk("a migrated file is recognised", got["action"], "already")
    chk("...and not rewritten", got["rows"], 0)
    chk("...and its bytes are identical", raw(path) == once, True)
    chk("no temp file was left behind", tmp_left(path), False)

    header, _ = read_csv(path)
    chk("the columns were not appended twice", len(header), len(G5C.COLUMNS))


def wrong_header(tmp):
    """Anything but those 21 columns is refused, and nothing is written."""
    cases = (
        ("a file from before off_tissue (20 columns)",
         [c for c in G5C.LEGACY_COLUMNS if c != "off_tissue"]),
        ("the right 21 columns in the wrong order",
         G5C.LEGACY_COLUMNS[:5][::-1] + G5C.LEGACY_COLUMNS[5:]),
        ("21 columns, one of them not ours",
         G5C.LEGACY_COLUMNS[:-1] + ["something_else"]),
    )
    for label, cols in cases:
        path = os.path.join(tmp, "wrong.csv")
        before = write_csv(path, cols, [r[:len(cols)] for r in ROWS])
        said = ""
        try:
            MOD.migrate(path, backup=False)
            raised = "nothing"
        except SystemExit as exc:
            raised = "SystemExit"
            said = str(exc)
        chk(f"{label} is refused", raised, "SystemExit")
        chk("...naming the file", os.path.basename(path) in said, True)
        chk("...leaving it byte for byte as it was", raw(path) == before, True)
        chk("...and no temp file", tmp_left(path), False)
        os.remove(path)


def dry_run(tmp):
    """A dry run reports the work and writes nothing."""
    path = os.path.join(tmp, "roi_nuclei.csv")
    before = write_csv(path, G5C.LEGACY_COLUMNS, ROWS)
    got = MOD.migrate(path, dry_run=True, backup=False)
    chk("a dry run still counts the rows", got["rows"], len(ROWS))
    chk("...and says what it would do", got["action"], "backfilled")
    chk("...but the file is unchanged", raw(path) == before, True)
    chk("...and no temp file remains", tmp_left(path), False)


def line_endings(tmp):
    """The rewrite keeps the terminator the file already used.

    roi_nuclei.csv is written by csv.writer on Windows, so its lines end CRLF.
    This stage must not be the thing that silently rewrites a whole dataset
    from LF into CRLF or back, so it copies the terminator rather than taking
    csv.writer's default.
    """
    for nl in ("\r\n", "\n"):
        path = os.path.join(tmp, "endings.csv")
        write_csv(path, G5C.LEGACY_COLUMNS, ROWS, terminator=nl)
        MOD.migrate(path, backup=False)
        body = raw(path)
        chk(f"a {nl!r} file stays {nl!r}", body.count(b"\r\n" if nl == "\r\n"
                                                      else b"\n"),
            len(ROWS) + 1)
        if nl == "\n":
            chk("...with no stray CR", b"\r" in body, False)
        os.remove(path)


def main():
    tmp = tempfile.mkdtemp(prefix="ls6h_")
    try:
        print()
        print("--- what gets filled in, and where it comes from ---")
        constants_check()
        paired_study_fallback()
        print()
        print("--- a file written before the provenance columns ---")
        happy_path(tmp)
        default_backup(tmp)
        print()
        print("--- a file that has already been migrated ---")
        already_migrated(tmp)
        print()
        print("--- a header this stage does not understand ---")
        wrong_header(tmp)
        print()
        print("--- a dry run ---")
        dry_run(tmp)
        print()
        print("--- line endings ---")
        line_endings(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
