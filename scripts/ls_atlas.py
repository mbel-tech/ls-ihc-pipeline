"""Which atlas plate set this study uses, and whether a plate is still itself.

Two questions, one home, because both were answered in several places and the
copies disagreed.

WHICH SET. `04e`, `04k` and `04l` read `atlas_plate_set.dir` from the config;
`04a_reformat`, `04b` and `04c` hardcoded `atlas/plates`. On this operator's
drive that is not a cosmetic difference: `plates` holds 47 merged figures and
`plates_final` holds 64 reframed plates, so `plate_012` denotes a different
picture in each, and 17 of the 64 ids do not exist in `plates` at all.

IS THIS STILL THE SAME PLATE. Curation records which plate a section sits on.
Keyed by INDEX into a sorted array, swapping the atlas silently renumbers every
assignment; keyed by ID alone, it silently succeeds against a plate that has
been re-rendered. Both happened here - `plates` -> `plates_final` on
2026-09-06, same ids, different pictures, nothing reported. So identity is the
plate IMAGE's bytes: that is the thing the operator drew on.

`verify()` never returns a bare boolean. Four named outcomes, because the right
response differs: a re-render can have its landmarks rescaled, a re-crop cannot,
and a plate that is gone needs a person.
"""

import csv
import hashlib
import os
import re

# What `04a_atlas_extract.py` writes, and the fallback when a study declares
# nothing. `ls_config` carries the same default; this is the one place a READER
# asks, so the two cannot be given different answers by accident.
EXTRACTED = "plates"

# ONE vocabulary, used by this module, by the page's `verifyPlate` and by the
# `plate_verified` column. Three names for the same state is how a section
# verifies in the importer and not in the page.
OK = "ok"                 # the id is there and the image is byte-identical
RESIZED = "resized"       # same id, new bytes, same proportions
CHANGED = "changed"       # same id, new bytes, different proportions
GONE = "gone"             # the id is not in this plate set
UNCHECKED = "unchecked"   # an id, but nothing to check it against yet
BY_INDEX = "by_index"     # no id at all - an export from before fingerprints
OUTCOMES = (OK, RESIZED, CHANGED, GONE, UNCHECKED, BY_INDEX)

# A re-render at a new size keeps its proportions; a re-crop does not. 1% is
# wide enough to absorb rounding at the sizes atlas plates come in (a 1089x643
# plate re-rendered at 1634x964 is 0.03% off) and narrow enough that trimming a
# margin off one edge reads as CHANGED.
ASPECT_TOLERANCE = 0.01

# The digest is truncated because it is written into every curated row and read
# by eye in a CSV. 12 hex characters is 48 bits; these sets hold tens of plates,
# not billions, and the consequence of a collision is one section verifying that
# should have been flagged - not a wrong number.
DIGEST_CHARS = 12
CACHE_NAME = "fingerprints.csv"
CACHE_COLUMNS = ("plate_id", "image_file", "bytes", "mtime", "digest")

_TRAILING_INT = re.compile(r"(\d+)\s*$")


def set_dir(cfg):
    """The plate set directory name this study uses.

    A malformed block is judged rather than crashed on, for the reason
    `ls_channels.marker_names` gives: every caller of this is a module-level
    stage constant evaluated at import, and a traceback there takes all 46
    stages down at once.
    """
    block = (cfg or {}).get("atlas_plate_set")
    if not isinstance(block, dict):
        return EXTRACTED
    name = block.get("dir")
    return name if isinstance(name, str) and name else EXTRACTED


def plate_dir(cfg, set_name=None):
    """`<out_root>/atlas/<set>`. `set_name` overrides the study's choice.

    The override exists for exactly two callers: `04b` and `04c`, which are
    retired matchers kept as evidence and must keep reading the set they were
    measured against. They pass `EXTRACTED` by name so that stays a decision
    rather than a leftover literal.
    """
    out_root = (cfg or {}).get("out_root") or ""
    return os.path.join(out_root, "atlas", set_name or set_dir(cfg))


def plate_order(rows, key="plate_id"):
    """Plate rows in atlas order.

    Numerically on the trailing integer when every id has a distinct one, and
    as text otherwise. `04l` sorted on the raw string, which is correct only
    because this atlas zero-pads to three digits: an atlas numbering
    `plate_1 .. plate_100` orders 1, 10, 100, 2 under a string sort, and every
    stored index then means a different plate with no error anywhere.
    """
    rows = list(rows or [])
    hits = [_TRAILING_INT.search(str(r.get(key, ""))) for r in rows]
    numbers = [int(h.group(1)) for h in hits if h]
    if len(numbers) == len(rows) and len(set(numbers)) == len(rows):
        return sorted(rows, key=lambda r:
                      int(_TRAILING_INT.search(str(r.get(key, ""))).group(1)))
    return sorted(rows, key=lambda r: str(r.get(key, "")))


def fingerprint(path):
    """A digest of the plate image's BYTES, or None when it is not there.

    The bytes, not the `plates.csv` row: two different renderings of the same
    anatomy share every value in that row, which is precisely the case this has
    to catch. Not the id either - the 09-06 swap reused all 64.
    """
    try:
        with open(path, "rb") as fh:
            digest = hashlib.sha256()
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()[:DIGEST_CHARS]


def _cache(path):
    """{image_file: (bytes, mtime, digest)} from a previous run."""
    out = {}
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    out[row["image_file"]] = (int(row["bytes"]),
                                              int(float(row["mtime"])),
                                              row["digest"])
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        pass
    return out


def fingerprints(directory, rows=None):
    """{plate_id: {"fp", "px_w", "px_h", "image_file"}} for one plate set.

    Cached to `<set>/fingerprints.csv` and re-hashed only where size or mtime
    moved, because the curator page rebuilds this on every generation and 64
    images is real work to hash for a question whose answer rarely changes. The
    cache is derived: delete it and it comes back.

    A plate whose image is missing gets `fp: None` and keeps its row. Dropping
    it is what shifted every later index in `04l`; a plate that is present in
    the table and absent on disk is a gap to report, not a plate to forget.
    """
    if rows is None:
        try:
            with open(os.path.join(directory, "plates.csv"),
                      newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        except OSError:
            return {}

    cached, fresh, changed = _cache(os.path.join(directory, CACHE_NAME)), {}, False
    out = {}
    for row in rows:
        name = row.get("image_file") or ""
        path = os.path.join(directory, name)
        try:
            stat = os.stat(path)
            size, mtime = stat.st_size, int(stat.st_mtime)
        except OSError:
            out[row.get("plate_id")] = {"fp": None, "image_file": name,
                                        "px_w": _int(row.get("px_w")),
                                        "px_h": _int(row.get("px_h"))}
            continue
        hit = cached.get(name)
        if hit and hit[0] == size and hit[1] == mtime:
            digest = hit[2]
        else:
            digest = fingerprint(path)
            changed = True
        fresh[name] = (size, mtime, digest)
        out[row.get("plate_id")] = {"fp": digest, "image_file": name,
                                    "px_w": _int(row.get("px_w")),
                                    "px_h": _int(row.get("px_h"))}

    if changed or set(fresh) != set(cached):
        _write_cache(os.path.join(directory, CACHE_NAME), fresh)
    return out


def _write_cache(path, fresh):
    """Best effort. A cache that cannot be written costs time, not correctness."""
    try:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(CACHE_COLUMNS)
            for name in sorted(fresh):
                size, mtime, digest = fresh[name]
                writer.writerow([_id_for(name), name, size, mtime, digest])
    except OSError:
        pass


def _id_for(image_file):
    """The plate id a cache row is about, for a human reading the file."""
    return os.path.splitext(os.path.basename(image_file))[0]


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _shape(px):
    """`"1089x643"` -> `(1089, 643)`, or None."""
    try:
        w, h = str(px).lower().split("x")
        w, h = int(float(w)), int(float(h))
    except (AttributeError, TypeError, ValueError):
        return None
    return (w, h) if w > 0 and h > 0 else None


def verify(stored, current):
    """One of OK / RESIZED / CHANGED / GONE / UNCHECKED / BY_INDEX.

    `stored` is what curation recorded: `plate_id`, `fp`, and `px` as `"WxH"`.
    `current` is `fingerprints()` for the set now on disk.

    UNCHECKED and BY_INDEX both mean "this assignment predates fingerprints" -
    every existing section, on the first load after this lands - and differ only
    in whether an id was recorded. Neither is OK. Fingerprinting whatever is
    there on first sight and calling it verified would launder exactly the
    2026-09-06 failure into a green tick.
    """
    plate_id = (stored or {}).get("plate_id") or ""
    if not plate_id:
        return BY_INDEX
    now = (current or {}).get(plate_id)
    if now is None or not now.get("fp"):
        return GONE
    was = (stored or {}).get("fp")
    if not was:
        return UNCHECKED
    if was == now["fp"]:
        return OK

    old, new = _shape((stored or {}).get("px")), (now.get("px_w"), now.get("px_h"))
    if not old or not all(new):
        return CHANGED
    old_ratio, new_ratio = old[0] / old[1], new[0] / new[1]
    if abs(old_ratio - new_ratio) <= ASPECT_TOLERANCE * max(old_ratio, new_ratio):
        return RESIZED
    return CHANGED


def scale_between(stored_px, current):
    """The factor a RESIZED plate's landmark coordinates need, or None.

    `plate_x`/`plate_y` are pixels of the plate image as it was when the
    operator clicked. A re-render at a new size leaves them pointing at the
    wrong place by exactly the size ratio.
    """
    old = _shape(stored_px)
    if not old or not current or not current.get("px_w"):
        return None
    return float(current["px_w"]) / float(old[0])


_CACHE = {}


def for_config(cfg):
    """`(plate_dir, fingerprints)` for a study, memoised on the directory.

    Memoised for the same reason `ls_paths.for_config` is: most callers are
    module-level stage constants and there are 46 stages.
    """
    directory = plate_dir(cfg)
    if directory not in _CACHE:
        _CACHE[directory] = (directory, fingerprints(directory))
    return _CACHE[directory]
