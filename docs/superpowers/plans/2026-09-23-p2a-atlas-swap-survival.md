# P2a — curation survives an atlas swap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A curated section's atlas plate is stored as an identity that can be checked, so swapping the atlas either still resolves, or says it cannot — never silently means a different plate.

**Architecture:** One new module, `scripts/ls_atlas.py`, owns plate identity: which plate set the study uses, a fingerprint of each plate image, and a four-way `verify()`. The curator stores `plate_id` + fingerprint beside the integer index and resolves by id on load; the two importers do the same through one shared function. Landmarks belonging to a section whose plate no longer verifies are withheld from the transform until a person re-confirms.

**Tech Stack:** Python 3.13 (`work/appenv/Scripts/python.exe`), plain-script tests (no pytest), Pillow + numpy for the synthetic atlas fixture, Node for the curator page suites.

Spec: `docs/superpowers/specs/2026-09-10-atlas-swap-survival-design.md`.

---

## Standing rules

**Never run a numbered stage to test a change.** Stage scripts overwrite `out_root`,
which holds 130 curated sections and a 961,233-row `roi_nuclei.csv`. Call `build()` or
`main([...])` in-process with output constants redirected, or use `--help`.

**Never `git add -A`, `git add .`, or `git commit -a`.** Stage the exact paths each task
names.

**Never write anything under `E:\LS-analysis`** — with ONE sanctioned exception, the
derived `atlas/<set>/fingerprints.csv` that Task 1 creates and Task 3 refreshes. It is a
cache: delete it and it comes back. Nothing else on that drive may be created, modified
or deleted by any task in this plan. The drive moved from `D:` on 2026-09-23;
`config.json` points at `E:` now.

After every task:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh
```

Expected: the line **`ALL SUITES PASS`** with nothing after it. **Any failure belongs to
this plan** — the suite was fully green at `0eb38da`.

**Do not gate on a suite count.** The count was wrong three different ways during Task 2
(the plan said 70, implementers reported 69, a reviewer counted 75), and a gate whose
expected value is wrong gets "fixed" by adjusting the expectation — which is this repo's
signature failure. Gate on the property instead.

**The half that actually matters:** `run.sh` skips all **15 curator page suites** wholesale
when it cannot read `out_root`, and used to print a bare `ALL SUITES PASS` over them. One
`E:` hiccup during Task 4, 5 or 7 — which are *entirely* page-suite work — and a green run
would have proved nothing. Demonstrated, not theorised:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && LS_BUILD_CONFIG=/nonexistent/x.json bash tests/run.sh 2>&1 | tail -2
```

Zero page suites run. The summary line now says so:
`ALL SUITES PASS - BUT THE 15 CURATOR PAGE SUITES WERE SKIPPED`. **If you see that line,
your run did not test the curators — fix the reason and run it again.**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: `ALL PASS`, zero **changed** constants across all 46 stages. New constants are
expected in Tasks 1 and 8.

---

## What is on the drive, measured

Read before planning; these numbers decide several tasks.

| set | rows | image files | extension | columns beyond the common five |
|---|---|---|---|---|
| `atlas/plates` | 47 | 47 | `.jpeg` | `index_on_page, n_seeds, n_seeds_raster, n_text_labels, regions, overlay_written` |
| `atlas/plates_merged` | 47 | 47 | `.png` | `index_on_page, n_strips, x0, y0, x1, y1` |
| `atlas/plates_final` | 64 | 64 | `.png` | `source_figure, box, x0, y0, x1, y1` |

The five columns every set has: `plate_id, page, image_file, px_w, px_h`.
`seeds.csv` has an **identical** header in all three sets and carries `region`.

`config.json` says `atlas_plate_set.dir = "plates_final"`.

**The sets are not three renderings of one atlas.** `plate_012` is figure 12 of 47 in
`plates` and reframed plate 12 of 64 in `plates_final`. 17 of `plates_final`'s ids do not
exist in `plates` at all.

---

## File structure

| File | Responsibility |
|---|---|
| `scripts/ls_atlas.py` | **New.** The only thing that answers "which plate set" and "is this the same plate". `set_dir`, `plate_dir`, `fingerprint`, `fingerprints`, `verify`, `scale_between`, `plate_order`, `for_config`, and `restore_plate` from Task 6. |
| `tests/_atlas_fixture.py` | **New.** Two synthetic plate sets, `before` and `after`, exercising all four `verify()` outcomes. Not a test — shared setup, like `tests/_fixture.py`. |
| `tests/test_ls_atlas.py` | **New.** The module's own suite. |
| `scripts/04l_roi_curator.py` | Plate array ordering and the missing-image gap; the fingerprint table into the page; state migration, the transform gate, the banner, the three new export columns. |
| `scripts/04q_import_curation.py` | Restores by id through the shared rule. |
| `app/import_exports.py` | The mirror of the above. Same rule, same function. |
| `scripts/04k_level_curator.py` | Level anchors by id rather than index. |
| `scripts/04a_reformat.py` | Resolves the plate set through `ls_atlas`; takes `regions` from `seeds.csv`. |
| `scripts/04b_atlas_match.py`, `scripts/04c_atlas_match.py` | Use the resolver, naming the extraction set explicitly. |
| `tests/test_import_curation.py` | Rewritten where it pins the index-wins bug. |

---

## Scope decision, taken during planning

The spec's §5 said all three hardcoded readers move to the configured set. **Narrowed,
for a stated reason.**

`04a_reformat` **does** move. It builds `reformatted/plates/<plate_id>.png`, and
`04d_rotation_curator:527` and `04e_register_elastix:405` read those images while taking
`plates.csv` from the *configured* set. Today that join is wrong for every id: 17 of 64
have no image at all (04e silently `continue`s), and the other 47 resolve to a picture of
a different plate. That is a live defect in two stages the operator uses.

`04b` and `04c` **do not** move. Both are in `app/stages.py::NOT_LISTED` as *"measured to
fail on this data (LOGS 2026-08-12); kept as evidence"*. Re-pointing them at a different
plate set invalidates the measurement they exist to record. They lose the bare literal —
they call the resolver — but they name the extraction set explicitly, with the reason in
a comment. 04b's `atlas_proposals_v2.csv` does still feed 04d's plate preview; that
mismatch is recorded in Task 8 Step 6 as a known, deliberate gap rather than fixed here.

---

## Task 1: `scripts/ls_atlas.py` — plate identity in one place

**Files:**
- Create: `scripts/ls_atlas.py`
- Create: `tests/test_ls_atlas.py`

Standalone. Nothing imports it yet.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ls_atlas.py`:

```python
"""Plate identity: which set, which plate, and whether it is still that plate.

`verify()` is the whole point. A stored plate assignment that no longer matches
must come back as a NAMED outcome - resized, changed, gone - and never as a
silent success, because an id-keyed restore against a re-rendered atlas
succeeds and is wrong. That happened on this drive on 2026-09-06.

Run:  work/appenv/Scripts/python.exe tests/test_ls_atlas.py
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_atlas as A                                          # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


# --- which set ------------------------------------------------------------
chk("the configured set is used",
    A.set_dir({"atlas_plate_set": {"dir": "plates_final"}}), "plates_final")
chk("a config that says nothing gets the extraction set",
    A.set_dir({}), A.EXTRACTED)
chk("a malformed block is judged, not crashed on",
    A.set_dir({"atlas_plate_set": "plates_final"}), A.EXTRACTED)
chk("plate_dir joins out_root/atlas/<set>",
    A.plate_dir({"out_root": os.path.join("X:", "s"),
                 "atlas_plate_set": {"dir": "plates_final"}}),
    os.path.join("X:", "s", "atlas", "plates_final"))
chk("...and can be asked for a different set by name",
    A.plate_dir({"out_root": os.path.join("X:", "s")}, set_name="plates_merged"),
    os.path.join("X:", "s", "atlas", "plates_merged"))


# --- ordering -------------------------------------------------------------
# The live atlas zero-pads to three digits, so a string sort happens to work.
# An atlas that does not pad scrambles under one, silently.
padded = [{"plate_id": "plate_%03d" % n} for n in (3, 1, 2)]
chk("padded ids order numerically",
    [r["plate_id"] for r in A.plate_order(padded)],
    ["plate_001", "plate_002", "plate_003"])

bare = [{"plate_id": "plate_%d" % n} for n in (2, 10, 1, 100)]
chk("UNPADDED ids order numerically too",
    [r["plate_id"] for r in A.plate_order(bare)],
    ["plate_1", "plate_2", "plate_10", "plate_100"])

words = [{"plate_id": x} for x in ("caudal", "atlas_b", "atlas_a")]
chk("ids with no number order as text, deterministically",
    [r["plate_id"] for r in A.plate_order(words)],
    ["atlas_a", "atlas_b", "caudal"])

mixed = [{"plate_id": "plate_1"}, {"plate_id": "rostral"}]
chk("a mixed set falls back to text rather than guessing",
    [r["plate_id"] for r in A.plate_order(mixed)], ["plate_1", "rostral"])


# --- fingerprints and verify ----------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    def plate(name, data):
        path = os.path.join(tmp, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    a = plate("a.png", b"PLATE-A-BYTES")
    b = plate("b.png", b"PLATE-B-BYTES")
    chk("a fingerprint is stable", A.fingerprint(a), A.fingerprint(a))
    chk("...and different content gives a different one",
        A.fingerprint(a) == A.fingerprint(b), False)
    chk("a file that is not there has no fingerprint",
        A.fingerprint(os.path.join(tmp, "nope.png")), None)

    fp_a, fp_b = A.fingerprint(a), A.fingerprint(b)
    current = {"plate_001": {"fp": fp_a, "px_w": 100, "px_h": 200},
               "plate_002": {"fp": fp_b, "px_w": 100, "px_h": 200}}

    chk("same id, same bytes -> ok",
        A.verify({"plate_id": "plate_001", "fp": fp_a}, current), A.OK)
    chk("same id, new bytes, same shape -> resized",
        A.verify({"plate_id": "plate_001", "fp": fp_b, "px": "50x100"}, current),
        A.RESIZED)
    chk("same id, new bytes, new shape -> changed",
        A.verify({"plate_id": "plate_001", "fp": fp_b, "px": "50x400"}, current),
        A.CHANGED)
    chk("an id the set does not have -> gone",
        A.verify({"plate_id": "plate_099", "fp": fp_a}, current), A.GONE)
    chk("an id with no stored fingerprint is UNCHECKED, not ok",
        A.verify({"plate_id": "plate_001"}, current), A.UNCHECKED)
    chk("...and an id this set does not have is still gone",
        A.verify({"plate_id": "plate_099"}, current), A.GONE)
    chk("no id at all restores by index",
        A.verify({}, current), A.BY_INDEX)

    # The aspect test is what separates a re-render from a re-crop, and 1% is
    # wide enough for a rounding difference and narrow enough to catch a crop.
    chk("a 0.25% aspect drift still reads as a resize",
        A.verify({"plate_id": "plate_001", "fp": fp_b, "px": "1000x2005"}, current),
        A.CHANGED if False else A.RESIZED)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_atlas.py
```

Expected: `ModuleNotFoundError: No module named 'ls_atlas'`.

- [ ] **Step 3: Write `scripts/ls_atlas.py`**

```python
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
# NANOSECONDS, not whole seconds. A plate replaced in place with one of the same
# byte count inside the same wall-clock second kept its stale digest under
# `int(st_mtime)`, so a changed plate verified as OK - the one failure this
# module exists to prevent, reproduced during review. `04a4_plate_rebuild`
# overwrites this directory in place and writes several plates per second.
#
# The trap in reading it back: a ns timestamp is ~1.79e18, past float64's
# exact-integer ceiling of 2^53, so `int(float(row["mtime_ns"]))` corrupts the
# low digits and the comparison silently never matches again. Parse with
# `int()`, never through `float`.
CACHE_COLUMNS = ("image_stem", "image_file", "bytes", "mtime_ns", "digest")

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
                                              int(row["mtime_ns"]),
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
            size, mtime = stat.st_size, stat.st_mtime_ns
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
                writer.writerow([_stem(name), name, size, mtime, digest])
    except OSError:
        pass


def _stem(image_file):
    """The image filename without its extension, for a human reading the cache.

    NOT the plate id: this atlas's `plates.csv` has `plate_id=plate_001` against
    `image_file=plate_001_p01.png`, so calling this column `plate_id` put a
    value in it that appears in no `plates.csv`. The cache keys on `image_file`
    either way; the column is legibility, and a legibility column that lies is
    worse than none.
    """
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
```

- [ ] **Step 4: Run the test**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_atlas.py
```

Expected: `ALL PASS`.

- [ ] **Step 5: Check it against the real atlas, read-only**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import sys; sys.path.insert(0, 'scripts')
import ls_atlas as A
from ls_config import CONFIG
d, fps = A.for_config(CONFIG)
print(d)
print('plates fingerprinted:', len(fps))
print('missing images      :', [k for k, v in fps.items() if not v['fp']])
import csv, os
rows = list(csv.DictReader(open(os.path.join(d, 'plates.csv'), newline='', encoding='utf-8')))
old = [r['plate_id'] for r in sorted(rows, key=lambda r: r['plate_id'])]
new = [r['plate_id'] for r in A.plate_order(rows)]
print('order identical to the string sort:', old == new)
"
```

Expected: `E:\LS-analysis\atlas\plates_final`, 64 fingerprinted, no missing images,
**order identical to the string sort: True** — the live atlas must not move.

- [ ] **Step 6: Confirm the cache was written and is reused**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && ls -la "E:/LS-analysis/atlas/plates_final/fingerprints.csv" && head -3 "E:/LS-analysis/atlas/plates_final/fingerprints.csv"
```

Expected: a 65-line CSV with the header `plate_id,image_file,bytes,mtime,digest`.
This is the one file this plan writes under `out_root`, and it is derived data.

- [ ] **Step 7: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/ls_atlas.py tests/test_ls_atlas.py && git commit -m "ls_atlas: which plate set, and whether a plate is still itself

Plate identity had two homes that disagreed - three stages hardcoded
atlas/plates while three read the configured set - and curation stored the
plate as an index into a sorted array, so a swap renumbered every assignment
silently. verify() answers with four named outcomes rather than a boolean,
because a re-render can have its landmarks rescaled and a re-crop cannot.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

> **Task 1 landed as `f07a4c7`, `262db3e`, `9d9be53` and its quality-review round. The
> committed `scripts/ls_atlas.py` and `tests/test_ls_atlas.py` are the authority, not the
> Step 1 and Step 3 blocks above.** Review changed the module's shape: `verify` became
> `plate_status` with a `verified()` companion (a function named like a predicate that
> returned six truthy strings was a footgun for the five tasks about to branch on it);
> `set_dir` became `set_name`; `for_config` no longer memoises the fingerprint map (a
> long-lived curator server would have gone on verifying against the pre-swap atlas and
> answered `OK` to everything); and the stored side of `plate_status` takes the persisted
> `plate_id`/`plate_fp`/`plate_px` names so a `roi_plates.csv` row passes straight in.
> **Tasks 3–8 must call the committed signatures, not the ones written below.**
>
> On the suite specifically, the Step 1 block — review grew it from 20 assertions to 42 and the
> block was not back-ported. Re-deriving Task 1 from the block alone rebuilds the weaker
> suite. What it lacks: an `ASPECT_TOLERANCE` straddling pair (without it any tolerance
> from 0.0025 to 0.74 passes — a factor of 300); any test of `fingerprints()` at all,
> including the missing-image-keeps-its-row invariant that Task 3 depends on; the two
> `verify()` branches for an absent image and a missing `px`; `scale_between()`; and a test
> that the cache key is nanoseconds rather than whole seconds. Each of those was added
> because a mutation of the committed module passed the suite without it.

## Task 2: `tests/_atlas_fixture.py` — a synthetic atlas, twice

**Files:**
- Create: `tests/_atlas_fixture.py`
- Modify: `tests/test_ls_atlas.py` (append a section)

**Why this task exists:** `tests/_fixture.py:63` creates a **zero-byte `atlas.pdf`**. No
stage that opens an atlas has ever been exercised by a test. Every later task in this
plan needs two plate sets to swap between.

- [ ] **Step 1: Write the fixture**

Create `tests/_atlas_fixture.py`:

```python
"""Two plate sets, before and after a swap. Not a test - shared setup.

Shaped on the swap that actually happened here on 2026-09-06: same ids, some
plates re-rendered, some genuinely different, some gone. Four plates instead of
sixty-four, one per outcome of `ls_atlas.verify`:

    plate_001   byte-identical            -> OK
    plate_002   the same image at 1.5x    -> RESIZED
    plate_003   re-cropped, new aspect    -> CHANGED
    plate_004   absent from `after`       -> GONE

`plate_005` exists only in `after`, so a test can check that a new plate is not
mistaken for a moved one.

The images are deterministic - a seeded pattern, not random - so a fingerprint
is stable across runs and a failure is reproducible.
"""

import csv
import os

import numpy as np
from PIL import Image

PLATE_W, PLATE_H = 120, 80
COLUMNS = ("plate_id", "page", "image_file", "px_w", "px_h", "regions")


def _pattern(w, h, seed):
    """A deterministic greyscale plate. Different seed, different bytes."""
    ys, xs = np.mgrid[0:h, 0:w]
    value = (xs * (seed + 3) + ys * (seed + 7)) % 251
    return np.uint8(value)


def _write(path, array):
    Image.fromarray(array, mode="L").save(path)


def build(root):
    """Lay out `<root>/before/` and `<root>/after/`. Returns (before, after)."""
    before = os.path.join(root, "before")
    after = os.path.join(root, "after")
    for d in (before, after):
        os.makedirs(d, exist_ok=True)

    base = {n: _pattern(PLATE_W, PLATE_H, n) for n in (1, 2, 3, 4)}

    rows_before = []
    for n in (1, 2, 3, 4):
        name = "plate_%03d.png" % n
        _write(os.path.join(before, name), base[n])
        rows_before.append({"plate_id": "plate_%03d" % n, "page": n,
                            "image_file": name, "px_w": PLATE_W,
                            "px_h": PLATE_H, "regions": "Dl;Dm"})

    rows_after = []
    # plate_001: the same bytes.
    _write(os.path.join(after, "plate_001.png"), base[1])
    rows_after.append({"plate_id": "plate_001", "page": 1,
                       "image_file": "plate_001.png", "px_w": PLATE_W,
                       "px_h": PLATE_H, "regions": "Dl;Dm"})
    # plate_002: the same picture, re-rendered 1.5x. Same aspect, new bytes.
    big = np.asarray(Image.fromarray(base[2], mode="L").resize(
        (int(PLATE_W * 1.5), int(PLATE_H * 1.5)), Image.NEAREST))
    _write(os.path.join(after, "plate_002.png"), big)
    rows_after.append({"plate_id": "plate_002", "page": 2,
                       "image_file": "plate_002.png",
                       "px_w": int(PLATE_W * 1.5), "px_h": int(PLATE_H * 1.5),
                       "regions": "Dl;Dm"})
    # plate_003: re-cropped. The aspect moves, so this is not a resize.
    crop = base[3][:, : PLATE_W // 2]
    _write(os.path.join(after, "plate_003.png"), crop)
    rows_after.append({"plate_id": "plate_003", "page": 3,
                       "image_file": "plate_003.png", "px_w": PLATE_W // 2,
                       "px_h": PLATE_H, "regions": "Dl"})
    # plate_004 is absent. plate_005 is new.
    _write(os.path.join(after, "plate_005.png"), _pattern(PLATE_W, PLATE_H, 5))
    rows_after.append({"plate_id": "plate_005", "page": 5,
                       "image_file": "plate_005.png", "px_w": PLATE_W,
                       "px_h": PLATE_H, "regions": "Vd"})

    _plates_csv(before, rows_before)
    _plates_csv(after, rows_after)
    _seeds_csv(before, rows_before)
    _seeds_csv(after, rows_after)
    return before, after


def _plates_csv(directory, rows):
    with open(os.path.join(directory, "plates.csv"), "w",
              newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _seeds_csv(directory, rows):
    """Two seeds per plate, in the schema every real set shares."""
    keys = ("plate_id", "page", "plate_seq", "region", "region_raw",
            "is_unknown", "colour_hex", "from_raster", "x_px", "y_px",
            "x_frac", "y_frac")
    out = []
    for r in rows:
        for i, region in enumerate((r["regions"].split(";") or ["Dl"])[:2], 1):
            out.append({"plate_id": r["plate_id"], "page": r["page"],
                        "plate_seq": i, "region": region, "region_raw": region,
                        "is_unknown": 0, "colour_hex": "#ff0000",
                        "from_raster": 1, "x_px": 10 * i, "y_px": 20 * i,
                        "x_frac": round(10 * i / float(r["px_w"]), 4),
                        "y_frac": round(20 * i / float(r["px_h"]), 4)})
    with open(os.path.join(directory, "seeds.csv"), "w",
              newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(keys))
        writer.writeheader()
        writer.writerows(out)
```

- [ ] **Step 2: Append the swap section to `tests/test_ls_atlas.py`**

Insert immediately before the final `print()` / `sys.exit` block:

```python
# --- the swap, end to end -------------------------------------------------
sys.path.insert(0, HERE)
import _atlas_fixture as FIX                                  # noqa: E402

print()
print("--- a whole plate set swapped underneath the curation ---")

with tempfile.TemporaryDirectory() as tmp:
    before, after = FIX.build(tmp)
    was = A.fingerprints(before)
    now = A.fingerprints(after)
    chk("four plates before", sorted(was), ["plate_00%d" % n for n in (1, 2, 3, 4)])
    chk("four after, one of them new",
        sorted(now), ["plate_001", "plate_002", "plate_003", "plate_005"])

    def stored(pid):
        return {"plate_id": pid, "fp": was[pid]["fp"],
                "px": "%dx%d" % (was[pid]["px_w"], was[pid]["px_h"])}

    chk("an untouched plate verifies", A.verify(stored("plate_001"), now), A.OK)
    chk("a re-rendered plate is a resize", A.verify(stored("plate_002"), now), A.RESIZED)
    chk("a re-cropped plate has changed", A.verify(stored("plate_003"), now), A.CHANGED)
    chk("a dropped plate is gone", A.verify(stored("plate_004"), now), A.GONE)
    chk("the rescale factor is the size ratio",
        round(A.scale_between(stored("plate_002")["px"], now["plate_002"]), 3), 1.5)
    chk("...and there is none to apply for an unchanged plate",
        A.scale_between(stored("plate_001")["px"], now["plate_001"]), 1.0)

    # The cache must not answer for a file that has been replaced in place.
    import shutil
    swapped = os.path.join(tmp, "swapped")
    shutil.copytree(before, swapped)
    A.fingerprints(swapped)                     # writes the cache
    shutil.copy(os.path.join(after, "plate_003.png"),
                os.path.join(swapped, "plate_003.png"))
    again = A.fingerprints(swapped)
    chk("a replaced image is re-hashed, not served from the cache",
        again["plate_003"]["fp"], now["plate_003"]["fp"])
```

- [ ] **Step 3: Run it**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_atlas.py
```

Expected: `ALL PASS`, including the eight new lines.

- [ ] **Step 4: Confirm the fixture is not collected as a suite**

`tests/run.sh` globs `tests/test_*.py`, so `_atlas_fixture.py` is not run directly.
Verify:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh 2>&1 | grep -c "=== _atlas_fixture"
```

Expected: `0`.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add tests/_atlas_fixture.py tests/test_ls_atlas.py && git commit -m "A synthetic atlas, before and after a swap

tests/_fixture.py creates a zero-byte atlas.pdf, so no stage that opens an
atlas has ever been exercised. This builds two plate sets shaped on the swap
that happened here on 2026-09-06: one plate identical, one re-rendered larger,
one re-cropped, one gone, one new.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: `04l` Python — order the plates, report the gap, ship the fingerprints

**Files:**
- Modify: `scripts/04l_roi_curator.py:5062-5095` (the `pl` build) and the `IO.fill` call at `:5105-5112`
- Test: `tests/test_roi_curator_plates.py` (new)

Two defects live in five lines here.

```python
    for p in sorted(plates, key=lambda p: p["plate_id"]):
        img = os.path.join(PLATE_DIR, p["image_file"])
        if not os.path.exists(img):
            continue
```

A **string** sort, correct only because this atlas zero-pads; and a `continue` that
**drops the plate and shifts every later index by one**.

- [ ] **Step 1: Write the failing test**

Create `tests/test_roi_curator_plates.py`:

```python
"""The curator's plate array: its order, and what a missing image does to it.

Both defects here are silent. A string sort is right only for a zero-padded
atlas; `plate_1 .. plate_100` scrambles, and every stored index then means a
different plate. And skipping a plate whose image is absent shifts every later
index by one, which renumbers the back half of the atlas with nothing said.

Run:  work/appenv/Scripts/python.exe tests/test_roi_curator_plates.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from _fixture import load_stage, use_temp_study               # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


study = use_temp_study(atlas_plate_set={"dir": "before"})
sys.path.insert(0, os.path.join(REPO, "scripts"))
import _atlas_fixture as FIX                                  # noqa: E402

atlas_root = os.path.join(study.out_root, "atlas")
os.makedirs(atlas_root, exist_ok=True)
before, after = FIX.build(atlas_root)

C = load_stage("04l_roi_curator.py")

rows = C.plate_rows()
chk("every plate in the table is in the array", len(rows), 4)
chk("...in atlas order", [r["id"] for r in rows],
    ["plate_001", "plate_002", "plate_003", "plate_004"])
chk("each carries its fingerprint", all(r.get("fp") for r in rows), True)
chk("...and its pixel size", rows[0]["w"], FIX.PLATE_W)

# Remove one image. The plate must KEEP its slot.
os.remove(os.path.join(before, "plate_002.png"))
rows = C.plate_rows()
chk("a plate whose image is gone keeps its position", len(rows), 4)
chk("...and the ones after it do not shift",
    [r["id"] for r in rows],
    ["plate_001", "plate_002", "plate_003", "plate_004"])
chk("...and it is marked rather than dropped", rows[1]["missing"], 1)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_roi_curator_plates.py
```

Expected: `AttributeError: module ... has no attribute 'plate_rows'`.

- [ ] **Step 3: Extract `plate_rows()` and fix both defects**

In `scripts/04l_roi_curator.py`, add `import ls_atlas as AT` beside the existing
`import ls_paths as LP` line, then replace the block beginning
`for p in sorted(plates, key=lambda p: p["plate_id"]):` with a call to a new
module-level function, and define that function above `build()`:

```python
def plate_rows(plate_dir=None):
    """The plate array the page indexes into, in atlas order.

    TWO THINGS THAT USED TO BE WRONG HERE, both silently.

    The sort was `key=lambda p: p["plate_id"]` - a STRING sort, correct only
    because this atlas zero-pads to three digits. An atlas numbering
    `plate_1 .. plate_100` orders 1, 10, 100, 2, and every index stored against
    it means a different plate with no error anywhere. `ls_atlas.plate_order`
    is numeric-aware and falls back to text when the ids carry no number.

    And a plate whose image was absent was `continue`d - dropped from the array,
    shifting every later index by one. One missing PNG renumbered the back half
    of the atlas. It now keeps its slot and carries `missing: 1`, so the page
    can refuse to draw it and say why.
    """
    plate_dir = plate_dir or PLATE_DIR
    with open(os.path.join(plate_dir, "plates.csv"), newline="",
              encoding="utf-8") as fh:
        plates = list(csv.DictReader(fh))
    seeds = load_seeds(plate_dir)
    prints = AT.fingerprints(plate_dir, plates)

    out = []
    for p in AT.plate_order(plates):
        pid = p["plate_id"]
        sd = seeds.get(pid, [])
        hulls = region_hulls(sd)
        tag_rois(sd, hulls)
        pw, ph = int(p["px_w"]), int(p["px_h"])
        nn = 0.0
        if len(sd) > 1:
            pts = [(x["xf"] * pw, x["yf"] * ph) for x in sd]
            diag = math.hypot(pw, ph)
            near = sorted(min(math.dist(a, b) for j, b in enumerate(pts) if j != i)
                          for i, a in enumerate(pts))
            nn = near[len(near) // 2] / diag
        fp = (prints.get(pid) or {}).get("fp")
        out.append({"id": pid, "nn": round(nn, 5),
                    "img": f"../atlas/{PLATE_SET}/{p['image_file']}",
                    "w": pw, "h": ph,
                    "fp": fp, "missing": 0 if fp else 1,
                    "labelled": int(bool(sd)), "seeds": sd,
                    "hulls": hulls})
    return out
```

Then in `build()`, replace the removed loop with:

```python
    pl = plate_rows()
    gaps = [p["id"] for p in pl if p["missing"]]
    if gaps:
        print(f"  !! {len(gaps)} plate image(s) missing from {PLATE_SET}: "
              + ", ".join(gaps[:8]) + (" ..." if len(gaps) > 8 else ""))
        print("     They keep their place in the array so no assignment moves.")
```

Keep the `"nn"` comment block that currently sits inside the loop — move it into
`plate_rows()` unchanged.

- [ ] **Step 4: Run the test**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_roi_curator_plates.py
```

Expected: `ALL PASS`.

- [ ] **Step 5: Prove the live page does not move**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import csv, os, sys
sys.path.insert(0, 'scripts')
import ls_atlas as A
from ls_config import CONFIG
d = A.plate_dir(CONFIG)
rows = list(csv.DictReader(open(os.path.join(d,'plates.csv'), newline='', encoding='utf-8')))
old = [r['plate_id'] for r in sorted(rows, key=lambda r: r['plate_id'])
       if os.path.exists(os.path.join(d, r['image_file']))]
new = [r['plate_id'] for r in A.plate_order(rows)]
print('same array:', old == new, len(old), len(new))
"
```

Expected: `same array: True 64 64`.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/04l_roi_curator.py tests/test_roi_curator_plates.py && git commit -m "04l: the plate array is ordered, and a missing image is a gap not a shift

The sort was on the raw plate_id string, right only because this atlas
zero-pads to three digits; plate_1 .. plate_100 scrambles under it and every
stored index then means a different plate. And a plate whose PNG was absent was
dropped from the array, shifting every later index by one.

Verified against the live 64-plate set: the array is identical.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: the export gains plate identity

**Files:**
- Modify: `scripts/04l_roi_curator.py:3258` (the `pl` header) and `:3321-3324` (the row)
- Test: whichever suite asserts the export header. Find it first — do not guess:
  `grep -rln "plate_index" tests/*.test.js`

`roi_plates.csv` already carries `plate_set` and `plate_id`. It needs the fingerprint,
the pixel size and the verification state.

- [ ] **Step 1: Widen the header**

Replace line 3258's array with:

```javascript
  const pl=[["scene_uid","animal","marker","subset","section_order","plate_set","plate_id","plate_index",
             "plate_fp","plate_px","plate_verified",
```

leaving the remainder of that header literal exactly as it is.

- [ ] **Step 2: Widen the row**

Replace the `pl.push([...])` at `:3321-3324` with:

```javascript
    pl.push([d.uid,d.animal,d.m,d.sub,d.order,PLATE_SET, chosen?P.id:"", chosen?s.plate:"",
             // Identity, so a restore can CHECK rather than trust the index.
             // plate_px is here only so a re-render's landmarks can be scaled:
             // once the image has changed, the current set can no longer say
             // what size it used to be.
             chosen?(P.fp||""):"", chosen?(P.w+"x"+P.h):"", s.verified||"",
             chosen?(P.labelled?1:0):"", n, nBg, T?T.kind:"", status,
             s.fav?1:0, (s.rot||0).toFixed(1),
             excl?1:0]);
```

- [ ] **Step 3: Check the header and the row still line up**

The page suites parse the exports. Run them:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && grep -rn "plate_index\|plate_set" tests/*.test.js && bash tests/run.sh
```

Expected: `ALL SUITES PASS`. Any suite that asserts the header or a column count has to
move from 16 columns to 19; say in a comment which three were added and why, rather than
just bumping the number.

- [ ] **Step 4: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/04l_roi_curator.py tests/ && git commit -m "roi_plates.csv carries plate identity, not just an index

plate_fp is the fingerprint of the plate image as it was when the operator
chose it; plate_px is its size, kept because a re-render's landmarks need the
old width to scale by and the current set can no longer supply it;
plate_verified records whether the assignment has been checked.

plate_index stays, and stays written. It is no longer the key - it is a record
of what the array looked like, and the fallback for a file exported before
this change.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: the page resolves by id, and refuses to compute on what it cannot verify

**Files:**
- Modify: `scripts/04l_roi_curator.py` — `initState` (`:1390-1396`), `st()` (`:1488`), `transform()` (`:1590`), the three `transform(s.pairs)` callers (`:1697`, `:2685`, `:3311`), and the banner
- Modify: `scripts/04l_roi_curator.py` — bounds at the 13 `PLATES[...]` sites
- Test: `tests/plates.test.js` (new)

`initState(raw, seed)` at `:1390` is the **one** place stored state is hydrated —
localStorage and the embedded seed both pass through it. That is the migration hook.

`transform(pairs)` at `:1590` is the **one** place a fit is computed, and its own comment
says so: *"Filtered here rather than at each call site, so a new caller cannot forget."*
That is the gate.

- [ ] **Step 1: Write the failing test**

Create `tests/plates.test.js`. The harness is `tests/harness.js` and its API is
`const { env, load, chk, note, done } = require("./harness")`; `load()` takes a
**destructuring expression as a string** naming what to lift out of the page, and an
optional page name defaulting to `"curator"` (see `tests/review.test.js:17` for the
shape). The page under test is built by `run.sh` from the operator's real config, so
`PLATES` is the live 64-plate array — the fakes below are passed as the second argument
to each function rather than replacing it:

```javascript
// A section's plate must survive an atlas swap, or say that it did not.
//
// The failure this pins: keyed on the integer index, every assignment silently
// means a different plate after a swap. Keyed on the id ALONE it silently
// succeeds against a plate that has been re-rendered - which is what happened
// here on 2026-09-06, same 64 ids, 34 rows differing in geometry.

const { load, chk, done } = require("./harness");

const P = load(`{resolvePlate, verifyPlate, plateAt, transform, BLANK_PLATE}`);

// A three-plate atlas standing in for the one on screen. Passed in rather than
// swapped for PLATES, so this suite does not depend on the operator's atlas.
const PLATES = [
  { id: "plate_001", fp: "aaaaaaaaaaaa", w: 100, h: 200, missing: 0, seeds: [], hulls: [] },
  { id: "plate_002", fp: "bbbbbbbbbbbb", w: 150, h: 300, missing: 0, seeds: [], hulls: [] },
  { id: "plate_003", fp: "cccccccccccc", w: 50,  h: 200, missing: 0, seeds: [], hulls: [] },
];
const page = P;

chk("an assignment whose fingerprint matches is verified",
    page.resolvePlate({ plate: 0, plate_id: "plate_001", plate_fp: "aaaaaaaaaaaa",
                        plate_px: "100x200" }, PLATES).verified, "ok");

chk("a re-rendered plate is a resize",
    page.resolvePlate({ plate: 0, plate_id: "plate_002", plate_fp: "old",
                        plate_px: "100x200" }, PLATES).verified, "resized");

chk("...and its landmarks are scaled by the size ratio",
    page.resolvePlate({ plate: 0, plate_id: "plate_002", plate_fp: "old",
                        plate_px: "100x200",
                        pairs: [[10, 10, 20, 20, 0, 0, "roi"]] }, PLATES)
        .pairs[0][2], 30);

chk("a re-cropped plate has changed",
    page.resolvePlate({ plate: 0, plate_id: "plate_003", plate_fp: "old",
                        plate_px: "100x200" }, PLATES).verified, "changed");

chk("a plate the set no longer has is gone",
    page.resolvePlate({ plate: 0, plate_id: "plate_099", plate_fp: "x" }, PLATES).verified,
    "gone");

chk("the ASSIGNMENT is kept in every case",
    page.resolvePlate({ plate: 1, plate_id: "plate_099", plate_fp: "x" }, PLATES).plate_id,
    "plate_099");

chk("an export with no id at all restores by index and says so",
    page.resolvePlate({ plate: 2 }, PLATES).verified, "by_index");

chk("an id with no fingerprint is unchecked, not verified",
    page.resolvePlate({ plate: 0, plate_id: "plate_001" }, PLATES).verified, "unchecked");

chk("...and by index means the index, not a guess",
    page.resolvePlate({ plate: 2 }, PLATES).plate, 2);

chk("an id that moved position is followed to its new slot",
    page.resolvePlate({ plate: 0, plate_id: "plate_003", plate_fp: "cccccccccccc",
                        plate_px: "50x200" }, PLATES).plate, 2);

// The gate.
chk("an unverified section's landmarks do not reach the transform",
    page.transform({ verified: "changed",
                     pairs: [[0,0,0,0,0,0,"roi"],[1,1,1,1,0,0,"roi"],
                             [2,2,2,2,0,0,"roi"]] }), null);

chk("...and a verified one's do",
    page.transform({ verified: "ok",
                     pairs: [[0,0,0,0,0,0,"roi"],[1,1,1,1,0,0,"roi"],
                             [2,2,2,2,0,0,"roi"]] }) !== null, true);

chk("a stored index past the end of a shorter atlas does not throw",
    page.plateAt({ plate: 99 }, PLATES).id, "");

done();
```

`load()` can only lift names the page actually exposes, so `resolvePlate`, `verifyPlate`,
`plateAt`, `transform` and `BLANK_PLATE` must be declared at the page's top level in
Step 3 — not nested inside another function.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh 2>&1 | grep -A10 "=== plates.test.js"
```

Expected: `page.resolvePlate is not a function`.

- [ ] **Step 3: Add `resolvePlate`, `plateAt` and the gate to the page**

First add the token, so the page is handed the tolerance rather than repeating it.
In `build()`'s `IO.fill` call, alongside `__PLATES__` and `__PLATESET__`:

```python
        "__ASPECTTOL__": AT.ASPECT_TOLERANCE,
```

and near the other page constants (beside `const PLATE_SET = __PLATESET__;`):

```javascript
const ASPECT_TOL = __ASPECTTOL__;
```

Then, after the `st()` definition at `:1488`, add:

```javascript
// ---- plate identity --------------------------------------------------------
//
// A section records which plate it sits on. Stored as the INTEGER INDEX into
// PLATES, that is a claim about an array, not about an atlas: swap the plate
// set and every assignment means a different plate, silently. Stored as the ID
// alone it is a claim that succeeds against a plate that has been re-rendered -
// which is what happened here on 2026-09-06, all 64 ids reused, 34 of them a
// different picture.
//
// So: resolve by id, then CHECK the image's fingerprint.
const PLATE_BY_ID = Object.fromEntries(PLATES.map((p, i) => [p.id, i]));
const BLANK_PLATE = {id: "", fp: "", w: 0, h: 0, missing: 1, seeds: [], hulls: []};

// Never PLATES[s.plate] bare. A store written against a longer atlas indexes
// past the end, and `.seeds` on undefined is a TypeError that takes the page
// down on load - the one moment the operator has no way to recover.
const plateAt = (s, plates) => (plates || PLATES)[s && s.plate] || BLANK_PLATE;

const shapeOf = px => {
  const m = /^(\d+)x(\d+)$/.exec(String(px || ""));
  return m ? [+m[1], +m[2]] : null;
};

// The same four outcomes ls_atlas.verify answers with, computed the same way,
// because the page and the importers must agree about what "still the same
// plate" means or a section verifies in one and not the other.
function verifyPlate(rec, plates) {
  if (!rec || !rec.plate_id) return "by_index";
  const i = PLATE_BY_ID[rec.plate_id];
  const p = i === undefined ? null : (plates || PLATES)[i];
  if (!p || p.missing) return "gone";
  if (!rec.plate_fp) return "unchecked";
  if (rec.plate_fp === p.fp) return "ok";
  const was = shapeOf(rec.plate_px);
  if (!was || !p.w || !p.h) return "changed";
  const a = was[0] / was[1], b = p.w / p.h;
  // ASPECT_TOL comes from ls_atlas.ASPECT_TOLERANCE through IO.fill, NOT a
  // literal 0.01. Python and JS agreeing today is not the same as agreeing
  // after someone tunes the tolerance, and a section that verifies in the
  // importer but not in the page is the exact split this module exists to
  // close. Same for the digest length, if the page ever compares prefixes.
  return Math.abs(a - b) <= ASPECT_TOL * Math.max(a, b) ? "resized" : "changed";
}

// Rebuild one stored record against the atlas that is actually loaded.
//
// THE ASSIGNMENT IS ALWAYS KEPT. A section whose plate no longer verifies is
// shown with the plate the operator chose, marked, and its landmarks withheld
// from the fit until a person confirms - never dropped, and never used as if
// nothing had happened.
function resolvePlate(rec, plates) {
  const out = Object.assign({}, rec);
  const state = verifyPlate(rec, plates);
  out.verified = state;
  const i = PLATE_BY_ID[rec && rec.plate_id];
  if (i !== undefined) out.plate = i;
  if (state === "resized") {
    // plate_x/plate_y are pixels of the image as it was. A re-render at a new
    // size leaves them wrong by exactly the size ratio. Scaled and MARKED, not
    // accepted: a re-render can crop as well as scale, and the ratio cannot
    // tell the two apart.
    const was = shapeOf(rec.plate_px), p = (plates || PLATES)[i];
    if (was && p && p.w) {
      const k = p.w / was[0];
      out.pairs = (rec.pairs || []).map(q => {
        const c = q.slice();
        c[2] = c[2] * k;
        c[3] = c[3] * k;
        return c;
      });
    }
  }
  return out;
}
```

- [ ] **Step 4: Migrate on load**

Replace `initState` at `:1390-1396` with:

```javascript
function initState(raw, seed){
  let v = null;
  try {
    if (raw) { const parsed = decided(JSON.parse(raw)); if (Object.keys(parsed).length) v = parsed; }
  } catch (e) {}
  if (!v) v = decided(seed);
  // EVERY stored record passes through here - the browser's store and the
  // embedded seed both - so this is the one place an assignment made against a
  // different plate set can be checked. Migrating anywhere else would leave
  // whichever of the two did not pass through it silently trusted.
  return Object.fromEntries(
    Object.entries(v).map(([uid, rec]) => [uid, resolvePlate(rec, PLATES)]));
}
```

- [ ] **Step 5: Gate the transform**

Replace `transform(pairs)` at `:1590` with:

```javascript
// The transform actually used: TPS once there are enough points, affine below.
function transform(s){
  // NOTHING IS COMPUTED FROM AN UNVERIFIED SECTION. Its landmarks were placed
  // against a plate image that is no longer the one on screen, so a fit from
  // them is a number with no meaning - and it would look exactly like a good
  // one. Confirming the plate is what releases them.
  if (s && s.verified && s.verified !== "ok") return null;
  const pairs = (s && s.pairs) || [];
  // A background disc is a position on the SECTION with no counterpart on the
  // plate, so it must never enter the fit - its (0,0) plate coordinate would
  // drag the whole spline to the corner. Filtered here rather than at each call
  // site, so a new caller cannot forget: there is no way to ask for a transform
  // that includes them.
  const p = pairs.filter(q => q[6] !== "bg");
  return tps(p) || affine(p);
}
```

Change the three callers from `transform(s.pairs)` to `transform(s)`:

- `:1697` `const s=st(active), T=transform(s), u=uiScale(c);`
- `:2685` `const s=st(active), T=transform(s);`
- `:3311` `const T=transform(s);`

All three already keep `T` and test it, because `tps(p) || affine(p)` has always
returned `null` below three pairs.

- [ ] **Step 6: Make every `PLATES[...]` bounds-safe**

Replace each of these with `plateAt(...)`. The full list, verified:

| line | now | becomes |
|---|---|---|
| 1500 | `PLIMG[st(active).plate]` | `PLIMG[st(active).plate] \|\| PLIMG[0]` |
| 1699 | `numScale(PLATES[s.plate], c, u)` | `numScale(plateAt(s), c, u)` |
| 1730 | `const Ppl = PLATES[s.plate];` | `const Ppl = plateAt(s);` |
| 1819 | `P=PLATES[s.plate]` | `P=plateAt(s)` |
| 2162 | `s => PLATES[s.plate].seeds` | `s => plateAt(s).seeds` |
| 2172 | `s => (PLATES[s.plate].hulls \|\| [])` | `s => (plateAt(s).hulls \|\| [])` |
| 2555 | `PLATES[st(active).plate]` | `plateAt(st(active))` |
| 2781 | `const P=PLATES[s.plate];` | `const P=plateAt(s);` |
| 2821 | `regionKey(PLATES[st(active).plate], ...)` | `regionKey(plateAt(st(active)), ...)` |
| 2902 | `const P=PLATES[+v];` | `const P=PLATES[+v] \|\| BLANK_PLATE;` |
| 2992 | `PLATES[s.plate].id.replace(...)` | `plateAt(s).id.replace(...)` |
| 3310 | `const P=PLATES[s.plate], ...` | `const P=plateAt(s), ...` |
| 4039 | `(PLATES[i] ? PLATES[i].id : "")` | already guarded — leave it |
| 4046 | `sl.plate === undefined ? null : PLATES[sl.plate]` | already guarded — leave it |

- [ ] **Step 7: The banner**

After the state is built, add a one-time report. Put it beside the existing backup
notice (around `:1418`):

```javascript
// WHAT THE OPERATOR IS TOLD. A count, not a silent degradation: sections whose
// plate no longer verifies are still on screen with the plate they chose, and
// the only way to know their landmarks are being withheld is to be told.
(function plateNotice(){
  const by = {};
  Object.values(S).forEach(r => {
    if (r.verified && r.verified !== "ok") by[r.verified] = (by[r.verified]||0)+1;
  });
  const n = Object.values(by).reduce((a, b) => a + b, 0);
  if (!n) return;
  const parts = [];
  if (by.changed)  parts.push(by.changed + " changed");
  if (by.resized)  parts.push(by.resized + " re-rendered at a new size");
  if (by.gone)     parts.push(by.gone + " no longer in this atlas");
  if (by.unchecked) parts.push(by.unchecked + " never fingerprinted");
  if (by.by_index) parts.push(by.by_index + " recorded before plate ids were kept");
  const bar = document.createElement("div");
  bar.className = "notice";
  bar.textContent = n + " section(s) need their plate re-confirming: "
                  + parts.join(", ") + ". Their landmarks are not being used "
                  + "until you confirm each one.";
  document.body.insertBefore(bar, document.body.firstChild);
})();
```

- [ ] **Step 8: Confirming clears the mark**

In `onSlide` at `:2900`, where `s.plate=+v; save();` already runs, record the identity
of what was chosen:

```javascript
  const s=st(active); s.plate=+v;
  // Choosing a plate IS the confirmation, and it re-stamps identity from the
  // atlas that is loaded now - so a section confirmed after a swap carries the
  // new fingerprint and stops being flagged.
  const P = PLATES[+v] || BLANK_PLATE;
  s.plate_id = P.id; s.plate_fp = P.fp || ""; s.plate_px = P.w + "x" + P.h;
  s.verified = "ok";
  save();
```

- [ ] **Step 9: Run everything**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh
```

Expected: `ALL SUITES PASS`.

- [ ] **Step 10: Confirm the live page is unchanged for a study that did not swap**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'scripts')
import importlib.util, os
spec = importlib.util.spec_from_file_location('c','scripts/04l_roi_curator.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
rows = m.plate_rows()
print('plates:', len(rows), 'missing:', sum(r['missing'] for r in rows))
print('first:', rows[0]['id'], rows[0]['fp'])
" 2>&1 | grep -v '^  !!'
```

Expected: `plates: 64 missing: 0`.

- [ ] **Step 11: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/04l_roi_curator.py tests/plates.test.js && git commit -m "04l: a section's plate is an identity the page can check

Resolved by id and verified against the plate image's fingerprint on load, in
initState - the one place both the browser's store and the embedded seed pass
through. An assignment that no longer verifies is KEPT and marked; its
landmarks are withheld from transform(), which is the one place a fit is
computed, so no caller can use them by forgetting.

A re-render at a new size has its plate coordinates scaled by the size ratio
and is still marked, because a re-render can crop as well as scale and the
ratio cannot tell the two apart.

Every PLATES[s.plate] is bounds-safe: a store written against a longer atlas
used to throw on .seeds at load, which is the one moment there is no way to
recover.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: both importers restore by id, through one rule

**Files:**
- Modify: `scripts/04q_import_curation.py:175-230` (`build`)
- Modify: `app/import_exports.py:133-200` (`_blank`, `rebuild`)
- Modify: `tests/test_import_curation.py:70-95, 215-230`
- Test: `tests/test_import_curation.py`

The two are deliberate mirrors; P1.4 established that fixing one and not the other is how
the 3x coordinate displacement survived. The shared piece is the **per-row plate
resolution**, not the whole function — `04q.build` takes rows, `import_exports.rebuild`
takes paths.

- [ ] **Step 1: Rewrite the assertions that pin the bug**

`tests/test_import_curation.py:72-73` supplies a row where id and index deliberately
disagree, and `:221-222` asserts the **index** wins. Replace the fixture rows:

```python
PLATES = [
    # plate_id and plate_index deliberately DISAGREE. They used to, because the
    # page wrote the index it had and the id it had and nothing checked them
    # against each other; the importer took the index, so an export made against
    # one atlas restored against another silently. The id is the key now.
    {"scene_uid": "A_s01a_sc00", "marker": "AF568", "plate_id": "plate_010",
     "plate_index": "9", "plate_fp": "aaaaaaaaaaaa", "plate_px": "100x200",
     "status": "registered", "favorite": "0",
     "view_rotation_deg": "12.5", "excluded": "0"},
```

leaving rows B, C and D as they are but adding `"plate_fp": "", "plate_px": ""` to each.

Replace the two assertions at `:221-222`:

```python
    chk("a named plate reads as assigned", state["A_s01a_sc00"]["assigned"], True)
    # THE ID WINS. The index is kept as a record of what the array looked like
    # and used only when there is no id at all.
    chk("...and the plate comes from the id", state["A_s01a_sc00"]["plate_id"], "plate_010")
    chk("...not from the index it disagrees with", state["A_s01a_sc00"]["plate"], 9)
    chk("...and it is marked unverified until the atlas is there to check",
        state["A_s01a_sc00"]["verified"], "unchecked")
    chk("no plate named, not assigned", state["B_s01b_sc00"]["assigned"], False)
    chk("...and the index falls back to 0", state["B_s01b_sc00"]["plate"], 0)
```

Everything else in that file — the 3x frame scale, the background-disc recovery, the
`n` stamp, the decision flags — is load-bearing and stays exactly as written.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_import_curation.py
```

Expected: `FAIL ...and the plate comes from the id` — `KeyError: 'plate_id'`.

- [ ] **Step 3: Add the shared rule to `ls_atlas.py`**

```python
STATE_FIELDS = ("plate", "plate_id", "plate_fp", "plate_px", "verified")


def restore_plate(row, index_value):
    """The plate fields for one restored section.

    ONE implementation for both importers. `04q_import_curation` and
    `app/import_exports` are deliberate mirrors and were fixed apart once
    before, which is how a 3x coordinate displacement survived in one of them
    for weeks.

    The index is kept and returned. It is no longer the key - it is what the
    array looked like when the export was written, and the only thing to fall
    back to for a file exported before fingerprints existed.

    `verified` is "unchecked" rather than a verdict: these importers run without
    the atlas loaded, so they record WHAT WAS CLAIMED and leave the checking to
    whoever has the plate set in front of them. Calling it verified here would
    be a verdict reached without looking.
    """
    plate_id = (row.get("plate_id") or "").strip()
    return {
        "plate": index_value,
        "plate_id": plate_id,
        "plate_fp": (row.get("plate_fp") or "").strip(),
        "plate_px": (row.get("plate_px") or "").strip(),
        "verified": UNCHECKED if plate_id else BY_INDEX,
    }
```

- [ ] **Step 4: Call it from `04q`**

Add `import ls_atlas as AT` beside `import ls_paths as LP`, and replace the plate lines
in `build()`:

```python
        idx = cell(r, "plate_index")
        state[uid] = dict(
            AT.restore_plate(r, int(num(idx)) if idx else 0),
            pairs=[],
            polys=[],
            # Export collapses `assigned || n > 0` into plate_id - see the
            # module docstring; a named plate is read as a chosen one.
            assigned=bool(cell(r, "plate_id")),
            noroi=cell(r, "status") == "no_roi",
            fav=cell(r, "favorite") == "1",
            rot=tidy(num(cell(r, "view_rotation_deg"))),
```

keeping the remaining keys of that dict literal unchanged.

Extend `STATE_FIELDS` at `04q:96`:

```python
STATE_FIELDS = ("plate", "plate_id", "plate_fp", "plate_px", "verified",
                "pairs", "polys", "assigned", "noroi", "fav", "rot", "excl")
```

- [ ] **Step 5: Call it from `app/import_exports.py`**

Replace `_blank()` at `:133`:

```python
def _blank():
    return {"plate": 0, "plate_id": "", "plate_fp": "", "plate_px": "",
            "verified": "by_index", "pairs": [], "assigned": False,
            "noroi": False, "fav": False, "rot": 0.0, "excl": False}
```

and the plate block at `:177-182`:

```python
            idx = (r.get("plate_index") or "").strip()
            e.update(AT.restore_plate(r, int(float(idx)) if idx else 0))
            if idx or e["plate_id"]:
                # A recorded plate means the plate was a decision: the export
                # only writes one when the operator chose it.
                e["assigned"] = True
```

Add the import. `app/import_exports.py` already loads sibling modules from `scripts/`
(see `SCRIPTS` at `:52`); follow that pattern exactly rather than adding a second one.

- [ ] **Step 6: Run both suites**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_import_curation.py && work/appenv/Scripts/python.exe tests/test_import_exports.py
```

Expected: `ALL PASS` from both. Note that `tests/test_import_exports.py` does **not**
pin the bug — its fixture uses `plate_id: plate_009` with `plate_index: 8`, which agree.

- [ ] **Step 7: Import the operator's real export, read-only**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import sys, os; sys.path.insert(0,'scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('q','scripts/04q_import_curation.py')
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
# NOT reformatted/ - there is no roi_plates.csv there. The curator exports
# through a clicked <a download>, so they land wherever the browser puts them;
# on this machine that is Downloads, in timestamped sets, with the browser's
# own (1)/(2) disambiguation on the older ones. reformatted/ holds what a
# STAGE wrote: roi_regions_used_AF568.csv (Sep 7, 1246 rows - 612 ROI and 634
# background over 138 sections) is 05a's output, not an export.
#   ls -t ~/Downloads/roi_plates*.csv | head -1
R = r'C:\Users\marti\Downloads'
plates = q.load(os.path.join(R, 'roi_plates_07.09.2026_11.27.csv'))
marks  = q.load(os.path.join(R, 'roi_landmarks_07.09.2026_11.27.csv'))
regions= q.load(os.path.join(R, 'roi_regions_07.09.2026_11.27.csv'))
S, *_ = q.build(plates, marks, regions, q.k_from_disk())
print('sections:', len(S))
from collections import Counter
print(Counter(v['verified'] for v in S.values()))
print(Counter(bool(v['plate_id']) for v in S.values()))
" 2>&1 | grep -v '^  !!'
```

Expected: the operator's section count, every one `by_index` or `unchecked`, and
**nothing raised**. This writes nothing.

- [ ] **Step 8: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/ls_atlas.py scripts/04q_import_curation.py app/import_exports.py tests/test_import_curation.py && git commit -m "Both importers restore the plate by id, through one function

04q_import_curation and app/import_exports are deliberate mirrors that were
fixed apart once before - which is how a 3x coordinate displacement survived in
one of them. restore_plate() in ls_atlas is the single implementation.

The index is kept and still written: it is a record of what the array looked
like, and the fallback for an export made before fingerprints existed. Those
restore as by_index, which is honest - calling them verified would launder the
2026-09-06 failure into a green tick.

tests/test_import_curation.py deliberately fed a row whose id and index
disagreed and asserted the INDEX won. Rewritten to assert the id does.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: level anchors by id

**Files:**
- Modify: `scripts/04k_level_curator.py:178-182` and its `save`/`load`
- Test: `tests/level_curator.test.js` — it already exists and `run.sh:104` already builds the 04k page for it

`04k:179` is `let anchors = JSON.parse(localStorage.getItem(KEY) || "{}"); // uid -> plate index`.
The same defect, one file over.

- [ ] **Step 1: Write the failing assertion**

Append to `tests/level_curator.test.js`, lifting the new function out of the 04k page —
note the second argument to `load`, which selects that page rather than the ROI curator:

```javascript
// 04k stores uid -> plate index too. An anchor that no longer resolves must
// leave the monotonic constraint rather than anchor a whole animal's series to
// the wrong level: everything between two anchors is interpolated from them.
const L = load(`{migrateAnchors}`, "level_curator");

const FAKE = [{id: "plate_001"}, {id: "plate_002"}, {id: "plate_003"}];

chk("an anchor follows its plate id",
    L.migrateAnchors({ "LS1_s01a": { id: "plate_003", at: 0 } }, FAKE)["LS1_s01a"].at,
    2);
chk("an anchor whose plate is gone is dropped, not moved",
    L.migrateAnchors({ "LS1_s01a": { id: "plate_099", at: 0 } }, FAKE)["LS1_s01a"],
    undefined);
chk("a bare integer anchor from before this change still loads",
    L.migrateAnchors({ "LS1_s01a": 1 }, FAKE)["LS1_s01a"].at, 1);
chk("...and picks up the id that was at that position",
    L.migrateAnchors({ "LS1_s01a": 1 }, FAKE)["LS1_s01a"].id, "plate_002");
```

`migrateAnchors` must be declared at the 04k page's top level for `load` to reach it.

- [ ] **Step 2: Store `{id, at}` rather than a bare integer**

Replace `04k:179` with:

```javascript
// uid -> {id, at}. It was uid -> plate index, which is a claim about an ARRAY:
// swap the plate set and every anchor silently moves a whole animal's series to
// a different level, with the interpolation between anchors carrying the error
// to every section in between. The index is kept as `at` for the slider; `id`
// is what survives a swap.
const PLATE_BY_ID = Object.fromEntries(PLATES.map((p, i) => [p.id, i]));

function migrateAnchors(raw, plates){
  const by = Object.fromEntries((plates || PLATES).map((p, i) => [p.id, i]));
  const out = {};
  Object.entries(raw || {}).forEach(([uid, v]) => {
    if (typeof v === "number") { out[uid] = {id: ((plates||PLATES)[v]||{}).id || "", at: v}; return; }
    if (!v || !v.id) return;
    const i = by[v.id];
    // An anchor to a plate this atlas does not have is DROPPED from the
    // constraint rather than left pointing at whatever now sits at its index.
    // A wrong anchor is worse than a missing one: everything between two
    // anchors is interpolated from them.
    if (i === undefined) return;
    out[uid] = {id: v.id, at: i};
  });
  return out;
}

let anchors = migrateAnchors(JSON.parse(localStorage.getItem(KEY) || "{}"), PLATES);
```

Every read of `anchors[uid]` becomes `anchors[uid].at`, and every write becomes
`anchors[uid] = {id: PLATES[i].id, at: i}`. Find them:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && grep -n "anchors\[" scripts/04k_level_curator.py
```

- [ ] **Step 3: Use the shared plate array**

`04k:364` builds its own `pl` list. Replace it with a call into the same ordering rule so
04k and 04l cannot disagree about which plate is index 4:

```python
    pl = [{"id": p["plate_id"], "img": f"../atlas/{PLATE_SET}/{p['image_file']}",
           "regions": p.get("regions", "")}
          for p in AT.plate_order(plates)]
```

adding `import ls_atlas as AT`. Note `p.get("regions", "")` — `plates_final/plates.csv`
has **no** `regions` column, so `p["regions"]` would raise `KeyError` for the set this
study actually uses.

- [ ] **Step 4: Run the suites and commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh && git add scripts/04k_level_curator.py tests/plates.test.js && git commit -m "04k: a level anchor is a plate id, not an array position

Everything between two anchors is interpolated from them, so an anchor that
silently moves carries the error to every section in between. An anchor whose
plate is not in this atlas is dropped from the constraint rather than left
pointing at whatever now sits at its index.

Also: the plate array is built through ls_atlas.plate_order, so 04k and 04l
cannot disagree about which plate is index 4 - and regions is read with .get,
because plates_final has no such column and this study uses plates_final.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: the plate set is resolved in one place

**Files:**
- Modify: `scripts/04a_reformat.py:84, 712-731`
- Modify: `scripts/04b_atlas_match.py:64`, `scripts/04c_atlas_match.py:99`
- Modify: `scripts/04e_register_elastix.py:47-48`, `scripts/04k_level_curator.py:75-76`, `scripts/04l_roi_curator.py:727-728`
- Test: `tests/test_small_fixes.py` (it already has a "04k: plate set comes from config" section — extend it)

**Read the scope decision above before starting.** `04a_reformat` moves to the configured
set. `04b` and `04c` keep the extraction set, named explicitly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_small_fixes.py`, following its existing section style:

```python
print()
print("04a/04b/04c: the plate set is resolved, not hardcoded")
print()

with temp_study(atlas_plate_set={"dir": "plates_final"}) as study:
    RF = load_stage("04a_reformat.py")
    chk("04a reformats the set the study uses",
        os.path.basename(RF.PLATE_DIR), "plates_final")
    B = load_stage("04b_atlas_match.py")
    chk("04b keeps the set it was measured against",
        os.path.basename(B.PLATE_DIR), "plates")
    chk("...and says so rather than repeating a literal",
        "EXTRACTED" in open(os.path.join(REPO, "scripts", "04b_atlas_match.py"),
                            encoding="utf-8").read(), True)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_small_fixes.py 2>&1 | grep -A3 "plate set is resolved"
```

Expected: `FAIL 04a reformats the set the study uses  'plates'`.

- [ ] **Step 3: `04a_reformat`**

Replace `:84`:

```python
# The set the study CHOSE, not the raw extraction. 04a writes
# reformatted/plates/<plate_id>.png, and 04d:527 and 04e:405 read those images
# while taking plates.csv from the configured set. On this drive that join was
# wrong for every id: plates holds 47 merged figures and plates_final holds 64
# reframed plates, so 17 ids had no image at all (04e silently continue'd past
# them) and the other 47 resolved to a picture of a different plate.
PLATE_DIR = AT.plate_dir(CONFIG)
```

adding `import ls_atlas as AT` beside the other sibling imports.

Replace the `regions` read at `:730`. `plates_final/plates.csv` has **no** `regions`
column; `seeds.csv` does, with an identical header in every set:

```python
    # regions came from a plates.csv column that only the raw extraction set
    # has. seeds.csv carries the same information in every set, under an
    # identical header, so it is derived rather than required.
    regions_of = {}
    try:
        with open(os.path.join(PLATE_DIR, "seeds.csv"), newline="",
                  encoding="utf-8") as fh:
            for s in csv.DictReader(fh):
                regions_of.setdefault(s["plate_id"], []).append(s.get("region", ""))
    except OSError:
        pass
```

placed just before the plate loop, and in the row:

```python
        rows.append({"kind": "plate", "id": p["plate_id"], "angle": round(angle, 1),
                     "fill": round(float(mask.mean()), 4),
                     "regions": p.get("regions")
                                or ";".join(sorted(set(
                                    r for r in regions_of.get(p["plate_id"], []) if r)))})
```

- [ ] **Step 4: `04b` and `04c`**

`04b:64`:

```python
# THE EXTRACTION SET, deliberately - not the study's configured set.
#
# 04b is in app/stages.py NOT_LISTED as "measured to fail on this data
# (LOGS 2026-08-12); kept as evidence". Re-pointing it at plates_final would
# change the candidate universe from 47 figures to 64 plates and invalidate the
# measurement it exists to record. The literal is gone; the choice is not.
#
# KNOWN GAP: its atlas_proposals_v2.csv still feeds 04d's plate preview, which
# renders from the configured set. Not closed here - see the plan's scope note.
PLATE_DIR = AT.plate_dir(CONFIG, set_name=AT.EXTRACTED)
```

`04c:99` gets the same two-line version of that comment and the same call.

Leave `04c`'s `r["regions"]` read as it is — it reads the extraction set, which has the
column.

- [ ] **Step 5: The three that already read the config**

`04e:47-48`, `04k:75-76` and `04l:727-728` each carry their own copy of
`CONFIG.get("atlas_plate_set", {}).get("dir", "plates")`. Replace all three with:

```python
PLATE_SET = AT.set_name(CONFIG)
PLATE_DIR = AT.plate_dir(CONFIG)
```

- [ ] **Step 6: Record the 04e gap rather than leaving it to be rediscovered**

Add to `scripts/04e_register_elastix.py`, beside the `plate_path` line at `:405`:

```python
        # A plate id with no reformatted image is SKIPPED silently below. That
        # was masking a real mismatch until 2026-09-23: 04a built these images
        # from the hardcoded extraction set while plates.csv came from the
        # configured one, so 17 of 64 ids had no image and the other 47 pointed
        # at a different plate. Both now read the same set. Counted rather than
        # skipped in silence, so the next mismatch is visible.
```

and a counter printed at the end of the loop:

```python
    if skipped_plates:
        print(f"  !! {len(skipped_plates)} section(s) skipped: no reformatted plate "
              f"image for {sorted(set(skipped_plates))[:6]}")
```

- [ ] **Step 7: Verify, in process, that nothing else moved**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: `ALL PASS`. `04a_reformat.PLATE_DIR`, `04b.PLATE_DIR` and `04c.PLATE_DIR`
**will** appear as changed constants — that is this task. Every other constant must be
unchanged. Read the diff and confirm exactly those three moved.

- [ ] **Step 8: Run everything and commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh
```

Expected: `ALL SUITES PASS`.

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/04a_reformat.py scripts/04b_atlas_match.py scripts/04c_atlas_match.py scripts/04e_register_elastix.py scripts/04k_level_curator.py scripts/04l_roi_curator.py tests/test_small_fixes.py && git commit -m "One place decides which atlas plate set a stage reads

Three stages hardcoded atlas/plates while three read the configured set. That
is not cosmetic here: plates holds 47 merged figures, plates_final holds 64
reframed plates, and 17 of the 64 ids do not exist in plates at all.

04a_reformat moves to the configured set, because it builds the plate images
04d and 04e read while those two take plates.csv from the configured one - so
that join was wrong for every id. Its regions column comes from seeds.csv,
which has an identical header in every set, because plates_final has no such
column.

04b and 04c keep the extraction set, named rather than hardcoded: both are
NOT_LISTED as measured to fail, and re-pointing them would invalidate the
measurement they are kept for.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verification, for the whole plan

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh
```

70 suites (68 at `0eb38da`, plus `test_ls_atlas.py`, `test_roi_curator_plates.py` and
`plates.test.js`, minus none). `ALL SUITES PASS`.

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Zero changed constants except the three `PLATE_DIR`s from Task 8.

**The guarantees that matter, as tests rather than arguments:**

- `ls_atlas.plate_order` over the live 64-row `plates.csv` returns the **identical** order
  to today's string sort (Task 1 Step 5).
- `04l.plate_rows()` over the live atlas returns 64 plates, none missing (Task 5 Step 10).
- The operator's real Sep 7 export imports without raising, and every section comes back
  `by_index` or `unchecked` — never a false `ok` (Task 6 Step 7).
- `06a` and `06c` are untouched by this plan: `plate_id` is empty on all 1,236 rows of
  `roi_measurements.csv` and `05a` never writes it, so **an atlas swap moves no count and
  no density**. Confirm once, at the end:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import csv
rows = list(csv.DictReader(open(r'E:\LS-analysis\results\roi_measurements.csv', newline='', encoding='utf-8')))
print(len(rows), 'rows;', sum(1 for r in rows if (r.get('plate_id') or '').strip()), 'with a plate_id')
"
```

Expected: `1236 rows; 0 with a plate_id`.

---

## Risks

- **The operator's authoritative curation is not the file a migration would target.**
  `curation/ls_roi_curator_v1.json` is dated Sep 3, has 288 sections and **zero
  polygons**; the real work — 612 polygons over 138 sections — is in the browser's
  `localStorage` and in `E:\LS-analysis\reformatted\roi_regions_used_AF568.csv`. Task 5
  migrates in `initState`, which both the store and the seed pass through, so anything
  that loads is upgraded. **Export before changing the atlas** is the operating
  instruction and it is in the banner.

- **Every existing section will be marked on the first load after Task 5.** None of them
  carries a fingerprint. They restore as `by_index`, which is honest about what they are.
  The alternative — fingerprinting whatever is there on first sight and calling it
  verified — would launder exactly the 2026-09-06 failure into a green tick.

- **`verify`'s RESIZED test uses aspect ratio**, which cannot distinguish a rescale from
  a symmetric crop. That is why rescaled landmarks are flagged rather than accepted.

- **Task 8 changes 04a_reformat's output on this study**, because it currently reformats
  the wrong plate pictures. Nothing downstream of the section measurements reads them —
  04d shows them and 04e registers against them — but a `reformatted/plates/` rebuild is
  a real change and the operator should be told before it is run.

- **A temp study cannot be pointed at the fixture's set by config.** `ls_config.py:460`
  restricts `atlas_plate_set.dir` to `choices=["plates", "plates_merged", "plates_final"]`,
  so `temp_study(atlas_plate_set={"dir": "before"})` is refused at import of any stage.
  Task 3 worked around it correctly — name a valid set to satisfy validation, then pass the
  fixture directory straight to `plate_rows(before)` through the explicit override the
  function already has. **Tasks 5 and 7 will hit the same wall; use the same escape hatch.**

  Not a genericity bug, on inspection: those three names are produced by the pipeline's own
  atlas chain (`04a` → `plates`, `04a2` → `plates_merged`, `04a4` → `plates_final`), so a
  second lab running that chain gets the same three. It only bites a lab supplying a
  pre-built plate set under a name of their own, which is P2b/P2c's problem, not P2a's.

- **Not fixed here:** 04b's proposals still feed 04d's preview across a plate-set
  boundary (Task 8 Step 4 records it); `_reframe_proposals.json`; anything about
  ingesting a new atlas, which is P2b and P2c.
