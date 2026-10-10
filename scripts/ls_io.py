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


WULLIMANN_SET = "plates_wullimann"
ATLAS_SOURCES = ("salmon", "wullimann1996")


def atlas_source(config):
    """Which atlas the run uses: "salmon" (the default) or "wullimann1996".

    An unknown value raises rather than falling back to salmon. A typo that
    silently picked the other atlas would register sections against the wrong
    species and nothing downstream would say so.
    """
    src = config.get("atlas_source") or "salmon"
    if src not in ATLAS_SOURCES:
        raise ValueError("atlas_source %r is not one of %s" % (src, ", ".join(ATLAS_SOURCES)))
    return src


def plate_set(config):
    """The plate-set directory name under `<out_root>/atlas/` for this run.

    Every stage that reads plates takes the name from here, so they cannot
    disagree. Wullimann has its own fixed set; salmon keeps the operator's
    `atlas_plate_set.dir` choice (plates / plates_merged / plates_final).
    """
    if atlas_source(config) == "wullimann1996":
        return WULLIMANN_SET
    return config.get("atlas_plate_set", {}).get("dir", "plates")


def reformatted_plates_dir(config):
    """Subdirectory of `reformatted/` that holds the reformatted plates.

    Salmon keeps `plates`, so existing work is untouched. Wullimann gets its own
    folder: 04c globs every plate mask in the folder it reads, so two atlases
    sharing one would be matched against each other's plates.
    """
    return WULLIMANN_SET if atlas_source(config) == "wullimann1996" else "plates"


def check_plate_set(rows, active, what="landmarks"):
    """Refuse rows made against a different plate set than the one in use.

    Plate ids repeat between sets (plate_009 names a different image in
    `plates` and in `plates_final`) and the curator stores a plate's position in
    the sorted list, so rows from another set resolve to the wrong picture
    without any error. Rows with no `plate_set` cell (older exports) pass.
    """
    seen = sorted({(r.get("plate_set") or "").strip() for r in rows} - {""})
    bad = [s for s in seen if s != active]
    if bad:
        raise SystemExit("%s were made against plate set %s but this run uses %s "
                         "(atlas_source / atlas_plate_set in config.json). Plate "
                         "ids are not comparable between sets." % (what, ", ".join(bad), active))


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
