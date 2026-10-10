"""Stage 6h - fill in the segmentation provenance columns on an existing
roi_nuclei.csv, so a file written before they existed says what it is.

`05c_detect_rois.py` gained `segmented_on`, `backend` and `nucleus_shaped` on
2026-09-08, taking COLUMNS from 21 to 24. They record how each object was
produced, per row rather than per config, because a dataset outlives the config
that made it and 06a's Abercrombie gate depends on the answer.

**What their absence means is known, not guessed.** Before those columns existed
this pipeline had exactly one route to an object: segment the counterstain with
StarDist and measure the marker inside the nuclear mask. There was no other
path in the code to take. So every row of a pre-provenance file is
nuclear / stardist / nucleus-shaped, and that is what this fills in - the same
reading 06a's Task 6 gate already gives a column that is not there, and the
same three values 05c writes today for a nuclear-segmented marker. An upgraded
file is indistinguishable from one written fresh.

`segmented_on` gets the counterstain's name AS THE STUDY DECLARES IT rather
than the literal "nuclear", so a backfilled row and a freshly appended one in
the same file say the same thing instead of two spellings of it. For the live
study that string IS "nuclear": it is `paired`, so it declares no channel table
by definition, and its counterstain has no declared name. Both the header and
the fill values are imported from 05c rather than restated here - two lists
that must agree are one list.

**This stage is not the only route, and is not the one a resume takes.**
`05c.check_header(..., legacy=...)` backfills the same three columns in place
when a run resumes onto an old file, which is what the operator's next
detection run will do on its own. This exists for the case that has no
detection run in it: migrating the dataset now, without loading StarDist,
without reading a CZI, and without committing to re-segment anything - and
with a dry run, a backup and a verify pass, which a resume's inline rewrite
does not stop to offer.

**It refuses anything but exactly those 21 columns, in that order.** The values
above are true of a pre-provenance file and of nothing else, and the append is
positional, so a permuted header would take every row scrambled. A file from
before `off_tissue` (20 columns) is a different migration and 06g owns it; run
that first, and this second. Nothing here is inferred from a header it does not
recognise.

**Every row, or no rows.** Accepting a partial rewrite - old rows at 21 fields,
new ones at 24 - is the failure this stage exists to make impossible:
csv.DictReader hands back None, not an error, for a field the header does not
name; None is falsy; and 06a would then withhold the Abercrombie correction
from every correctly-nuclear row. So the new bytes go to a temp file beside the
target and one `os.replace` swaps them in, through `ls_io.atomic_save` for its
retry - the D: volume does not merely drop writes, it goes away, and a
half-written roi_nuclei.csv is the whole dataset.

Running it twice is a no-op: a file already at 24 columns is left alone.

It needs room for two more copies of the table while it runs - the temp file
and, unless `--no-backup`, the pre-migration backup - so about three times the
file's size free on the volume. `--dry-run` needs none of that and reads the
whole table, which is the cheap way to find out whether it would be accepted.

Run:  python 06h_backfill_provenance.py --dry-run
      python 06h_backfill_provenance.py
      python 06h_backfill_provenance.py --verify
"""

import argparse
import csv
import importlib.util
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# 05c owns the header and owns what a missing provenance column means. Imported
# by path like every other cross-stage import here, so this file cannot drift
# from the one it is migrating towards. It loads StarDist lazily inside
# load_model(), so importing it costs no weights.
_spec = importlib.util.spec_from_file_location(
    "_g5c", os.path.join(_HERE, "05c_detect_rois.py"))
G5C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G5C)

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(_HERE, "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

OUT_ROOT = CONFIG["out_root"]
RESULTS_DIR = os.path.join(OUT_ROOT, "results")
NUCLEI_CSV = os.path.join(RESULTS_DIR, "roi_nuclei.csv")

#: Where the pre-migration copy goes, taken from the file being migrated rather
#: than from the config. `--path` exists so this can be rehearsed on a copy of
#: the operator's table, and a backup directory resolved from the config would
#: make that rehearsal write into their real results/ - the one thing it must
#: not do. For the default path the two are the same directory.
BACKUP_NAME = "_pre_06h_backup"
BACKUP_DIR = os.path.join(RESULTS_DIR, BACKUP_NAME)

#: The header this stage writes, and the one it accepts.
COLUMNS = list(G5C.COLUMNS)
LEGACY_COLUMNS = list(G5C.LEGACY_COLUMNS)

#: Column -> the value every pre-provenance row gets. 05c's, not a copy.
PROVENANCE = dict(G5C.LEGACY_PROVENANCE)

#: How to build one output row: for each column of COLUMNS, either the index it
#: sits at in the old header, or the value to fill in. Computed once rather than
#: per row - this runs over hundreds of thousands of them - and by NAME, so it
#: stays right if the three columns ever move out of last place.
_MAP = [(LEGACY_COLUMNS.index(c), None) if c in LEGACY_COLUMNS
        else (None, PROVENANCE[c]) for c in COLUMNS]


def backup_dir_for(path):
    return os.path.join(os.path.dirname(os.path.abspath(path)),
                        BACKUP_NAME)


def terminator(path):
    """The line ending the file already uses.

    roi_nuclei.csv is written by csv.writer on Windows, so its lines end CRLF -
    but this stage rewrites every byte of a 121 MB file, and flipping the
    terminator of the whole dataset is not something a provenance backfill
    should do as a side effect. Copy it instead of taking csv.writer's default.
    """
    with open(path, "rb") as fh:
        first = fh.readline()
    return "\r\n" if first.endswith(b"\r\n") else "\n"


def read_header(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh), None) or []


def refuse(path, header):
    """Say which header this is and which migration it needs, then stop."""
    missing = [c for c in LEGACY_COLUMNS if c not in header]
    extra = [c for c in header if c not in LEGACY_COLUMNS]
    why = (f"missing {missing}" if missing else "") + \
          (f" extra {extra}" if extra else "") or \
          "the same columns in a different order"
    hint = ""
    if missing == ["off_tissue"] and not extra:
        hint = ("\n   This is a file from before `off_tissue`. Run "
                "06g_flag_off_tissue.py first - it leaves the file at exactly "
                "the header this stage takes, so the two together carry an old "
                "file all the way to the current one.")
    raise SystemExit(
        f"!! {path} does not have the header this stage migrates from ({why}).\n"
        f"   It fills in {', '.join(f'{k}={v!r}' for k, v in PROVENANCE.items())}, "
        f"which is true of a file written before those columns existed and of "
        f"nothing else, and it appends positionally - so a header it does not "
        f"recognise is not something to guess at.{hint}")


def rewrite(path, out):
    """Copy every row of `path` under COLUMNS into the writer `out`.

    `out` is None for a dry run: the same pass, the same refusals, nothing
    written. Returns the number of rows.

    A row that is not 21 fields wide is refused rather than padded. The file is
    already inconsistent at that point and the whole purpose here is to end up
    with one width; guessing which field is missing would write a row whose
    columns are not what they say. Nothing has been replaced when this raises.
    """
    n = 0
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for line, row in enumerate(rd, 2):
            if not row:
                continue
            if len(row) != len(LEGACY_COLUMNS):
                raise SystemExit(
                    f"!! {path} line {line} has {len(row)} fields, not "
                    f"{len(LEGACY_COLUMNS)}. Nothing was written. A row whose "
                    f"width is not the header's cannot be moved to a new "
                    f"header without inventing which column it is missing.")
            if out is not None:
                out.writerow([row[i] if i is not None else v for i, v in _MAP])
            n += 1
            if n % 200000 == 0:
                print(f"\r  {n} rows", end="")
    return n


def back_up(path, backup_dir):
    """Keep the file about to be replaced. An existing backup is never redone -
    the first one is the pre-migration state, a second would be a copy of the
    already-migrated file."""
    os.makedirs(backup_dir, exist_ok=True)
    dst = os.path.join(backup_dir, os.path.basename(path))
    if os.path.exists(dst):
        print(f"  backup already exists, left alone: {dst}")
        return dst
    print(f"  backing up to {dst} ...")
    shutil.copy2(path, dst)
    return dst


def verify_file(path):
    """Re-read what was written: one header, one width, no short rows."""
    widths = set()
    rows = 0
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        header = next(rd, None) or []
        for row in rd:
            if not row:
                continue
            rows += 1
            widths.add(len(row))
    ok = header == COLUMNS and widths <= {len(COLUMNS)}
    print(f"  verify: {rows} rows, {len(header)} columns, "
          f"widths {sorted(widths)} - {'ok' if ok else 'NOT OK'}")
    return ok


def migrate(path, dry_run=False, backup=True, backup_dir=None, verify=False):
    """Append the provenance columns to `path`, filling in every existing row.

    Returns `{"action": "backfilled" | "already", "rows": n, "path": path}`.
    Raises SystemExit rather than touching a file whose header is not the
    pre-provenance one.
    """
    if not os.path.exists(path):
        raise SystemExit(f"!! {path} not found")

    header = read_header(path)
    if header == COLUMNS:
        # Not an error and not work: the operator re-runs stages, and 05c's own
        # resume backfills this too, so arriving here twice is expected.
        print(f"  {path}\n  already has {', '.join(PROVENANCE)} - nothing to do")
        return {"action": "already", "rows": 0, "path": path}
    if header != LEGACY_COLUMNS:
        refuse(path, header)

    print(f"  {path}")
    print(f"  {len(header)} columns -> {len(COLUMNS)}, filling in "
          + ", ".join(f"{k}={v!r}" for k, v in PROVENANCE.items()))

    if dry_run:
        n = rewrite(path, None)
        print(f"\r  {n} rows would be rewritten            ")
        print("\ndry run - nothing written")
        return {"action": "backfilled", "rows": n, "path": path, "dry_run": True}

    nl = terminator(path)
    with IO.atomic_save(path) as tmp:
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            out = csv.writer(fh, lineterminator=nl)
            out.writerow(COLUMNS)
            n = rewrite(path, out)
        # Inside the block, so it copies the file that is about to be replaced
        # and so a failure here leaves the original in place with the tmp
        # removed. The replace is the last thing that happens.
        if backup:
            back_up(path, backup_dir or backup_dir_for(path))
    print(f"\r  {n} rows rewritten under {len(COLUMNS)} columns            ")

    if verify:
        verify_file(path)
    return {"action": "backfilled", "rows": n, "path": path}


def main():
    ap = argparse.ArgumentParser(
        description="Backfill segmented_on / backend / nucleus_shaped onto an "
                    "existing roi_nuclei.csv.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--path", default=NUCLEI_CSV,
                    help="the file to migrate (default: this study's)")
    args = ap.parse_args()

    got = migrate(args.path, dry_run=args.dry_run, backup=not args.no_backup,
                  verify=args.verify)
    if got["action"] == "backfilled" and not args.dry_run:
        print()
        print("  next: 05c_detect_rois.py can resume onto it, and 06a reads "
              "the Abercrombie gate off these columns")


if __name__ == "__main__":
    main()
