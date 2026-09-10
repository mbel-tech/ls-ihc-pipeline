"""Shared file-writing helpers: tmp-then-replace, with a retry.

Every keyed output in the pipeline - the reformat index, the analysis set, the
override files, the ROI geometry, the workbooks - is read by a later stage as
the truth about a section. A half-written copy of any of them is worse than the
previous copy, so nothing here writes in place: the bytes go to `<path>.tmp`
beside the target and `os.replace` swaps them in as one step.

The retry came from 01k_saturation_raw.py. The D: volume does not merely drop
writes - it goes away: a dropout on 2026-09-01 killed 01k and 01g within nine
minutes of each other, both with `FileNotFoundError` on a path that exists,
which is what a vanished volume looks like from inside `open()`. Five attempts
over ~31 s; if the drive is still gone after that it is not a blip, and the
exception propagates rather than being swallowed.

Imported by path, like every other cross-script import here:

    _lsio = importlib.util.spec_from_file_location(
        "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
    IO = importlib.util.module_from_spec(_lsio)
    _lsio.loader.exec_module(IO)
"""

import contextlib
import csv
import json
import os
import re
import time


def _retry(fn, path, attempts):
    for attempt in range(attempts):
        try:
            return fn()
        except OSError as exc:
            if attempt == attempts - 1:
                raise
            wait = 2 ** attempt
            print("\n  !! write to %s failed (%s); retrying in %ds" % (path, exc, wait))
            time.sleep(wait)


def atomic_write_csv(path, rows, keys, attempts=5):
    """Write `rows` (dicts) under `keys` to `path`: header always, atomically.

    `keys` is required rather than taken from `rows[0]`. An empty result must
    still produce a file with a header, so a downstream reader sees "nothing
    here" instead of last week's rows - or a crash on `rows[0]`.
    """
    tmp = path + ".tmp"

    def go():
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, path)

    _retry(go, path, attempts)


def pick_column(fieldnames, *candidates, what=None):
    """The first candidate present in a CSV header, or a refusal naming all of
    them.

    Never defaults. `r[uid_col]` raising KeyError 400 rows into a loop is worse
    than refusing at the header, and `.get()` returning "" for a moved column is
    worse than both: a blank cell and a renamed column look identical.

    That last shape is not hypothetical here. `04n_roi_worklist.py` read its
    partner columns through a `num(r, k)` helper built on `.get()`, so the day
    04m renamed `pcna_focus_score` the worklist would have kept its column,
    kept its 454 rows and written an empty string into every one of them - a
    file that is the right size, the right shape and silently carries no
    numbers. Asked once against `fieldnames`, before the loop, a rename is a
    stop with both names in the message instead.

    `what` names the file for the message, since a header on its own does not
    say which of five CSVs a stage was reading.

    Raises SystemExit, the refusal every stage in this pipeline uses, so an
    operator gets the message rather than a traceback.
    """
    have = list(fieldnames or [])
    for candidate in candidates:
        if candidate in have:
            return candidate
    where = f" in {what}" if what else ""
    raise SystemExit(
        f"none of the columns {list(candidates)} is{where} - the header is "
        f"{have}. One of them was renamed, or this is not the file it should "
        f"be; either way the value cannot be read and a blank is not an answer.")


@contextlib.contextmanager
def atomic_save(path, attempts=5):
    """`with atomic_save(path) as tmp:` - write to `tmp`; `path` is swapped in
    when the block ends without an exception.

    For writers that own their file format (openpyxl, PIL): the tmp path has
    no useful extension, so pass the format explicitly - `im.save(tmp,
    format="PNG")`, and openpyxl's `wb.save(tmp)` does not care.
    """
    tmp = path + ".tmp"
    try:
        yield tmp
        _retry(lambda: os.replace(tmp, path), path, attempts)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def embed(obj):
    """JSON for a <script> block.

    `json.dumps` leaves `</script>` and `<!--` alone, and either one inside a
    string value ends the block or opens an HTML comment. Both are escaped in
    a way a JS string literal ignores: `<\\/` reads as `</`, `<\\!--` as `<!--`.
    """
    return json.dumps(obj).replace("</", "<\\/").replace("<!--", "<\\!--")


def fill(template, values):
    """Substitute every `__NAME__` placeholder in ONE pass.

    Chained `str.replace` calls re-scan the JSON just inserted, so a placeholder
    name inside a data value would be substituted as well. A placeholder the
    template does not carry is a programming error and raises.
    """
    for name in values:
        if name not in template:
            raise KeyError(f"placeholder {name} is not in the template")
    pattern = re.compile("|".join(re.escape(k) for k in values))
    return pattern.sub(lambda m: embed(values[m.group(0)]), template)
