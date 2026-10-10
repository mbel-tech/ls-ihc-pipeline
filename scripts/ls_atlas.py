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

`plate_status()` never returns a bare boolean - six named outcomes, because the
right response differs: a re-render can have its landmarks rescaled, a re-crop
cannot, and a plate that is gone (or merely unreadable right now) needs a
person. `verified(outcome)` is the one honest place to ask "is this fine",
because `if plate_status(...):` is true for every one of GONE, CHANGED,
UNCHECKED and BY_INDEX too - they are all non-empty strings.
"""

import csv
import hashlib
import os
import re

import ls_io as IO

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
GONE = "gone"             # the id is not in this plate set, OR it is there and
                           # its image cannot currently be read
UNCHECKED = "unchecked"   # an id, but nothing to check it against yet
BY_INDEX = "by_index"     # no id at all - an export from before fingerprints
OUTCOMES = (OK, RESIZED, CHANGED, GONE, UNCHECKED, BY_INDEX)

# A re-render at a new size keeps its proportions; a re-crop does not. 1% is
# wide enough to absorb rounding at the sizes atlas plates come in (a 1089x643
# plate re-rendered at 1634x964 is 0.082% off) and narrow enough that trimming
# a margin off one edge reads as CHANGED.
ASPECT_TOLERANCE = 0.01

# The digest is truncated because it is written into every curated row and read
# by eye in a CSV. 12 hex characters is 48 bits; these sets hold tens of plates,
# not billions, and the consequence of a collision is one section verifying that
# should have been flagged - not a wrong number.
DIGEST_CHARS = 12
CACHE_NAME = "fingerprints.csv"
CACHE_COLUMNS = ("image_stem", "image_file", "bytes", "mtime_ns", "digest")

_TRAILING_INT = re.compile(r"(\d+)\s*$")
# The same grammar the curator page's own `shapeOf` parses - `^(\d+)x(\d+)$` -
# and nothing wider. Python's old float()-based parser accepted "1089.0X643";
# the page's regex does not, so the same stored `px` string read RESIZED in
# one and CHANGED in the other. See `_shape`.
_SHAPE_RE = re.compile(r"^(\d+)x(\d+)$")


def set_name(cfg):
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


# `plate_dir`'s own parameter is ALSO spelled `set_name` - the override it
# accepts - which would shadow this function by that name inside that one
# scope. Called through this alias there instead of by the bare name.
_default_set_name = set_name


def plate_dir(cfg, set_name=None):
    """`<out_root>/atlas/<set>`. `set_name` overrides the study's choice.

    The override exists for exactly two callers: `04b` and `04c`, which are
    retired matchers kept as evidence and must keep reading the set they were
    measured against. They pass `EXTRACTED` by name so that stays a decision
    rather than a leftover literal.
    """
    out_root = (cfg or {}).get("out_root") or ""
    return os.path.join(out_root, "atlas", set_name or _default_set_name(cfg))


def plate_order(rows, key="plate_id"):
    """Plate rows in atlas order.

    Numerically on the trailing integer when every id has a distinct one, and
    as text otherwise. `04l` sorted on the raw string, which is correct only
    because this atlas zero-pads to three digits: an atlas numbering
    `plate_1 .. plate_100` orders 1, 10, 100, 2 under a string sort, and every
    stored index then means a different plate with no error anywhere. Two ids
    that share a trailing number ("plate_01" and "plate_1") are exactly as
    ambiguous as no number at all, so that falls back to text too rather than
    guessing which one is "first".
    """
    rows = list(rows or [])
    hits = [_TRAILING_INT.search(str(r.get(key, ""))) for r in rows]
    numbers = [int(h.group(1)) for h in hits if h]
    if len(numbers) == len(rows) and len(set(numbers)) == len(rows):
        return sorted(rows, key=lambda r:
                      int(_TRAILING_INT.search(str(r.get(key, ""))).group(1)))
    return sorted(rows, key=lambda r: str(r.get(key, "")))


def fingerprint(path):
    """A digest of the plate image's BYTES, or None when it cannot be read.

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
    """{image_file: (bytes, mtime_ns, digest)} from a previous run.

    `mtime_ns` is read as `int`, never `float`. A raw `st_mtime_ns` is around
    1.79e18 - past float64's exact-integer ceiling of 2**53 (~9.0e15) - so
    routing it through `float()` rounds off the low digits, the comparison in
    `fingerprints()` silently stops matching, and the cache becomes a
    permanent no-op that re-hashes every plate on every run.

    A digest is trusted only when it is exactly `DIGEST_CHARS` long. A write
    cut short by the volume going away mid-line (`ls_io.py`) can still leave a
    row that parses - `plate_001,p1.png,123,456,b926` passes both `int()`
    calls with a four-character digest - and a short string accepted here
    would be served back as a fingerprint. `_write_cache` also no longer
    writes in place for exactly this reason; this check is the read-side twin
    of that fix, for whatever an OLDER version of this module already left
    on disk.
    """
    out = {}
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    digest = row["digest"]
                    if len(digest) != DIGEST_CHARS:
                        continue
                    out[row["image_file"]] = (int(row["bytes"]),
                                              int(row["mtime_ns"]),
                                              digest)
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        pass
    return out


def _read_plates_csv(directory):
    """`list(csv.DictReader(...))` for `<directory>/plates.csv`, or `None` when
    it genuinely is not there.

    Retried through `ls_io`'s own retry helper before either answer is
    trusted: `ls_io.py`'s docstring records a volume dropout that presented as
    `FileNotFoundError` on a path that was really there. Only a
    `FileNotFoundError` that survives every retry is read as "no plates.csv" -
    a legitimate answer for a fresh out_root, so this returns `None` and the
    caller reports an empty set. Every OTHER `OSError` - a locked file, a
    permissions error, a drive that stays gone for a reason other than "the
    file was never written" - is left to propagate rather than being folded
    into that same empty answer: an empty set reads as every plate GONE,
    indistinguishable from a real swap, and training an operator to click
    through GONE is the same laundering this module exists to stop, one level
    up.
    """
    path = os.path.join(directory, "plates.csv")

    def go():
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    try:
        return IO.retry(go, path, attempts=5, what="read of")
    except FileNotFoundError:
        return None


def _hash_one(directory, row, cached, fresh):
    """`(plate_id, entry)` for one `plates.csv` row.

    Stats the image, answers from the cache when size and `mtime_ns` both
    still match, and re-hashes otherwise. `fresh` is mutated in place with
    whatever THIS row's cache entry should now be - which may be nothing at
    all, when the read fails and there is no earlier good entry to fall back
    on; see the comment inline for why a failed read is never seated as a
    blank digest.
    """
    plate_id = row.get("plate_id")
    name = row.get("image_file") or ""
    path = os.path.join(directory, name)
    px_w, px_h = _int(row.get("px_w")), _int(row.get("px_h"))

    try:
        stat = os.stat(path)
        size, mtime_ns = stat.st_size, stat.st_mtime_ns
    except OSError:
        return plate_id, {"fp": None, "image_file": name,
                          "px_w": px_w, "px_h": px_h}

    hit = cached.get(name)
    if hit and hit[0] == size and hit[1] == mtime_ns:
        digest = hit[2]
        fresh[name] = hit
    else:
        digest = fingerprint(path)
        if digest:
            fresh[name] = (size, mtime_ns, digest)
        elif hit:
            # The read failed on a file whose size or mtime moved since the
            # last successful hash - locked, or caught mid-write. Keep the
            # OLD entry rather than seating a blank one: a blank digest would
            # be trusted as a fingerprint by every future call and never
            # retried, because size/mtime as of THIS run would then be what
            # the cache compares against. The stale entry's ORIGINAL
            # (size, mtime_ns) still will not match a healthy read next time,
            # so the retry keeps happening until it succeeds. If there is no
            # earlier entry either, `fresh` simply gets nothing for this
            # name - not a cache miss to remember, just nothing learned yet.
            fresh[name] = hit

    return plate_id, {"fp": digest, "image_file": name,
                      "px_w": px_w, "px_h": px_h}


def fingerprints(directory, rows=None):
    """{plate_id: {"fp", "px_w", "px_h", "image_file"}} for one plate set, in
    `plates.csv` ROW ORDER - not `plate_order()`'s atlas order. A caller that
    needs atlas order calls that separately; enumerating this dict as if it
    already were in atlas order is the exact index-shift bug Task 3 exists to
    avoid.

    Cached to `<set>/fingerprints.csv` and re-hashed only where size or
    `mtime_ns` moved, because hashing every plate on every call is real work
    when nothing changed. The cache is derived: delete it (or pass --rehash to
    `main`) and it comes back. It CANNOT tell a real re-render from a
    timestamp-preserving copy of the same bytes at the same size - the default
    mode of `robocopy`, `rsync -t`, most archive extractors - because that
    also matches on `(size, mtime_ns)`. Nothing keyed on filesystem metadata
    can; only the digest itself, recomputed, can, which is exactly the work
    this cache exists to avoid doing on every call that does not need it.

    `rows`, when given, is a CALLER'S OWN SUBSET (04l, from Task 3 onward): the
    on-disk cache is MERGED with it rather than overwritten down to that
    subset, so two callers alternating over different slices of the same set
    do not erase each other's entries. Only a full read of `plates.csv`
    (`rows=None`) prunes a cache row whose plate left the table.

    A plate whose image is missing gets `fp: None` and keeps its row. Dropping
    it is what shifted every later index in `04l`; a plate that is present in
    the table and absent on disk is a gap to report, not a plate to forget.

    `plate_id` and `image_file` are required columns, checked once against the
    header rather than defaulting through `.get()` on every row: a renamed or
    absent `plate_id` column would otherwise key every row on `None` and
    collapse the map to one entry. A duplicate `plate_id` is reported and the
    FIRST row wins, rather than the last silently overwriting it - the same
    index-stability invariant the missing-image case protects.
    """
    full_read = rows is None
    if full_read:
        rows = _read_plates_csv(directory)
        if rows is None:
            return {}

    if rows:
        header = rows[0].keys()
        IO.pick_column(header, "plate_id", what="plates.csv")
        IO.pick_column(header, "image_file", what="plates.csv")

    cache_path = os.path.join(directory, CACHE_NAME)
    cached = _cache(cache_path)
    fresh = {}
    out = {}
    seen_ids = set()

    for row in rows:
        plate_id = row.get("plate_id")
        if plate_id in seen_ids:
            print(f"  !! duplicate plate_id {plate_id!r} in plates.csv - "
                  f"keeping the first, ignoring {row.get('image_file')!r}")
            continue
        seen_ids.add(plate_id)
        pid, entry = _hash_one(directory, row, cached, fresh)
        out[pid] = entry

    merged = fresh if full_read else {**cached, **fresh}
    if merged != cached:
        _write_cache(cache_path, merged)
    return out


def _write_cache(path, fresh):
    """Best effort. A cache that cannot be written costs time, not correctness.

    Through `ls_io.atomic_write_csv`: a plain `open(path, "w")` truncates
    before writing a byte, on a volume `ls_io.py` documents as going away
    mid-write, and a truncated final ROW still parses - see `_cache`'s digest-
    length check for what that would otherwise let back in as a fingerprint.
    """
    rows = [{"image_stem": _image_stem(name), "image_file": name,
             "bytes": size, "mtime_ns": mtime_ns, "digest": digest}
            for name, (size, mtime_ns, digest) in sorted(fresh.items())]
    try:
        IO.atomic_write_csv(path, rows, CACHE_COLUMNS)
    except OSError:
        pass


def _image_stem(image_file):
    """`image_file` without its directory or extension, for a human reading the
    cache.

    NOT the plate id: `plates.csv` on the live atlas pairs
    `plate_id=plate_001` with `image_file=plate_001_p01.png`, so the id and the
    filename stem already disagree by one component. Recording this column as
    `plate_id` would put `plate_001_p01` in a table where no row's actual id is
    ever that string. The cache itself keys on `image_file`, not on this column
    - it is legibility only.
    """
    return os.path.splitext(os.path.basename(image_file))[0]


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _shape(px):
    """`"1089x643"` -> `(1089, 643)`, or None.

    Grammar pinned to match the curator page's own `shapeOf` exactly:
    `^(\\d+)x(\\d+)$`, integers only, lowercase `x`, no surrounding
    whitespace, no sign, no decimal point. Python's previous parser went
    through `float()` and accepted things like `"1089.0X643"` that the page's
    regex does not - the SAME stored `px` string reading RESIZED here and
    CHANGED there is the same failure this module exists to prevent, one
    layer up, in the one place both sides are supposed to agree.
    """
    match = _SHAPE_RE.match(px if isinstance(px, str) else "")
    if not match:
        return None
    w, h = int(match.group(1)), int(match.group(2))
    return (w, h) if w > 0 and h > 0 else None


def plate_status(stored, current):
    """One of OK / RESIZED / CHANGED / GONE / UNCHECKED / BY_INDEX - never a
    bare boolean. `verified(outcome)` is the honest predicate; `if
    plate_status(...):` is true for GONE, CHANGED, UNCHECKED and BY_INDEX too,
    since they are all non-empty strings.

    `stored` is what curation PERSISTS, in the PERSISTED names -
    `plate_id`, `plate_fp`, `plate_px` (as `"WxH"`) - so a `roi_plates.csv` row
    can be passed straight in. `current` is `fingerprints()` for the set now
    on disk, in FINGERPRINTS' OWN names - `fp`, `px_w`, `px_h`. These are
    DELIBERATELY not the same names: `current` describes a PLATE's identity,
    `stored` describes a SECTION's record of one, and the two being visibly
    different is what stops a hand-translation between them from going
    unnoticed when one name is missed - the same way this module's other four
    hardcoded copies went unnoticed.

    UNCHECKED and BY_INDEX both mean "this assignment predates fingerprints" -
    every existing section, on the first load after this lands - and differ
    only in whether an id was recorded. Neither is OK. Fingerprinting whatever
    is there on first sight and calling it verified would launder exactly the
    2026-09-06 failure into a green tick.
    """
    stored = stored or {}
    plate_id = stored.get("plate_id") or ""
    if not plate_id:
        return BY_INDEX
    now = (current or {}).get(plate_id)
    if now is None or not now.get("fp"):
        return GONE
    was = stored.get("plate_fp")
    if not was:
        return UNCHECKED
    if was == now["fp"]:
        return OK

    old, new = _shape(stored.get("plate_px")), (now.get("px_w"), now.get("px_h"))
    if not old or not all(new):
        return CHANGED
    old_ratio, new_ratio = old[0] / old[1], new[0] / new[1]
    if abs(old_ratio - new_ratio) <= ASPECT_TOLERANCE * max(old_ratio, new_ratio):
        return RESIZED
    return CHANGED


def verified(outcome):
    """True only for OK. Every other outcome needs a person, or a rescale."""
    return outcome == OK


# What a restored record carries about its plate. `04q_import_curation` states
# the whole record's shape in its own STATE_FIELDS; these five are the part
# that comes from here, named once so the two importers cannot drift on which
# keys a restore is supposed to produce.
STATE_FIELDS = ("plate", "plate_id", "plate_fp", "plate_px", "verified")


def restore_plate(row, index_value):
    """The plate fields for one restored section, from one exported row.

    ONE implementation for both importers. `04q_import_curation` and
    `app/import_exports` are deliberate mirrors and were fixed apart once
    before, which is how a 3x coordinate displacement survived in one of them
    for weeks.

    THE ID IS THE KEY. The index is kept and returned, but it is no longer what
    resolves the plate - it is what the array looked like when the export was
    written, and the only thing left to fall back to for a file exported before
    ids were kept. The id is not followed to a new slot here: that needs the
    atlas, and these importers run without one. `04l`'s `resolvePlate` does it
    at load, against the plate set actually on disk.

    `verified` IS CARRIED, NOT COMPUTED. `plate_verified` is a verdict the page
    reached against the atlas that was loaded at the time, and it is the most
    specific true statement about the row that exists. Recomputing it from the
    row would replace it with something vaguer and sometimes wrong: a `by_index`
    row has a blank `plate_fp` BY DESIGN - the id names the plate at the stored
    index, nothing was ever fingerprinted - so a recompute answers `unchecked`
    over a column that says `by_index`. A `changed` or `gone` row would come
    back `unchecked` the same way, and the evidence that something moved would
    be gone from the only file carrying it.

    A value this module does not recognise is passed through as it stands,
    rather than being translated into one that is recognised. It comes from a
    newer export or a hand-edited file, and every reader downstream is safe for
    it: `04l` withholds a record's landmarks from the fit on any `verified`
    that is not exactly `ok`, and the banner counts it. Rewriting it to
    `unchecked` would be this module inventing a verdict about a row it did not
    understand - the one thing it exists not to do.

    Derived only when the column says nothing - absent, as in an export written
    before it existed, or blank, as on a row that never named a plate. An id
    with nothing to check it against is UNCHECKED. Neither is OK, and neither
    can be: nothing here has looked at a plate.

    NO ID IS BY_INDEX WHATEVER THE COLUMN SAYS - the one claim not carried,
    because `plate_status` and the page's `verifyPlate` both answer BY_INDEX
    before reading anything else when there is no id, and this has to agree
    with them or a section verifies in one place and not the other. A verdict
    is a statement ABOUT a plate_id; with no id it names nothing, and a real
    export cannot produce one - `04l` gates both columns on the same `chosen`.
    A hand-edited row claiming `ok` beside a blank id is the only way to reach
    this, and that is exactly a false OK.
    """
    plate_id = (row.get("plate_id") or "").strip()
    verdict = (row.get("plate_verified") or "").strip()
    if not plate_id:
        verdict = BY_INDEX
    elif not verdict:
        verdict = UNCHECKED
    return {
        "plate": index_value,
        "plate_id": plate_id,
        "plate_fp": (row.get("plate_fp") or "").strip(),
        "plate_px": (row.get("plate_px") or "").strip(),
        "verified": verdict,
    }


def scale_between(stored_px, current):
    """The `(sx, sy)` factors a RESIZED plate's landmark coordinates need, or
    None.

    `plate_x`/`plate_y` are pixels of the plate image as it was when the
    operator clicked. A re-render at a new size leaves them pointing at the
    wrong place by exactly the size ratio - separately per axis, not one
    factor for both: RESIZED tolerates up to `ASPECT_TOLERANCE` of aspect
    drift, which on a 1634 px plate is on the order of ten pixels of height
    that a single width-only factor would get wrong, handed to a registration
    fit as coordinates it was never measured against.
    """
    old = _shape(stored_px)
    if not old or not current or not current.get("px_w") or not current.get("px_h"):
        return None
    return (float(current["px_w"]) / float(old[0]),
            float(current["px_h"]) / float(old[1]))


_CACHE = {}


def for_config(cfg):
    """`(plate_dir, fingerprints)` for a study.

    Only the DIRECTORY is memoised, on the facts that decide it - most callers
    are module-level stage constants, and there are 46 of them. The
    fingerprint MAP is recomputed on every call, never cached past it:
    `app/curator_view.py` runs a long-lived threaded HTTP server, and caching
    the map for that process's lifetime would answer every request with
    whatever was on disk when the server started. An atlas swapped while the
    server is open would then verify against the pre-swap map - and because
    the STORED fingerprints came from that same map, every section would read
    OK. That is precisely the 2026-09-06 failure, reintroduced through the
    memo. `fingerprints()` has its own on-disk cache keyed on `(size,
    mtime_ns)`, so calling it again costs one `stat()` per plate when nothing
    changed, not a re-hash - `ls_paths.for_config` was safe to memoise fully
    because it caches a pure object with no state of its own; this caches the
    state of a drive.
    """
    out_root = (cfg or {}).get("out_root") or ""
    name = set_name(cfg)
    key = (out_root, name)
    if key not in _CACHE:
        _CACHE[key] = plate_dir(cfg)
    directory = _CACHE[key]
    return (directory, fingerprints(directory))


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog="ls_atlas.py",
        description=("Report which atlas plate set this study uses, and "
                     "whether every plate in it has an image on disk."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rehash", action="store_true",
                        help="delete the fingerprint cache first, so every "
                             "plate is re-hashed from bytes rather than "
                             "answered from the cache.")
    args = parser.parse_args(argv)

    from ls_config import CONFIG, CONFIG_PATH
    directory = plate_dir(CONFIG)
    print(f"config   {CONFIG_PATH}")
    print(f"set      {set_name(CONFIG)}")
    print(f"dir      {directory}")

    if args.rehash:
        cache_path = os.path.join(directory, CACHE_NAME)
        try:
            os.remove(cache_path)
            print(f"  removed {cache_path}")
        except OSError:
            pass

    fps = fingerprints(directory)
    print(f"plates   {len(fps)}")
    missing = sorted(k for k, v in fps.items() if not v.get("fp"))
    if missing:
        print(f"  !! {len(missing)} plate(s) with no image on disk: {missing}")
    else:
        print("  every plate has an image on disk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
