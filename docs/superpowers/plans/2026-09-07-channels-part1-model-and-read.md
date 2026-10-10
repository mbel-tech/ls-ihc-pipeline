# Channel model and the shared read — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A study can declare what its CZI channels are and what each one is for, and every stage reads a channel through one helper that passes `scene=`.

**Architecture:** Two new sibling modules under `scripts/`, imported the way `ls_config` and `ls_naming` already are. `ls_channels.py` owns the channel table — parsing, validation, and resolving a declared channel to a plane index in a particular file. `czi_read.py` owns the read itself: one function that takes a scene and a plane and returns a 2-D array, asserting what `np.squeeze` currently assumes. The four stages that hold `plane={"C": 0}` literals are migrated onto it. Nothing about the LS study's behaviour changes except the numbers the `scene=` fix corrects.

**Tech Stack:** Python 3.13 (`work/appenv/Scripts/python.exe`), `pylibCZIrw`, numpy. Tests are plain scripts with a `chk()` helper, run by `tests/run.sh` — this repo has no pytest.

**This is plan 1 of 3** for `docs/superpowers/specs/2026-09-07-channels-and-markers-design.md`. Plan 2 is the multiplex layout (one frame per scene, layout-aware stages, marker naming through outputs). Plan 3 is detection modes, co-localisation and Abercrombie gating. Plan 2's code edits files this plan rewrites, so it is written after this one lands.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/ls_channels.py` | **New.** The channel table: `Channel`, parse from config, validate, resolve to plane indices for one file. Knows nothing about reading pixels. |
| `scripts/czi_read.py` | **New.** One read: a scene, a plane, a zoom, out comes a 2-D array. Knows nothing about roles. |
| `scripts/ls_config.py` | `acquisition.layout` and `acquisition.channels` join SPEC; validation delegates to `ls_channels`. |
| `scripts/01_overviews.py` | `read_scene` becomes a thin wrapper over `czi_read`; its four call sites pass the scene. |
| `scripts/01k_saturation_raw.py` | `measure()` takes a scene and passes it down. |
| `scripts/05a_roi_geometry.py` | Its one `plane={"C": 0}` read goes through the helper. |
| `scripts/05c_detect_rois.py` | Its two reads go through the helper. |
| `docs/scene_fix_report.py` | **New.** One-off: quantifies how far clipping moved, for review. Not a stage. |
| `tests/test_ls_channels.py` | **New.** Parsing, validation, resolution. |
| `tests/test_czi_read.py` | **New.** The helper, against a fake reader. |

Two modules rather than one because they have different dependencies and different reasons to change: `ls_channels` is pure config logic testable with no CZI at all, `czi_read` is the only thing that touches `pylibCZIrw`.

---

## Task 1: The channel table

**Files:**
- Create: `scripts/ls_channels.py`
- Test: `tests/test_ls_channels.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ls_channels.py`:

```python
"""The channel table: what a study says its CZI channels are, and what each is for.

Reading the wrong plane produces a plausible number rather than an error, so
resolution is the part that must never guess. A declared channel resolves by
the CZI's own channel name first - which survives channels being acquired in a
different order - and by index only as a fallback. When neither works it says
what it wanted and what the file actually has.

Run:  python tests/test_ls_channels.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_channels as CH                                    # noqa: E402

failures = []


def chk(name, got, want):
    ok = got == want
    shown = got if len(repr(got)) < 90 else f"<{type(got).__name__}>"
    print(f"{'ok  ' if ok else 'FAIL'} {name:60} {shown!r}")
    if not ok:
        print(f"     want {want!r}")
        failures.append(name)


BLOCK = [
    {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
    {"name": "pERK", "role": "marker", "czi_name": "AF568", "index": 1,
     "segment": "nuclear"},
    {"name": "GFAP", "role": "marker", "czi_name": "AF647", "index": 2,
     "segment": "own", "backend": "threshold", "nucleus_shaped": False},
]

print("--- parsing ---")
chans = CH.parse(BLOCK)
chk("every declared channel is parsed", [c.name for c in chans],
    ["DAPI", "pERK", "GFAP"])
chk("the nuclear channel is findable", CH.nuclear(chans).name, "DAPI")
chk("markers are the ones to measure", [c.name for c in CH.markers(chans)],
    ["pERK", "GFAP"])
chk("segment defaults to nuclear when a nuclear channel exists",
    CH.parse([BLOCK[0], {"name": "X", "role": "marker", "index": 1}])[1].segment,
    "nuclear")
chk("a marker on its own channel defaults to stardist",
    CH.parse([{"name": "X", "role": "marker", "index": 0,
               "segment": "own"}])[0].backend, "stardist")

print()
print("--- resolving a declared channel to a plane in one file ---")
chk("by CZI channel name, whatever the order",
    CH.resolve(chans, ["AF647", "DAPI", "AF568"]),
    {"DAPI": 1, "pERK": 2, "GFAP": 0})
chk("by index when the file names nothing",
    CH.resolve(chans, [None, None, None]),
    {"DAPI": 0, "pERK": 1, "GFAP": 2})
chk("by index when the name is not among them",
    CH.resolve(CH.parse([{"name": "M", "role": "marker",
                          "czi_name": "AF488", "index": 1}]),
               ["DAPI", "AF568"]),
    {"M": 1})

try:
    CH.resolve(chans, ["DAPI"])
    chk("a channel that resolves to nothing raises", False, True)
except CH.ChannelError as exc:
    chk("a channel that resolves to nothing raises", True, True)
    chk("...and names the channel it wanted", "pERK" in str(exc), True)
    chk("...and what the file actually has", "DAPI" in str(exc), True)

print()
print("--- what a study may not declare ---")


def errs(block, layout="multiplex"):
    return CH.validate(block, layout)


chk("a valid table has nothing to say", errs(BLOCK), [])
chk("two channels cannot share a name",
    len(errs([BLOCK[0], dict(BLOCK[1], name="DAPI")])), 1)
chk("a name has to be usable as a folder",
    len(errs([dict(BLOCK[0], name="a/b")])), 1)
chk("there is at most one nuclear channel",
    len(errs([BLOCK[0], dict(BLOCK[1], role="nuclear")])), 1)
chk("something has to be a marker",
    len(errs([BLOCK[0]])), 1)
chk("an unknown role is refused",
    len(errs([BLOCK[0], dict(BLOCK[1], role="whatever")])), 1)

# The contradiction the spec names: StarDist is a nucleus detector, so asking
# for it on something declared not nucleus-shaped would under-detect silently.
bad = errs([BLOCK[0], dict(BLOCK[1], segment="own", backend="stardist",
                           nucleus_shaped=False)])
chk("stardist on a non-nuclear marker is refused", len(bad), 1)
chk("...and says why", "nucleus" in bad[0].lower(), True)

chk("segment: nuclear needs a nuclear channel to segment",
    len(errs([dict(BLOCK[1], segment="nuclear")])), 1)
chk("...but own-channel markers alone are fine",
    errs([dict(BLOCK[1], segment="own", backend="stardist",
               nucleus_shaped=True)]), [])

chk("the paired layout declares no channels",
    len(errs(BLOCK, layout="paired")), 1)
chk("...and an empty table is what it wants", errs([], layout="paired"), [])
chk("multiplex with no channels at all is refused",
    len(errs([], layout="multiplex")), 1)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_channels.py
```

Expected: `ModuleNotFoundError: No module named 'ls_channels'`

- [ ] **Step 3: Write the module**

Create `scripts/ls_channels.py`:

```python
"""What a study's CZI channels are, and what each one is for.

A channel is declared once, in the study config, and resolved to a plane index
per file. Resolution goes by the CZI's own channel name first and the declared
index only as a fallback, because a file acquired with its channels in a
different order would otherwise be read plane-for-plane and produce a perfectly
plausible wrong number.

Nothing here opens a CZI. It takes the channel names a file reports - which
`czi_meta.read_metadata` already extracts - and says which plane each declared
channel is. `czi_read.py` does the reading.
"""

import re

NUCLEAR, MARKER, REGISTRATION, IGNORE = (
    "nuclear", "marker", "registration", "ignore")
ROLES = (NUCLEAR, MARKER, REGISTRATION, IGNORE)

#: How a marker's own objects are found.
SEGMENT_NUCLEAR, SEGMENT_OWN = "nuclear", "own"
SEGMENTS = (SEGMENT_NUCLEAR, SEGMENT_OWN)

#: What finds them when they are found on the marker's own channel.
BACKENDS = ("stardist", "threshold")

#: A channel name becomes a directory and a CSV value, so it has to survive
#: both. Deliberately narrow: a name is typed once and lives for years.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.+-]{0,63}$")


class ChannelError(Exception):
    """A declared channel could not be found in a file."""


class Channel:
    def __init__(self, name, role, czi_name=None, index=None,
                 segment=None, backend=None, nucleus_shaped=True):
        self.name = name
        self.role = role
        self.czi_name = czi_name
        self.index = index
        self.segment = segment
        self.backend = backend
        self.nucleus_shaped = nucleus_shaped

    def __repr__(self):
        return f"<Channel {self.name} {self.role}>"


def parse(block, has_nuclear=None):
    """`acquisition.channels` as a list of Channel, with defaults filled in."""
    entries = list(block or [])
    if has_nuclear is None:
        has_nuclear = any((e or {}).get("role") == NUCLEAR for e in entries)

    out = []
    for entry in entries:
        entry = entry or {}
        role = entry.get("role")
        segment = entry.get("segment")
        if role == MARKER and not segment:
            # Measuring a marker inside nuclei is what this pipeline has always
            # done, so it stays the default wherever there are nuclei to use.
            segment = SEGMENT_NUCLEAR if has_nuclear else SEGMENT_OWN
        backend = entry.get("backend")
        if segment == SEGMENT_OWN and not backend:
            backend = "stardist"
        out.append(Channel(
            name=entry.get("name"), role=role,
            czi_name=entry.get("czi_name"), index=entry.get("index"),
            segment=segment, backend=backend,
            nucleus_shaped=entry.get("nucleus_shaped", True)))
    return out


def nuclear(channels):
    """The nuclear counterstain, or None when a study has none."""
    return next((c for c in channels if c.role == NUCLEAR), None)


def markers(channels):
    """The channels that get measured, in declared order."""
    return [c for c in channels if c.role == MARKER]


def resolve(channels, czi_channel_names):
    """{channel name: plane index} for one file.

    `czi_channel_names` is what the file reports, in plane order - the `name`
    of each entry `czi_meta` returns, which may be None.
    """
    names = list(czi_channel_names)
    lowered = {str(n).lower(): i for i, n in enumerate(names) if n}
    out = {}
    for chan in channels:
        if chan.czi_name and str(chan.czi_name).lower() in lowered:
            out[chan.name] = lowered[str(chan.czi_name).lower()]
            continue
        if chan.index is not None and 0 <= chan.index < len(names):
            out[chan.name] = chan.index
            continue
        raise ChannelError(
            f"channel {chan.name!r} is declared as {chan.czi_name!r} "
            f"(plane {chan.index}), and this file has "
            f"{[n for n in names] or 'no named channels'} - "
            f"{len(names)} plane(s). Fix the channel table in Settings, or "
            f"this file is not part of this study.")
    return out


def validate(block, layout):
    """Errors in a declared channel table. [] when it is usable."""
    errors = []
    entries = list(block or [])

    if layout == "paired":
        if entries:
            errors.append(
                "acquisition.channels must be empty for the paired layout: "
                "each scan carries the nuclear channel plus whichever marker "
                "that pass used, so the marker is read per file rather than "
                "declared once.")
        return errors

    if not entries:
        errors.append(
            "acquisition.channels is empty. A multiplex study has to say what "
            "its channels are; nothing can be inferred safely from a file.")
        return errors

    channels = parse(entries)

    seen = set()
    for chan in channels:
        if not chan.name or not NAME_RE.match(str(chan.name)):
            errors.append(
                f"channel name {chan.name!r} is not usable - it becomes a "
                f"folder name and a CSV value.")
        elif chan.name in seen:
            errors.append(f"two channels are both called {chan.name!r}.")
        seen.add(chan.name)

        if chan.role not in ROLES:
            errors.append(
                f"channel {chan.name!r} has role {chan.role!r}; it must be one "
                f"of {', '.join(ROLES)}.")

    nuclei = [c for c in channels if c.role == NUCLEAR]
    if len(nuclei) > 1:
        errors.append(
            f"{len(nuclei)} channels are marked nuclear "
            f"({', '.join(c.name for c in nuclei)}); there can be at most one.")

    if not markers(channels):
        errors.append(
            "no channel has role 'marker', so there is nothing to measure.")

    for chan in markers(channels):
        if chan.segment not in SEGMENTS:
            errors.append(
                f"channel {chan.name!r} has segment {chan.segment!r}; it must "
                f"be one of {', '.join(SEGMENTS)}.")
        if chan.segment == SEGMENT_NUCLEAR and not nuclei:
            errors.append(
                f"channel {chan.name!r} is segmented on the nuclear channel, "
                f"but this study declares none. Give it segment 'own', or "
                f"declare a nuclear channel.")
        if chan.segment == SEGMENT_OWN:
            if chan.backend not in BACKENDS:
                errors.append(
                    f"channel {chan.name!r} has backend {chan.backend!r}; it "
                    f"must be one of {', '.join(BACKENDS)}.")
            elif chan.backend == "stardist" and not chan.nucleus_shaped:
                errors.append(
                    f"channel {chan.name!r} asks for the stardist backend but "
                    f"is declared not nucleus_shaped. StarDist is a nucleus "
                    f"detector: on cytoplasmic or fibre staining it would "
                    f"under-detect and report no error. Use the threshold "
                    f"backend, or say the objects are nucleus-shaped.")
    return errors
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_channels.py
```

Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/ls_channels.py tests/test_ls_channels.py && git commit -m "ls_channels: what a study's CZI channels are, and what each is for

A channel resolves to a plane by the CZI's own channel name first and the
declared index only as a fallback. A file acquired with its channels in a
different order would otherwise be read plane-for-plane and produce a
perfectly plausible wrong number.

Validation refuses the contradiction the spec names: the stardist backend on a
marker declared not nucleus-shaped, which would under-detect cytoplasmic
staining and report nothing."
```

---

## Task 2: The channel table joins the config spec

**Files:**
- Modify: `scripts/ls_config.py` (SPEC list; `validate()`)
- Modify: `tests/test_ls_config.py` (add a section)
- Regenerate: `config.example.json`, `docs/config-reference.md`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ls_config.py`, immediately before the final `print()` / `sys.exit()` block:

```python
# --------------------------------------------------------------------------
print()
print("--- the acquisition block ---")

sys.path.insert(0, SCRIPTS)
import ls_channels as CH                                    # noqa: E402

CHANS = [
    {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
    {"name": "pERK", "role": "marker", "czi_name": "AF568", "index": 1},
]

with tempfile.TemporaryDirectory() as tmp:
    chk("layout defaults to multiplex",
        C.apply_defaults(minimal(tmp))["acquisition"]["layout"], "multiplex")

    ok = minimal(tmp, acquisition={"layout": "multiplex", "channels": CHANS})
    chk("a declared channel table validates", C.validate(ok)[0], [])

    errs, _ = C.validate(minimal(tmp, acquisition={"layout": "sideways",
                                                   "channels": CHANS}))
    chk("an unknown layout is an error", len(errs), 1)

    # ls_channels owns the rules; ls_config must surface them rather than
    # duplicating them, or the two will disagree about what is valid.
    errs, _ = C.validate(minimal(
        tmp, acquisition={"layout": "multiplex",
                          "channels": [CHANS[0]]}))
    chk("a channel-table fault is reported by the config validator",
        any("marker" in e for e in errs), True)

    errs, _ = C.validate(minimal(
        tmp, acquisition={"layout": "paired", "channels": CHANS}))
    chk("paired declaring channels is an error", len(errs), 1)

    chk("paired with none is fine",
        C.validate(minimal(tmp, acquisition={"layout": "paired"}))[0], [])
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_config.py
```

Expected: `FAIL layout defaults to multiplex` with `KeyError: 'acquisition'`

- [ ] **Step 3: Add the keys to SPEC**

In `scripts/ls_config.py`, insert these two entries into `SPEC` immediately **before** the `Key("channels.dapi_index", ...)` entry:

```python
    # ---- acquisition ------------------------------------------------------
    Key("acquisition.layout", "str",
        "How the markers were imaged: one multi-channel scan per section, or "
        "one scan per marker.",
        required=True, default="multiplex", label="Acquisition layout",
        choices=["multiplex", "paired"],
        note="`multiplex` is one scan per section carrying every marker as a "
             "channel, which is what a new study should be. `paired` is the "
             "LS layout: each marker is a separate physical scan of the same "
             "section, joined by 02_pair_passes. Paired declares no channel "
             "table, because each of its scans carries the nuclear channel "
             "plus whichever marker that pass used.",
        consumers=["01_overviews", "02_pair_passes", "04a_reformat", "05c",
                   "app"]),

    Key("acquisition.channels", "raw",
        "What each CZI channel is: its name, what it is for, and how it is "
        "found in a file.",
        default=[], label="Channels",
        note="One entry per channel: `name` is the identity used in every "
             "output path and the `marker` column; `role` is nuclear, marker, "
             "registration or ignore; `czi_name` is what the microscope calls "
             "it, which is how it is located in a file; `index` is the plane "
             "to fall back on. A marker also carries `segment` (nuclear or "
             "own), and for own, a `backend` and whether its objects are "
             "`nucleus_shaped`. Empty for the paired layout.",
        consumers=["01_overviews", "05c", "app"]),
```

- [ ] **Step 4: Delegate validation to `ls_channels`**

In `scripts/ls_config.py`, inside `validate()`, immediately **before** the `for key, value in missing_paths(cfg):` loop, add:

```python
    # The channel table's rules live in ls_channels, which owns the concept.
    # Restating them here would let the validator and the reader disagree
    # about what is usable.
    acquisition = cfg.get("acquisition") or {}
    layout = acquisition.get("layout", "multiplex")
    if layout in ("multiplex", "paired"):
        try:
            import ls_channels
            for problem in ls_channels.validate(
                    acquisition.get("channels"), layout):
                errors.append(f"{path}: acquisition.channels - {problem}")
        except ImportError:                                 # pragma: no cover
            pass
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_config.py
```

Expected: `ALL PASS`

- [ ] **Step 6: Regenerate the two generated files and check them**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/ls_config.py --write-example && work/appenv/Scripts/python.exe scripts/ls_config.py --docs docs/config-reference.md && work/appenv/Scripts/python.exe tests/test_config_example.py
```

Expected: `ALL PASS`, and `git diff config.example.json` shows only the added `acquisition` block.

- [ ] **Step 7: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/ls_config.py tests/test_ls_config.py config.example.json docs/config-reference.md && git commit -m "config: a study declares its acquisition layout and its channels

acquisition.layout is multiplex or paired; the channel table's own rules stay
in ls_channels, which owns the concept, and the config validator surfaces them
rather than restating them - two copies would eventually disagree about what
is usable."
```

---

## Task 3: One read, with a scene

**Files:**
- Create: `scripts/czi_read.py`
- Test: `tests/test_czi_read.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_czi_read.py`:

```python
"""The one place the pipeline reads pixels out of a CZI.

Two things it exists to stop.

`scene=` was passed nowhere. 219 of 222 files have overlapping scene
rectangles, so a read of one scene's rectangle composites the tissue of
whichever neighbours overlap it - 2241 of 2572 scenes, and clipped fractions
overstated by up to 2.6x. See docs/czi-reading-audit.md finding 1.

And `np.squeeze` was assuming the result is grayscale. A channel with an RGB
pixel type squeezes to 3-D and every downstream shape check would compare the
wrong thing.

A fake reader is used rather than a real file: the point is which arguments
reach `read()`, and a fixture that needs a 3 GB image cannot run on a machine
without the dataset.

Run:  python tests/test_czi_read.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import czi_read as CR                                       # noqa: E402

failures = []


def chk(name, got, want):
    ok = got == want
    shown = got if len(repr(got)) < 90 else f"<{type(got).__name__}>"
    print(f"{'ok  ' if ok else 'FAIL'} {name:60} {shown!r}")
    if not ok:
        print(f"     want {want!r}")
        failures.append(name)


class Rect:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


class FakeDoc:
    """Records the arguments it was called with, and returns what it is told."""

    def __init__(self, out=None):
        self.calls = []
        self.out = np.zeros((4, 6), dtype=np.uint16) if out is None else out

    def read(self, **kwargs):
        self.calls.append(kwargs)
        return self.out


RECT = Rect(10, 20, 6, 4)

print("--- the scene reaches the reader ---")
doc = FakeDoc()
CR.read_plane(doc, RECT, 1, scene=3, zoom=0.125)
call = doc.calls[0]
chk("the scene is passed", call["scene"], 3)
chk("the plane is passed", call["plane"], {"C": 1})
chk("the rectangle is passed", call["roi"], (10, 20, 6, 4))
chk("the zoom is passed", call["zoom"], 0.125)
chk("zoom defaults to native", FakeDoc().read.__name__, "read")

doc = FakeDoc()
CR.read_plane(doc, RECT, 0, scene=0)
chk("scene 0 is a scene, not a missing one", doc.calls[0]["scene"], 0)
chk("...and the default zoom is 1.0", doc.calls[0]["zoom"], 1.0)

# A scene must be given. Defaulting it to None would silently restore exactly
# the behaviour this helper exists to end.
try:
    CR.read_plane(FakeDoc(), RECT, 0)
    chk("omitting the scene is a programming error", False, True)
except TypeError:
    chk("omitting the scene is a programming error", True, True)

print()
print("--- the result is a plane, and is checked to be one ---")
doc = FakeDoc(np.zeros((1, 4, 6, 1), dtype=np.uint16))
chk("singleton axes are squeezed away", CR.read_plane(doc, RECT, 0, scene=1).shape,
    (4, 6))

doc = FakeDoc(np.zeros((4, 6, 3), dtype=np.uint8))
try:
    CR.read_plane(doc, RECT, 0, scene=1)
    chk("a non-grayscale plane raises rather than being squeezed", False, True)
except CR.ReadError as exc:
    chk("a non-grayscale plane raises rather than being squeezed", True, True)
    chk("...and says which scene and channel", "scene 1" in str(exc), True)

print()
print("--- reading several channels of one scene ---")
doc = FakeDoc()
planes = CR.read_planes(doc, RECT, {"DAPI": 0, "pERK": 2}, scene=5, zoom=0.5)
chk("one array per requested channel", sorted(planes), ["DAPI", "pERK"])
chk("each read named its own plane",
    sorted(c["plane"]["C"] for c in doc.calls), [0, 2])
chk("...at the same scene", {c["scene"] for c in doc.calls}, {5})
chk("...and the same zoom", {c["zoom"] for c in doc.calls}, {0.5})

doc = FakeDoc()
try:
    CR.read_planes(doc, RECT, {}, scene=1)
    chk("asking for no channels raises", False, True)
except CR.ReadError:
    chk("asking for no channels raises", True, True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_czi_read.py
```

Expected: `ModuleNotFoundError: No module named 'czi_read'`

- [ ] **Step 3: Write the module**

Create `scripts/czi_read.py`:

```python
"""The one place this pipeline reads pixels out of a CZI.

It exists because of two findings in docs/czi-reading-audit.md.

**Finding 1, confirmed and widespread.** `scene=` was passed nowhere. 219 of
the 222 files have at least one overlapping pair of scene rectangles, and 2241
of 2572 scenes are involved in an overlap, so reading a scene's rectangle
without naming the scene composites whichever neighbours overlap it - up to
20.6% foreign pixels, and clipped fractions overstated by up to 2.6x. `scene`
is a required argument here, not a defaulted one: a default of None would
restore exactly the behaviour this module exists to end.

**Finding 8.** `np.squeeze` was assuming the plane is grayscale. A channel with
an RGB pixel type squeezes to 3-D, and every downstream shape comparison would
then be comparing the wrong thing. The result is checked, and says which scene
and channel when it is not what was expected.

Which plane a named channel IS lives in `ls_channels`; this module takes an
index and does not know what it means.
"""

import numpy as np


class ReadError(Exception):
    """A read returned something that is not a single 2-D plane."""


def read_plane(doc, rect, channel, *, scene, zoom=1.0):
    """One scene, one channel, at one zoom, as a 2-D array.

    `scene` is keyword-only and has no default, so a caller that has not
    thought about it fails at the call rather than reading the wrong pixels.
    """
    arr = doc.read(roi=(rect.x, rect.y, rect.w, rect.h),
                   plane={"C": int(channel)}, scene=int(scene), zoom=float(zoom))
    out = np.squeeze(arr)
    if out.ndim != 2:
        raise ReadError(
            f"reading channel {channel} of scene {scene} gave a "
            f"{out.ndim}-D array of shape {out.shape}, not a single plane. A "
            f"channel with an RGB pixel type does this; every shape check "
            f"downstream assumes 2-D.")
    return out


def read_planes(doc, rect, planes, *, scene, zoom=1.0):
    """{name: 2-D array} for several channels of the SAME scene.

    Named channels rather than a list, so a caller cannot mix up which array
    it got - which is the mistake `dapi, mark = read(0), read(1)` invites.
    """
    if not planes:
        raise ReadError("read_planes was asked for no channels.")
    return {name: read_plane(doc, rect, index, scene=scene, zoom=zoom)
            for name, index in planes.items()}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_czi_read.py
```

Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/czi_read.py tests/test_czi_read.py && git commit -m "czi_read: one read, and it names the scene

scene= was passed nowhere in the repository. 2241 of 2572 scenes are involved
in an overlapping rectangle, so a read that does not name its scene composites
a neighbour's tissue - up to 20.6% foreign pixels, clipped fraction overstated
by up to 2.6x. It is a required keyword argument here, not a defaulted one: a
default would restore the behaviour this module exists to end.

np.squeeze was also assuming grayscale. The result is checked and says which
scene and channel when it is not a single plane."
```

---

## Task 4: `01_overviews` reads through it

**Files:**
- Modify: `scripts/01_overviews.py:154-158` (`read_scene`), `:249-250`, `:324-325`
- Test: `tests/test_czi_read.py` (add a section)

`read_scene` keeps its name and gains a required `scene`. Every caller already
has it: line 246 is `s = int(r["scene_index"])`, and `rects[s]` is indexed by
exactly that.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_czi_read.py`, immediately before the final `print()` / `sys.exit()` block:

```python
# --------------------------------------------------------------------------
print()
print("--- 01_overviews reads through it ---")

import importlib.util                                       # noqa: E402

sys.path.insert(0, HERE)
from _fixture import use_temp_study                         # noqa: E402

use_temp_study()
spec = importlib.util.spec_from_file_location(
    "probe_ov", os.path.join(REPO, "scripts", "01_overviews.py"))
OV = importlib.util.module_from_spec(spec)
sys.modules["probe_ov"] = OV
spec.loader.exec_module(OV)

doc = FakeDoc()
OV.read_scene(doc, RECT, 1, 0.125, scene=7)
chk("01_overviews passes the scene down", doc.calls[0]["scene"], 7)
chk("...and still the plane it asked for", doc.calls[0]["plane"], {"C": 1})

try:
    OV.read_scene(FakeDoc(), RECT, 1, 0.125)
    chk("a caller that forgot the scene fails at the call", False, True)
except TypeError:
    chk("a caller that forgot the scene fails at the call", True, True)
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_czi_read.py
```

Expected: `FAIL 01_overviews passes the scene down` — `KeyError: 'scene'`

- [ ] **Step 3: Rewrite `read_scene` and its callers**

In `scripts/01_overviews.py`, replace lines 154-158:

```python
def read_scene(czidoc, rect, channel, zoom, *, scene):
    """One scene, one channel, at the requested zoom, as 2-D uint16.

    Delegates to czi_read, which names the scene. Without that, a read of this
    rectangle composites whichever neighbouring scenes overlap it - which is
    2241 of the 2572 scenes in this dataset.
    """
    return CR.read_plane(czidoc, rect, channel, scene=scene, zoom=zoom)
```

Add the import beside the other sibling imports, immediately after the
`from ls_config import ...` line:

```python
import czi_read as CR  # noqa: E402
```

Replace lines 249-250:

```python
                dapi = apply_tile_field(read_scene(czidoc, rects[s], 0, zoom, scene=s), fields.get(0), 1 / zoom)
                mark = apply_tile_field(read_scene(czidoc, rects[s], 1, zoom, scene=s), fields.get(1), 1 / zoom)
```

Replace lines 324-325:

```python
                    dapi_raw = read_scene(czidoc, rects[s], 0, zoom, scene=s)
                    mark_raw = read_scene(czidoc, rects[s], 1, zoom, scene=s)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_czi_read.py
```

Expected: `ALL PASS`

- [ ] **Step 5: Check no other caller was missed**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && grep -rn "read_scene(" scripts/*.py
```

Expected: every hit inside `01_overviews.py` passes `scene=`; the two in
`01k_saturation_raw.py:106-107` do not yet — that is Task 5.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/01_overviews.py tests/test_czi_read.py && git commit -m "01_overviews: name the scene when reading it

Every caller already had the scene index in hand - the loop is keyed on it and
uses it to pick the rectangle - so this only stopped it being thrown away
between there and the read."
```

---

## Task 5: `01k_saturation_raw` reads through it

**Files:**
- Modify: `scripts/01k_saturation_raw.py:104-107` (`measure`), and its call site
- Test: `tests/test_ceilings.py` (add a case)

- [ ] **Step 1: Find the call site**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && grep -n "measure(" scripts/01k_saturation_raw.py
```

Note the line number of the call — the step below refers to it as the call site.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_ceilings.py`, immediately before its final `print()` /
`sys.exit()` block:

```python
# --------------------------------------------------------------------------
print()
print("--- 01k names the scene it measures ---")


class _Rect:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


class _FakeDoc:
    def __init__(self):
        self.calls = []

    def read(self, **kwargs):
        self.calls.append(kwargs)
        import numpy as _np
        return _np.zeros((4, 6), dtype=_np.uint16)


_doc = _FakeDoc()
K.measure(_doc, _Rect(0, 0, 6, 4), {}, 1.0, False, scene=9)
chk("both channels are read from the named scene",
    sorted({c["scene"] for c in _doc.calls}), [9])
chk("...and they are the two channels it measures",
    sorted(c["plane"]["C"] for c in _doc.calls), [0, 1])
```

`tests/test_ceilings.py` loads `01_overviews.py` as `OV` through
`importlib.util.spec_from_file_location` and does not import 01k. Add it the
same way, immediately after the block that loads `OV`:

```python
_kspec = importlib.util.spec_from_file_location(
    "k01", os.path.join(SCRIPTS, "01k_saturation_raw.py"))
K = importlib.util.module_from_spec(_kspec)
_kspec.loader.exec_module(K)
```

- [ ] **Step 3: Run it to make sure it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ceilings.py
```

Expected: `TypeError: measure() got an unexpected keyword argument 'scene'`

- [ ] **Step 4: Thread the scene through**

In `scripts/01k_saturation_raw.py`, replace lines 104-107:

```python
def measure(czidoc, rect, fields, zoom, want_mask, ceiling=CEILING, *, scene):
    """Raw clipping for both channels, and the corrected figure for comparison.

    `scene` is required: measuring clipping on a rectangle that composites a
    neighbour's tissue is how the clipped fraction came to be overstated by up
    to 2.6x in the first place.
    """
    dapi_raw = OV.read_scene(czidoc, rect, 0, zoom, scene=scene)
    mark_raw = OV.read_scene(czidoc, rect, 1, zoom, scene=scene)
```

At the call site found in Step 1, add `scene=int(r["scene_index"])` to the
arguments. If the loop variable is not `r`, use whichever row is being measured
— every row in that loop comes from `manifest_scenes.csv`, which carries
`scene_index` (column 7).

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ceilings.py
```

Expected: `ALL PASS`

- [ ] **Step 6: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/01k_saturation_raw.py tests/test_ceilings.py && git commit -m "01k: measure clipping on the scene, not on whatever overlaps it

This stage is the one that measures clipping, so it is the one the scene fix
matters most to: a rectangle that composites a neighbour reports that
neighbour's saturated pixels as this section's."
```

---

## Task 6: `05a_roi_geometry` reads through it

**Files:**
- Modify: `scripts/05a_roi_geometry.py:779`
- Test: `tests/test_roi_geometry.py` (add a case)

- [ ] **Step 1: Read the surrounding function**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && sed -n '765,790p' scripts/05a_roi_geometry.py
```

The row `g` comes from `load_csv(GEOM_CSV)` — `reformatted/roi_geometry_<marker>.csv`
— which carries `scene_index` as its fifth column, so the scene is already in
hand at the read.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_roi_geometry.py`, immediately before its final `print()` /
`sys.exit()` block:

```python
# --------------------------------------------------------------------------
print()
print("--- 05a names the scene it checks against ---")

import inspect                                              # noqa: E402

src = inspect.getsource(G5)
chk("05a reads through the shared helper", "CR.read_plane" in src, True)
chk("no bare plane read is left in it", 'plane={"C": 0}' in src, False)
chk("the scene comes from the geometry row",
    'scene=int(g["scene_index"])' in src, True)
```

`tests/test_roi_geometry.py` already binds `05a_roi_geometry.py` as `G5` and
defines `chk(label, got, want)` with a `fails` counter; the lines above use
both as they are.

- [ ] **Step 3: Run it to make sure it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_roi_geometry.py
```

Expected: `FAIL 05a reads through the shared helper`

- [ ] **Step 4: Replace the read**

In `scripts/05a_roi_geometry.py`, replace the line at 779:

```python
            native = CR.read_plane(doc, _Rect(rx, ry, rw, rh), DAPI_PLANE,
                                   scene=int(g["scene_index"]), zoom=zoom)
```

Immediately above the enclosing function, add:

```python
class _Rect:
    """czi_read takes a rectangle object; this file has loose coordinates."""

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h
```

Add beside the other sibling imports:

```python
import czi_read as CR  # noqa: E402
```

and, next to the other module constants:

```python
# Plane 0 under the paired layout. The multiplex layout resolves this from the
# channel table instead - see plan 2.
DAPI_PLANE = 0
```

Delete the now-unused local `np.squeeze(...)` wrapper on that read if one
remains; `czi_read` does the squeeze and checks it.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_roi_geometry.py
```

Expected: `ALL PASS`

- [ ] **Step 6: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/05a_roi_geometry.py tests/test_roi_geometry.py && git commit -m "05a: read the scene it is checking, not the rectangle around it

This read is the one that compares a stored overview against the file it came
from, so reading a composited rectangle here made the comparison test the
wrong pixels."
```

---

## Task 7: `05c_detect_rois` reads through it

**Files:**
- Modify: `scripts/05c_detect_rois.py:455-456`
- Test: `tests/test_detect_resume.py` (add a case)

`g` here is a `roi_boxes` row, which carries `scene_index` (column 11).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_detect_resume.py`, immediately before its final `print()` /
`sys.exit()` block:

```python
# --------------------------------------------------------------------------
print()
print("--- 05c measures the scene, not its neighbours ---")

import inspect                                              # noqa: E402

src = inspect.getsource(G5C)
chk("05c reads through the shared helper", "CR.read_planes" in src, True)
chk("no bare plane read is left",
    'doc.read(roi=roi, plane=' in src, False)
chk("the scene comes from the box's own row",
    'scene=int(g["scene_index"])' in src, True)
```

`tests/test_detect_resume.py` already binds `05c_detect_rois.py` as `G5C`.

- [ ] **Step 2: Run it to make sure it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_detect_resume.py
```

Expected: `FAIL 05c reads through the shared helper`

- [ ] **Step 3: Replace the two reads**

In `scripts/05c_detect_rois.py`, replace lines 455-456:

```python
                planes = CR.read_planes(
                    doc, _Rect(x0, y0, bw, bh),
                    {"dapi": DAPI_C, "mark": MARK_C},
                    scene=int(g["scene_index"]))
                dapi = planes["dapi"].astype(np.float32)
                mark = planes["mark"].astype(np.float32)
```

Add beside the other sibling imports:

```python
import czi_read as CR  # noqa: E402
```

and, next to the other module constants:

```python
class _Rect:
    """czi_read takes a rectangle object; this file has loose coordinates."""

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_detect_resume.py
```

Expected: `ALL PASS`

- [ ] **Step 5: Check every read now names a scene**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && grep -rn "\.read(roi=" scripts/*.py
```

Expected: the only hits are inside `scripts/czi_read.py` and
`scripts/00d_czi_selftest.py` (which already passed `scene=`).

- [ ] **Step 6: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/05c_detect_rois.py tests/test_detect_resume.py && git commit -m "05c: detect in the scene, not in the rectangle around it

This is the last read in the pipeline that did not name its scene. Every read
outside czi_read.py now goes through it.

read_planes takes named channels rather than a list, because dapi, mark =
read(0), read(1) is exactly the shape that lets two arrays get swapped."
```

---

## Task 8: The LS study declares its layout

**Files:**
- Modify: `config.json` (not tracked; back it up first)
- Test: `tests/test_ls_regression.py` (already exists; run it)

- [ ] **Step 1: Back up the live config**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && cp config.json config.json.before-acquisition
```

`.gitignore` already covers `config.json.*`, so this cannot be committed.

- [ ] **Step 2: Add the block**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe - <<'PY'
import collections, io, json, os
p = "config.json"
cfg = json.load(io.open(p, encoding="utf-8"),
                object_pairs_hook=collections.OrderedDict)
assert "acquisition" not in cfg
cfg["_acquisition_note"] = (
    "This study is PAIRED: pERK and PCNA are separate physical scans of the "
    "same section, joined by 02_pair_passes. A paired study declares no "
    "channel table - each scan carries DAPI plus whichever marker that pass "
    "used, so the marker is read per file from the manifest.")
cfg["acquisition"] = collections.OrderedDict([("layout", "paired"),
                                              ("channels", [])])
tmp = p + ".tmp"
with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
os.replace(tmp, p)
print("added acquisition: paired")
PY
```

- [ ] **Step 3: Check the config validates**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/ls_config.py --check
```

Expected: `0 error(s)`. The nine "removed in schema v1" warnings are expected and unchanged.

- [ ] **Step 4: Run the constants regression**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: `ALL PASS`, `no stage derives anything different from the migrated study`. This proves no path or threshold moved. It says nothing about pixel values — Task 9 is what measures those.

- [ ] **Step 5: Run everything**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh
```

Expected: every suite passes except `test_join_metadata.py`, which fails on
`SHAPES` missing from `analysis/plot_roi_figures.R` — a pre-existing failure
from uncommitted work in that file, unrelated to this plan.

- [ ] **Step 6: Commit**

Nothing to commit — `config.json` is gitignored. Note in the next commit
message that the live config gained `acquisition: paired`.

---

## Task 9: Measure what the scene fix moved

**Files:**
- Create: `docs/scene_fix_report.py`

The spec requires a measured before/after report rather than a test, because
the fix changes real numbers on purpose and a test that asserted them
unchanged would defeat it. This is a one-off tool, deliberately not a numbered
stage: adding one would require `app/stages.py` and `docs/pipeline-guide.md`,
both of which carry uncommitted work.

- [ ] **Step 1: Write the tool**

Create `docs/scene_fix_report.py`:

```python
"""How much the scene fix moved this dataset's clipping numbers.

Not a stage, and not a test. The `scene=` fix changes real values on purpose -
a read that does not name its scene composites whichever neighbours overlap it,
and 2241 of 2572 scenes are involved in an overlap - so a test asserting the
numbers unchanged would defeat the fix. This measures the difference instead,
so it can be reviewed and quoted.

Reads only. Writes one CSV and prints a summary.

Run:  python docs/scene_fix_report.py [--limit N]
"""

import argparse
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import czi_read as CR                                       # noqa: E402
import ls_config as LC                                      # noqa: E402

CONFIG = LC.load()
OUT_ROOT = CONFIG["out_root"]
SOURCE_DIR = CONFIG["source_dir"]
MANIFEST = os.path.join(OUT_ROOT, "manifest", "manifest_scenes.csv")
FILES = os.path.join(OUT_ROOT, "manifest", "manifest_files.csv")
REPORT = os.path.join(OUT_ROOT, "qc", "scene_fix_report.csv")

COLUMNS = ["scene_uid", "animal", "file", "scene_index",
           "clipped_without_scene", "clipped_with_scene", "ratio",
           "foreign_fraction"]


def ceilings():
    """file -> clip ceiling, as the manifest records it."""
    with open(FILES, newline="", encoding="utf-8") as fh:
        return {r["file"]: float(r.get("clip_ceiling") or 65535)
                for r in csv.DictReader(fh)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many scenes (0 = all)")
    ap.add_argument("--zoom", type=float, default=0.125,
                    help="zoom to measure at; 0.125 is the overview scale")
    args = ap.parse_args()

    from pylibCZIrw import czi as pyczi

    with open(MANIFEST, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    ceiling_by = ceilings()

    by_file = {}
    for r in rows:
        by_file.setdefault(r["file"], []).append(r)

    out, done = [], 0
    for fname, scenes in sorted(by_file.items()):
        path = os.path.join(SOURCE_DIR, fname)
        if not os.path.exists(path):
            continue
        ceiling = ceiling_by.get(fname, 65535)
        with pyczi.open_czi(path) as doc:
            rects = doc.scenes_bounding_rectangle
            for r in scenes:
                s = int(r["scene_index"])
                if s not in rects:
                    continue
                rect = rects[s]
                with_scene = CR.read_plane(doc, rect, 1, scene=s, zoom=args.zoom)
                # The old behaviour, reproduced exactly: same rectangle, no
                # scene, so whatever overlaps it comes too.
                without = np.squeeze(doc.read(
                    roi=(rect.x, rect.y, rect.w, rect.h),
                    plane={"C": 1}, zoom=args.zoom))
                if without.ndim != 2 or without.shape != with_scene.shape:
                    continue
                a = float((without >= ceiling).mean())
                b = float((with_scene >= ceiling).mean())
                out.append({
                    "scene_uid": r["scene_uid"], "animal": r["animal"],
                    "file": fname, "scene_index": s,
                    "clipped_without_scene": round(a, 6),
                    "clipped_with_scene": round(b, 6),
                    "ratio": round(a / b, 3) if b else "",
                    "foreign_fraction": round(
                        float((without != with_scene).mean()), 6),
                })
                done += 1
                if args.limit and done >= args.limit:
                    break
        if args.limit and done >= args.limit:
            break

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out)

    moved = [r for r in out if r["foreign_fraction"] > 0]
    print(f"scenes measured        : {len(out)}")
    print(f"scenes whose pixels moved: {len(moved)} "
          f"({100.0 * len(moved) / max(len(out), 1):.1f}%)")
    if moved:
        ratios = [r["ratio"] for r in moved if r["ratio"] != ""]
        if ratios:
            print(f"clipped fraction was overstated by a median of "
                  f"{np.median(ratios):.2f}x, up to {max(ratios):.2f}x")
        worst = sorted(moved, key=lambda r: -r["foreign_fraction"])[:5]
        print("\nmost affected sections:")
        for r in worst:
            print(f"  {r['scene_uid']}: {100 * r['foreign_fraction']:.1f}% "
                  f"foreign pixels, clipped "
                  f"{r['clipped_without_scene']:.4f} -> "
                  f"{r['clipped_with_scene']:.4f}")
    print(f"\nwritten to {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it on a small sample first**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe docs/scene_fix_report.py --limit 40
```

Expected: a summary naming a percentage of affected scenes and a median
overstatement ratio. The audit predicts roughly 87% affected and up to 2.6×.
If it reports 0% affected, stop — either `scene=` is not reaching the reader or
the sample happened to miss every overlap; re-run with `--limit 300` before
concluding anything.

- [ ] **Step 3: Run it fully**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe docs/scene_fix_report.py
```

This opens all 222 files; expect it to take a while. It only reads.

- [ ] **Step 4: Commit the tool**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add docs/scene_fix_report.py && git commit -m "A measured report of what the scene fix moved

The fix changes real numbers on purpose, so a test asserting them unchanged
would defeat it. This measures the difference instead - per scene, how many
pixels were another section's and how far the clipped fraction was overstated -
so it can be reviewed and quoted rather than assumed.

The live config also gained acquisition: paired, declaring the LS layout. It is
gitignored, so it does not appear in this commit."
```

- [ ] **Step 5: Report the outcome**

Show the operator the summary and `<out_root>/qc/scene_fix_report.csv`. The
decision of whether to re-run `01_overviews`, `01k`, `01g` and `04j` on the
corrected reads is theirs, not this plan's — re-running changes the analysis
set, and 130 sections have already been curated against the current one.

---

## Self-review

**Spec coverage for this plan's slice.** Channel table and roles → Task 1.
Config declaration and validation → Task 2. Resolution by name then index →
Task 1. Shared read helper with `scene=` → Tasks 3-7. The `np.squeeze`
assumption → Task 3. The measured before/after report → Task 9. LS declaring
`paired` → Task 8.

**Deferred to plan 2, deliberately:** one frame per scene, layout-aware stage
list, marker naming through output paths, the composite. **Plan 3:** segmentation
backends, co-localisation, Abercrombie gating. Task 1 builds the `segment`,
`backend` and `nucleus_shaped` fields and validates them now, because a channel
table that cannot express them would have to be migrated later; nothing reads
them until plan 3.

**Names used consistently:** `ls_channels.parse/validate/resolve/markers/nuclear`,
`ChannelError`; `czi_read.read_plane/read_planes`, `ReadError`. `read_plane`
takes `scene` keyword-only with no default in every task that calls it.

**One risk this plan does not remove.** After Task 7 the pipeline reads
correctly but `D:\LS-analysis` still holds outputs measured the old way. Until
the affected stages are re-run, `qc/saturation_raw.csv` and the analysis set
derived from it describe reads that composited neighbours. Task 9 quantifies
that; acting on it is the operator's call.
