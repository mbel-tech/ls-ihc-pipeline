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
import os
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
