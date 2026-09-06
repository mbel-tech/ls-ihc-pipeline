# Tier 3 Robustness and Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Tier 3 review items: one atomic-write helper behind every keyed CSV, workbook and mask output; empty-input guards where a first run or a partial run crashes on `rows[0]`, `lab[0]`, `raw.max()` or a blank cell; safe JSON embedding and attribute escaping in the four generated curator pages; quoted CSV exports; keyboard-modifier and form-control guards; a drag draft in the rotation curator instead of a localStorage write per pointermove; honest tri-state records in the rotation curator and no phantom records in the ROI curator; the exclusion list written after the review merge in 04a; non-destructive `--survey` and `--preview` modes; "unmeasured" kept distinct from "censored_out"; closed zip handles and a real middle pick; workbook columns resolved by name; a 12th plot shape; a refresh loop that parses versions and reads UTF-8; and a test build that never rewrites the operator's live curator pages.

**Architecture:** The pipeline is a chain of standalone scripts under `scripts/` that import each other by file path (`importlib.util.spec_from_file_location`), each with a module-level `CONFIG` read from `config.json` (or `LS_CONFIG`) and a `main()`. Four scripts (`04b`, `04d`, `04k`, `04l`) generate single-file HTML curators by substituting `__PLACEHOLDER__` tokens in a Python string with `json.dumps` output; the curator behaviour is vanilla JS inside those strings. Tests are `tests/test_*.py` (plain scripts, a `chk(label, got, want)` helper, exit code = failures) and `tests/*.test.js` (Node against a DOM stub in `tests/harness.js`, which `eval`s the JS lifted from a built page). `bash tests/run.sh` builds the pages and runs both families. New shared code goes in one new module, `scripts/ls_io.py`, imported by path like everything else.

**Tech Stack:** Python 3.13 (`work/appenv/Scripts/python.exe`), numpy, Pillow, openpyxl (06c/06d only), vanilla browser JS in Python string templates, Node 20+ for the JS suites, R 4.x for `analysis/`, bash for `tests/run.sh`, git.

---

Conventions used below:

- `PY` means `work/appenv/Scripts/python.exe` run from the repo root `C:/Users/marti/repos/ls-ihc-pipeline`.
- Line numbers are from the working tree on 2026-09-03 (which already carries the Tier 1 edits: `LS_CONFIG` resolver, `main()` per script). They will drift by a few lines as earlier tasks land; the quoted code is the anchor, the number is a hint.
- The path-import boilerplate every task uses for `ls_io.py` is:

```python
_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)
```

  Scripts that do not yet `import importlib.util` (04a, 04h, 04m) need that import added; the others already have it.

- Every Python test file starts with the same preamble as `tests/test_roi_geometry.py:21-45` (path-import the script under test, define `chk`, `fails`), and ends with:

```python
print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

---

### Task 1: `scripts/ls_io.py` - atomic CSV and file writes, moved out of 01k

**Files:**
- Create: `scripts/ls_io.py`
- Modify: `scripts/01k_saturation_raw.py:91-121` (delete `atomic_write`), `:59-62` (add the IO import after `OV`), `:294-295`, `:323`, `:328`
- Test: `tests/test_ls_io.py`

`scripts/01k_saturation_raw.py:91-121` already has the right idiom (tmp file, `os.replace`, five attempts with 1/2/4/8 s backoff). It has two limits: it returns silently on empty rows (`if not rows: return`, line 105), so an empty result leaves last run's file standing, and it is CSV-only, so the workbooks (06c/06d) and the PNG masks (01k:295) cannot use it.

- [x] **Step 1: Write the failing test** `tests/test_ls_io.py`

```python
"""ls_io: tmp-then-replace writes, with a retry.

Run:  python tests/test_ls_io.py
"""

import csv
import importlib.util
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

_spec = importlib.util.spec_from_file_location("lsio", os.path.join(SCRIPTS, "ls_io.py"))
IO = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(IO)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


tmp = tempfile.mkdtemp(prefix="lsio_")
real_replace, real_sleep = IO.os.replace, IO.time.sleep
try:
    p = os.path.join(tmp, "out.csv")
    IO.atomic_write_csv(p, [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}], ["a", "b"])
    chk("rows round-trip", read(p), [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}])
    chk("no .tmp left behind", os.path.exists(p + ".tmp"), False)

    IO.atomic_write_csv(p, [], ["a", "b"])
    with open(p, encoding="utf-8") as fh:
        chk("empty rows -> header only", fh.read(), "a,b\r\n")

    IO.atomic_write_csv(p, [{"a": 1, "b": 2, "extra": 3}], ["a", "b"])
    chk("extra keys are ignored", read(p), [{"a": "1", "b": "2"}])

    # A dropout: os.replace fails twice, then works. The old file must be intact
    # in between, and the retry must not sleep for real.
    IO.atomic_write_csv(p, [{"a": "old", "b": "old"}], ["a", "b"])
    calls, slept = {"n": 0}, []

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError("volume vanished")
        return real_replace(src, dst)

    IO.os.replace, IO.time.sleep = flaky, slept.append
    try:
        IO.atomic_write_csv(p, [{"a": "new", "b": "new"}], ["a", "b"])
    finally:
        IO.os.replace, IO.time.sleep = real_replace, real_sleep
    chk("retried until the replace went through", calls["n"], 3)
    chk("backoff doubled", slept, [1, 2])
    chk("the new content landed", read(p)[0]["a"], "new")

    # Exhausted attempts propagate, and the previous file is still there.
    IO.atomic_write_csv(p, [{"a": "keep", "b": "keep"}], ["a", "b"])

    def dead(src, dst):
        raise OSError("gone")

    IO.os.replace, IO.time.sleep = dead, lambda s: None
    raised = ""
    try:
        IO.atomic_write_csv(p, [{"a": "lost", "b": "lost"}], ["a", "b"], attempts=2)
    except OSError as exc:
        raised = str(exc)
    finally:
        IO.os.replace, IO.time.sleep = real_replace, real_sleep
    chk("exhausted attempts raise", raised, "gone")
    chk("...and the old file is untouched", read(p)[0]["a"], "keep")

    # atomic_save: a context that hands out the temp path.
    q = os.path.join(tmp, "blob.bin")
    with IO.atomic_save(q) as t:
        chk("temp path is beside the target", os.path.dirname(t), tmp)
        with open(t, "wb") as fh:
            fh.write(b"abc")
        chk("target absent until the block ends", os.path.exists(q), False)
    with open(q, "rb") as fh:
        chk("target written on exit", fh.read(), b"abc")
    chk("temp gone on exit", os.path.exists(t), False)

    boom = ""
    try:
        with IO.atomic_save(q) as t:
            with open(t, "wb") as fh:
                fh.write(b"partial")
            raise ValueError("writer died")
    except ValueError as exc:
        boom = str(exc)
    chk("an exception inside the block propagates", boom, "writer died")
    with open(q, "rb") as fh:
        chk("...and leaves the previous file alone", fh.read(), b"abc")
    chk("...and cleans the temp up", os.path.exists(t), False)
finally:
    IO.os.replace, IO.time.sleep = real_replace, real_sleep
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

- [x] **Step 2: Run it, expect the import to fail**

```
work/appenv/Scripts/python.exe tests/test_ls_io.py
```
Expected: `FileNotFoundError: ... scripts/ls_io.py` (traceback, exit 1).

- [x] **Step 3: Create `scripts/ls_io.py`**

```python
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
```

- [x] **Step 4: Run the test, expect all pass**

```
work/appenv/Scripts/python.exe tests/test_ls_io.py
```
Expected: 16 `ok` lines and `ALL PASS`.

- [x] **Step 5: Point 01k at it**

In `scripts/01k_saturation_raw.py`:

1. After the `OV` import block (line 59-62) add the IO boilerplate from the conventions above.
2. Delete `def atomic_write(...)` (lines 91-121, including its docstring).
3. Replace both `atomic_write(OUT_CSV, rows, KEYS)` (lines 323 and 328) with `IO.atomic_write_csv(OUT_CSV, rows, KEYS)`.
4. Replace lines 294-295

```python
                        mask_path = os.path.join(MASK_DIR, uid + "_clipped.png")
                        Image.fromarray((m["mask"] * 255).astype(np.uint8)).save(mask_path)
```
with
```python
                        mask_path = os.path.join(MASK_DIR, uid + "_clipped.png")
                        with IO.atomic_save(mask_path) as tmp:
                            Image.fromarray((m["mask"] * 255).astype(np.uint8)).save(tmp, format="PNG")
```

`import time` stays: `t0 = time.time()` still uses it.

- [x] **Step 6: Verify 01k still compiles and no longer defines the helper**

```
work/appenv/Scripts/python.exe -m py_compile scripts/01k_saturation_raw.py && grep -c "def atomic_write" scripts/01k_saturation_raw.py
```
Expected: compile succeeds, grep prints `0`.

- [x] **Step 7: Commit**

```
git add scripts/ls_io.py scripts/01k_saturation_raw.py tests/test_ls_io.py
git commit -m "ls_io: shared tmp-then-replace writer, lifted out of 01k

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Every keyed output goes through `ls_io`

**Files:**
- Modify: `scripts/04a_reformat.py:716-719`, `scripts/04j_censor_clipped.py:208-211`, `scripts/04g_artifact_mask.py:366-369`, `scripts/04f_exclusion_candidates.py:253-256`, `scripts/04h_symmetry_axis.py:258-261`, `scripts/04i_propagate_to_perk.py:255-258`, `scripts/04m_sections_dataset.py:170-173`, `scripts/04p_section_provenance.py:379-382`, `scripts/05a_roi_geometry.py:768-772`, `scripts/06a_roi_dataset.py:272-275`, `scripts/06c_excel_dataset.py:127`
- Test: `tests/test_atomic_adoption.py`

Each of these currently opens the final path with `"w"` and writes into it directly, so a crash or a drive dropout mid-write leaves a truncated file under the name the next stage reads. 06c's `write_workbook()` (`06c:99-127`) is shared with 06d, so one change covers both workbooks. The test is a source scan: the scripts need the imaging data to run end-to-end, and what has to hold is simply that the in-place `open(..., "w")` at each site is gone and the helper is called.

- [x] **Step 1: Write the failing test** `tests/test_atomic_adoption.py`

```python
"""Every keyed output is written through ls_io, never in place.

A source scan, because these scripts need the imaging data to run. What has to
hold is that the in-place `open(path, "w")` at each output site is gone and
the atomic helper is called for that path.

Run:  python tests/test_atomic_adoption.py
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


# script -> (fragment that must be GONE, fragment that must be PRESENT)
SITES = {
    "04a_reformat.py": ('with open(out_csv, "w"', "IO.atomic_write_csv(out_csv, rows, keys)"),
    "04j_censor_clipped.py": ('with open(out_csv, "w"', "IO.atomic_write_csv(out_csv, rows, ANALYSIS_KEYS)"),
    "04g_artifact_mask.py": ('with open(out, "w"', "IO.atomic_write_csv(out, rows, SUMMARY_KEYS)"),
    "04f_exclusion_candidates.py": ('with open(out, "w"', "IO.atomic_write_csv(out, "),
    "04h_symmetry_axis.py": ('with open(OUT_CSV, "w"', "IO.atomic_write_csv(OUT_CSV, out, SYM_KEYS)"),
    "04i_propagate_to_perk.py": ('with open(OUT_CSV, "w"', "IO.atomic_write_csv(OUT_CSV, rows, OVERRIDE_KEYS)"),
    "04m_sections_dataset.py": ('with open(OUT_CSV, "w"', "IO.atomic_write_csv(OUT_CSV, rows, COLUMNS)"),
    "04p_section_provenance.py": ('with open(OUT_CSV, "w"', "IO.atomic_write_csv(OUT_CSV, rows, COLUMNS)"),
    "05a_roi_geometry.py": ('with open(path, "w", newline="", encoding="utf-8") as fh:\n            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))',
                            "IO.atomic_write_csv(path, rows, list(rows[0].keys()))"),
    "06a_roi_dataset.py": ('with open(path, "w", newline="", encoding="utf-8") as fh:\n            w = csv.DictWriter(fh, fieldnames=list(data[0].keys()))',
                           "IO.atomic_write_csv(path, data, list(data[0].keys()))"),
    "06c_excel_dataset.py": ("    wb.save(path)", "with IO.atomic_save(path) as tmp:\n        wb.save(tmp)"),
    "01k_saturation_raw.py": (".save(mask_path)", "with IO.atomic_save(mask_path) as tmp:"),
}

for name, (gone, present) in SITES.items():
    with open(os.path.join(SCRIPTS, name), encoding="utf-8") as fh:
        src = fh.read()
    chk(f"{name}: in-place write gone", gone in src, False)
    chk(f"{name}: atomic write present", present in src, True)
    chk(f"{name}: imports ls_io", '"ls_io.py"' in src, True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

- [x] **Step 2: Run it, expect 22 FAILs (01k's three lines already pass from Task 1)**

```
work/appenv/Scripts/python.exe tests/test_atomic_adoption.py
```

- [x] **Step 3: Make the edits**

Add the IO import boilerplate (conventions above) near the other path-imports in each file; `04a`, `04h` and `04m` also need `import importlib.util` added to their import block. Then, per site:

**`04a_reformat.py:716-719`** - replace
```python
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
```
with
```python
    IO.atomic_write_csv(out_csv, rows, keys)
```

**`04j_censor_clipped.py`** - add after `TOLERANCE = 0.01` (line 121):
```python
ANALYSIS_KEYS = ["scene_uid", "animal", "section_order", "censored_fraction",
                 "censored_fraction_in_tissue", "recorded_saturated_fraction",
                 "recorded_saturated_fraction_raw", "in_analysis_set", "reason"]
```
and replace lines 208-211 with `IO.atomic_write_csv(out_csv, rows, ANALYSIS_KEYS)`.

**`04g_artifact_mask.py`** - add after `MASK_DIR = ...` (line 83):
```python
SUMMARY_KEYS = ["scene_uid", "animal", "section_order", "excluded", "tissue_mm2",
                "n_compact", "n_elongated", "compact_mm2", "elongated_mm2",
                "artifact_mm2", "artifact_pct_of_tissue", "measurable_mm2",
                "saturated_fraction"]
```
and replace lines 366-369 with `IO.atomic_write_csv(out, rows, SUMMARY_KEYS)`.

**`04f_exclusion_candidates.py:253-256`** - replace with
```python
    IO.atomic_write_csv(out, sorted(rows, key=lambda r: (-r["proposed"], r["animal"], r["section_order"])), keys)
```

**`04h_symmetry_axis.py`** - add after `OUT_CSV = ...` (line 88):
```python
SYM_KEYS = ["scene_uid", "animal", "section_order", "proposed_rotation",
            "sym_score", "margin", "confidence"]
```
and replace lines 258-261 with `IO.atomic_write_csv(OUT_CSV, out, SYM_KEYS)`.

**`04i_propagate_to_perk.py`** - add after `OUT_CSV = ...` (line 61):
```python
OVERRIDE_KEYS = ["perk_scene_uid", "pcna_scene_uid", "animal", "extra_rotation", "flip",
                 "excluded", "align_iou", "flip_margin", "confidence", "reason"]
```
(both `rows.append` sites, lines 203-207 and 248-254, build exactly these ten keys) and replace lines 255-258 with `IO.atomic_write_csv(OUT_CSV, rows, OVERRIDE_KEYS)`.

**`04m_sections_dataset.py:170-173`** - replace with `IO.atomic_write_csv(OUT_CSV, rows, COLUMNS)`.

**`04p_section_provenance.py:379-382`** - replace with `IO.atomic_write_csv(OUT_CSV, rows, COLUMNS)` (keep the `os.makedirs(REFORMAT_DIR, exist_ok=True)` above it).

**`05a_roi_geometry.py:768-772`** - replace with
```python
    for path, rows in ((geom_csv(marker), geom), (box_csv(marker), boxes)):
        IO.atomic_write_csv(path, rows, list(rows[0].keys()))
```
(`geom` is guarded non-empty by the `if not geom: return 1` at line 759; `boxes` is built from `geom`.)

**`06a_roi_dataset.py:272-275`** - replace with
```python
        IO.atomic_write_csv(path, data, list(data[0].keys()))
```
(the `if not data:` branch above it, which removes a stale file, stays).

**`06c_excel_dataset.py:127`** - replace `    wb.save(path)` with
```python
    with IO.atomic_save(path) as tmp:
        wb.save(tmp)
```

- [x] **Step 4: Run the scan and the existing Python suites**

```
work/appenv/Scripts/python.exe tests/test_atomic_adoption.py
for t in tests/test_*.py; do work/appenv/Scripts/python.exe "$t" > /dev/null || echo "FAIL $t"; done
```
Expected: `ALL PASS` from the scan; no `FAIL` lines (the import chains 04j->04a, 06d->06c->06b->05a->04a etc. all still load).

- [x] **Step 5: Commit**

```
git add scripts/04a_reformat.py scripts/04j_censor_clipped.py scripts/04g_artifact_mask.py scripts/04f_exclusion_candidates.py scripts/04h_symmetry_axis.py scripts/04i_propagate_to_perk.py scripts/04m_sections_dataset.py scripts/04p_section_provenance.py scripts/05a_roi_geometry.py scripts/06a_roi_dataset.py scripts/06c_excel_dataset.py tests/test_atomic_adoption.py
git commit -m "Keyed outputs are written tmp-then-replace through ls_io

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `embed()` / `fill()` - one-pass, escaped JSON into the curator pages

**Files:**
- Modify: `scripts/ls_io.py` (add `embed`, `fill`), `scripts/04l_roi_curator.py:3779-3787`, `scripts/04d_rotation_curator.py:494-497`, `scripts/04k_level_curator.py:329-330`, `scripts/04b_atlas_match.py:316`
- Test: `tests/test_embed.py`

All four generators do `PAGE.replace("__X__", json.dumps(x)).replace("__Y__", json.dumps(y))...`. Two defects: `json.dumps` does not escape `</script>` or `<!--`, so a section reason or a region label containing either would end the script block; and chained `.replace` re-scans the JSON just inserted, so a value containing a later placeholder's name would be substituted too. One helper, one pass.

- [x] **Step 1: Write the failing test** `tests/test_embed.py`

```python
"""JSON embedded in a <script> block: escaped, and substituted in one pass.

Run:  python tests/test_embed.py
"""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

_spec = importlib.util.spec_from_file_location("lsio", os.path.join(SCRIPTS, "ls_io.py"))
IO = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(IO)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


chk("plain values are plain JSON", IO.embed({"a": 1, "b": [True, None]}), '{"a": 1, "b": [true, null]}')
chk("a closing tag cannot end the block", IO.embed("x</script>y"), '"x<\\/script>y"')
chk("a comment opener is neutralised", IO.embed("<!-- z"), '"<\\!-- z"')
chk("other slashes are left alone", IO.embed("a/b"), '"a/b"')
chk("an int embeds as itself", IO.embed(170), "170")

page = IO.fill("<script>const A = __A__; const B = __B__; const N = __N__;</script>",
               {"__A__": {"s": "</script><!--"}, "__B__": ["__A__", "__N__"], "__N__": 7})
chk("the closing tag is escaped in place", "</script><!--" in page, False)
chk("placeholders inside a VALUE are not substituted", '["__A__", "__N__"]' in page, True)
chk("every placeholder is filled", "__N__;" in page, False)
chk("the number lands", "const N = 7;" in page, True)

# A placeholder the template does not carry is a programming error, not a no-op.
boom = ""
try:
    IO.fill("<script>__A__</script>", {"__A__": 1, "__ZZ__": 2})
except KeyError as exc:
    boom = str(exc)
chk("an unused placeholder raises", "__ZZ__" in boom, True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

- [x] **Step 2: Run it, expect `AttributeError: module 'lsio' has no attribute 'embed'`**

```
work/appenv/Scripts/python.exe tests/test_embed.py
```

- [x] **Step 3: Add to `scripts/ls_io.py`** (add `import json` and `import re` to its imports)

```python
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
```

- [x] **Step 4: Run the test, expect `ALL PASS`**

- [x] **Step 5: Use it in the four generators** (each gets the IO import boilerplate; 04b, 04d, 04k, 04l all already have `import os`; 04b/04d/04k need `import importlib.util` added; 04l has no `importlib` import either - add it)

`04l_roi_curator.py:3779-3787` - replace the `page = (PAGE.replace(...)...)` chain with
```python
    page = IO.fill(PAGE, {
        "__SEED__": seed, "__PROV__": load_provenance(), "__DATA__": data,
        "__PLATES__": pl, "__PLATESET__": PLATE_SET, "__MARKERS__": markers,
        "__MARKER__": args.marker, "__SECGRID__": SEC_GRID, "__GROUPS__": GROUPS})
```

`04d_rotation_curator.py:494-497` - replace with
```python
    page = IO.fill(PAGE, {"__DATA__": data, "__AUTO__": auto, "__SYM__": sym,
                          "__THUMB__": args.thumb})
```
(`__THUMB__` was `str(args.thumb)`; `embed(170)` is `170`, the same text.)

`04k_level_curator.py:329-330` - replace with
```python
    page = IO.fill(PAGE, {"__DATA__": data, "__PLATES__": pl})
```

`04b_atlas_match.py:316` - replace with
```python
    page = IO.fill(TEMPLATE, {"__DATA__": ordered})
```

- [x] **Step 6: Regenerate one page and check the placeholders are gone**

```
work/appenv/Scripts/python.exe scripts/04k_level_curator.py > /dev/null && grep -c "__DATA__\|__PLATES__" "$(work/appenv/Scripts/python.exe -c "import json;print(json.load(open('config.json'))['out_root'])")/reformatted/level_curator.html"
```
Expected: `0`.

- [x] **Step 7: Commit**

```
git add scripts/ls_io.py scripts/04l_roi_curator.py scripts/04d_rotation_curator.py scripts/04k_level_curator.py scripts/04b_atlas_match.py tests/test_embed.py
git commit -m "Curator pages embed JSON through one escaped, single-pass fill()

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Test build hygiene - `--out`, `tests/build/`, page-aware harness, invariant assertions, two new suites

**Files:**
- Modify: `scripts/04l_roi_curator.py:3610-3619` (add `--out`), `:3788-3792`; `scripts/04d_rotation_curator.py:418-425`, `:498-502`; `scripts/04k_level_curator.py:306-310`, `:331-335`; `tests/run.sh` (rewrite); `tests/harness.js:43-45`, `:153-158`; `tests/channels.test.js:19-23`; `tests/guided.test.js:42-47`; `tests/shotgun.test.js:30-70`, `:120-128`, `:195`, `:249-250`, `:293-296`
- Create: `tests/rotation_curator.test.js`, `tests/level_curator.test.js`

`tests/run.sh:35` regenerates `<out_root>/reformatted/roi_curator.html` with `--no-seed` and line 68 regenerates it again with the seed - the file the operator is curating in is rewritten twice per test run, and a crash between the two leaves it seedless. `tests/harness.js:45` hard-codes `build/curator.js`, so only 04l can be tested. `channels.test.js:19-20` asserts 454/788 rows, `:23` asserts every row has a composite, `guided.test.js:43,47` assert 8 and 42 seeds, and `shotgun.test.js` names six animals and plate indices 9/12 - all facts about the operator's data, not about the code.

- [x] **Step 1: Add `--out` to the three generators**

`04l_roi_curator.py` - after the `--rgb` argument (line 3615-3618) add
```python
    ap.add_argument("--out", default=CURATOR_HTML, metavar="HTML",
                    help="where to write the page (default: the live curator under "
                         "out_root). tests/run.sh points this at tests/build/ so a "
                         "test run never rewrites the page being curated in")
```
and change line 3788 `with open(CURATOR_HTML, "w", encoding="utf-8") as fh:` to `with open(args.out, "w", encoding="utf-8") as fh:`, line 3792 `print(f"wrote {CURATOR_HTML}")` to `print(f"wrote {args.out}")`.

`04d_rotation_curator.py` - after `--thumb` (line 423-424) add the same `--out` argument (default `CURATOR_HTML`); change line 498 to `with open(args.out, ...)` and line 502 to `print(f"wrote {args.out}")`.

`04k_level_curator.py` - after `--animal` (line 308) add the same `--out`; change line 331 to `args.out` and line 335 to `print(f"wrote {args.out}")`.

- [x] **Step 2: Rewrite `tests/run.sh`**

```bash
#!/usr/bin/env bash
# Run the curator suites and the Python suites.
#
#   bash tests/run.sh
#
# The curators are generated pages, so there is a build step: each page is
# regenerated INTO tests/build/ with --out, its <script> is lifted out, and the
# suites run against that. The operator's live pages under out_root are never
# touched, so a test run cannot rewrite or downgrade a file someone is curating
# in.
#
# --no-seed matters for the ROI curator. The page normally embeds whatever
# curation is in out_root/curation; a suite reading that would start with
# hundreds of sections it knows nothing about, and its counts would change every
# time someone curated. --no-proposals does the same for the rotation curator.
# Tests must not depend on the operator's data.
#
# What these cover: state, ordering and what reaches the exports. What they do
# not: anything visual. Canvas calls are swallowed by the stub, so rendering is
# checked in a real browser instead.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TESTS="$REPO/tests"
BUILD="$TESTS/build"

# Prefer the app venv, since that is the interpreter the pipeline is built on.
PY="${PY:-$REPO/work/appenv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"

mkdir -p "$BUILD"

# build_page <script> <name> [args...]: generate scripts/<script> to
# tests/build/<name>.html and lift its largest <script> block to <name>.js.
build_page () {
  local script="$1" name="$2"; shift 2
  echo "building $name..."
  "$PY" "$REPO/scripts/$script" "$@" --out "$BUILD/$name.html" > /dev/null || {
    echo "could not generate $name"; exit 2; }
  "$PY" - "$BUILD/$name.html" "$BUILD/$name.js" <<'PYEOF' || exit 2
import io, re, sys
html = io.open(sys.argv[1], encoding="utf-8").read()
js = max(re.findall(r"<script>(.*?)</script>", html, re.S), key=len)
io.open(sys.argv[2], "w", encoding="utf-8", newline="").write(js)
print(f"  {len(js)} chars -> {sys.argv[2]}")
PYEOF
}

build_page 04l_roi_curator.py curator --marker AF568 --worklist --rgb --no-seed
build_page 04d_rotation_curator.py rotation_curator --no-proposals
build_page 04k_level_curator.py level_curator

fail=0
for t in "$TESTS"/*.test.js; do
  echo
  echo "=== $(basename "$t") ==="
  node "$t" || fail=1
done

# The Python suites run alongside rather than inside the Node harness: they
# exercise the scripts directly and have no browser stub to share.
for t in "$TESTS"/test_*.py; do
  [ -e "$t" ] || continue
  echo
  echo "=== $(basename "$t") ==="
  "$PY" "$t" || fail=1
done

echo
if [ "$fail" -eq 0 ]; then echo "ALL SUITES PASS"; else echo "SUITE FAILURES"; fi
exit "$fail"
```

- [x] **Step 3: Make the harness page-aware** - in `tests/harness.js` replace lines 43-45

```js
// Written by tests/run.sh, which regenerates the page with --no-seed and lifts
// out its <script>. Not committed: it is a build product of a generated file.
const CURATOR_JS = path.join(__dirname, "build", "curator.js");
```
with
```js
// Written by tests/run.sh, which regenerates each page into tests/build/ and
// lifts out its <script>. Not committed: build products of generated files.
//   curator.js           04l_roi_curator.py   (--no-seed)
//   rotation_curator.js  04d_rotation_curator.py (--no-proposals)
//   level_curator.js     04k_level_curator.py
const builtJs = page => path.join(__dirname, "build", page + ".js");
const CURATOR_JS = builtJs("curator");
```
and replace lines 153-158
```js
function load(exportExpr) {
  if (!fs.existsSync(CURATOR_JS)) {
    console.error(`missing ${CURATOR_JS}\nRun tests/run.sh, which extracts it.`);
    process.exit(2);
  }
  let js = fs.readFileSync(CURATOR_JS, "utf8");
```
with
```js
function load(exportExpr, page = "curator") {
  const file = builtJs(page);
  if (!fs.existsSync(file)) {
    console.error(`missing ${file}\nRun tests/run.sh, which builds it.`);
    process.exit(2);
  }
  let js = fs.readFileSync(file, "utf8");
```

- [x] **Step 4: Replace the data-dependent assertions**

`tests/channels.test.js:19-23` - replace
```js
chk("pERK rows", perk.length, 454);
chk("PCNA rows", pcna.length, 788);
chk("no uid collides across channels",
    new Set(X.DATA.map(d=>d.uid)).size, X.DATA.length);
chk("every row has a composite", X.DATA.filter(d=>d.rgb).length, X.DATA.length);
```
with
```js
chk("pERK side is populated", perk.length > 0, true);
chk("PCNA side is populated", pcna.length > 0, true);
chk("no uid collides across channels",
    new Set(X.DATA.map(d=>d.uid)).size, X.DATA.length);
chk("rgb is a per-row flag", X.DATA.every(d=>typeof d.rgb==="boolean"), true);
chk("...and the image path follows it",
    X.DATA.every(d=>d.img.includes("_rgb/")===d.rgb), true);
```

`tests/guided.test.js:42-47` - replace
```js
chk("the atlas's own uncertain seeds are flagged",
    allSeeds.filter(sd=>sd.unk).length, 8);
chk("...and all of them are Rm",
    [...new Set(allSeeds.filter(sd=>sd.unk).map(sd=>sd.region))].join(), "Rm");
chk("the Vd/Vv/POA group is flagged separately",
    allSeeds.filter(sd=>sd.amb).length, 42);
```
with
```js
chk("unk is a 0/1 flag on every seed", allSeeds.every(sd=>sd.unk===0||sd.unk===1), true);
chk("every uncertain seed is Rm - the only region the atlas marks '??'",
    allSeeds.filter(sd=>sd.unk).every(sd=>sd.region==="Rm"), true);
chk("amb is set exactly on the Vd/Vv/POA group",
    allSeeds.every(sd=>!!sd.amb===["Vd","Vv","POA"].includes(sd.region)), true);
```

`tests/shotgun.test.js` - replace lines 30-70 (from `const perk = ...` to `const ungrouped = ...`) with
```js
const perk = X.DATA.filter(d => d.m === "AF568");
const pcna = X.DATA.filter(d => d.m === "AF488");
const byAnimal = a => perk.filter(d => d.animal === a);

// The fixture needs six animals: one control with twelve sections (the
// overflow), one control with a PCNA section, one control with two sections,
// two exercise animals, and one outside the key. They are picked from whatever
// the page carries rather than named, so the suite does not depend on which
// animals were scanned.
const A = [...new Set(perk.map(d => d.animal))].sort((a, b) => +a.slice(2) - +b.slice(2));
const CTRL_BIG = A.find(a => byAnimal(a).length >= 12);
const rest = A.filter(a => a !== CTRL_BIG && byAnimal(a).length >= 2 && pcna.some(d => d.animal === a));
chk("an animal with twelve pERK sections exists", !!CTRL_BIG, true);
chk("five more animals with two sections and a PCNA side", rest.length >= 5, true);
const [CTRL_A, CTRL_C, EX_A, EX_B, OUT] = rest;
// Two distinct plates are all the layout needs; which two does not matter.
const PA = 0, PB = Math.min(3, X.PLATES.length - 1);
chk("the page carries at least two plates", PA < PB, true);

// GROUPS is a const in the page, so it is emptied and refilled rather than
// replaced. CLEARED FIRST, for the same reason S is above: the page embeds
// whatever groups.by_animal config.json holds, and config.json is gitignored -
// it differs per machine and changes the day somebody fills in the real
// unblinding key.
X.GROUPS.order.length = 0;
for (const k of Object.keys(X.GROUPS.by_animal)) delete X.GROUPS.by_animal[k];
X.GROUPS.order.push("control", "exercise");
Object.assign(X.GROUPS.by_animal, {
  [CTRL_A]: "control", [CTRL_BIG]: "control", [CTRL_C]: "control",
  [EX_A]: "exercise", [EX_B]: "exercise",
});

const fav = (d, plate, extra) => {
  const s = X.st(d.uid);
  s.fav = true; s.plate = plate; s.assigned = true;
  Object.assign(s, extra || {});
  return d;
};

// plate PA: one section per treatment, the simplest slide there is.
const a9 = fav(byAnimal(CTRL_A)[0], PA);
const b9 = fav(byAnimal(EX_A)[0], PA);
// plate PB: twelve control sections, so one half overflows and the other does not.
const twelve = byAnimal(CTRL_BIG).slice(0, 12);
twelve.forEach(d => fav(d, PB));
fav(byAnimal(EX_B)[0], PB);
// plate PA again, other channel: a separate slide, never mixed in with the pERK one.
const pcna9 = fav(pcna.filter(d => d.animal === CTRL_A)[0], PA);
// the ones that must NOT come through
const noPlate = X.st(byAnimal(CTRL_C)[0].uid);   noPlate.fav = true;
const dropped = fav(byAnimal(CTRL_C)[1], PA, {excl: true});
const ungrouped = fav(byAnimal(OUT)[0], PA);     // animal not in the key
```
then:
- line 120 `chk("plate 9 pERK, plate 9 PCNA, plate 12 over two pages", slides.length, 4);` keep the count, rename label to `"plate A pERK, plate A PCNA, plate B over two pages"`;
- lines 121-123: replace `"9AF568 9AF488 12AF568 12AF568"` with `` `${PA}AF568 ${PA}AF488 ${PB}AF568 ${PB}AF568` ``;
- line 128: replace `"LS22"` with `CTRL_A`;
- line 195: `X.PLATES[9].id` -> `X.PLATES[PA].id`;
- lines 249-250: `X.PLATES[9].seeds` -> `X.PLATES[PA].seeds`, `X.PLATES[12].seeds` -> `X.PLATES[PB].seeds`;
- line 258: `X.secRegions({plate: 9, pairs: ...})` -> `{plate: PA, ...}`;
- lines 293 and 296: `X.PLATES[9]` -> `X.PLATES[PA]`.

- [x] **Step 5: Create the two new suites** (smoke level now; Tasks 5, 7, 8, 9 extend them)

`tests/rotation_curator.test.js`
```js
// 04d rotation curator: the record per section, what a proposal is, and the
// export. Built with --no-proposals, so AUTO and SYM start empty and each
// test injects what it needs.

const { env, load, chk, note, done } = require("./harness");
const { els, store, blobs, fire } = env;

const X = load(`{KEY, DATA, AUTO, SYM, state, get, setState, toggleExclude, isExcluded,
  isAuto, isSymAuto, symOf, exportCsv, render, counts, paint, onDown, onMove, onUp,
  get drag(){return drag}, set active(v){active=v}, get active(){return active}}`,
  "rotation_curator");

els["animal"].value = "";                 // all animals
chk("the page carries sections", X.DATA.length > 0, true);
chk("no proposals were embedded", Object.keys(X.AUTO).length + Object.keys(X.SYM).length, 0);
const disk = u => JSON.parse(store[X.KEY] || "{}")[u];

const u = X.DATA[0].uid;
chk("untouched: rotation 0, not excluded", X.get(u).r + "/" + X.isExcluded(u), "0/false");
X.setState(u, 45, false);
chk("a rotation is stored", X.state[u].r, 45);
chk("...and written to storage", disk(u).r, 45);
X.setState(u, 0, false);
chk("back to 0 with no proposal drops the record", u in X.state, false);

blobs.length = 0; X.exportCsv();
chk("nothing to export -> only the header line", blobs[0].split("\n").length, 1);
chk("export header", blobs[0].split("\n")[0],
    "scene_uid,extra_rotation,flip,excluded,rotation_source,decision,reason");

done();
```

`tests/level_curator.test.js`
```js
// 04k level curator: anchors, the interpolation between them, and the export.

const { env, load, chk, note, done } = require("./harness");
const { els, store, blobs, fire } = env;

const X = load(`{KEY, DATA, PLATES, anchors, rows, assign, render, select, setAnchor,
  dropAnchor, showPlate, exportCsv, set active(v){active=v}, get active(){return active}}`,
  "level_curator");

els["animal"].value = X.DATA[0].animal;
const list = X.rows();
chk("the animal has sections", list.length >= 3, true);
chk("plates are loaded", X.PLATES.length >= 2, true);

chk("no anchors -> nothing assigned", X.assign(list).every(a => a.plate === null), true);
X.render();
chk("render selects the first section", X.active, list[0].uid);

X.active = list[0].uid; els["slider"].value = 0; X.setAnchor();
X.active = list[list.length - 1].uid; els["slider"].value = 1; X.setAnchor();
const asg = X.assign(list);
chk("two anchors", asg.filter(a => a.kind === "anchor").length, 2);
chk("everything between is interpolated", asg.slice(1, -1).every(a => a.kind === "interp"), true);
chk("anchors persist", Object.keys(JSON.parse(store[X.KEY])).length, 2);

blobs.length = 0; X.exportCsv();
const lines = blobs[0].split("\n");
chk("export header", lines[0], "scene_uid,animal,section_order,plate_id,plate_index,source,regions");
chk("one row per section of the anchored animal", lines.length - 1, list.length);

done();
```

- [x] **Step 6: Run the whole build and note the live page is untouched**

```
LIVE="$(work/appenv/Scripts/python.exe -c "import json;print(json.load(open('config.json'))['out_root'])")/reformatted/roi_curator.html"
stat -c %Y "$LIVE"; bash tests/run.sh; stat -c %Y "$LIVE"; ls tests/build
```
Expected: `ALL SUITES PASS`; the two `stat` values are identical; `tests/build` lists `curator.html curator.js rotation_curator.html rotation_curator.js level_curator.html level_curator.js` (plus `shotgun.pptx`).

- [x] **Step 7: Commit**

```
git add scripts/04l_roi_curator.py scripts/04d_rotation_curator.py scripts/04k_level_curator.py tests/run.sh tests/harness.js tests/channels.test.js tests/guided.test.js tests/shotgun.test.js tests/rotation_curator.test.js tests/level_curator.test.js
git commit -m "tests: build every curator into tests/build with --out; data-free assertions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Curator pages - escape attribute values, replace inline `onclick` with delegated listeners

**Files:**
- Modify: `scripts/04l_roi_curator.py:2067-2070` (strip cell), `:3201-3202` (review cell), `:926-927` (register the two listeners); `scripts/04d_rotation_curator.py:354`, `:359-367` (render), `:172` (add `esc`); `scripts/04k_level_curator.py:214-215`, `:247-249`, `:165` (add `esc` and the listener); `scripts/04b_atlas_match.py:401-402`, `:386` (add `esc` and the listener)
- Test: `tests/rotation_curator.test.js`, `tests/level_curator.test.js`, `tests/channels.test.js` (append)

`04d:354` puts `AUTO[d.uid].reason` (free text from `exclusion_candidates.csv`) straight into a `title="..."` attribute and into `innerHTML`; `04k:247-249` puts `p.regions` into `innerHTML`; `04b:404` puts `c.regions` into `innerHTML`. `04l:2069`, `04l:3202`, `04k:215` and `04b:402` build `onclick="select('${uid}')"` strings - a uid or plate id containing a quote breaks out of the handler. `04l` already has `esc()` at `:3088`; the review grid at `:3201-3204` uses it for `title` but still emits `onclick`.

- [x] **Step 1: Write the failing tests**

Append to `tests/rotation_curator.test.js` before `done();`:
```js
// ---- attribute escaping ---------------------------------------------------
note("");
X.AUTO[u] = {reason: 'no tissue" onmouseover="alert(1)', mm2: 1};
X.render();
chk("a reason cannot break out of the title attribute",
    els["wall"].innerHTML.includes('onmouseover="alert'), false);
chk("...it is entity-escaped", els["wall"].innerHTML.includes("&quot; onmouseover=&quot;"), true);
delete X.AUTO[u];
```
Append to `tests/level_curator.test.js` before `done();`:
```js
// ---- escaping and delegated clicks ---------------------------------------
note("");
X.render();
chk("the strip carries no inline handlers", els["strip"].innerHTML.includes("onclick="), false);
chk("...cells are addressed by data-uid", els["strip"].innerHTML.includes(`data-uid="${list[0].uid}"`), true);
X.PLATES[0].regions = "Dm|<b>x</b>";
X.showPlate(0);
chk("region labels are escaped before the pipe becomes a dot",
    els["plateRegions"].innerHTML, "Dm &middot; &lt;b&gt;x&lt;/b&gt;");
```
Append to `tests/channels.test.js` before `done();`:
```js
// ---- no inline handlers on the strip ---------------------------------------
X.render();
chk("strip cells carry data-uid, not onclick", els["strip"].innerHTML.includes("onclick="), false);
```

- [x] **Step 2: Run them, expect the new lines to FAIL**

```
bash tests/run.sh 2>&1 | grep -E "^FAIL|SUITE"
```
Expected: `FAIL a reason cannot break out...`, `FAIL the strip carries no inline handlers`, `FAIL region labels are escaped...`, `FAIL strip cells carry data-uid...`, `SUITE FAILURES`.

- [x] **Step 3: 04l** - replace lines 2067-2070
```js
  el("strip").innerHTML = list.map(d=>
    `<div class="cell ${cellClass(d.uid)} ${active===d.uid?"active":""}"
      data-uid="${d.uid}" onclick="select('${d.uid}')">
```
with
```js
  el("strip").innerHTML = list.map(d=>
    `<div class="cell ${cellClass(d.uid)} ${active===d.uid?"active":""}"
      data-uid="${esc(d.uid)}">
```
Replace lines 3201-3202
```js
  return `<div class="${cls.join(" ")}" data-uid="${p.scene_uid}" `
       + `onclick="revPick('${p.scene_uid}')" `
```
with
```js
  return `<div class="${cls.join(" ")}" data-uid="${esc(p.scene_uid)}" `
```
`esc` is a `const` defined at line 3088, after `render()`'s definition but before any call - both uses run at call time, so the order is fine. After line 927 (`el("marker").value = DEFAULT_MARKER;`) add
```js
// One listener per container instead of an onclick string per cell: the uid
// never has to survive being pasted into a JS string literal.
el("strip").addEventListener("click", e => {
  const c = e.target.closest && e.target.closest(".cell"); if(c) select(c.dataset.uid);
});
el("revGrid").addEventListener("click", e => {
  const c = e.target.closest && e.target.closest(".rc"); if(c) revPick(c.dataset.uid);
});
```

- [x] **Step 4: 04d** - after `const el = id => document.getElementById(id);` (line 172) add
```js
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
```
Replace line 354
```js
        ${AUTO[d.uid] ? `<div class="why" title="${AUTO[d.uid].reason}">${AUTO[d.uid].reason}</div>` : ""}
```
with
```js
        ${AUTO[d.uid] ? `<div class="why" title="${esc(AUTO[d.uid].reason)}">${esc(AUTO[d.uid].reason)}</div>` : ""}
```
and in `render()` make the per-cell wiring tolerate a missing cell (the stub's `querySelector` returns null; a real page never hits it): replace lines 359-361
```js
  rows.forEach(d => {
    const cell = document.querySelector(`[data-uid="${CSS.escape(d.uid)}"]`);
    const stack = cell.querySelector(".stack");
```
with
```js
  rows.forEach(d => {
    const cell = document.querySelector(`[data-uid="${CSS.escape(d.uid)}"]`);
    if(!cell) return;
    const stack = cell.querySelector(".stack");
```

- [x] **Step 5: 04k** - after `const el = id => document.getElementById(id);` (line 165) add the same `esc` as in Step 4, plus
```js
el("strip").addEventListener("click", e => {
  const c = e.target.closest && e.target.closest(".cell"); if(c) select(c.dataset.uid);
});
```
Replace lines 214-215
```js
    return `<div class="cell ${a.kind==="anchor"?"anchor":""} ${a.kind==="extrap"?"extrap":""}
                 ${active===d.uid?"active":""}" data-uid="${d.uid}" onclick="select('${d.uid}')">
```
with
```js
    return `<div class="cell ${a.kind==="anchor"?"anchor":""} ${a.kind==="extrap"?"extrap":""}
                 ${active===d.uid?"active":""}" data-uid="${esc(d.uid)}">
```
Replace lines 247-249
```js
  el("plateRegions").innerHTML = p.regions
    ? p.regions.replace(/\\|/g, " &middot; ")
    : "<span class='unlab'>no region labels on this plate</span>";
```
with
```js
  el("plateRegions").innerHTML = p.regions
    ? esc(p.regions).replace(/\\|/g, " &middot; ")
    : "<span class='unlab'>no region labels on this plate</span>";
```

- [x] **Step 6: 04b** - after `const el = id => document.getElementById(id);` (line 386) add the same `esc` and
```js
el("cands").addEventListener("click", e => {
  const c = e.target.closest && e.target.closest(".cand"); if(c) setMark(c.dataset.plate);
});
```
Replace lines 401-405
```js
  el("cands").innerHTML = d.candidates.map((c,k) => `
    <div class="cand ${chosen===c.plate_id?'chosen':''}" onclick="setMark('${c.plate_id}')">
      <img src="${c.img}" alt="">
      <div class="cap"><b>${k+1}. ${c.plate_id}</b> p${c.page} &middot; IoU ${c.score}
      ${c.regions ? '<br>'+c.regions : ''}</div>
```
with
```js
  el("cands").innerHTML = d.candidates.map((c,k) => `
    <div class="cand ${chosen===c.plate_id?'chosen':''}" data-plate="${esc(c.plate_id)}">
      <img src="${esc(c.img)}" alt="">
      <div class="cap"><b>${k+1}. ${esc(c.plate_id)}</b> p${esc(c.page)} &middot; IoU ${c.score}
      ${c.regions ? '<br>'+esc(c.regions) : ''}</div>
```

- [x] **Step 7: Run the suites, expect `ALL SUITES PASS`**

```
bash tests/run.sh 2>&1 | grep -E "^FAIL|SUITE"
```

- [x] **Step 8: Commit**

```
git add scripts/04l_roi_curator.py scripts/04d_rotation_curator.py scripts/04k_level_curator.py scripts/04b_atlas_match.py tests/rotation_curator.test.js tests/level_curator.test.js tests/channels.test.js
git commit -m "Curators: escape free text in attributes, delegate clicks instead of onclick strings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: 04l exports quote every field

> **Status 2026-09-03:** done in Tier 2 (commit "curator: export scale per section, and every CSV cell quoted"): `dl()` maps every cell through `csvq`, and `exportReview` no longer pre-quotes `why`. Only the dedicated `tests/csvq.test.js` below is still worth adding; skip the implementation steps if `dl` already reads `r.map(csvq)`.


**Files:**
- Modify: `scripts/04l_roi_curator.py:2266-2269` (`dl`), `:3096-3099` (`csvq`, moved up), `:3576` (`exportReview` row)
- Test: `tests/csvq.test.js`

`dl()` at `04l:2266-2269` joins with `","` and quotes nothing; `csvq` at `:3096` exists and is applied only to the `why` field of `exportReview` (`:3576`). `roi_landmarks.csv` carries `seed_region`, `roi_regions.csv` carries `region`/`ambiguity_group` - region labels from `seeds.csv`, free text. Quote in `dl()` so every export gets it, and stop pre-quoting in `exportReview` (or the field is quoted twice).

- [x] **Step 1: Write the failing test** `tests/csvq.test.js`

```js
// Every 04l export goes through one quoting rule.

const { env, load, chk, note, done } = require("./harness");
const { els, store, blobs } = env;

const X = load(`{KEY, PLATES, st, rows, select, onSlideUser, exportCsv, exportReview, csvq, dl,
  set active(v){active=v}, get active(){return active}}`);

chk("plain stays plain", X.csvq("Dm"), "Dm");
chk("a comma is quoted", X.csvq("a,b"), '"a,b"');
chk("a quote is doubled", X.csvq('say "hi"'), '"say ""hi"""');
chk("null is empty", X.csvq(null), "");

blobs.length = 0;
X.dl([["h1", "h2"], ["x,y", 'q"r'], [1, ""]], "t.csv");
chk("dl quotes each field", blobs[0], 'h1,h2\n"x,y","q""r"\n1,');

// A region label with a comma reaches roi_regions.csv intact.
const pi = X.PLATES.findIndex(P => P.labelled), P = X.PLATES[pi];
els["animal"].value = "LS105";
const uid = X.rows()[0].uid; X.select(uid, true); X.active = uid; X.onSlideUser(pi);
P.seeds[0].region = "Dm, medial"; P.seeds[0].amb = "";
const s = X.st(uid);
s.pairs.push([10, 10, 20, 20, 1, 5], [30, 30, 40, 40, 2, 5], [50, 50, 60, 60, 3, 5]);
blobs.length = 0; X.exportCsv();
const rg = blobs[2].split("\n"), hdr = rg[0].split(",");
chk("the region is quoted", rg.slice(1).some(l => l.includes('"Dm, medial"')), true);
const cols = l => l.match(/("([^"]|"")*"|[^,]*)(,|$)/g).length - 1;
chk("...so every row has the header's column count", rg.slice(1).every(l => cols(l) === hdr.length), true);

// exportReview: one level of quoting, not two.
s.rev = {act: "drop", why: 'torn, "badly"', status: "measured"};
blobs.length = 0; X.exportReview();
chk("the review reason is quoted exactly once",
    blobs[0].split("\n")[1].includes('"torn, ""badly"""'), true);
chk("...not wrapped twice", blobs[0].includes('"""torn'), false);

done();
```

- [x] **Step 2: Run it, expect `dl quotes each field` and the region/review lines to FAIL**

```
bash tests/run.sh 2>&1 | grep -E "^FAIL|SUITE"
```

- [x] **Step 3: Implement** - in `04l_roi_curator.py` cut the `csvq` definition (lines 3091-3099, comment included) and paste it immediately above `function dl(...)` (line 2266); then replace lines 2266-2269
```js
function dl(rowsArr,name){
  const b=new Blob([rowsArr.map(r=>r.join(",")).join("\\n")],{type:"text/csv"});
```
with
```js
// Every field of every export is quoted by one rule, here, so a region label
// or a reason with a comma cannot shift the columns of the row it sits in.
function dl(rowsArr,name){
  const b=new Blob([rowsArr.map(r=>r.map(csvq).join(",")).join("\\n")],{type:"text/csv"});
```
and in `exportReview` (line 3576) change `csvq(r.why || "")` to `r.why || ""`. Update the moved comment's first sentence to: `// dl() applies this to every field; it is defined here because exportReview and the region exports both need it.`

- [x] **Step 4: Run the suites, expect `ALL SUITES PASS`** (guided/channels split on `,` and read numeric or comma-free columns, so they are unaffected).

- [x] **Step 5: Commit**

```
git add scripts/04l_roi_curator.py tests/csvq.test.js
git commit -m "04l: every export field goes through csvq

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Keyboard guards - modifiers and form controls

**Files:**
- Modify: `scripts/04l_roi_curator.py:2077-2094`, `scripts/04d_rotation_curator.py:311-321`, `scripts/04k_level_curator.py:277-283`
- Test: `tests/keys.test.js` (new), `tests/rotation_curator.test.js`, `tests/level_curator.test.js` (append)

`04l:2077-2149` handles `x`, `f`, `a`, `d`... with no check on `ctrlKey`/`metaKey`/`altKey`, so Ctrl+F (find) excludes nothing but Ctrl+X excludes the active section. It bails on `TEXTAREA`/`SELECT` and some `INPUT`s (`:2089-2094`). `04d:311-321` and `04k:277-283` check neither modifiers nor focus: typing `a` in the animal `<select>`'s type-ahead sets an anchor.

- [x] **Step 1: Write the failing tests**

`tests/keys.test.js`
```js
// Shortcuts fire on plain keys only, and never while a form control has focus.

const { env, load, chk, note, done } = require("./harness");
const { els, fire } = env;

const X = load(`{st, rows, select, isExcl, set active(v){active=v}, get active(){return active}}`);
els["animal"].value = "LS105";
const uid = X.rows()[0].uid; X.select(uid, true); X.active = uid;
const key = (k, extra) => fire("keydown",
  Object.assign({key: k, target: {tagName: "BODY"}, preventDefault() {}}, extra || {}));

key("x", {ctrlKey: true});  chk("ctrl+x is the browser's", X.isExcl(uid), false);
key("x", {metaKey: true});  chk("cmd+x too", X.isExcl(uid), false);
key("x", {altKey: true});   chk("alt+x too", X.isExcl(uid), false);
key("x", {target: {tagName: "INPUT", type: "text"}});
chk("typing in a text box is typing", X.isExcl(uid), false);
key("x");                   chk("plain x excludes", X.isExcl(uid), true);
key("X", {shiftKey: true}); chk("shift is not a modifier here", X.isExcl(uid), false);

done();
```

Append to `tests/rotation_curator.test.js` before `done();`:
```js
// ---- keyboard guards ------------------------------------------------------
note("");
X.active = u;
const key = (k, extra) => fire("keydown",
  Object.assign({key: k, target: {tagName: "BODY"}, preventDefault() {}}, extra || {}));
key("x", {ctrlKey: true});
chk("ctrl+x does not exclude", X.isExcluded(u), false);
key("x", {target: {tagName: "SELECT"}});
chk("a key inside the animal select does nothing", X.isExcluded(u), false);
key("ArrowRight", {target: {tagName: "INPUT", type: "range"}});
chk("arrows inside a slider do nothing", X.get(u).r, 0);
key("x");
chk("plain x excludes", X.isExcluded(u), true);
key("x");
chk("...and toggles back", X.isExcluded(u), false);
```

Append to `tests/level_curator.test.js` before `done();`:
```js
// ---- keyboard guards ------------------------------------------------------
note("");
X.active = list[1].uid;
const key = (k, extra) => fire("keydown",
  Object.assign({key: k, target: {tagName: "BODY"}, preventDefault() {}}, extra || {}));
const nBefore = Object.keys(X.anchors).length;
key("a", {ctrlKey: true});
chk("ctrl+a selects text, sets no anchor", Object.keys(X.anchors).length, nBefore);
key("a", {target: {tagName: "SELECT"}});
chk("type-ahead in the animal select sets no anchor", Object.keys(X.anchors).length, nBefore);
els["slider"].value = 0;
key("a");
chk("plain a anchors", X.anchors[list[1].uid], 0);
key("d");
chk("plain d drops it", list[1].uid in X.anchors, false);
```

- [x] **Step 2: Run, expect the modifier/focus lines to FAIL** (`bash tests/run.sh 2>&1 | grep -E "^FAIL|SUITE"`)

- [x] **Step 3: 04l** - after line 2077 `addEventListener("keydown", e=>{` insert as the first statement
```js
  // Ctrl/Cmd/Alt chords belong to the browser - Ctrl+F finds, Ctrl+X cuts -
  // and a chord must never read as the bare letter. Shift is a real modifier
  // here (Shift+drag snaps), so it is left alone.
  if(e.ctrlKey || e.metaKey || e.altKey) return;
```

- [x] **Step 4: 04d** - replace lines 311-313
```js
addEventListener("keydown", e => {
  if(!active) return;
  const s = get(active);
```
with
```js
addEventListener("keydown", e => {
  if(e.ctrlKey || e.metaKey || e.altKey) return;
  // A focused control eats its own keys: the animal select does type-ahead
  // on letters, and a range input steps itself on the arrows.
  const tag = e.target && e.target.tagName;
  if(tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if(!active) return;
  const s = get(active);
```

- [x] **Step 5: 04k** - replace lines 277-278
```js
addEventListener("keydown", e => {
  if(!active) return;
```
with
```js
addEventListener("keydown", e => {
  if(e.ctrlKey || e.metaKey || e.altKey) return;
  const tag = e.target && e.target.tagName;
  if(tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if(!active) return;
```

- [x] **Step 6: Run the suites, expect `ALL SUITES PASS`**

- [x] **Step 7: Commit**

```
git add scripts/04l_roi_curator.py scripts/04d_rotation_curator.py scripts/04k_level_curator.py tests/keys.test.js tests/rotation_curator.test.js tests/level_curator.test.js
git commit -m "Curators: ignore modifier chords and keys typed into form controls

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: 04d - draft the rotation during the drag, commit on release

**Files:**
- Modify: `scripts/04d_rotation_curator.py:293-301` (`onMove`, `onUp`), `:286-292` (`onDown`), `:365-366` (pointer listeners)
- Test: `tests/rotation_curator.test.js` (append)

`04d:293-300` calls `setState()` on every `pointermove`, which serialises the whole state to `localStorage` and repaints per event. Keep the angle on the `drag` object, paint only the transform, and call `setState` once on `pointerup`/`pointercancel` - the same shape as 04l's `draftRot` (`tests/rotation.test.js`).

- [x] **Step 1: Write the failing test** - append to `tests/rotation_curator.test.js` before `done();`

```js
// ---- drag: a draft until release ------------------------------------------
note("");
const ev = (x, y) => ({clientX: x, clientY: y, button: 0, pointerId: 1, preventDefault() {},
  currentTarget: {getBoundingClientRect: () => ({left: 0, top: 0, width: 200, height: 200}),
                  setPointerCapture() {}}});
const v = X.DATA[1].uid;
delete X.state[v];
X.onDown(ev(200, 100), v);                     // 0 deg from the centre (100,100)
X.onMove({clientX: 100, clientY: 200, shiftKey: false});   // 90 deg
chk("mid-drag: nothing in the record", v in X.state, false);
chk("...nothing on disk", disk(v), undefined);
chk("...but the draft is live", Math.round(X.drag.r), 90);
X.onUp();
chk("release commits the angle", X.state[v].r, 90);
chk("...to disk", disk(v).r, 90);
chk("...and ends the drag", X.drag, null);

X.onDown(ev(200, 100), v);
X.onUp();
chk("a press that never moved changes nothing", X.state[v].r, 90);
```

- [x] **Step 2: Run, expect `mid-drag: nothing in the record` and `...but the draft is live` to FAIL**

- [x] **Step 3: Implement** - replace lines 293-301
```js
function onMove(e){
  if(!drag) return;
  let delta = angleOf(e, drag.rect) - drag.start;
  if(Math.abs(delta) > 0.5) drag.moved = true;
  let r = drag.base + delta;
  if(e.shiftKey) r = Math.round(r/15)*15;
  setState(drag.uid, r, get(drag.uid).f);
  el("live").textContent = `${drag.uid}: ${get(drag.uid).r}\\u00B0`;
}
function onUp(){ drag = null; }
```
with
```js
// The angle is a DRAFT until the pointer is released. Writing state on every
// pointermove serialised the whole store to localStorage and repainted the
// cell per event; now only the transform moves, and one setState() lands on
// release - so a drag that is cancelled leaves the record exactly as it was.
function onMove(e){
  if(!drag) return;
  let delta = angleOf(e, drag.rect) - drag.start;
  if(Math.abs(delta) > 0.5) drag.moved = true;
  let r = drag.base + delta;
  if(e.shiftKey) r = Math.round(r/15)*15;
  drag.r = ((Math.round(r) % 360) + 360) % 360;
  const cell = document.querySelector(`[data-uid="${CSS.escape(drag.uid)}"] .sec`);
  if(cell) cell.style.transform = `rotate(${drag.r}deg) scaleX(${get(drag.uid).f ? -1 : 1})`;
  el("live").textContent = `${drag.uid}: ${drag.r}\\u00B0`;
}
function onUp(){
  if(drag && drag.moved) setState(drag.uid, drag.r, get(drag.uid).f);
  else if(drag) paint(drag.uid);       // put an un-moved cell back exactly
  drag = null;
}
```
`onDown` (line 289) already records `base: get(uid).r`; add `r: get(uid).r` to that object literal so a release after a sub-threshold move has a value. The `pointerup`/`pointercancel` listeners at lines 365-366 already call `onUp`.

- [x] **Step 4: Run the suites, expect `ALL SUITES PASS`**

- [x] **Step 5: Commit**

```
git add scripts/04d_rotation_curator.py tests/rotation_curator.test.js
git commit -m "04d: rotation is a draft during the drag, stored once on release

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: 04d - `r` is stored only when the user rotated; explicit 0 survives on a proposed section

**Files:**
- Modify: `scripts/04d_rotation_curator.py:194-200` (`isSymAuto`, `get`), `:208-222` (`setState`, `toggleExclude`), `:398-406` (export `rsrc` and the skip rule)
- Test: `tests/rotation_curator.test.js` (append)

`toggleExclude` (`:219-223`) calls `setState(uid, s.r, s.f, ...)` with `s = get(uid)`, whose `r` is `symOf(uid)` when the user never rotated - so the proposal is copied into the record, `isSymAuto` (`:195`) turns false, and the export (`:402-404`) reports `manual_overrode_auto` for a section nobody rotated. `setState` (`:214`) deletes the record when `r === 0 && !f && x === undefined`, so a proposed section cannot be set to 0: `get()` falls back to the proposal again.

- [x] **Step 1: Write the failing test** - append to `tests/rotation_curator.test.js` before `done();`

```js
// ---- tri-state rotation ---------------------------------------------------
note("");
const w = X.DATA[2].uid;
delete X.state[w];
X.SYM[w] = {r: 30, score: 0.9, conf: "high"};
chk("a proposal is applied", X.get(w).r, 30);
chk("...and reads as auto", X.isSymAuto(w), true);
X.toggleExclude(w);
chk("excluding does not adopt the proposal", X.state[w].r, undefined);
chk("...it is still auto", X.isSymAuto(w), true);
chk("...and the exclusion is recorded", X.state[w].x, true);
X.toggleExclude(w);
chk("restoring is an explicit keep", X.state[w].x, false);
X.setState(w, 0, false, undefined);
chk("0 on a proposed section is a decision", X.get(w).r, 0);
chk("...that is stored", X.state[w].r, 0);
chk("...and is no longer auto", X.isSymAuto(w), false);

blobs.length = 0; X.exportCsv();
const rowsOut = blobs[0].split("\n").slice(1).map(l => l.split(","));
const rw = rowsOut.find(r => r[0] === w);
chk("the export carries the explicit 0", rw[1], "0");
chk("...sourced as an overruled proposal", rw[4], "manual_overrode_auto");
const w2 = X.DATA[3].uid;
delete X.state[w2]; X.SYM[w2] = {r: 12, score: 0.9, conf: "high"};
blobs.length = 0; X.exportCsv();
const rw2 = blobs[0].split("\n").slice(1).map(l => l.split(",")).find(r => r[0] === w2);
chk("an untouched proposal exports as auto_symmetry", rw2[4], "auto_symmetry");
delete X.SYM[w]; delete X.SYM[w2];
X.setState(X.DATA[4].uid, 0, false, undefined);
chk("0 with no proposal stores nothing", X.DATA[4].uid in X.state, false);
```

- [x] **Step 2: Run, expect `excluding does not adopt the proposal`, `0 on a proposed section is a decision`, `...sourced as an overruled proposal` to FAIL**

- [x] **Step 3: Implement** - replace lines 194-200
```js
const symOf = uid => (SYM[uid] ? SYM[uid].r : 0);
// The user's own rotation wins; with none, the symmetry proposal stands.
const isSymAuto = uid => !!SYM[uid] && !(state[uid] && state[uid].r !== undefined);

const save = () => localStorage.setItem(KEY, JSON.stringify(state));
// Effective rotation: the user's if they have set one, otherwise 04h's proposal.
// Dragging writes into `state` and takes over from then on.
const get  = uid => state[uid] || {r: symOf(uid), f:false};
```
with
```js
const symOf = uid => (SYM[uid] ? SYM[uid].r : 0);
// TRI-STATE, like `x`. `r` ABSENT from the record means "no rotation decided,
// use the proposal"; `r` present - including an explicit 0 - is the user's.
const hasOwnR   = uid => !!(state[uid] && state[uid].r !== undefined);
const isSymAuto = uid => !!SYM[uid] && !hasOwnR(uid);

const save = () => localStorage.setItem(KEY, JSON.stringify(state));
// Effective rotation: the user's if they have set one, otherwise 04h's proposal.
const get  = uid => ({r: hasOwnR(uid) ? state[uid].r : symOf(uid),
                      f: !!(state[uid] && state[uid].f)});
```
Replace lines 208-223 (`setState` and `toggleExclude`) with
```js
// `r` undefined = leave the rotation decision as it is (absent stays absent).
function setState(uid, r, f, x){
  const prev = state[uid];
  if(x === undefined) x = prev ? prev.x : undefined;   // keep "no decision yet"
  let rOwn = r === undefined ? (prev ? prev.r : undefined)
                             : ((Math.round(r) % 360) + 360) % 360;
  // 0 with no proposal says nothing, so it is not stored; 0 AGAINST a proposal
  // is the user overruling it, and must survive.
  if(rOwn === 0 && !SYM[uid]) rOwn = undefined;
  if(rOwn === undefined && !f && x === undefined) delete state[uid];
  else {
    state[uid] = {f: !!f};
    if(rOwn !== undefined) state[uid].r = rOwn;
    if(x !== undefined) state[uid].x = x;
  }
  save(); paint(uid); counts();
}

function toggleExclude(uid){
  // Flips against the *effective* state, so the first right-click on a proposal
  // restores it rather than appearing to do nothing. The rotation decision is
  // passed through untouched: excluding a section is not rotating it.
  setState(uid, undefined, get(uid).f, !isExcluded(uid));
}
```
In `exportCsv` replace lines 398-404
```js
    if(!s.r && !s.f && !excl && !AUTO[d.uid]) return;
    ...
    const rsrc = !s.r ? ""
               : isSymAuto(d.uid) ? "auto_symmetry"
               : (SYM[d.uid] ? "manual_overrode_auto" : "manual");
```
with (keeping the `decision`/`reason` lines between them as they are)
```js
    if(!s.r && !s.f && !excl && !AUTO[d.uid] && !hasOwnR(d.uid)) return;
    ...
    const rsrc = hasOwnR(d.uid) ? (SYM[d.uid] ? "manual_overrode_auto" : "manual")
               : (s.r ? "auto_symmetry" : "");
```
The keyboard `r`/`0` bindings (`:317-318`) call `setState(active, 0, ...)` and now store an explicit 0 on proposed sections - which is what pressing "reset" on a proposal should mean. `resetAll` and the v2 migration (`:154-163`) build records with `r: s.r || 0`; leave the migration alone (a stored `r:0` under the new rule is read as "own 0", which is what v2 recorded).

- [x] **Step 4: Run the suites, expect `ALL SUITES PASS`** (the Task 8 drag test passes `r` through `setState` with a nonzero angle, unaffected)

- [x] **Step 5: Commit**

```
git add scripts/04d_rotation_curator.py tests/rotation_curator.test.js
git commit -m "04d: rotation is stored only when the user rotated; explicit 0 overrules a proposal

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: 04l - no phantom records, seed adoption on decisions only, landmark counts exclude background discs, one exclusion rule

**Files:**
- Modify: `scripts/04l_roi_curator.py:844-854` (state init, `save`), `:1621-1622` (`status`), `:1875` (`isDone`), `:1900-1907` (`cellTag`), `:2185-2199` (export gate and status), `:2293-2300` (`adoptSeed`)
- Test: `tests/seed.test.js` (new), `tests/rotation.test.js:57` (one edit)

`select()` (`:1852`) calls `st(uid)`, which creates `{plate:0, pairs:[], ...}`; `onSlide()` (`:1818`) then `save()`s, so every section merely looked at is persisted and later treated as work by the S initialiser (`:845-851`: "if the store has any keys, it wins") and by `adoptSeed` (`:2296`: seed entries are skipped whenever the browser has *any* record). `status()` (`:1622`) runs `st(active)` with `active === null` and creates `S["null"]`. `isDone` (`:1875`) and `cellTag` (`:1901`) count `s.pairs.length`, which includes background discs, while the export counts `roiPairs(s)`. The export (`:2189-2199`) tests `s.excl`, but the strip uses `isExcl(uid)` (`:1883`), which honours a reinstatement.

- [x] **Step 1: Write the failing test** `tests/seed.test.js`

```js
// A record is work only if it holds a decision. Looking at a section is not one.

const { env, load, chk, note, done } = require("./harness");
const { els, store, blobs } = env;

const X = load(`{KEY, S, SEED_STATE, st, rows, select, onSlide, status, initState, hasDecision,
  hasRoiWork, adoptSeed, exportCsv, isExcl, isDone, cellTag, toggleExcl,
  set active(v){active=v}, get active(){return active}}`);

const blank = () => ({plate: 0, pairs: [], assigned: false, noroi: false, fav: false, rot: 0, excl: false});
chk("a fresh record is not a decision", X.hasDecision(blank()), false);
chk("a favourite is", X.hasDecision({...blank(), fav: true}), true);
chk("a background disc is", X.hasDecision({...blank(), pairs: [[1, 2, 3, 4, 0, 5, "bg"]]}), true);
chk("a review verdict is", X.hasDecision({...blank(), rev: {act: "drop"}}), true);
chk("a tilt is", X.hasDecision({...blank(), rot: 12}), true);
chk("but a tilt is not ROI work", X.hasRoiWork({...blank(), rot: 12}), false);
chk("undefined is not", X.hasDecision(undefined), false);

const seed = {A: {...blank(), fav: true}, B: blank()};
chk("seed fills an empty store, minus blanks", Object.keys(X.initState(null, seed)).join(), "A");
chk("stored work wins over the seed",
    Object.keys(X.initState(JSON.stringify({C: {...blank(), excl: true}}), seed)).join(), "C");
chk("a store holding only blanks counts as empty",
    Object.keys(X.initState(JSON.stringify({B: blank()}), seed)).join(), "A");
chk("garbage in the store is ignored", Object.keys(X.initState("{not json", seed)).join(), "A");

els["animal"].value = "LS105";
const uids = X.rows().map(d => d.uid);
chk("fixture needs five sections", uids.length >= 5, true);
X.select(uids[0], true);
X.onSlide(4);
chk("select + slide stores no record", uids[0] in JSON.parse(store[X.KEY] || "{}"), false);
X.active = uids[0]; X.toggleExcl();
chk("...but a decision does", JSON.parse(store[X.KEY])[uids[0]].excl, true);

X.active = null; X.status();
chk("status() with nothing selected adds no record", "null" in X.S, false);

for (const k of Object.keys(X.SEED_STATE)) delete X.SEED_STATE[k];
Object.assign(X.SEED_STATE, {[uids[1]]: {...blank(), fav: true}, [uids[2]]: blank()});
X.adoptSeed();
chk("adopt takes the decided seed entry", X.S[uids[1]].fav, true);
chk("...and skips the blank one", uids[2] in X.S, false);

const s = X.st(uids[3]);
s.pairs.push([1, 1, 2, 2, 0, 5, "bg"], [1, 1, 2, 2, 0, 5, "bg"], [1, 1, 2, 2, 0, 5, "bg"]);
chk("three background discs do not make a section done", X.isDone(uids[3]), false);
chk("...and the cell tag counts landmarks only", X.cellTag(uids[3]), "");
s.pairs.push([1, 1, 2, 2, 1, 5], [1, 1, 2, 2, 2, 5], [1, 1, 2, 2, 3, 5]);
chk("three landmarks do", X.isDone(uids[3]), true);
chk("...and the tag says 3 pts", X.cellTag(uids[3]), "3 pts");

const t = X.st(uids[4]); t.excl = true; t.rev = {act: "restore"};
chk("a reinstated section is not excluded on screen", X.isExcl(uids[4]), false);
blobs.length = 0; X.exportCsv();
const pl = blobs[0].split("\n"), h = pl[0].split(",");
const row = pl.slice(1).map(l => l.split(",")).find(r => r[0] === uids[4]);
chk("...nor in the export", row[h.indexOf("excluded")], "0");
chk("...and its status is not 'excluded'", row[h.indexOf("status")] === "excluded", false);

done();
```

and in `tests/rotation.test.js:57` change
```js
chk("...on disk too", disk(uid).rot.toFixed(1), "0.0");
```
to
```js
chk("...on disk too - a zero tilt on an undecided section stores nothing",
    (disk(uid).rot || 0).toFixed(1), "0.0");
```

- [x] **Step 2: Run, expect `LOAD ERROR: initState is not defined`** (`node tests/seed.test.js` after `bash tests/run.sh` has built the page)

- [x] **Step 3: Implement** - replace lines 844-854
```js
const SEED_STATE = __SEED__;
let S = (function(){
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) { const v = JSON.parse(raw); if (v && Object.keys(v).length) return v; }
  } catch (e) {}
  return SEED_STATE && Object.keys(SEED_STATE).length ? SEED_STATE : {};
})();
let active = null, pending = null;   // pending section point awaiting its plate partner
const el = id => document.getElementById(id);
const save = () => localStorage.setItem(KEY, JSON.stringify(S));
```
with
```js
const SEED_STATE = __SEED__;
// WHAT COUNTS AS WORK. `st()` creates a record the moment a section is looked
// at, and the slider writes into it - so "the store has records" never meant
// "the operator decided something". These two predicates are the only rule:
// hasRoiWork is what exportCsv reports; hasDecision adds the two things kept
// but exported elsewhere (a tilt, a Review-mode verdict).
const hasRoiWork  = r => !!r && !!(r.assigned || r.fav || r.excl || r.noroi
                                   || (r.pairs && r.pairs.length));
const hasDecision = r => hasRoiWork(r) || !!(r && (r.rot || r.rev));
const decided = obj => Object.fromEntries(
  Object.entries(obj || {}).filter(([, v]) => hasDecision(v)));
// Whatever this browser already holds wins - but only what it holds that is a
// decision. A store of looked-at sections is an empty store.
function initState(raw, seed){
  try {
    if (raw) { const v = decided(JSON.parse(raw)); if (Object.keys(v).length) return v; }
  } catch (e) {}
  return decided(seed);
}
let S = initState(localStorage.getItem(KEY), SEED_STATE);
let active = null, pending = null;   // pending section point awaiting its plate partner
const el = id => document.getElementById(id);
// Only decisions reach disk. The in-memory record for a section being looked
// at stays (the plate it is on is needed while it is on screen); it is simply
// not persisted until something is decided about it.
const save = () => localStorage.setItem(KEY, JSON.stringify(decided(S)));
```
At line 1621-1622 change
```js
function status(){
  const s=st(active), T=transform(s.pairs);
```
to
```js
function status(){
  if(!active) return;
  const s=st(active), T=transform(s.pairs);
```
At line 1875 change
```js
const isDone   = uid => (S[uid]?.pairs?.length || 0) >= 3;
```
to
```js
// LANDMARKS, not pairs: a background disc is a pair too, and three of them
// would light the cell green with nothing registered.
const nRoi     = uid => S[uid]?.pairs ? roiPairs(S[uid]).length : 0;
const isDone   = uid => nRoi(uid) >= 3;
```
At line 1901 change `const s=S[uid], n=s?.pairs?.length||0;` to `const s=S[uid], n=nRoi(uid);`.
In `exportCsv` replace line 2185
```js
    if(!s || !(s.assigned || s.fav || s.excl || s.pairs.length)) continue;
```
with
```js
    if(!hasRoiWork(s)) continue;
```
and lines 2189-2199: introduce `const excl = isExcl(d.uid);` before `const status = ...`, then use `excl` in place of `s.excl` in the `status` expression and in the last column (`excl?1:0`). Replace lines 2293-2300 (`adoptSeed`) with
```js
function adoptSeed(){
  const before = Object.keys(S).length;
  for(const [uid, v] of Object.entries(SEED_STATE || {}))
    if(hasDecision(v) && !hasDecision(S[uid])) S[uid] = v;
  save();
  el("seedOffer").style.display = "none";
  render(); status();
  console.log(`adopted seed: ${before} -> ${Object.keys(S).length} sections`);
}
```
and in the seed-offer block (`:2278`) count `missing` with the same rule: `const missing = Object.keys(SEED_STATE).filter(u => hasDecision(SEED_STATE[u]) && !hasDecision(S[u])).length;`.

- [x] **Step 4: Run the suites, expect `ALL SUITES PASS`**

- [x] **Step 5: Commit**

```
git add scripts/04l_roi_curator.py tests/seed.test.js tests/rotation.test.js
git commit -m "04l: only decisions are stored, seeded or adopted; landmark counts exclude discs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Empty-input guards in the Python scripts

**Files:**
- Modify: `scripts/00b_verify_extraction.py:169-172`; `scripts/04c_atlas_match.py:281-285`; `scripts/01k_saturation_raw.py:330-346`; `scripts/04l_roi_curator.py:3619`, `:3643`, `:3813`; `scripts/04a_reformat.py:768`; `scripts/02_pair_passes.py:73-74`; `scripts/01_overviews.py:273-274`; `scripts/01g_saturation_map.py:74`, `:141-155`, `:267-276`, `:348-351`
- Test: `tests/test_empty_guards.py`

Each is a first-run or partial-run crash: `rows[0].keys()` on an empty result (00b:170, 04c:283), `raw.max()` on an empty array (01k:333), `lab[0]` when no plate carries seeds (04l:3813), a bare `open(args.worklist)` (04l:3643), `plt.subplots(2, 1)` returning a 1-D axes array indexed as 2-D (04a:768-771), `float("")` on a blank `center_x_um` (02:73-74), `ranges[marker]` when `display_ranges.json` predates a marker (01_overviews:274), and 01g's module-level `_fallbacks` (:74) that is appended to by `analyse()` and never cleared, so a second `main()` in one process (the app runs stages in-process) reports the previous run's sections.

- [x] **Step 1: Write the failing test** `tests/test_empty_guards.py`

```python
"""First-run and partial-run inputs that used to crash.

Run:  python tests/test_empty_guards.py
"""

import csv
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
PY = sys.executable


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


tmp = tempfile.mkdtemp(prefix="guards_")
try:
    # 00b: no archives -> no rows, and the writer must still produce a header.
    V = load("v", "00b_verify_extraction.py")
    chk("00b check() with an empty inventory", V.check({}, False), [])
    chk("00b names its columns", V.STATUS_KEYS[:2], ["file", "zip"])

    # 01k: summarise() on nothing measured returns instead of raw.max()
    K = load("k", "01k_saturation_raw.py")
    K.summarise([], measured=0, failed=0)
    chk("01k summarise([]) returns", True, True)

    # 04a preview with n=1: subplots(2, 1) must still index as [row, col]
    RF = load("rf", "04a_reformat.py")
    sec, pla = os.path.join(tmp, "sec"), os.path.join(tmp, "pla")
    os.makedirs(sec); os.makedirs(pla)
    Image.fromarray(np.zeros((8, 8), np.uint8)).save(os.path.join(sec, "s1.png"))
    Image.fromarray(np.zeros((8, 8), np.uint8)).save(os.path.join(pla, "p1.png"))
    RF.REFORMAT_DIR = tmp
    RF.preview([{"kind": "plate", "id": "p1", "angle": 0.0},
                {"kind": "section", "id": "s1", "angle": 0.0}], sec, pla, 1)
    chk("04a preview(n=1) writes", os.path.exists(os.path.join(tmp, "reformat_preview.png")), True)

    # 02: a blank centre cell reads as nan, not a crash
    P = load("p", "02_pair_passes.py")
    P.MANIFEST_DIR = tmp
    with open(os.path.join(tmp, "manifest_scenes.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["slide", "scene_index", "slide_serial", "section_order",
                                           "center_x_um", "center_y_um"])
        w.writeheader()
        w.writerow({"slide": 1, "scene_index": 0, "slide_serial": 1, "section_order": 1,
                    "center_x_um": "", "center_y_um": "12.5"})
    rows = P.load_scenes()
    chk("02 blank centre -> nan", np.isnan(rows[0]["center_x_um"]), True)
    chk("02 filled centre still parses", rows[0]["center_y_um"], 12.5)

    # 01_overviews: a marker missing from display_ranges.json is a clear stop
    O = load("o", "01_overviews.py")
    chk("01 channel_range returns the pair", O.channel_range({"DAPI": {"lo": 1, "hi": 9}}, "DAPI"), (1, 9))
    msg = ""
    try:
        O.channel_range({"DAPI": {"lo": 1, "hi": 9}}, "AF488")
    except SystemExit as exc:
        msg = str(exc)
    chk("01 missing marker names the file to delete", "display_ranges.json" in msg and "AF488" in msg, True)

    # 01g: no module-level fallback list; analyse() reports through its argument
    G = load("g", "01g_saturation_map.py")
    chk("01g has no module-level _fallbacks", hasattr(G, "_fallbacks"), False)
    fb = []
    got = G.analyse({"animal": "LSX", "marker_channel": "AF568", "scene_uid": "nope",
                     "slide": "1", "section_order": "1"}, 5.2, fb)
    chk("01g analyse() on a missing section returns None", got, None)
    chk("...and records no fallback", fb, [])

    # 04l: --worklist that does not exist stops with a message, not a traceback
    r = subprocess.run([PY, os.path.join(SCRIPTS, "04l_roi_curator.py"),
                        "--worklist", os.path.join(tmp, "nope.csv"),
                        "--out", os.path.join(tmp, "x.html")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    chk("04l missing worklist exits 1", r.returncode, 1)
    chk("...without a traceback", "Traceback" in r.stderr, False)
    chk("...and names 04n", "04n_roi_worklist" in (r.stdout + r.stderr), True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

- [x] **Step 2: Run it, expect `AttributeError: module 'v' has no attribute 'STATUS_KEYS'`**

- [x] **Step 3: Implement, file by file**

**00b** - add after `QC_DIR = ...` (line 35):
```python
STATUS_KEYS = ["file", "zip", "expected_bytes", "actual_bytes", "status", "crc_ok"]
```
(the six keys `check()` builds at lines 85-92) and replace lines 169-172 with `IO.atomic_write_csv(out, rows, STATUS_KEYS)` (add the IO import boilerplate; 00b needs `import importlib.util`).

**04c** - before line 281 `out = os.path.join(REPORT_DIR, "atlas_proposals_v2.csv")` add
```python
    if not proposals:
        raise SystemExit("no sections matched - is reformat_index.csv empty? Run 04a_reformat.py first")
```
and replace lines 282-285 with `IO.atomic_write_csv(out, proposals, list(proposals[0].keys()))` (add the IO import).

**01k** - move lines 330-346 (from `raw = np.array(...)` to the closing `print("=" * 74)`) into a function placed above `main()`:
```python
def summarise(rows, measured, failed):
    """The console summary. Returns early on nothing measured: np.max on an
    empty array raises, and a run whose only file failed still has to exit
    with a sentence rather than a traceback."""
    print()
    print("=" * 74)
    print("measured %d, failed %d, %s now holds %d sections"
          % (measured, failed, OUT_CSV, len(rows)))
    if not rows:
        print("nothing measured - is the source drive mounted?")
        print("=" * 74)
        return
    raw = np.array([float(r["saturated_fraction_raw"]) for r in rows])
    dap = np.array([float(r["saturated_fraction_dapi_raw"]) for r in rows])
    ratio = np.array([float(r["raw_over_corrected"]) for r in rows if r["raw_over_corrected"]])
    print("  marker clipping (raw) : median %.6f  p95 %.6f  max %.6f"
          % (np.median(raw), np.percentile(raw, 95), raw.max()))
    print("  DAPI clipping (raw)   : median %.6f  max %.6f   <- expected near zero"
          % (np.median(dap), dap.max()))
    if len(ratio):
        print("  raw / corrected       : median %.3f  p05 %.3f  p95 %.3f  (n=%d)"
              % (np.median(ratio), np.percentile(ratio, 5), np.percentile(ratio, 95), len(ratio)))
    print("=" * 74)
```
and call `summarise(rows, measured, failed)` where the block was; then `if not rows: return` before `merge_into_focus(rows)`.

**04l** - after `args = ap.parse_args()` (line 3619) add
```python
    if args.worklist and not os.path.exists(args.worklist):
        raise SystemExit(f"--worklist: {args.worklist} not found - run 04n_roi_worklist.py first")
```
and replace line 3813
```python
    print(f"  {len(lab)} plates carry seeds: {lab[0]['id']} .. {lab[-1]['id']}")
```
with
```python
    print(f"  {len(lab)} plates carry seeds"
          + (f": {lab[0]['id']} .. {lab[-1]['id']}" if lab else " - no region can be placed yet"))
```

**04a:768** - change `fig, ax = plt.subplots(2, n, figsize=(2.1 * n, 4.6))` to `fig, ax = plt.subplots(2, n, figsize=(2.1 * n, 4.6), squeeze=False)`.

**02_pair_passes** - add above `load_scenes()`:
```python
def _fnum(v):
    """A float cell, or nan for a blank one - a scene with no recorded centre
    must load, and be ignored by the distance maths, rather than kill the run."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")
```
and change lines 73-74 to `r["center_x_um"] = _fnum(r["center_x_um"])` / `r["center_y_um"] = _fnum(r["center_y_um"])`.

**01_overviews** - add above `export()`:
```python
def channel_range(ranges, name):
    """(lo, hi) for a channel, or a clear stop when display_ranges.json predates it."""
    if name not in ranges:
        raise SystemExit(f"{RANGES_PATH} has no entry for {name} - it was sampled before "
                         f"this marker existed. Delete it and rerun to resample.")
    return ranges[name]["lo"], ranges[name]["hi"]
```
and replace lines 273-274 with
```python
        d_lo, d_hi = channel_range(ranges, "DAPI")
        m_lo, m_hi = channel_range(ranges, marker)
```

**01g** - delete `_fallbacks = []` (line 74); change the signature at line 141 to `def analyse(row, um_px, fallbacks):` and line 154 to `fallbacks.append(row["scene_uid"])`; in `main()` add `fallbacks = []` right after `args = ap.parse_args()` (line ~275), pass it at the `analyse(...)` call site, and change lines 348-351 to read `fallbacks` instead of `_fallbacks`.

- [x] **Step 4: Run the test, expect `ALL PASS`**; then `bash tests/run.sh` still passes.

- [x] **Step 5: Commit**

```
git add scripts/00b_verify_extraction.py scripts/04c_atlas_match.py scripts/01k_saturation_raw.py scripts/04l_roi_curator.py scripts/04a_reformat.py scripts/02_pair_passes.py scripts/01_overviews.py scripts/01g_saturation_map.py tests/test_empty_guards.py
git commit -m "Empty and partial inputs stop with a sentence, not a traceback

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: 04a - the exclusion list is written after the review merge; excluded renders are never masked

**Files:**
- Modify: `scripts/04a_reformat.py:454-500` (`load_overrides`), `:558-561` (main), `:651-674` (loop)
- Test: `tests/test_excluded_write.py`

`load_overrides()` writes `excluded_sections*.csv` at `:495-500`, before `apply_review()` at `:561` merges `section_review.csv` over the same dict - so the canonical list on disk never carries a Review-mode drop or reinstatement, and `04o_section_rgb.py:173` calls `load_overrides(paths)` too, rewriting it on every composite build. In the section loop, `art` (`:654-656`) and `cen` (`:657`) are loaded for excluded sections under `--render-excluded --mask-artifacts`, and the `.npy` masks are written (`:671-674`), while `04o:225-227` renders an excluded section unmasked on the assumption that 04a did - so `04o --verify` fails on exactly those.

- [x] **Step 1: Write the failing test** `tests/test_excluded_write.py`

```python
"""excluded_sections.csv is written once, after the review merge, by main().

Run:  python tests/test_excluded_write.py
"""

import csv
import importlib.util
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

_spec = importlib.util.spec_from_file_location("rf", os.path.join(SCRIPTS, "04a_reformat.py"))
RF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RF)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


tmp = tempfile.mkdtemp(prefix="excl_")
try:
    paths = {"overrides": os.path.join(tmp, "rotation_overrides.csv"), "uid_col": "scene_uid",
             "excluded": os.path.join(tmp, "excluded_sections.csv")}
    with open(paths["overrides"], "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["scene_uid", "extra_rotation", "flip", "excluded",
                                           "rotation_source", "decision", "reason"])
        w.writeheader()
        w.writerow({"scene_uid": "A", "extra_rotation": "12", "flip": "0", "excluded": "0",
                    "rotation_source": "manual", "decision": "", "reason": ""})
        w.writerow({"scene_uid": "B", "extra_rotation": "0", "flip": "0", "excluded": "1",
                    "rotation_source": "", "decision": "manual", "reason": "torn"})

    overrides, excluded = RF.load_overrides(paths)
    chk("rotations still load", overrides, {"A": (12.0, False)})
    chk("exclusions still load", excluded, {"B": ("manual", "torn")})
    chk("load_overrides writes nothing by default", os.path.exists(paths["excluded"]), False)

    RF.write_excluded(paths["excluded"], {})
    with open(paths["excluded"], encoding="utf-8") as fh:
        chk("an empty list is a header-only file", fh.read(), "scene_uid,decision,reason\r\n")

    merged = dict(excluded)
    merged["C"] = ("manual", "excluded on review")
    RF.write_excluded(paths["excluded"], merged)
    rows = read(paths["excluded"])
    chk("the merged list is what lands", [r["scene_uid"] for r in rows], ["B", "C"])
    chk("...with its reasons", rows[1]["reason"], "excluded on review")

    # Which masks an excluded section gets: none, whatever the flags say.
    chk("kept section, both flags", RF.wants_masks(False, True, True, set(), "X"), (True, True))
    chk("kept section, rejected mask", RF.wants_masks(False, True, True, {"X"}, "X"), (False, True))
    chk("excluded section is rendered raw", RF.wants_masks(True, True, True, set(), "X"), (False, False))
    chk("no flags, no masks", RF.wants_masks(False, False, False, set(), "X"), (False, False))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

- [x] **Step 2: Run, expect `FAIL load_overrides writes nothing by default` then `AttributeError: ... write_excluded`**

- [x] **Step 3: Implement** - in `04a_reformat.py`:

Change the signature at line 454 to `def load_overrides(paths=None, write=False):` and replace lines 493-500
```python
    # Written out separately as the canonical list, so any stage can honour
    # exclusions without parsing the curator's export format.
    if excluded:
        with open(paths["excluded"], "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["scene_uid", "decision", "reason"])
            for uid in sorted(excluded):
                w.writerow([uid, excluded[uid][0], excluded[uid][1]])
    return out, excluded
```
with
```python
    # The canonical list is written by main(), AFTER apply_review() has merged
    # section_review.csv over this - writing it here published a list that
    # never carried a Review-mode drop or reinstatement, and every caller of
    # this loader (04o builds composites) rewrote it. `write=True` is for a
    # caller that has no review to merge and wants the old behaviour.
    if write:
        write_excluded(paths["excluded"], excluded)
    return out, excluded


def write_excluded(path, excluded):
    """`excluded_sections*.csv`: the canonical exclusion list, one row per
    section, so any stage can honour it without parsing a curator export.
    Header-only when there is nothing to exclude: an absent file reads as
    "never computed", which is a different fact."""
    rows = [{"scene_uid": uid, "decision": excluded[uid][0], "reason": excluded[uid][1]}
            for uid in sorted(excluded)]
    IO.atomic_write_csv(path, rows, ["scene_uid", "decision", "reason"])


def wants_masks(is_excl, mask_artifacts, censor, mask_rejected, uid):
    """(use artifact mask, use censor mask) for one section.

    An excluded section is rendered RAW whatever the flags say. 04o builds its
    composite unmasked - the blue plane has to equal this picture - and a
    section on screen so somebody can decide whether to reinstate it cannot
    be judged with the artifact already painted black.
    """
    if is_excl:
        return False, False
    return (mask_artifacts and uid not in mask_rejected), censor
```
In `main()` replace lines 558-561
```python
    overrides, excluded = load_overrides(paths) if args.apply_overrides else ({}, {})
    mask_rejected = set()
    if args.apply_overrides:
        excluded, mask_rejected = apply_review(excluded, args.marker)
```
with
```python
    overrides, excluded = load_overrides(paths) if args.apply_overrides else ({}, {})
    mask_rejected = set()
    if args.apply_overrides:
        excluded, mask_rejected = apply_review(excluded, args.marker)
        # After the merge, unconditionally: header-only means "nothing excluded".
        write_excluded(paths["excluded"], excluded)
```
In the loop replace lines 651-657
```python
        art = (load_artifact(r["scene_uid"], (WORK_SIZE, WORK_SIZE))
               if args.mask_artifacts and r["scene_uid"] not in mask_rejected
               else None)
        cen = load_censor(r["scene_uid"], (WORK_SIZE, WORK_SIZE)) if args.censor else None
```
with
```python
        use_art, use_cen = wants_masks(is_excl, args.mask_artifacts, args.censor,
                                       mask_rejected, r["scene_uid"])
        art = load_artifact(r["scene_uid"], (WORK_SIZE, WORK_SIZE)) if use_art else None
        cen = load_censor(r["scene_uid"], (WORK_SIZE, WORK_SIZE)) if use_cen else None
```
and lines 671-674
```python
        if args.mask_artifacts:
            np.save(os.path.join(sec_dir, r["scene_uid"] + "_artifact.npy"), amask)
        if args.censor:
            np.save(os.path.join(sec_dir, r["scene_uid"] + "_censor.npy"), cmask)
```
with
```python
        # No mask products for an excluded section: it is a picture to look at,
        # and 05c reads these .npy files as "this section is in the analysis".
        if use_art:
            np.save(os.path.join(sec_dir, r["scene_uid"] + "_artifact.npy"), amask)
        if use_cen:
            np.save(os.path.join(sec_dir, r["scene_uid"] + "_censor.npy"), cmask)
```
The `no_mask` accounting at lines 661-662 keys on `args.mask_artifacts and art is None and uid not in mask_rejected` - add `and not is_excl` so an excluded section is not reported as "had no 04g mask". `04o_section_rgb.py:173` needs no change: with the default `write=False` it can no longer rewrite the list.

- [x] **Step 4: Run `tests/test_excluded_write.py` and `tests/test_section_review.py`, expect both `ALL PASS`**

- [x] **Step 5: Commit**

```
git add scripts/04a_reformat.py tests/test_excluded_write.py
git commit -m "04a: write the exclusion list after the review merge; render excluded sections unmasked

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: 04f `--survey` writes its own file; 04g `--preview N` stops after N and writes no masks

**Files:**
- Modify: `scripts/04f_exclusion_candidates.py:92-93` (add `SURVEY_CSV`), `:251-257`; `scripts/04g_artifact_mask.py:315-331`, `:355`, `:363-366`
- Test: `tests/test_survey_preview.py`

`04f --survey` blanks every proposal (`:211-212`) and then writes the result to `exclusion_candidates.csv` (`:251-257`) - the file 04d reads its proposals from, so a survey run silently un-proposes everything. `04g --preview N` collects `N` overlays (`:355`) but the loop runs the whole index (`:315`) and writes every mask to `MASK_DIR` (`:331`) before `:363-366` returns; a "look at three" run rewrites 1,381 masks.

- [x] **Step 1: Write the failing test** `tests/test_survey_preview.py`

```python
"""--survey and --preview are read-only modes.

Run:  python tests/test_survey_preview.py
"""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


F = load("f", "04f_exclusion_candidates.py")
chk("a normal run writes the candidates", os.path.basename(F.output_path(False)), "exclusion_candidates.csv")
chk("a survey writes its own file", F.output_path(True).replace("\\", "/").endswith("qc/exclusion/survey.csv"), True)
chk("...and not the candidates", F.output_path(True) == F.output_path(False), False)

G = load("g", "04g_artifact_mask.py")
chk("no preview: process everything, write masks", G.run_plan(0, 0), (True, True))
chk("preview 3 with 2 collected: keep going, no masks", G.run_plan(3, 2), (True, False))
chk("preview 3 with 3 collected: stop", G.run_plan(3, 3), (False, False))
with open(os.path.join(SCRIPTS, "04g_artifact_mask.py"), encoding="utf-8") as fh:
    src = fh.read()
chk("the mask write is gated on write_masks", "if write_masks:\n            with IO.atomic_save(" in src, True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

- [x] **Step 2: Run, expect `AttributeError: module 'f' has no attribute 'output_path'`**

- [x] **Step 3: 04f** - after `REFORMAT_DIR = ...` (line 92) add
```python
CANDIDATES_CSV = os.path.join(REFORMAT_DIR, "exclusion_candidates.csv")
SURVEY_CSV = os.path.join(OUT_ROOT, "qc", "exclusion", "survey.csv")


def output_path(survey):
    """--survey measures and proposes nothing, so it must not overwrite the
    proposals 04d reads. It gets its own file under qc/."""
    return SURVEY_CSV if survey else CANDIDATES_CSV
```
and replace lines 251-252
```python
    out = os.path.join(REFORMAT_DIR, "exclusion_candidates.csv")
    keys = [...]
```
with
```python
    out = output_path(args.survey)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    keys = [...]
```
(the `IO.atomic_write_csv(out, ...)` line from Task 2 stays).

- [x] **Step 4: 04g** - add above `main()`:
```python
def run_plan(preview, collected):
    """(keep processing, write masks). --preview N is a LOOK: it stops once N
    overlays are collected and writes nothing to MASK_DIR on the way."""
    if not preview:
        return True, True
    return collected < preview, False
```
In the loop replace line 315-316
```python
    for i, r in enumerate(index):
        uid = r["id"]
```
with
```python
    for i, r in enumerate(index):
        go, write_masks = run_plan(args.preview, len(previews))
        if not go:
            break
        uid = r["id"]
```
and line 331
```python
        Image.fromarray(mask).save(os.path.join(MASK_DIR, uid + "_artifact.png"))
```
with
```python
        if write_masks:
            with IO.atomic_save(os.path.join(MASK_DIR, uid + "_artifact.png")) as tmp:
                Image.fromarray(mask).save(tmp, format="PNG")
```
Change the `if not rows: raise SystemExit("nothing masked ...")` at line 361 to `if not rows and not args.preview:` so a preview that found no artifact in its first few sections reports rather than dies; the existing `if previews: overlay(previews); if args.preview: return` at 363-366 stays.

- [x] **Step 5: Run the test, expect `ALL PASS`**

- [x] **Step 6: Commit**

```
git add scripts/04f_exclusion_candidates.py scripts/04g_artifact_mask.py tests/test_survey_preview.py
git commit -m "04f --survey and 04g --preview no longer overwrite the real outputs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: 04j records unmeasured sections and refuses to shrink a complete analysis set; 04m parses every reason and says "unmeasured"

**Files:**
- Modify: `scripts/04j_censor_clipped.py:145-151` (add `--allow-partial`), `:165-171` (loop), `:199-206`, `:208` (guard), `:213-233` (stats); `scripts/04m_sections_dataset.py:72-87` (`classify`), `:109-127` (status)
- Test: `tests/test_analysis_set.py`

`04j:168-171` skips a section with no raw clipping mask, so the analysis set simply lacks the row and `04m:123-127` reads "no row" as `censored_out`, which is a false statement about clipping. A `04j` run on a half-built `censor_raw/` therefore overwrites a complete `perk_analysis_set.csv` with a partial one and every missing section becomes "censored". `04m.classify()` (`:79`) recognises only the `manually excluded` prefix, but 04a records `"too damaged to measure"` (`04a:469`, the default when the curator export carries no reason) and `"excluded on review"` (`04a:446`) - both fall to `unparsed`.

- [x] **Step 1: Write the failing test** `tests/test_analysis_set.py`

```python
"""Unmeasured is not censored.

Run:  python tests/test_analysis_set.py
"""

import csv
import importlib.util
import os
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


J = load("j", "04j_censor_clipped.py")
M = load("m", "04m_sections_dataset.py")

row = J.unmeasured_row("U1", "LS1", "7")
chk("an unmeasured row is blank, not zero", row["in_analysis_set"], "")
chk("...and says why", row["reason"], "no raw clipping mask - run 01k_saturation_raw.py")
chk("...under the same columns", list(row.keys()), J.ANALYSIS_KEYS)

full = [{"scene_uid": "A", "in_analysis_set": 1}, {"scene_uid": "B", "in_analysis_set": 0}]
part = [{"scene_uid": "A", "in_analysis_set": 1}, {"scene_uid": "B", "in_analysis_set": ""}]
chk("complete means every row measured", J.is_complete(full), True)
chk("a blank makes it partial", J.is_complete(part), False)

tmp = tempfile.mkdtemp(prefix="aset_")
try:
    out = os.path.join(tmp, "perk_analysis_set.csv")
    chk("no file on disk: partial is allowed", J.guard_partial(out, part, False), None)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["scene_uid", "in_analysis_set"])
        w.writeheader(); w.writerows(full)
    msg = ""
    try:
        J.guard_partial(out, part, False)
    except SystemExit as exc:
        msg = str(exc)
    chk("a complete file is not replaced by a partial one", "--allow-partial" in msg, True)
    chk("...unless asked", J.guard_partial(out, part, True), None)
    chk("a complete result always writes", J.guard_partial(out, full, False), None)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

chk("04m: curator default reason", M.classify("too damaged to measure"), ("tissue_damaged", None))
chk("04m: review-mode reason", M.classify("excluded on review"), ("tissue_damaged", None))
chk("04m: curator export reason", M.classify("manually excluded: tissue too damaged to measure"), ("tissue_damaged", None))
chk("04m: focus reason still parses", M.classify("no resolvable nuclear detail (focus 0.061, threshold 0.1)"), ("out_of_focus", 0.061))

chk("04m: in set", M.fate({"in_analysis_set": "1", "reason": ""}), ("analysis_set", ""))
chk("04m: set aside", M.fate({"in_analysis_set": "0", "reason": "12% clipped"}), ("censored_out", "12% clipped"))
chk("04m: blank row is unmeasured", M.fate({"in_analysis_set": "", "reason": "no raw clipping mask"}),
    ("unmeasured", "no raw clipping mask"))
chk("04m: no row is unmeasured, not censored", M.fate(None),
    ("unmeasured", "no analysis-set row - 04j has not measured this section"))

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

- [x] **Step 2: Run, expect `AttributeError: module 'j' has no attribute 'unmeasured_row'`**

- [x] **Step 3: 04j** - add above `main()`:
```python
def unmeasured_row(uid, animal, section_order):
    """A section 01k has no raw mask for. Present in the file with a BLANK
    in_analysis_set, so 04m can say "unmeasured" rather than reading an absent
    row as censored - which is a false statement about clipping."""
    return {"scene_uid": uid, "animal": animal, "section_order": section_order,
            "censored_fraction": "", "censored_fraction_in_tissue": "",
            "recorded_saturated_fraction": "", "recorded_saturated_fraction_raw": "",
            "in_analysis_set": "", "reason": "no raw clipping mask - run 01k_saturation_raw.py"}


def is_complete(rows):
    return all(r["in_analysis_set"] != "" for r in rows)


def guard_partial(out_csv, rows, allow):
    """Refuse to replace a COMPLETE analysis set with a partial one.

    A 04j run on a half-built censor_raw/ used to shrink the set silently and
    every section it lacked became "censored" downstream. Now it stops, unless
    --allow-partial says the shrink is meant.
    """
    if allow or is_complete(rows) or not os.path.exists(out_csv):
        return None
    with open(out_csv, newline="", encoding="utf-8") as fh:
        old = list(csv.DictReader(fh))
    if old and is_complete(old):
        n_un = sum(1 for r in rows if r["in_analysis_set"] == "")
        raise SystemExit(f"{out_csv} is complete ({len(old)} rows) but this run has "
                         f"{n_un} unmeasured section(s). Run 01k_saturation_raw.py "
                         f"first, or pass --allow-partial to write anyway.")
    return None
```
In `main()`: add `ap.add_argument("--allow-partial", action="store_true", help="write the analysis set even if it has unmeasured sections and the file on disk is complete")`; replace lines 168-171
```python
        cen = censor_mask(uid)
        if cen is None:
            missing.append(uid)
            continue
```
with
```python
        cen = censor_mask(uid)
        if cen is None:
            missing.append(uid)
            rows.append(unmeasured_row(uid, animal, r["section_order"]))
            continue
```
change the message at line 204-205 from `were SKIPPED` to `are in the file as UNMEASURED (blank in_analysis_set)`; insert `guard_partial(out_csv, rows, args.allow_partial)` immediately before the `IO.atomic_write_csv(out_csv, rows, ANALYSIS_KEYS)` line; and in the stats (lines 213-233) use `keep = [r for r in rows if r["in_analysis_set"] == 1]`, `drop = [r for r in rows if r["in_analysis_set"] == 0]`, add `unmeasured = [r for r in rows if r["in_analysis_set"] == ""]` with a printed line `f"  unmeasured (no raw mask)                 : {len(unmeasured)}"`, and change the per-animal accumulator at line 233 to `d[1] += 1 if r["in_analysis_set"] == 1 else 0`.

- [x] **Step 4: 04m** - replace `classify()` lines 79-80
```python
    if reason.startswith("manually excluded"):
        return "tissue_damaged", None
```
with
```python
    # Three spellings of one decision: the curator export's prefix, 04a's
    # default when the export carried no reason (04a:469), and the Review
    # mode's default (04a:446).
    if (reason.startswith("manually excluded") or reason == "too damaged to measure"
            or reason == "excluded on review"):
        return "tissue_damaged", None
```
Add above `main()`:
```python
def fate(a):
    """(status, reason) for a section that is NOT excluded, from its analysis-set
    row. No row, or a blank in_analysis_set, is UNMEASURED - 04j has not seen a
    raw mask for it - and must not be reported as censored."""
    if a is None:
        return "unmeasured", "no analysis-set row - 04j has not measured this section"
    if a["in_analysis_set"] == "":
        return "unmeasured", a["reason"]
    if a["in_analysis_set"] == "1":
        return "analysis_set", ""
    return "censored_out", a["reason"]
```
and replace lines 123-127
```python
        elif a and a["in_analysis_set"] == "1":
            status, klass, value, reason = "analysis_set", "", None, ""
        else:
            status, klass, value = "censored_out", "", None
            reason = a["reason"] if a else ""
```
with
```python
        else:
            status, reason = fate(a)
            klass, value = "", None
```
Update the module docstring's three-fates list (lines 6-8) to four, adding `unmeasured    no 04j row yet, or no raw clipping mask - not a statement about clipping`, and add `'unmeasured':>11` to the per-animal table header and body at lines 188-193 (`c['unmeasured']`).

- [x] **Step 5: Run the test, expect `ALL PASS`**

- [x] **Step 6: Commit**

```
git add scripts/04j_censor_clipped.py scripts/04m_sections_dataset.py tests/test_analysis_set.py
git commit -m "04j/04m: unmeasured sections are recorded as such, never as censored

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 15: 00_manifest closes its zip handles and guards `sys.path`; 01b picks the middle file

**Files:**
- Modify: `scripts/00_manifest.py:33`, `:92-138` (`discover_sources`), `:433` (main); `scripts/01b_pick_sections.py:71-74`
- Test: `tests/test_stale_state.py`

`00_manifest.py:122` opens a `zipfile.ZipFile` per archive and stores closures over it in `entries`; nothing closes them, so the app (which runs stages in-process) keeps every archive open for the session. Line 33 inserts `scripts/` into `sys.path` unconditionally, once per import. `01b:72-74` computes `chosen_files = [files[int(i * stride)] ...]`, which for `n_files == 1` is always `files[0]` - the first slide of every animal, the opposite of the "spread" the docstring promises.

- [x] **Step 1: Write the failing test** `tests/test_stale_state.py`

```python
"""Handles closed, sys.path not duplicated, and a real middle pick.

Run:  python tests/test_stale_state.py
"""

import contextlib
import importlib.util
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


before = sys.path.count(SCRIPTS)
M = load("m1", "00_manifest.py")
load("m2", "00_manifest.py")
chk("loading 00_manifest twice adds scripts/ to sys.path at most once",
    sys.path.count(SCRIPTS) - before <= 1, True)

tmp = tempfile.mkdtemp(prefix="src_")
try:
    with open(os.path.join(tmp, "loose.czi"), "wb") as fh:
        fh.write(b"L")
    with zipfile.ZipFile(os.path.join(tmp, "arch.zip"), "w") as z:
        z.writestr("inner.czi", b"Z")
        z.writestr("notes.txt", b"n")
    M.SOURCE_DIR = tmp
    M.CONFIG["source_files"] = None
    with contextlib.ExitStack() as stack:
        entries = M.discover_sources(stack)
        chk("loose file then zip member", [e[1] for e in entries], ["loose.czi", "inner.czi"])
        with entries[1][3]() as fh:
            chk("the member opens while the stack is live", fh.read(), b"Z")
    closed = ""
    try:
        entries[1][3]()
    except ValueError as exc:
        closed = "closed" in str(exc)
    chk("the archive is closed with the stack", closed, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

B = load("b", "01b_pick_sections.py")
chk("one file from three is the middle one", B.pick_files(["a", "b", "c"], 1), ["b"])
chk("one file from one is that one", B.pick_files(["a"], 1), ["a"])
chk("two from five straddle the middle", B.pick_files(["a", "b", "c", "d", "e"], 2), ["b", "d"])
chk("all from all is all", B.pick_files(["a", "b", "c"], 3), ["a", "b", "c"])

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

- [x] **Step 2: Run, expect `TypeError: discover_sources() takes 0 positional arguments but 1 was given`**

- [x] **Step 3: 00_manifest** - replace line 33 `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` with
```python
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
```
Change line 92 to `def discover_sources(stack):`, extend its docstring with `` `stack` is a contextlib.ExitStack that owns every archive opened here; the openers are only valid while it is live. `` and replace lines 121-125
```python
        try:
            zf = zipfile.ZipFile(zpath)
        except zipfile.BadZipFile:
            print(f"  !! cannot open {zname}, skipping")
            continue
```
with
```python
        try:
            zf = stack.enter_context(zipfile.ZipFile(zpath))
        except zipfile.BadZipFile:
            print(f"  !! cannot open {zname}, skipping")
            continue
```
Add `import contextlib` to the imports, and in `main()` wrap the body from line 433 (`entries = discover_sources()`) to the end of the loop over `entries` (the `for source, member, container, opener in entries:` block) in `with contextlib.ExitStack() as stack:`, calling `entries = discover_sources(stack)`. Everything after that loop (the `section_order` pass, the three `_write_csv` calls, `_report`) sits outside the `with`, which is where the handles are released.

- [x] **Step 4: 01b** - add above `main()`:
```python
def pick_files(files, n_files):
    """`n_files` of `files`, evenly spread. Sampling at the CENTRE of each
    stride, so one file from a series is its middle slide - not the first,
    which is what `int(i * stride)` always returned for i = 0 and left every
    animal's tile-field sample on its most rostral slide."""
    stride = len(files) / n_files
    return [files[min(int((i + 0.5) * stride), len(files) - 1)] for i in range(n_files)]
```
and replace lines 73-74
```python
        stride = len(files) / n_files
        chosen_files = [files[min(int(i * stride), len(files) - 1)] for i in range(n_files)]
```
with
```python
        chosen_files = pick_files(files, n_files)
```

- [x] **Step 5: Run the test, expect `ALL PASS`**

- [x] **Step 6: Commit**

```
git add scripts/00_manifest.py scripts/01b_pick_sections.py tests/test_stale_state.py
git commit -m "00_manifest: archives closed by an ExitStack, sys.path guarded; 01b samples the middle slide

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 16: 06b resolves workbook columns by name; 06c/06d check config groups against 06b's metadata; a 12th plot shape

**Files:**
- Modify: `scripts/06b_join_sampling.py:61-63`, `:66-103` (`read_sheet`), `:122-124`, `:143-165`; `scripts/06c_excel_dataset.py:86-95` (`animal_environment`), `:149`; `scripts/06d_excel_by_slide.py:138`; `analysis/plot_roi_figures.R:133`, `:140-141`
- Test: `tests/test_join_metadata.py`

`06b:61-63` hard-codes column indices (`"treatment": 5`, `"sliced_july_2025": 17`). The live header row is `Fish ID, timepoint, enviroment, brackish Tank, sea water  tank, treatment, ... Body weight(g), Fork Length (cm), Sex, ..., Brain for, ..., slicing IHC July 2025, slicing MD MARCH 2026` - a column inserted before `treatment` silently reassigns every animal. `06c:149` and `06d:138` read `config.groups.by_animal` while 06b validates the workbook, so the two spreadsheets can carry a treatment the unblinding step never checked. `plot_roi_figures.R:133` lists 11 shapes and `:141` uses `rep_len`, so the twelfth animal silently repeats the first animal's mark.

- [x] **Step 1: Write the failing test** `tests/test_join_metadata.py`

```python
"""Workbook columns by name, groups checked against the unblinding, 12 shapes.

Run:  python tests/test_join_metadata.py
"""

import csv
import importlib.util
import os
import re
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


B = load("b", "06b_join_sampling.py")
# The live header, typos and double space included.
LIVE = {0: "Fish ID", 1: "timepoint", 2: "enviroment", 3: "brackish Tank", 4: "sea water  tank",
        5: "treatment", 6: "freshwater to brackish trasfer date", 7: "brackish to sea trasfer date",
        8: "Heart ID", 9: "Body weight(g)", 10: "Fork Length (cm)", 11: "Sex", 12: "Hearts in PFA",
        13: "Brain for", 14: "Stress test", 15: "notes", 16: "date", 17: "slicing IHC July 2025",
        18: "slicing MD MARCH 2026"}
col = B.resolve_columns(LIVE)
chk("live header resolves to the old indices",
    col, {"fish": 0, "timepoint": 1, "environment": 2, "brackish_tank": 3, "sea_tank": 4,
          "treatment": 5, "body_weight_g": 9, "fork_length_cm": 10, "sex": 11, "brain_for": 13,
          "sliced_july_2025": 17})
shifted = {0: "Fish ID", 1: "new column", **{k + 1: v for k, v in LIVE.items() if k > 0}}
chk("an inserted column moves every index", B.resolve_columns(shifted)["treatment"], 6)
msg = ""
try:
    B.resolve_columns({k: v for k, v in LIVE.items() if k != 5})
except SystemExit as exc:
    msg = str(exc)
chk("a missing column stops and is named", "treatment" in msg, True)

C = load("c", "06c_excel_dataset.py")
tmp = tempfile.mkdtemp(prefix="meta_")
try:
    meta = os.path.join(tmp, "animal_metadata.csv")
    chk("no metadata yet: config stands", C.resolve_groups({"LS1": "control"}, meta), {"LS1": "control"})
    with open(meta, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["animal", "treatment"])
        w.writeheader()
        w.writerows([{"animal": "LS1", "treatment": "control"}, {"animal": "LS2", "treatment": "exercise"}])
    chk("agreement: metadata fills what config lacks",
        C.resolve_groups({"LS1": "control"}, meta), {"LS1": "control", "LS2": "exercise"})
    msg = ""
    try:
        C.resolve_groups({"LS1": "exercise"}, meta)
    except SystemExit as exc:
        msg = str(exc)
    chk("disagreement fails and names the animal", "LS1" in msg and "06b" in msg, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

with open(os.path.join(REPO, "analysis", "plot_roi_figures.R"), encoding="utf-8") as fh:
    r_src = fh.read()
shapes = re.search(r"^SHAPES <- c\(([^)]*)\)", r_src, re.M).group(1)
chk("twelve distinct shapes", len(set(s.strip() for s in shapes.split(","))), 12)
fn = re.search(r"animal_shapes <- function\(levels_all\) \{(.*?)\n\}", r_src, re.S).group(1)
chk("animal_shapes stops on overflow", "stop(" in fn, True)
chk("...and no longer recycles", "rep_len" in fn, False)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

- [x] **Step 2: Run, expect `AttributeError: module 'b' has no attribute 'resolve_columns'`**

- [x] **Step 3: 06b** - replace lines 61-63 (`COL = {...}`) with
```python
# The columns this stage needs, by a prefix of the header cell after
# lower-casing and collapsing whitespace. The live sheet spells them
# "enviroment" and "sea water  tank"; the prefixes are chosen so a fixed typo
# still matches, and an inserted column moves the index rather than the
# meaning.
COLUMN_PREFIX = {"fish": "fish id", "timepoint": "timepoint", "environment": "enviro",
                 "brackish_tank": "brackish tank", "sea_tank": "sea water tank",
                 "treatment": "treatment", "body_weight_g": "body weight",
                 "fork_length_cm": "fork length", "sex": "sex", "brain_for": "brain for",
                 "sliced_july_2025": "slicing ihc july 2025"}


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def resolve_columns(header):
    """{key: column index} from the header row, or a SystemExit naming what is
    missing. Exactly one header cell may match each prefix."""
    cells = {i: _norm(v) for i, v in header.items()}
    out, bad = {}, []
    for key, prefix in COLUMN_PREFIX.items():
        hits = [i for i, v in cells.items() if v.startswith(prefix)]
        if len(hits) != 1:
            bad.append(f"{key} (header starting '{prefix}': {len(hits)} matches)")
        else:
            out[key] = hits[0]
    if bad:
        raise SystemExit("the sampling workbook's header does not match: " + "; ".join(bad))
    return out


def read_table(path):
    """(columns, data rows): the sheet with its header resolved."""
    rows = read_sheet(path)
    if not rows:
        raise SystemExit(f"{path}: the first worksheet is empty")
    return resolve_columns(rows[0]), rows[1:]
```
In `main()` replace lines 122-124
```python
    sheet = read_sheet(args.xlsx)[1:]
    fish = {r.get(COL["fish"], ""): r for r in sheet}
    sliced = {f for f, r in fish.items() if r.get(COL["sliced_july_2025"], "") == "x"}
```
with
```python
    COL, sheet = read_table(args.xlsx)
    fish = {r.get(COL["fish"], ""): r for r in sheet}
    sliced = {f for f, r in fish.items() if r.get(COL["sliced_july_2025"], "") == "x"}
```
(the remaining `COL[...]` uses at lines 143-165 now read the local.) Also switch the two `with open(META_CSV, "w"...)`/`DATASET_CSV` writes at lines 168-171 and 179-182 to `IO.atomic_write_csv(META_CSV, [meta[a] for a in animals], list(next(iter(meta.values())).keys()))` and `IO.atomic_write_csv(DATASET_CSV, out, list(out[0].keys()))` (add the IO import; `meas` is guarded non-empty by the file check at line 111, and `animals` is derived from it).

- [x] **Step 4: 06c** - replace lines 86-95 in `animal_environment()`
```python
    try:
        sheet = G6B.read_sheet(G6B.DEFAULT_XLSX)[1:]
    except Exception as exc:                                   # noqa: BLE001
        print(f"  (no environment: {exc})")
        return {}
    out = {}
    for r in sheet:
        fid = (r.get(G6B.COL["fish"], "") or "").strip()
        if fid.isdigit():
            out["LS" + fid] = (r.get(G6B.COL["environment"], "") or "").strip()
```
with
```python
    try:
        col, sheet = G6B.read_table(G6B.DEFAULT_XLSX)
    except Exception as exc:                                   # noqa: BLE001
        print(f"  (no environment: {exc})")
        return {}
    out = {}
    for r in sheet:
        fid = (r.get(col["fish"], "") or "").strip()
        if fid.isdigit():
            out["LS" + fid] = (r.get(col["environment"], "") or "").strip()
```
Add above `main()`:
```python
def resolve_groups(config_groups, meta_csv=None):
    """Treatment per animal. 06b is the unblinding step and validates the
    workbook; config.groups.by_animal is hand-typed. Where both exist they
    must agree, and the metadata fills in animals the config does not list."""
    meta_csv = meta_csv or G6B.META_CSV
    if not os.path.exists(meta_csv):
        return dict(config_groups)
    meta = {r["animal"]: r["treatment"] for r in G5.load_csv(meta_csv) if r.get("treatment")}
    clash = {a: (config_groups[a], meta[a]) for a in config_groups
             if a in meta and config_groups[a] != meta[a]}
    if clash:
        raise SystemExit(
            "config.groups.by_animal disagrees with results/animal_metadata.csv: "
            + ", ".join(f"{a}: config={c} workbook={m}" for a, (c, m) in sorted(clash.items()))
            + "\n  06b_join_sampling.py is the unblinding - fix config.json or rerun 06b.")
    return {**meta, **config_groups}
```
and change line 149 to `groups = resolve_groups((CONFIG.get("groups") or {}).get("by_animal") or {})`. In `06d:138` change to `groups = G6C.resolve_groups((CONFIG.get("groups") or {}).get("by_animal") or {})`.

- [x] **Step 5: R** - change `analysis/plot_roi_figures.R:133` to
```r
SHAPES <- c(21, 22, 23, 24, 25, 15, 16, 17, 18, 8, 14, 11)
```
(11 is the two-triangle star, distinct from 8 and 14 at PT 4.6), update the comment above it from "Eleven animals need eleven marks" to "Twelve animals need twelve marks", and replace lines 140-141
```r
animal_shapes <- function(levels_all) setNames(
  rep_len(SHAPES, length(levels_all)), levels_all)
```
with
```r
animal_shapes <- function(levels_all) {
  # Never recycle: a thirteenth animal drawn with the first animal's mark is a
  # figure that lies quietly. Add a shape here instead.
  if (length(levels_all) > length(SHAPES))
    stop(sprintf("%d animals but only %d shapes in SHAPES - add one", length(levels_all), length(SHAPES)))
  setNames(SHAPES[seq_along(levels_all)], levels_all)
}
```

- [x] **Step 6: Run the test, expect `ALL PASS`**; then `work/appenv/Scripts/python.exe tests/test_roi_dataset.py` still passes (it loads 06c).

- [x] **Step 7: Commit**

```
git add scripts/06b_join_sampling.py scripts/06c_excel_dataset.py scripts/06d_excel_by_slide.py analysis/plot_roi_figures.R tests/test_join_metadata.py
git commit -m "06b columns by name; 06c/06d groups checked against the unblinding; 12 plot shapes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 17: 06e - version-sorted Rscript, UTF-8 subprocess output, a stall counter that counts readings

**Files:**
- Modify: `scripts/06e_refresh_loop.py:23-30` (add `import re`), `:80-84`, `:160-161`, `:186`, `:208-216`
- Test: `tests/test_refresh_loop.py`

`06e:82-84` sorts `C:\Program Files\R\R-*\bin\Rscript.exe` lexically and takes the last, so `R-4.9.1` beats `R-4.10.0`. `:160-161` runs Rscript with `text=True` and no encoding, so a non-cp1252 byte in R's stderr raises `UnicodeDecodeError` inside the loop. `:210-212` sets `stalled = stalled + 1 if done == last else 0` with `last = None` on the first pass, so `--stall-cycles 3` needs four identical readings (three hours at the default interval) before it stops.

- [x] **Step 1: Write the failing test** `tests/test_refresh_loop.py`

```python
"""06e: Rscript by version, and a stall that counts readings.

Run:  python tests/test_refresh_loop.py
"""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

_spec = importlib.util.spec_from_file_location("e", os.path.join(SCRIPTS, "06e_refresh_loop.py"))
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


chk("version parsed from the path", E.rscript_version(r"C:\Program Files\R\R-4.10.0\bin\Rscript.exe"), (4, 10, 0))
chk("no version -> lowest", E.rscript_version(r"C:\x\Rscript.exe"), (0, 0, 0))
hits = [r"C:\Program Files\R\R-4.9.1\bin\Rscript.exe", r"C:\Program Files\R\R-4.10.0\bin\Rscript.exe",
        r"C:\Program Files\R\R-4.6.0\bin\Rscript.exe"]
chk("newest by version, not by name", E.newest(hits), hits[1])

# Readings 100, 100, 100 with --stall-cycles 3 stop on the THIRD reading.
stalled, last = 0, None
seen = []
for done in (100, 100, 100):
    stalled = E.stall_count(stalled, done, last)
    last = done
    seen.append(stalled)
chk("three identical readings count three", seen, [1, 2, 3])
chk("progress resets the count", E.stall_count(3, 101, 100), 1)

with open(os.path.join(SCRIPTS, "06e_refresh_loop.py"), encoding="utf-8") as fh:
    src = fh.read()
chk("Rscript output is decoded as UTF-8", 'encoding="utf-8", errors="replace"' in src, True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
```

- [x] **Step 2: Run, expect `AttributeError: module 'e' has no attribute 'rscript_version'`**

- [x] **Step 3: Implement** - add `import re` to the imports; add above `find_rscript()`:
```python
def rscript_version(path):
    """(major, minor, patch) from an `R-x.y.z` path component; (0,0,0) if none."""
    m = re.search(r"R-(\d+)\.(\d+)\.(\d+)", path)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def newest(hits):
    """The highest-versioned Rscript. Sorting the paths as text put R-4.9.1
    after R-4.10.0."""
    return max(hits, key=rscript_version)
```
replace lines 82-84
```python
    hits = sorted(glob.glob(pattern))
    if hits:
        return hits[-1]           # newest version by name
```
with
```python
    hits = glob.glob(pattern)
    if hits:
        return newest(hits)
```
replace lines 160-161
```python
            r = subprocess.run([rscript, script], cwd=_REPO, env=env,
                               capture_output=quiet, text=True)
```
with
```python
            # R writes UTF-8 (a degree sign in a caption, an em dash in a
            # warning); the console codepage is not. Decode explicitly, and
            # never let a stray byte take the loop down.
            r = subprocess.run([rscript, script], cwd=_REPO, env=env,
                               capture_output=quiet, text=True,
                               encoding="utf-8", errors="replace")
```
add above `main()`:
```python
def stall_count(stalled, done, last):
    """Consecutive readings at the same count, the current one included.

    Three identical readings ARE three stalled cycles; counting from the
    second made --stall-cycles 3 wait for a fourth, an hour later.
    """
    return stalled + 1 if last is not None and done == last else 1
```
and replace lines 210-213
```python
        stalled = stalled + 1 if done == last else 0
        last = done
        if stalled >= args.stall_cycles:
            print(f"\nSTALLED: {done}/{total} unchanged for {stalled} cycles. "
```
with
```python
        stalled = stall_count(stalled, done, last)
        last = done
        if stalled >= args.stall_cycles:
            print(f"\nSTALLED: {done}/{total} unchanged over {stalled} readings. "
```

- [x] **Step 4: Run the test, expect `ALL PASS`**

- [x] **Step 5: Run everything once more**

```
bash tests/run.sh 2>&1 | tail -3
```
Expected: `ALL SUITES PASS`.

- [x] **Step 6: Commit**

```
git add scripts/06e_refresh_loop.py tests/test_refresh_loop.py
git commit -m "06e: Rscript picked by version, UTF-8 output, stall counted in readings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review

Every review claim was checked against the working tree on 2026-09-03. Findings that changed the plan:

- **Item 2, "01k:~330 rows[0].keys()" - false as stated.** `01k_saturation_raw.py` never indexes `rows[0]`; its CSV writer is `atomic_write()` with an explicit `KEYS` list. The empty-input crash there is `raw.max()` on an empty array at `:330-336` (`np.median` warns, `.max()` raises `ValueError`). Task 11 guards that instead.
- **Item 8, "a proposal becomes 'manual'" - label inaccurate, defect real.** After `toggleExclude()` copies `symOf(uid)` into the record (`04d:219-223`), `exportCsv` at `:402-404` reports `manual_overrode_auto` (the `SYM[d.uid]` branch), not `manual`. Task 9 fixes the underlying copy either way.
- **Item 1, "04m (~:170), 04p (~:379)" - not `rows[0].keys()` sites.** Both already write with an explicit `COLUMNS` list; they are adopted in Task 2 for atomicity only, not for an empty-input crash.
- **Item 10, 04g** - `--limit N` (`04g:251`, `:311-312`) already truncates the index, so "stop after N" for `--preview` is implemented as a preview-specific break rather than by reusing `--limit`, which would also stop a normal run early.
- **Line drift.** `01_overviews` `ranges[marker]` is at `:274` (review said ~271); `04l`'s `__SEED__`/`__PROV__` replacements are at `:3779-3787` (review said ~3762-3770); `04l`'s form-control bail is at `:2089-2094` (review said ~1978); `04d`'s `title=` is at `:354` (review said ~351); `04l` `adoptSeed` is at `:2293-2300` (review said ~2276-2280); `04l` `status()` is at `:1621` (review said ~1605); `04l` `select()` is at `:1831` (review said ~930 - that number is `st()` at `:933`). All are the same code, shifted by the Tier 1 edits.
- **Item 7, "S init (~:845) treats blank records as work"** - confirmed at `:845-851`, but the root cause is `select()` -> `st(uid)` (`:1852`) followed by `onSlide()` -> `save()` (`:1818`), so Task 10 prunes at `save()` and in `initState()` rather than changing `select()`, which needs the in-memory record while the section is on screen. `tests/rotation.test.js:57` asserted that a restored (zero) tilt lands on disk; under the new rule a zero tilt on an otherwise-undecided section stores nothing, and that assertion is updated in the same task.
- **Item 13, 06b** - the live header row was read from the workbook (`06b.read_sheet(DEFAULT_XLSX)[0]`) to write `COLUMN_PREFIX` against the real spellings (`enviroment`, `sea water  tank`); the prefixes in Task 16 match those cells exactly and would also match the corrected spellings.

No review item was found to be entirely false; none was dropped.

## Addendum (2026-09-03, after Tier 2)

- `app/import_exports.py` `rebuild(..., k=3.0)` assumes every section was shown at 768 px. Since the ROI curator now stamps a frame per record and exports in canonical 256-px units regardless, a rebuild from CSV should set `k` per section from whether a composite exists (`sections_AF568_rgb/<uid>.png` or `sections_rgb/<uid>.png`), the rule `04q_import_curation.py` already applies, and write `frame` on the record. Add as a task beside Task 10.
- Task 11's 04j items: 04j now emits `gate` and reads the 04p tissue mask; the "row for uids with no raw mask" and `--allow-partial` parts of Task 14 still apply.
