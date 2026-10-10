# Channels part 2 — marker naming, the composite, and layout awareness

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the marker dimension a study setting rather than the literals
`AF568` and `AF488`, so a lab with different markers gets correct output paths,
column values and composites — while every LS path and column stays
byte-identical.

**Architecture:** One function, `ls_channels.marker_names(cfg)`, becomes the
single source of the marker list, layout-aware: under `multiplex` it reads the
declared channel table, under `paired` it reads a new `acquisition.markers`
list. Every `("AF568", "AF488")` tuple, every `choices=["AF568","AF488"]` and
every `MARKER_PLANE` dict is replaced by a call to it. The LS study declares
`markers: ["AF568","AF488"]`, so every derived constant resolves to what it is
today — which is exactly what P0's constants probe checks, mechanically, across
all 45 stages.

**Tech Stack:** Python 3.13 (`work/appenv/Scripts/python.exe`), plain-script
tests (no pytest anywhere in this repo), `tests/_stage_probe.py` for the
regression guarantee.

---

## Two things the spec did not settle

Both were found by reading the code rather than the spec, and both change what
gets built. They are recorded here because the spec is otherwise the authority.

**1. Under `paired` there is no channel table, so there is no marker list.**

The spec says, correctly, that `paired` "declares **no** channel table, because
it cannot: each LS scan carries DAPI plus whichever marker that pass used". It
then says the marker's identity is the name the operator gives it in that table.
For `paired`, those two statements leave the marker list with nowhere to come
from. `ls_channels.markers()` on the LS config returns `[]` today.

The list has to exist: `05a.MARKERS`, `01k.MASK_MARKERS`, `04a`'s `--marker`
choices and `04o.MARKER_PLANE` are all module-level constants built from it.

Rejected: **derive it from the manifest's `marker_channel` column.** The values
are there (`AF488` 1381 scenes, `AF568` 1191), but every one of those constants
is evaluated at *import*, and the manifest lives in `out_root`, which may be
absent, unwritten, or on an unplugged drive. P0 spent a task making a missing
path warn instead of killing all 45 stages at import; reading a CSV out of
`out_root` at import time would put that back, and worse — stage 00 *writes*
the manifest, so stage 00 would depend on its own output to import.

Chosen: **a new `acquisition.markers` key**, an ordered list of names. Declared,
validated, documented and generated like every other key. Under `multiplex` it
must be absent — the channel table already says what the markers are, and two
sources would drift. Under `paired` it is what the study declares.

**2. Adding the key and editing the live config must be ONE task.**

This is the trap that broke Tasks 3–7 during plan 1. `config.json` is
gitignored and holds the live study. The moment `acquisition.markers` exists in
`SPEC` with a paired-layout validation rule, the live config — which does not
have the key — becomes invalid, and *every stage fails at import*, because they
all validate on load. So Task 1 adds the key **and** writes it into
`config.json` **and** takes a backup, in that one task. Do not split it.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `scripts/ls_channels.py` | the channel model | **+** `marker_names(cfg)`, `LAYOUT_MULTIPLEX/PAIRED`; validation of `acquisition.markers` |
| `scripts/ls_config.py` | the key spec | **+** `acquisition.markers` Key |
| `scripts/05a_roi_geometry.py` | per-marker geometry paths, `all_boxes()` | `MARKERS` from config; uid guard becomes layout-aware |
| `scripts/04a_reformat.py` | per-marker reformat paths | `marker_paths()`, `--marker` choices from config |
| `scripts/04g`, `04j`, `04l`, `04o` | `--marker` argparse choices | choices from config |
| `scripts/01k_saturation_raw.py` | `MASK_MARKERS` | from config |
| `scripts/04o_section_rgb.py` | the composite | `MARKER_PLANE` → `display.composite`, generic |
| `scripts/ls_layouts.py` | **new** — which stages apply to which layout | the data half of `Stage.layouts` |
| `app/stages.py` | the stage list | **+** `layouts` field — **BLOCKED**, Task 10 |
| `tests/test_marker_names.py` | **new** | the marker list, both layouts |
| `tests/test_composite.py` | **new** | plane assignment and `display.composite` |
| `tests/test_layouts.py` | **new** | every numbered script applies to ≥1 layout |

---

## The regression guarantee

This plan changes ~20 files of path- and column-building code. The protection is
the constants probe built in P0 (`tests/_stage_probe.py`): import all 45 stages
and compare every derived module-level constant, before and after.

For LS, `marker_names(cfg)` must return exactly `["AF568", "AF488"]` — the same
tuple the literals gave — so **every path constant must be identical**. Not
"close": identical. A single differing constant means a stage is about to read
or write a different file on a drive holding 130 curated sections.

Run it after every task that touches a stage:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: `no stage derives anything different from the migrated study`.

---

## Task 1: `acquisition.markers` — the key, the validation, and the live config

**Files:**
- Modify: `scripts/ls_config.py` (SPEC, after the `acquisition.channels` Key at :246)
- Modify: `scripts/ls_channels.py`
- Modify: `config.json` (gitignored — the live LS study)
- Test: `tests/test_marker_names.py` (create)

- [ ] **Step 1: Back up the live config before touching anything**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && cp config.json config.json.before-markers && ls config.json.before-markers
```

`.gitignore` already covers `config.json.*`, so this backup cannot be committed.
Confirm that before moving on:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git status --short config.json.before-markers
```

Expected: **no output**. If the file is listed, stop — the backup would be
committed, and it holds absolute paths and the unblinding key.

- [ ] **Step 2: Write the failing test**

Create `tests/test_marker_names.py`:

```python
"""The marker list, which is layout-aware.

Under multiplex the channel table already says what the markers are. Under
paired there is no channel table - each scan carries the nuclear channel plus
one marker - so the study declares the list. Two sources for one fact is how
they drift, so each layout has exactly one.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_channels as CH                                    # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


print("--- multiplex: the channel table is the list ---")

MULTI = {"acquisition": {"layout": "multiplex", "channels": [
    {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
    {"name": "pERK", "role": "marker", "czi_name": "AF568", "index": 1},
    {"name": "PCNA", "role": "marker", "czi_name": "AF488", "index": 2}]}}

chk("markers come from the table, in declared order",
    CH.marker_names(MULTI), ["pERK", "PCNA"])
chk("the nuclear channel is not a marker",
    "DAPI" in CH.marker_names(MULTI), False)

print()
print("--- paired: the study declares the list ---")

PAIRED = {"acquisition": {"layout": "paired",
                          "markers": ["AF568", "AF488"]}}

chk("markers come from acquisition.markers",
    CH.marker_names(PAIRED), ["AF568", "AF488"])
chk("declared order is preserved",
    CH.marker_names({"acquisition": {"layout": "paired",
                                     "markers": ["AF488", "AF568"]}}),
    ["AF488", "AF568"])

print()
print("--- the two sources may not both be used ---")

both = {"acquisition": {"layout": "multiplex", "markers": ["X"], "channels": [
    {"name": "DAPI", "role": "nuclear", "index": 0},
    {"name": "pERK", "role": "marker", "index": 1}]}}
errors, _ = CH.validate(both["acquisition"], "multiplex")
chk("multiplex declaring acquisition.markers is an error",
    any("markers" in e for e in errors), True)

errs, _ = CH.validate({"layout": "paired", "markers": []}, "paired")
chk("paired with no markers is an error",
    any("markers" in e for e in errs), True)

errs, _ = CH.validate({"layout": "paired", "markers": ["A", "A"]}, "paired")
chk("a duplicate marker name is an error",
    any("twice" in e or "duplicate" in e for e in errs), True)

errs, _ = CH.validate({"layout": "paired", "markers": "AF568"}, "paired")
chk("a string instead of a list is judged, not crashed on",
    any("markers" in e for e in errs), True)

errs, _ = CH.validate({"layout": "paired", "markers": ["AF568"],
                       "channels": [{"name": "DAPI", "role": "nuclear",
                                     "index": 0}]}, "paired")
chk("paired declaring a channel table is an error",
    any("channel" in e.lower() for e in errs), True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 3: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_marker_names.py
```

Expected: `AttributeError: module 'ls_channels' has no attribute 'marker_names'`.

- [ ] **Step 4: Add `marker_names` and the layout constants to `ls_channels.py`**

Add just below the existing role constants (after line 25, `BACKENDS = ...`):

```python
# The two acquisition layouts, so no caller writes the string itself.
LAYOUT_MULTIPLEX, LAYOUT_PAIRED = "multiplex", "paired"
LAYOUTS = (LAYOUT_MULTIPLEX, LAYOUT_PAIRED)
```

Add after `markers()` (which ends at line 85):

```python
def marker_names(cfg):
    """The markers this study measures, in declared order, as plain names.

    Layout-aware because the two layouts genuinely know it differently:

      multiplex  one scan carries every marker, so the channel table says
                 which channels are markers and what they are called.
      paired     each scan carries the nuclear channel plus ONE marker, so
                 there is no table to read - the study declares the list.

    Deliberately NOT derived from the manifest's marker_channel column, though
    the values are there. Every caller of this is a module-level constant
    evaluated at import, the manifest lives under out_root, and out_root may be
    absent or on an unplugged drive - which is the exact failure P0 removed by
    making a missing path warn rather than kill all 45 stages at import. Stage
    00 also WRITES the manifest, so it would depend on its own output to
    import.
    """
    acq = (cfg or {}).get("acquisition") or {}
    if not isinstance(acq, dict):
        return []
    if acq.get("layout") == LAYOUT_PAIRED:
        declared = acq.get("markers") or []
        # A string is iterable, so list("AF568") would "succeed" and give six
        # single-letter markers. Judged, not crashed on and not accepted.
        if not isinstance(declared, (list, tuple)):
            return []
        return [str(m) for m in declared]
    return [c.name for c in markers(parse(acq.get("channels")))]
```

- [ ] **Step 5: Extend `validate()` to judge the new key**

`ls_channels.validate(block, layout)` already returns `(errors, warnings)` and
accumulates every fault rather than short-circuiting — keep that. Add, near the
top of the function body, before the channel-table checks:

```python
    declared = block.get("markers") if isinstance(block, dict) else None
    if declared is not None and not isinstance(declared, (list, tuple)):
        errors.append(
            f"`acquisition.markers` must be a list of marker names, not a "
            f"{type(declared).__name__}. A string would be read one letter at "
            f"a time.")
        declared = None

    if layout == LAYOUT_PAIRED:
        if not declared:
            errors.append(
                "`acquisition.markers` must name this study's markers. A "
                "paired study declares no channel table - each scan carries "
                "the nuclear channel plus one marker - so this list is the "
                "only record of what those markers are.")
        else:
            seen = set()
            for m in declared:
                if m in seen:
                    errors.append(
                        f"marker {m!r} is declared twice in "
                        f"`acquisition.markers`. Output paths are built from "
                        f"these names, so a repeat would have two markers "
                        f"writing to one file.")
                seen.add(m)
                if not NAME_RE.match(str(m)):
                    errors.append(
                        f"marker name {m!r} is not usable in a file path. "
                        f"Use letters, digits, spaces, and . _ + - only.")
        if block.get("channels"):
            errors.append(
                "a `paired` study declares no channel table: each of its "
                "scans carries the nuclear channel plus whichever marker that "
                "pass used, so there is no fixed table to write. Use "
                "`acquisition.markers` to name the markers.")
    elif declared:
        errors.append(
            "`acquisition.markers` applies to `paired` studies only. Under "
            "`multiplex` the channel table already says which channels are "
            "markers, and two sources for one fact is how they drift.")
```

Note the existing "nothing to measure" check must not fire for a paired study —
it is about the channel table. Guard it with `if layout == LAYOUT_MULTIPLEX:`
if it does not already only run there.

- [ ] **Step 6: Add the Key to `SPEC` in `ls_config.py`**

Immediately after the `acquisition.channels` Key (it ends around :262):

```python
    Key("acquisition.markers", "raw",
        "The markers a `paired` study measures, in the order they should "
        "appear. Not used under `multiplex`.",
        default=[], label="Markers (paired only)",
        note="A paired study declares no channel table, because each of its "
             "scans carries the nuclear channel plus whichever marker that "
             "pass used - so this list is the only record of what the markers "
             "are. It is NOT derived from the manifest's marker_channel "
             "column: every constant built from it is evaluated at import, "
             "and the manifest lives under out_root, which may be absent. "
             "Output paths, CSV column values and workbook sheets are built "
             "from these names, so changing one renames real files.",
        example=[],
        consumers=["01k_saturation_raw", "04a_reformat", "04g_artifact_mask",
                   "04j_censor_clipped", "04l_roi_curator", "04o_section_rgb",
                   "05a_roi_geometry"]),
```

`example=[]` is correct here and is *not* the trap that `acquisition.channels`
hit: the generated `config.example.json` is a **multiplex** template, and under
multiplex an empty `markers` is not merely allowed, it is required.

- [ ] **Step 7: Write the key into the live config**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import json, io
p = 'config.json'
cfg = json.load(io.open(p, encoding='utf-8'))
cfg.setdefault('acquisition', {})['markers'] = ['AF568', 'AF488']
io.open(p, 'w', encoding='utf-8').write(json.dumps(cfg, indent=2) + '\n')
print(cfg['acquisition'])
"
```

Expected: `{'layout': 'paired', 'channels': [], 'markers': ['AF568', 'AF488']}`.

`AF568` first: it is `05a`'s current `MARKER = "AF568"` default and the order
`MARKERS = ("AF568", "AF488")` gives. Order reaches `all_boxes()`'s row order
and therefore `roi_index`. Reversing it would renumber every disc.

- [ ] **Step 8: Confirm the live config still loads and still validates**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/ls_config.py --check
```

Expected: no errors. Warnings about the eleven retired keys are expected and
unrelated.

- [ ] **Step 9: Run the new test and the neighbours it could break**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_marker_names.py && work/appenv/Scripts/python.exe tests/test_ls_channels.py && work/appenv/Scripts/python.exe tests/test_ls_config.py && work/appenv/Scripts/python.exe tests/test_config_example.py
```

Expected: `ALL PASS` from each.

- [ ] **Step 10: Regenerate the example and the docs table**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/ls_config.py --write-example && work/appenv/Scripts/python.exe scripts/ls_config.py --docs
```

- [ ] **Step 11: Prove no stage moved**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: zero differing constants. Nothing consumes the key yet, so anything
else means the SPEC addition itself changed a derived value.

- [ ] **Step 12: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/ls_channels.py scripts/ls_config.py tests/test_marker_names.py config.example.json docs/config-reference.md && git commit -m "acquisition.markers: where a paired study's marker list lives

The spec says a paired study declares no channel table, and that a marker's
identity is the name the operator gives it in that table. For paired those two
leave the marker list with nowhere to come from - ls_channels.markers() returns
[] on the LS config - while 05a.MARKERS, 01k.MASK_MARKERS and four argparse
choices all need it at import.

Not derived from the manifest's marker_channel column, though the values are
there: every constant built from this is evaluated at import, the manifest
lives under out_root, and out_root may be absent - the exact failure P0 removed
by making a missing path warn instead of killing all 45 stages. Stage 00 also
writes the manifest, so it would depend on its own output to import.

The live config gained markers: [AF568, AF488] in this same change. Adding a
validated key without it would have made the live study invalid at import, and
every stage validates on load - the failure that broke tasks 3-7 of plan 1.
config.json is gitignored, so it is not in this commit.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: `05a_roi_geometry` reads the marker list

`05a` is first because it owns `MARKERS`, `resolve_paths()` and `all_boxes()` —
the uid-collision guard every downstream join depends on. Six stages import it.

**Files:**
- Modify: `scripts/05a_roi_geometry.py:110-193`
- Test: `tests/test_roi_geometry.py` (extend)

- [ ] **Step 1: Know what config this suite actually runs under**

**Read this before writing the test.** `tests/test_roi_geometry.py` calls
`use_temp_study()` at :36 and loads `05a_roi_geometry.py` as **`G5`** (not
`GEO`). The temp study is built from `config.example.json`, which is
**`multiplex` with ONE marker named `Marker1`**. So under this suite:

```
G5.MARKERS  ==  ("Marker1",)          not ("AF568", "AF488")
G5.MARKER   ==  "Marker1"
```

Asserting the LS markers here would fail, and "fixing" it by pointing the suite
at the live config would undo the reason `use_temp_study` exists — the suite
would then pass or fail on the operator's data. **The LS-specific claim belongs
to the constants probe (Step 6), which does run against the live study.**

The suite's `chk` is `chk(label, got, want)` comparing `str(got) == str(want)`
and incrementing a module-level `fails`; there is no `failures` list and no
`_raises`. Match it.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_roi_geometry.py`, before its exit lines:

```python
print()
print("--- the marker list comes from the study, not from a literal ---")

import ls_channels as _CH                                   # noqa: E402


def _raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


chk("05a's markers are the configured ones",
    list(G5.MARKERS), _CH.marker_names(G5.CONFIG))
chk("...which for this temp study is the example's one marker",
    list(G5.MARKERS), ["Marker1"])
chk("the default marker is the first declared",
    G5.MARKER, G5.MARKERS[0])
chk("an unknown marker is still refused",
    _raises(lambda: G5.use_marker("nope"), ValueError), True)
```

- [ ] **Step 3: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_roi_geometry.py
```

Expected: FAIL on `05a's markers are the configured ones` — `G5.MARKERS` is
the literal tuple and `marker_names` is not consulted.

- [ ] **Step 4: Replace the literal**

In `scripts/05a_roi_geometry.py`, replace line 123
(`MARKERS = ("AF568", "AF488")`) with:

```python
MARKERS = tuple(CH.marker_names(CONFIG))
```

and add the import beside the existing `ls_config` import at the top of the
module:

```python
import ls_channels as CH
```

Keep the comment block above it (lines 110-122) — it explains why the paths are
per-marker and why the uids must be disjoint, which is still true. Extend its
last paragraph so it does not name only the LS markers:

```python
# The markers of a `paired` study have DISJOINT scene_uids - they are separate
# acquisitions - so the two files never overlap and downstream stages that want
# everything can simply read both. Under `multiplex` they are the SAME scan, so
# the uids collide by construction; all_boxes() knows the difference.
```

- [ ] **Step 5: Make `MARKER` the first declared marker, not a literal**

Replace line 151 (`MARKER = "AF568"`) with:

```python
# The first declared marker is the default, so a study that declares one marker
# needs no --marker anywhere. For LS that is AF568, which is what this was.
MARKER = MARKERS[0] if MARKERS else None
```

`resolve_paths()`'s legacy-file branch at :146 tests `marker == "AF568"`. That
literal is correct and must stay — it names files that exist on the operator's
drive from before 2026-09-01. Change only its comment to say so:

```python
    # The literal is deliberate: these are files that exist on disk from before
    # 2026-09-01, under that exact name. It is a fact about this out_root, not
    # a fact about the study's markers.
```

- [ ] **Step 6: Run the test**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_roi_geometry.py
```

Expected: all `ok`, `fails` zero.

- [ ] **Step 7: Prove no stage moved — this is where the LS claim is checked**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: zero differences. The probe runs against the **live** study, so this
is the step that proves `MARKERS == ("AF568", "AF488")` for LS. `GEOM_CSV` and
`BOX_CSV` are derived from `MARKER`, so a wrong order shows up immediately as
two changed paths.

- [ ] **Step 8: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/05a_roi_geometry.py tests/test_roi_geometry.py && git commit -m "05a: the marker list is the study's, not a literal

MARKERS and MARKER now come from acquisition.markers. For LS they resolve to
exactly what the literals gave, which the constants probe checks across all 45
stages rather than this test asserting it alone.

resolve_paths keeps its AF568 literal: that branch names files that exist on
the operator's drive from before 2026-09-01, so it is a fact about this
out_root and not about the study's markers.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: `all_boxes()`'s uid guard becomes layout-aware

The spec names this the one change that could **corrupt a join rather than
fail**, so it gets its own task and its own colliding fixture under both
layouts.

Under `paired` a shared `scene_uid` across markers means two markers' boxes
interleave and every nucleus on that section is measured against the wrong disc
— silently. Under `multiplex` the markers are the same scan, so a shared uid is
the expected state.

**Files:**
- Modify: `scripts/05a_roi_geometry.py:165-193`
- Test: `tests/test_roi_geometry.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_roi_geometry.py`:

```python
print()
print("--- the uid-collision guard knows which layout it is in ---")

# Rows shaped like roi_boxes_*.csv: the guard only looks at scene_uid.
COLLIDE = [{"scene_uid": "X_s01a_sc00", "roi_index": "0"}]


def _boxes_under(layout, rows_by_marker):
    """all_boxes() with the file reads faked, under a chosen layout."""
    real_load, real_exists = GEO.load_csv, os.path.exists
    real_markers, real_layout = GEO.MARKERS, GEO.LAYOUT
    try:
        GEO.MARKERS = tuple(rows_by_marker)
        GEO.LAYOUT = layout
        GEO.load_csv = lambda p: rows_by_marker[os.path.basename(p)]
        os.path.exists = lambda p: True
        GEO.resolve_paths = lambda m: (m, m)
        return GEO.all_boxes()
    finally:
        GEO.load_csv, os.path.exists = real_load, real_exists
        GEO.MARKERS, GEO.LAYOUT = real_markers, real_layout


both = {"A": list(COLLIDE), "B": list(COLLIDE)}
chk("paired: a shared uid is still a hard stop",
    _raises(lambda: _boxes_under("paired", both), SystemExit), True)
chk("multiplex: a shared uid is the expected state",
    len(_boxes_under("multiplex", both)), 2)

apart = {"A": [{"scene_uid": "P_s01a_sc00", "roi_index": "0"}],
         "B": [{"scene_uid": "Q_s01a_sc00", "roi_index": "0"}]}
chk("paired: disjoint uids pass, as they always did",
    len(_boxes_under("paired", apart)), 2)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_roi_geometry.py
```

Expected: FAIL on `multiplex: a shared uid is the expected state` — the guard
raises `SystemExit` unconditionally.

- [ ] **Step 3: Add the layout constant and make the guard conditional**

Add beside `MARKERS` in `scripts/05a_roi_geometry.py`:

```python
LAYOUT = (CONFIG.get("acquisition") or {}).get("layout", CH.LAYOUT_MULTIPLEX)
```

In `all_boxes()`, replace the unconditional check (lines 183-191) with:

```python
        for r in rows:
            u = r["scene_uid"]
            # THE DISJOINTNESS IS CHECKED, NOT ASSUMED - under `paired`. 06a
            # joins a nucleus to its disc by (scene_uid, roi_index), where the
            # index is the position of the box in this list for that uid. If
            # two PAIRED markers ever shared a uid their boxes would interleave
            # and every nucleus on that section would be measured against the
            # wrong disc - silently, with plausible numbers.
            #
            # Under `multiplex` the markers are one scan of one section, so a
            # shared uid is what the data IS. The union below is then a
            # concatenation of the same sections' boxes, and roi_index stays
            # meaningful because each marker's boxes keep their own order.
            if LAYOUT == CH.LAYOUT_PAIRED and uids.get(u, m) != m:
                raise SystemExit(
                    f"scene_uid {u} appears under both {uids[u]} and {m}. "
                    f"Under the `paired` layout the per-marker box files must "
                    f"not overlap - every downstream join is by (scene_uid, "
                    f"roi_index) and would silently pair nuclei with the wrong "
                    f"discs. If these markers are one multi-channel scan, the "
                    f"study's acquisition.layout should be `multiplex`.")
            uids[u] = m
        out.extend(rows)
```

- [ ] **Step 4: Run the test**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_roi_geometry.py
```

Expected: `ALL PASS`, including `paired: a shared uid is still a hard stop`.
That one is the regression guard for LS and must never go green by accident —
if it passes while the multiplex case also passes, the branch is real.

- [ ] **Step 5: Prove no stage moved, and run the joins that depend on it**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py && bash tests/run.sh 2>&1 | tail -5
```

Expected: zero constant differences; `SUITE FAILURES` only from the known
pre-existing `test_join_metadata.py` (the owner's uncommitted
`analysis/plot_roi_figures.R` edit removed `SHAPES`). **Any other failing suite
is yours.**

- [ ] **Step 6: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/05a_roi_geometry.py tests/test_roi_geometry.py && git commit -m "05a: the uid guard knows which layout it is in

Under paired, two markers sharing a scene_uid means their boxes interleave and
every nucleus on that section is measured against the wrong disc, silently -
so that stays a hard stop. Under multiplex the markers ARE one scan of one
section, so a shared uid is what the data is, not a fault.

The spec names this the one change here that could corrupt a join rather than
fail, so it has a deliberately colliding fixture under both layouts. The paired
case must keep failing; if it ever passes, the branch has swallowed the guard.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: the four `--marker` argparse choices

Five stages hardcode `choices=["AF568", "AF488"]` (or the reverse order) and
two of them hardcode a `LABEL` dict mapping the fluorophore to a display name.
`04o` is left to Task 6, which rewrites it more deeply.

**Files:**
- Modify: `scripts/04a_reformat.py:566-567`
- Modify: `scripts/04g_artifact_mask.py` (its `--marker` argument)
- Modify: `scripts/04j_censor_clipped.py:151,297-298`
- Modify: `scripts/04l_roi_curator.py:4668,4751,4756`
- Test: `tests/test_marker_choices.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_marker_choices.py`:

```python
"""No stage offers a fixed list of markers.

A stage whose --marker choices are a literal cannot be pointed at a study with
different markers: argparse rejects the value before any code runs, so the
failure is a usage error about an unrelated fluorophore.
"""

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


# A choices= list holding a bare fluorophore-looking literal. The pattern is
# deliberately narrow: choices=[...] on ONE line with a quoted "AF..." in it.
LIT = re.compile(r"choices\s*=\s*[\[(][^\])]*[\"']AF\d+[\"']")
offenders = []
for path in sorted(glob.glob(os.path.join(REPO, "scripts", "*.py"))):
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if LIT.search(line):
                offenders.append(f"{os.path.basename(path)}:{n}")

chk("no stage hardcodes its marker choices", offenders, [])
for o in offenders:
    print(f"     {o}")

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it and watch it fail with the five real sites**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_marker_choices.py
```

Expected: FAIL listing exactly these five, all single-line `choices=`:

```
04a_reformat.py:566      default="AF488"   choices=["AF488", "AF568"]
04g_artifact_mask.py:301 default="AF488"   choices=["AF488", "AF568"]
04j_censor_clipped.py:297 default="AF568"  choices=["AF568", "AF488"]
04l_roi_curator.py:4664  default="AF568"   choices=("AF488", "AF568")
04o_section_rgb.py:137   default="AF568"   choices=("AF488", "AF568")
```

**Record the exact list** — it is the task's checklist, and a site the grep
missed is a site the plan missed. Note the defaults are not uniform: `04a` and
`04g` default to the second marker, the other three to the first. That
asymmetry is preserved, not tidied — see Step 3.

- [ ] **Step 2b: The help strings name the fluorophores too**

Four of the five carry help text like `"AF488 = PCNA (default), AF568 = pERK"`.
On a study with different markers that text is not merely stale, it is wrong —
it tells the operator the flag means something it does not. Replace each with
text built from the values:

```python
                    help=f"which marker to process (default {_default})")
```

`04l:4665-4668`'s help is longer and explains that both channels are always
loaded and this picks the opening view. Keep that explanation; drop only its
final line, the one mapping `AF568`/`AF488` to `pERK`/`PCNA`.

- [ ] **Step 3: Fix `04a_reformat.py`**

Replace lines 566-567:

```python
    ap.add_argument("--marker", default=GEO_MARKERS[0], choices=GEO_MARKERS,
                    help=f"which marker's sections to reformat "
                         f"(default {GEO_MARKERS[0]})")
```

where `GEO_MARKERS` is added near the top of the module, beside the existing
`ls_config` import:

```python
import ls_channels as CH
GEO_MARKERS = list(CH.marker_names(CONFIG))
```

**Two stages default to the SECOND marker, not the first.** `04a:566` and
`04g:301` both read `default="AF488", choices=["AF488", "AF568"]` — reversed
relative to `04j` and `05a`. That is not an accident: `AF488`/PCNA is the pass
that was curated first, and the default selects which sections get written.
Adopting the shared first-marker rule would silently point both at the other
pass.

Preserve it explicitly, in **both** stages:

```python
    # 04a and 04g have always defaulted to the SECOND marker (AF488 = PCNA):
    # it is the pass that was curated first. Kept rather than adopting the
    # first-declared default, because this default selects which sections get
    # written and a silent flip would reformat the wrong pass.
    _default = GEO_MARKERS[1] if len(GEO_MARKERS) > 1 else GEO_MARKERS[0]
    ap.add_argument("--marker", default=_default, choices=GEO_MARKERS,
                    help=f"which marker's sections to reformat "
                         f"(default {_default})")
```

The `len(...) > 1` guard is load-bearing: under a one-marker study — which is
what `config.example.json` declares, and therefore what every temp-study suite
runs — `GEO_MARKERS[1]` is an `IndexError` at **import**, taking the stage and
every suite that imports it down with it.

Also replace `marker_paths()`'s `if marker == "AF488":` branch at :400. Read
that branch first and determine what it does; if it selects the override source
for the pass that was curated first, express it as "the default marker" rather
than the literal:

```python
    if marker == _DEFAULT_MARKER:
```

with `_DEFAULT_MARKER` defined once at module level next to `GEO_MARKERS`.

- [ ] **Step 4: Fix `04j_censor_clipped.py`**

Replace the `LABEL` dict at :151:

```python
# Display names for the markers, when the study gives them one. A paired study
# names its markers by fluorophore, so this is usually empty and the marker's
# own name is what gets shown.
LABEL = {c.name: c.name for c in
         CH.markers(CH.parse((CONFIG.get("acquisition") or {}).get("channels")))}
```

and the argument at :297-298:

```python
    ap.add_argument("--marker", default=MARKERS[0], choices=MARKERS,
                    help=f"which marker to censor (default {MARKERS[0]})")
```

with `MARKERS = list(CH.marker_names(CONFIG))` at module level.

**Check every use of `LABEL`** before changing it — `grep -n LABEL
scripts/04j_censor_clipped.py`. If it is used as `LABEL[marker]` with no
fallback, a study whose markers are not in the dict raises `KeyError`. Use
`LABEL.get(marker, marker)` at each site.

- [ ] **Step 5: Fix `04g_artifact_mask.py` and `04l_roi_curator.py`**

`MARKERS = list(CH.marker_names(CONFIG))` at module level in both.

`04g:301` takes the **second-marker default** shown in Step 3 — it is the other
stage that defaults to `AF488`. `04l` takes `default=MARKERS[0]`.

`04l` additionally has two literal loops at :4751 and :4756:

```python
    for mk in ("AF568", "AF488"):
```
becomes
```python
    for mk in MARKERS:
```

and

```python
    data = per_marker["AF568"][0] + per_marker["AF488"][0]
```
becomes
```python
    data = [row for mk in MARKERS for row in per_marker[mk][0]]
```

That second one preserves order for two markers and stops being wrong for three.

- [ ] **Step 6: Run the new test, then the whole suite**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_marker_choices.py && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: `ALL PASS`, then zero constant differences.

- [ ] **Step 7: Confirm each changed stage still parses its own arguments**

The constants probe imports modules; it does not build their parsers. Check
that separately, without running any stage:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && for s in 04a_reformat 04g_artifact_mask 04j_censor_clipped 04l_roi_curator; do work/appenv/Scripts/python.exe scripts/$s.py --help > /dev/null 2>&1 && echo "ok   $s --help" || echo "FAIL $s --help"; done
```

Expected: four `ok` lines. `--help` exits before any work is done, so this
writes nothing. **This is the check that catches a `MARKERS[1]` on a
one-marker study.**

- [ ] **Step 8: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/04a_reformat.py scripts/04g_artifact_mask.py scripts/04j_censor_clipped.py scripts/04l_roi_curator.py tests/test_marker_choices.py && git commit -m "Stages offer the study's markers, not a fixed pair

A --marker whose choices are a literal rejects the value before any code runs,
so pointing the pipeline at a different study fails as a usage error about an
unrelated fluorophore.

04a keeps defaulting to the SECOND marker. That is not tidy, but the default
selects which pass gets reformatted, and adopting the shared first-marker rule
would silently write the other one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: `01k`'s mask markers

**Files:**
- Modify: `scripts/01k_saturation_raw.py:92`
- Test: `tests/test_ceilings.py` (extend)

- [ ] **Step 1: Write the failing test**

`tests/test_ceilings.py` also runs under `use_temp_study()` — one marker,
`Marker1` — and loads `01k_saturation_raw.py` as **`K`** (`OV` is
`01_overviews`). Its `chk` compares `got == want` and increments a module-level
`fails`. Append:

```python
print()
print("--- masks are written for the study's markers ---")

import ls_channels as _CH                                   # noqa: E402

chk("01k's mask markers are the configured ones",
    list(K.MASK_MARKERS), _CH.marker_names(K.CONFIG))
chk("...which for this temp study is the example's one marker",
    list(K.MASK_MARKERS), ["Marker1"])
```

The LS value is checked by the constants probe in Step 4, against the live
study — not here.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ceilings.py
```

Expected: FAIL on the first — `MASK_MARKERS` is the literal tuple.

- [ ] **Step 3: Replace the literal, keeping the comment**

The comment above `MASK_MARKERS` (lines 85-91) records a measured finding — that
AF488 does clip, contrary to what LOGS.md claimed, and why the 8-bit proxy could
not ask the question. That is evidence and stays. Replace only line 92:

```python
MASK_MARKERS = tuple(CH.marker_names(CONFIG))
```

with `import ls_channels as CH` added beside the `ls_config` import.

- [ ] **Step 4: Run the test and the probe**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ceilings.py && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: `ALL PASS`, zero differences.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/01k_saturation_raw.py tests/test_ceilings.py && git commit -m "01k: mask markers come from the study

The comment above it stays: that AF488 does clip, and that the 8-bit proxy
could not ask the question, is a measured finding rather than a note about
which two fluorophores this lab used.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: the composite

`04o_section_rgb.py:97` is `MARKER_PLANE = {"AF568": 0, "AF488": 1}` — first
marker to red, second to green, DAPI to blue. The spec wants that generic and
overridable by `display.composite`, with the LS defaults reproducing today's
output exactly.

**Files:**
- Modify: `scripts/ls_config.py` (SPEC — `display.composite`)
- Modify: `scripts/04o_section_rgb.py:97` and its uses
- Test: `tests/test_composite.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_composite.py`:

```python
"""Which marker lands in which RGB plane.

The default is positional - first marker red, second green, nuclear blue -
because that is what this pipeline has always produced and the curator's eye is
trained on it. display.composite overrides it by name.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_channels as CH                                    # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(56) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


LS = {"acquisition": {"layout": "paired", "markers": ["AF568", "AF488"]}}

print("--- the default is positional, and is what LS already gets ---")
chk("first marker is red", CH.marker_planes(LS), {"AF568": 0, "AF488": 1})

ONE = {"acquisition": {"layout": "paired", "markers": ["pERK"]}}
chk("one marker takes red only", CH.marker_planes(ONE), {"pERK": 0})

THREE = {"acquisition": {"layout": "paired",
                         "markers": ["A", "B", "C"]}}
chk("a third marker gets no plane by default",
    CH.marker_planes(THREE), {"A": 0, "B": 1})

print()
print("--- display.composite overrides by name ---")
OVER = {"acquisition": {"layout": "paired", "markers": ["A", "B", "C"]},
        "display": {"composite": ["C", "A"]}}
chk("named markers take red and green in order",
    CH.marker_planes(OVER), {"C": 0, "A": 1})

BAD = {"acquisition": {"layout": "paired", "markers": ["A", "B"]},
       "display": {"composite": ["A", "nope"]}}
try:
    CH.marker_planes(BAD)
    chk("an undeclared marker in display.composite is refused", False, True)
except CH.ChannelError as e:
    chk("an undeclared marker in display.composite is refused",
        "nope" in str(e), True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_composite.py
```

Expected: `AttributeError: module 'ls_channels' has no attribute 'marker_planes'`.

- [ ] **Step 3: Add `marker_planes` to `ls_channels.py`**

```python
def marker_planes(cfg):
    """{marker name: RGB plane index} for the composite. Blue is the nuclear
    channel and is not in here.

    Positional by default - first declared marker to red, second to green -
    because that is what this pipeline has always produced, and the curator's
    judgement of what a section looks like is trained on it. `display.composite`
    names the markers instead, in plane order.

    Beyond two markers the operator needs a channel picker in the curator;
    until then the third and later declared markers are simply not composited,
    which is visible rather than silently blended into one of the first two.
    """
    names = marker_names(cfg)
    chosen = ((cfg or {}).get("display") or {}).get("composite")
    if chosen:
        if not isinstance(chosen, (list, tuple)):
            raise ChannelError(
                f"`display.composite` must be a list of marker names, not a "
                f"{type(chosen).__name__}.")
        for m in chosen:
            if m not in names:
                raise ChannelError(
                    f"`display.composite` names {m!r}, which is not one of "
                    f"this study's markers ({', '.join(names) or 'none'}). "
                    f"The composite can only show a marker that is measured.")
        names = list(chosen)
    return {m: i for i, m in enumerate(names[:2])}
```

- [ ] **Step 4: Add the `display.composite` Key to `SPEC`**

```python
    Key("display.composite", "raw",
        "Which markers the RGB composite shows, in plane order: red then "
        "green. The nuclear channel is always blue.",
        default=[], label="Composite channels",
        note="Empty means positional - the first declared marker to red, the "
             "second to green - which is what this pipeline has always "
             "produced. Beyond two markers a study must say which two it "
             "wants shown; the rest are measured but not composited, because "
             "blending a third into one of the first two would change what "
             "the curator is judging without saying so.",
        example=[],
        consumers=["04o_section_rgb"]),
```

- [ ] **Step 5: Use it in `04o_section_rgb.py`**

Replace line 97:

```python
# Marker -> which RGB plane it lands in. DAPI always takes blue.
MARKER_PLANE = CH.marker_planes(CONFIG)
```

with `import ls_channels as CH` added beside the `ls_config` import.

Then `grep -n MARKER_PLANE scripts/04o_section_rgb.py` and check every use. A
site doing `MARKER_PLANE[marker]` must become `MARKER_PLANE.get(marker)` with an
explicit skip, so a third marker is not a `KeyError`:

```python
    plane = MARKER_PLANE.get(marker)
    if plane is None:
        # Measured, but not one of the two the composite shows. Skipping is
        # deliberate and says so; blending it into red or green would change
        # the picture the curator judges without any record of it.
        continue
```

Also fix `04o`'s `--marker` choices, the fifth site from Task 4:

```python
    ap.add_argument("--marker", default=MARKERS[0], choices=MARKERS, ...)
```

- [ ] **Step 6: Run the tests, regenerate, prove nothing moved**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_composite.py && work/appenv/Scripts/python.exe tests/test_marker_choices.py && work/appenv/Scripts/python.exe scripts/ls_config.py --write-example && work/appenv/Scripts/python.exe scripts/ls_config.py --docs && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: `ALL PASS` twice, then zero constant differences — `MARKER_PLANE` is a
module constant, so the probe compares it directly and will report
`{'AF568': 0, 'AF488': 1}` unchanged.

- [ ] **Step 7: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/ls_channels.py scripts/ls_config.py scripts/04o_section_rgb.py tests/test_composite.py config.example.json docs/config-reference.md && git commit -m "The composite maps markers by position, or by name

First declared marker to red, second to green, nuclear to blue - which is what
LS already gets, checked as a constant rather than asserted. display.composite
overrides it by name for a study with more than two markers.

A third marker is not composited and is not blended into one of the first two:
blending would change the picture the curator judges with no record of it. A
channel picker in the curator is the real answer and is follow-up.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: `ls_layouts` — which stages apply to which layout

The spec puts `layouts` on `Stage`. `app/stages.py` carries the owner's
uncommitted work, so the **data** lands here in its own module now and the field
is wired in Task 10 when that file is free.

This is not a workaround for its own sake: `run_all.sh` and the sidebar are
different consumers of the same fact, and `run_all.sh` is not blocked.

**Files:**
- Create: `scripts/ls_layouts.py`
- Test: `tests/test_layouts.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_layouts.py`:

```python
"""Which stages apply to which acquisition layout.

02_pair_passes pairs two physical scans of one section; 04i carries one pass's
curation onto the other. A multiplex study has one scan, so both have nothing
to do - not "run and produce nothing", which is how a stage that silently
returns [] gets mistaken for a stage that ran.
"""

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_layouts as LY                                     # noqa: E402
import ls_channels as CH                                    # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


chk("02_pair_passes is paired-only",
    LY.layouts_for("02_pair_passes.py"), ("paired",))
chk("04i_propagate_to_perk is paired-only",
    LY.layouts_for("04i_propagate_to_perk.py"), ("paired",))
chk("an ordinary stage applies to both",
    LY.layouts_for("05c_detect_rois.py"), CH.LAYOUTS)
chk("a stage nobody classified still applies to both",
    LY.layouts_for("99_not_a_stage.py"), CH.LAYOUTS)

chk("a paired study runs the paired-only stage",
    LY.applies("02_pair_passes.py", "paired"), True)
chk("a multiplex study does not",
    LY.applies("02_pair_passes.py", "multiplex"), False)

print()
print("--- every numbered script applies to at least one layout ---")

# The spec's guard: a stage must not vanish by being listed for no layout.
orphans = []
for path in sorted(glob.glob(os.path.join(REPO, "scripts", "*.py"))):
    name = os.path.basename(path)
    if not re.match(r"^\d", name):
        continue
    if not LY.layouts_for(name):
        orphans.append(name)

chk("no numbered script applies to no layout", orphans, [])
for o in orphans:
    print(f"     {o}")

print()
print("--- the exceptions are named, and only the named ones ---")
chk("exactly two stages are layout-restricted",
    sorted(LY.RESTRICTED), ["02_pair_passes.py", "04i_propagate_to_perk.py"])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_layouts.py
```

Expected: `ModuleNotFoundError: No module named 'ls_layouts'`.

- [ ] **Step 3: Write `scripts/ls_layouts.py`**

```python
"""Which stages apply to which acquisition layout.

Two stages exist only because LS imaged each marker as a separate scan:

  02_pair_passes        pairs the two passes onto the same physical sections.
  04i_propagate_to_perk carries the curated pass's discs onto the other one.

A `multiplex` study has ONE scan per section, so there is nothing to pair and
nothing to propagate. Neither stage is deleted: LS keeps working, and the code
that built that dataset stays readable.

Restricting them matters more than it looks. Run against a multiplex study,
02_pair_passes finds no second marker and writes an empty pairing - which reads
downstream as "these sections have no partner" rather than "this stage did not
apply". A stage that quietly produces nothing is indistinguishable from a stage
that ran and found nothing, and only one of those is a problem.

The data lives here rather than on `Stage` because `app/stages.py` and
`tests/test_stages.py` both carry uncommitted work; `Stage.layouts` reads from
this module once they are free. `run_all.sh` is a separate consumer of the same
fact and is not blocked.
"""

import ls_channels as CH

# Stage script name -> the layouts it applies to. Anything absent applies to
# both: the default has to be "applies", so that adding a stage cannot make it
# silently vanish from every study by omission.
RESTRICTED = {
    "02_pair_passes.py": (CH.LAYOUT_PAIRED,),
    "04i_propagate_to_perk.py": (CH.LAYOUT_PAIRED,),
}


def layouts_for(script):
    """The layouts `script` applies to. Both, unless it is restricted."""
    return RESTRICTED.get(script, CH.LAYOUTS)


def applies(script, layout):
    """True when `script` should run for a study of this layout."""
    return layout in layouts_for(script)


def skipped(layout):
    """The scripts a study of this layout does NOT run, sorted."""
    return sorted(s for s in RESTRICTED if not applies(s, layout))
```

- [ ] **Step 4: Run the test**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_layouts.py
```

Expected: `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/ls_layouts.py tests/test_layouts.py && git commit -m "ls_layouts: which stages a layout actually runs

02_pair_passes and 04i_propagate_to_perk exist because LS imaged each marker
as a separate scan. A multiplex study has one scan, so there is nothing to pair
and nothing to propagate.

Run anyway, 02_pair_passes writes an empty pairing, which reads downstream as
'these sections have no partner' rather than 'this stage did not apply'. A
stage that quietly produces nothing looks exactly like one that ran and found
nothing.

The data is here rather than on Stage because app/stages.py carries uncommitted
work. run_all.sh consumes the same fact and is not blocked.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: `run_all.sh` skips the stages that do not apply

**Files:**
- Modify: `scripts/run_all.sh`
- Test: `tests/test_run_all_layouts.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_all_layouts.py`:

```python
"""run_all.sh asks whether a stage applies before running it.

A static check: run_all.sh is bash and running it would run the pipeline.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


with open(os.path.join(REPO, "scripts", "run_all.sh"), encoding="utf-8") as fh:
    src = fh.read()

chk("run_all.sh reads the study's layout", "LAYOUT=" in src, True)
chk("...from the config, not from a literal",
    bool(re.search(r"LAYOUT=.*LS_CONFIG", src, re.S)), True)
chk("the paired-only stages are gated",
    src.count("layout_applies") >= 2, True)

# The gate must not be a literal list of stage names duplicated from
# ls_layouts.py - two lists is how they drift.
chk("the gate asks ls_layouts rather than repeating it",
    "ls_layouts" in src, True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_run_all_layouts.py
```

Expected: FAIL on all four.

- [ ] **Step 3: Add the layout gate to `run_all.sh`**

After the `OUT=` line (around :23), add:

```bash
# Which layout this study is, and therefore which stages apply. Asked of
# ls_layouts rather than listed here: two lists of stage names is how they
# drift, and the one that drifts silently is the one that skips a stage.
LAYOUT="$(python -c "import json,sys;print((json.load(open(sys.argv[1],encoding='utf-8')).get('acquisition') or {}).get('layout','multiplex'))" "$LS_CONFIG")" || exit 1
printf 'acquisition layout: %s\n' "$LAYOUT"

layout_applies() {
  python -c "import sys;sys.path.insert(0,sys.argv[1]);import ls_layouts;sys.exit(0 if ls_layouts.applies(sys.argv[2],sys.argv[3]) else 1)" "$SCRIPTS" "$1" "$LAYOUT"
}
```

Then wrap each of the two restricted stages. Find its `step` line
(`grep -n "02_pair_passes\|04i_propagate" scripts/run_all.sh`) and change it
from:

```bash
step 12 "pair the two passes" \
  python 02_pair_passes.py || exit 1
```

to:

```bash
if layout_applies 02_pair_passes.py; then
  step 12 "pair the two passes" \
    python 02_pair_passes.py || exit 1
else
  printf '\n[12] SKIP  pair the two passes (not used under %s)\n' "$LAYOUT"
fi
```

Use the real step numbers and titles from the file — do not renumber anything.

- [ ] **Step 4: Run the test, and check the script still parses**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_run_all_layouts.py && bash -n scripts/run_all.sh && echo "run_all.sh parses"
```

Expected: `ALL PASS`, then `run_all.sh parses`. `bash -n` checks syntax without
executing — **do not run `run_all.sh` itself**, it would run the pipeline over
`out_root`.

- [ ] **Step 5: Check the gate answers correctly for the live study**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import sys; sys.path.insert(0, 'scripts')
import ls_layouts, ls_config
lay = (ls_config.load().get('acquisition') or {}).get('layout')
print('layout:', lay)
print('02 runs:', ls_layouts.applies('02_pair_passes.py', lay))
print('04i runs:', ls_layouts.applies('04i_propagate_to_perk.py', lay))
print('skipped:', ls_layouts.skipped(lay))
"
```

Expected: `layout: paired`, both `True`, `skipped: []`. **LS must skip
nothing** — if either says `False`, the gate would drop a stage that built the
current dataset.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/run_all.sh tests/test_run_all_layouts.py && git commit -m "run_all.sh skips the stages a layout does not use

The gate asks ls_layouts rather than repeating the stage names: two lists is
how they drift, and the one that drifts silently is the one that skips a stage
that should have run.

Verified that the live paired study skips nothing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: multiplex frames — `04a_reformat` runs once per scene

This is the behaviour change the spec's headline rests on. Under `multiplex`
there is one frame per scene: rotation, cropping, the artifact mask and clipping
censorship are decided **once** for pixels that are the same pixels, and every
marker is measured inside the same curated discs.

**There is no multiplex data to test against.** LS is paired and no other study
exists yet. So this task is tested by synthetic fixture only, and that limit is
stated in the commit rather than glossed.

**Files:**
- Modify: `scripts/04a_reformat.py:392-418` (`marker_paths`)
- Test: `tests/test_reformat_layout.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_reformat_layout.py`:

```python
"""Under multiplex, the reformat is per SCENE, not per marker.

The pixels are the same pixels - one scan carries every marker - so rotation,
cropping, the artifact mask and the censor mask are decided once. Deciding them
twice would let two markers of one section disagree about where the section is.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

# A study of our own, and a PAIRED one: load_stage imports "under whatever
# config is currently named", so without this the suite would read the
# operator's live study and pass or fail on their data. config.example.json is
# multiplex, so the paired half has to be asked for explicitly.
from _fixture import use_temp_study, load_stage             # noqa: E402

STUDY = use_temp_study(acquisition={"layout": "paired",
                                    "markers": ["AF568", "AF488"]})
RF = load_stage("04a_reformat.py")

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


print("--- paired: one set of paths per marker, as today ---")
chk("the module read the paired layout", RF.LAYOUT, "paired")
a = RF.marker_paths("AF568")
b = RF.marker_paths("AF488")
chk("the two markers get different section dirs",
    a["sections"] != b["sections"], True)
chk("...and different indexes", a["index"] != b["index"], True)
chk("the section dir still carries the marker name",
    os.path.basename(a["sections"]), "sections_AF568")

print()
print("--- multiplex: one set of paths for every marker ---")
# marker_paths reads the module-level LAYOUT, so flipping it is the whole
# difference. Restored in `finally` because the module is process-global and a
# later assertion would otherwise inherit it.
_was = RF.LAYOUT
try:
    RF.LAYOUT = "multiplex"
    m1 = RF.marker_paths("pERK")
    m2 = RF.marker_paths("PCNA")
    chk("every marker shares one section dir", m1["sections"], m2["sections"])
    chk("...and one index", m1["index"], m2["index"])
    chk("the shared dir carries no marker name",
        os.path.basename(m1["sections"]), "sections")
finally:
    RF.LAYOUT = _was

chk("the layout was put back", RF.LAYOUT, "paired")

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

`temp_study(**overrides)` does `cfg.update(overrides)` on the config loaded from
`config.example.json` (`tests/_fixture.py:73`), so passing `acquisition=`
**replaces the whole block** — the example's `channels` table goes with it. That
is what a paired study needs: no channel table, and `markers` instead. No change
to the fixture is required.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_reformat_layout.py
```

Expected: FAIL on `every marker shares one section dir` — `marker_paths` always
suffixes.

- [ ] **Step 3: Make `marker_paths` layout-aware**

Add beside `GEO_MARKERS` at module level:

```python
LAYOUT = (CONFIG.get("acquisition") or {}).get("layout", CH.LAYOUT_MULTIPLEX)
```

In `marker_paths()`, before the existing per-marker `return`:

```python
    if LAYOUT == CH.LAYOUT_MULTIPLEX:
        # One scan carries every marker, so there is ONE frame per scene and
        # the reformat is decided once. Suffixing these by marker would write
        # the same pixels several times under different names, and would let
        # two markers of one section disagree about where the section is -
        # which is the thing the curator then has to reconcile by hand.
        return {"sections": os.path.join(REFORMAT_DIR, "sections"),
                "index": os.path.join(REFORMAT_DIR, "reformat_index.csv"),
                "excluded": os.path.join(REFORMAT_DIR,
                                         "excluded_sections.csv"),
                "lost": os.path.join(REFORMAT_DIR, "lost_sections.csv")}
```

Leave the paired branch and its docstring exactly as they are.

- [ ] **Step 4: Run the test**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_reformat_layout.py
```

Expected: `ALL PASS`.

- [ ] **Step 5: Prove the paired paths did not move**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py && bash tests/run.sh 2>&1 | tail -5
```

Expected: zero constant differences; only the known `test_join_metadata.py`
failure. This is the task with the most room to move a real path, so read the
probe output rather than only its exit code.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/04a_reformat.py tests/test_reformat_layout.py && git commit -m "04a: under multiplex the reformat is per scene, not per marker

One scan carries every marker, so rotation, cropping, the artifact mask and the
censor mask are decided once for pixels that are the same pixels. Suffixing the
outputs by marker would write them several times and let two markers of one
section disagree about where the section is.

Tested against a synthetic fixture only: LS is paired and no multiplex study
exists yet, so nothing here has met real multi-channel data. The paired paths
are unchanged, which the constants probe checks across all 45 stages.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: `Stage.layouts` — **DONE 2026-09-23** (commit 79c3a4e)

Unblocked when the owner committed `app/stages.py` and `tests/test_stages.py`
in 27d8635. Landed with P1.4 Task 11, which touches the same file. The test
compares against the whole of `ls_layouts.RESTRICTED` rather than the two
stages named below, and that caught `04m_sections_dataset.py` - restricted in
P1.4 Task 5 and never wired here. The sidebar dims an off-layout stage with a
reason rather than hiding it.

The plan as written follows.


**Do not start this task until `git status` shows `app/stages.py` and
`tests/test_stages.py` clean.** Both carry the owner's uncommitted work — two
blurb edits in `app/stages.py` and 28 added lines in `tests/test_stages.py`.
Staging either file would commit someone else's in-flight edits.

Check first:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git status --short app/stages.py tests/test_stages.py
```

If that prints anything, **stop and report the task as still blocked.** Do not
work around it with `git add -p`: the point is that the owner has not decided
what their change is yet.

**Files (when unblocked):**
- Modify: `app/stages.py` — `Stage.__init__` (:44-60), and `layouts=` on the two restricted entries
- Modify: `tests/test_stages.py`

- [ ] **Step 1: Add the field**

In `Stage.__init__`, add the parameter after `unblinds=False`:

```python
                 unblinds=False, layouts=None):
```

and in the body, after `self.unblinds = unblinds`:

```python
        # Which acquisition layouts this stage applies to. None means both -
        # the default has to be "applies", so a new stage cannot vanish from
        # every study by omission. ls_layouts holds the same fact for
        # run_all.sh; this reads from it rather than repeating it.
        self.layouts = tuple(layouts) if layouts else None

    def applies(self, layout):
        """True when this stage should be offered for a study of this layout."""
        return self.layouts is None or layout in self.layouts
```

- [ ] **Step 2: Read the restriction from `ls_layouts`, do not repeat it**

Near the top of `app/stages.py`, beside the existing sibling imports:

```python
_ly = importlib.util.spec_from_file_location(
    "_ly", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "ls_layouts.py"))
LY = importlib.util.module_from_spec(_ly)
_ly.loader.exec_module(LY)
```

and on the two stages, pass the module's answer rather than a literal:

```python
          layouts=LY.layouts_for("02_pair_passes.py"),
```
```python
          layouts=LY.layouts_for("04i_propagate_to_perk.py"),
```

- [ ] **Step 3: Add the spec's guard to `tests/test_stages.py`**

```python
print()
print("--- every numbered script applies to at least one layout ---")

orphans = [s.sid for s in STAGES if s.layouts is not None and not s.layouts]
chk("no stage is listed for no layout", orphans, [])

chk("02_pair_passes is paired-only",
    next(s for s in STAGES if s.script == "02_pair_passes.py").layouts,
    ("paired",))
chk("an ordinary stage applies to both",
    next(s for s in STAGES if s.script == "05c_detect_rois.py").layouts, None)
```

- [ ] **Step 4: Run the suite**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_stages.py && work/appenv/Scripts/python.exe tests/test_layouts.py
```

Expected: `ALL PASS` from both.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add app/stages.py tests/test_stages.py && git commit -m "Stage.layouts: the sidebar shows what applies to the open study

Reads ls_layouts rather than repeating the stage names, so the sidebar and
run_all.sh cannot disagree about which stages a study runs.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verification

After every task:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh
```

Expected: `SUITE FAILURES` with **exactly one** failing suite,
`test_join_metadata.py`, from the owner's uncommitted
`analysis/plot_roi_figures.R` edit removing `SHAPES`. Any second failing suite
belongs to this plan.

And the guarantee that matters:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: zero differing constants across all 45 stages. This plan rewrites the
code that builds ~39 output paths; a single moved constant means a stage is
about to read or write a different file on a drive holding 130 curated sections.

**Never run a numbered stage to test a change** — stage scripts overwrite
`out_root`. Call `build()` in-process, or use `--help`, or check statically.

**Never `git add -A`, `git add .`, or `git commit -a`.** Thirteen files carry
the owner's uncommitted and untracked work. Stage the exact paths each task
names.

---

## Self-review

**Spec coverage.** Marker identity as the operator's name → Tasks 1-5. LS paths
byte-identical → the constants probe, run in every task. The composite and
`display.composite` → Task 6. Layout-aware stage list → Tasks 7-8, with
`Stage.layouts` at Task 10. One frame per scene under multiplex → Task 9. The
uid-collision guard becoming layout-aware, which the spec flags as the one
change that could corrupt a join → Task 3, with a colliding fixture under both
layouts as the spec requires.

**Two spec gaps closed rather than papered over.** Where a paired study's marker
list comes from (`acquisition.markers`, Task 1) and why not the manifest. That
the key and the live config edit must be one task, because otherwise every
stage fails at import — the failure that broke Tasks 3-7 of plan 1.

**Deferred, deliberately.** `02_pair_passes` and `04i_propagate_to_perk` keep
their internal marker literals: they are `paired`-only by Task 7, and a stage
that runs only under the layout that has those markers may name them. Rewriting
them generically would be work that no study can ever exercise. Plan 3 keeps its
scope: segmentation backends, co-localisation, Abercrombie gating.

**Names used consistently.** `ls_channels.marker_names(cfg)`,
`marker_planes(cfg)`, `LAYOUT_MULTIPLEX` / `LAYOUT_PAIRED` / `LAYOUTS`;
`ls_layouts.layouts_for(script)` / `applies(script, layout)` /
`skipped(layout)` / `RESTRICTED`. Every stage that needs the list defines
`MARKERS` as `list(CH.marker_names(CONFIG))` and a layout as `LAYOUT`.

**The risk this plan does not remove.** Task 9 gives multiplex studies one frame
per scene, but nothing here has met real multi-channel data — LS is paired and
no multiplex study exists. The synthetic fixtures check the path shapes and the
layout branches; they cannot check that a real multiplex CZI reformats
correctly. The first multiplex study will find things, and that is stated in
Task 9's commit rather than left for someone to discover.
