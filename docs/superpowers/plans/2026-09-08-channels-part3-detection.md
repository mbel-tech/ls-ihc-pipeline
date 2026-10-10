# Channels part 3 — segmentation backends, co-localisation, Abercrombie gating

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a marker be segmented on its own channel rather than on the nuclear
one, relate objects across markers, and stop applying a nuclear correction to
things that are not nuclei.

**Architecture:** A new `scripts/ls_segment.py` owns the backends — `stardist`
(what 05c does today, lifted out) and `threshold` (median + 3×1.4826×MAD, then
connected components above a minimum area). `05c_detect_rois.py` dispatches per
marker on the channel table's `segment` / `backend` fields. Co-localisation is
computed in 05c, where both markers' label images exist in the same pass, and
written to a join table. `06a_roi_dataset.py` gates Abercrombie on whether the
counted objects are nucleus-shaped, and records the reason when it withholds it.

**Tech Stack:** Python 3.13 (`work/appenv/Scripts/python.exe`), StarDist,
`skimage.measure` (already used by 05c at :413), plain-script
tests (no pytest anywhere in this repo).

---

## Read this before Task 1

**Nothing in this plan can be exercised on real data.** The live LS study is
`paired`, declares no channel table, and both its markers are `segment: nuclear`
— the route that already exists. There is no multiplex study, and no study
declaring `segment: own`. So every backend, every co-localisation pair and every
withheld Abercrombie factor in this plan is tested against **synthetic fixtures
only**.

That is not a reason to skip it — the code has to exist before a study can
declare it — but it must be said in each commit rather than implied away. The
first real study using `segment: own` will find things. Write the tests so that
what they *do* guarantee is clear, and do not let a green suite read as "this
has been validated on microscopy".

**The regression guarantee still applies.** LS must not move:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: `no stage derives anything different from the migrated study []`, all
45 stages. Read the output, not the exit code.

**Standing repo rules.** Never `git add -A` / `git add .` / `git commit -a` —
thirteen files carry the owner's uncommitted work, and `app/stages.py` and
`tests/test_stages.py` are off limits. Never run a numbered stage script; they
overwrite `out_root`, which holds 130 curated sections. `config.json` and
`config.json.*` are gitignored. Full suite is `bash tests/run.sh` — 58 suites,
exactly one expected failure (`test_join_metadata.py`, pre-existing, from the
owner's uncommitted `analysis/plot_roi_figures.R` dropping `SHAPES`).

---

## Two things the spec leaves open

**1. What "per-section background" means for the threshold backend.**

The spec says the threshold backend uses "per-section background by the same
median + 3 × 1.4826 × MAD rule `06a` already uses for positivity". But 06a
computes that from **background discs** — regions the operator curated as
containing no signal. At segmentation time in 05c those discs exist as ROI rows,
but a marker's own channel is being segmented inside *every* ROI, including the
background ones, so using them would be circular for the very discs it is
supposed to measure.

**Chosen:** the threshold is computed **from the pixels of the frame being
segmented**, per ROI. In a fluorescence section most pixels are background, so
the median is a background estimate and the MAD is its spread. This is the same
*rule* as 06a's, applied to a different sample, and the difference is recorded
in the output rather than left for a reader to infer.

Rejected: reusing 06a's curated background discs, because 05c runs before 06a
and would have to read a file it produces.

**2. Where co-localisation is computed.**

"A is co-localised with B when A's centroid falls inside B's mask" needs B's
**mask**, not just its centroid — so it cannot be done from `roi_nuclei.csv`
after the fact. Persisting every object mask would cost far more disk than the
pipeline currently uses.

**Chosen:** compute it in `05c_detect_rois.py`, in the same pass, while both
markers' label images are in memory for the same ROI. This is only possible when
the markers come from one scan — which is exactly the `multiplex` layout that
co-localisation is for.

Under `paired` the markers are separate physical scans of different sections and
their objects are not in the same coordinate frame at all, so co-localisation is
**not computed** and the output file is not written. That is a refusal with a
reason, not an empty file: an empty `roi_colocalisation.csv` would read as "no
objects overlap".

Markers with `segment: nuclear` all share the *same* nuclear objects, so
co-localising them with each other is degenerate — every object contains itself.
Those pairs are skipped, and the skip is recorded.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `scripts/ls_segment.py` | **new** — the backends and the dispatch | `BACKENDS`, `segment(image, backend, ...)`, `threshold_labels`, `stardist_labels`, `SegmentError` |
| `scripts/ls_channels.py` | the channel model | **+** validation: `stardist` with `nucleus_shaped: false` is refused |
| `scripts/ls_config.py` | the key spec | **+** `detection.threshold.min_area_um2`, `detection.threshold.mad_k` |
| `scripts/05c_detect_rois.py` | detection | dispatch per marker; new output columns; co-localisation |
| `scripts/06a_roi_dataset.py` | the dataset | Abercrombie gated on nucleus-shaped, reason recorded |
| `scripts/06c_excel_dataset.py` | the workbook | carry the reason through |
| `tests/test_ls_segment.py` | **new** | both backends against synthetic fields with known objects |
| `tests/test_colocalisation.py` | **new** | centroid containment both ways, incl. the asymmetric case |
| `tests/test_abercrombie_gate.py` | **new** | applied, withheld, and the recorded reason |

---

## Task 1: `ls_segment` — the threshold backend

Standalone and testable alone: a function from an image to a label array, with
no config, no CZI and no StarDist.

**Files:**
- Create: `scripts/ls_segment.py`
- Test: `tests/test_ls_segment.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ls_segment.py`:

```python
"""The segmentation backends, against synthetic fields with known objects.

Synthetic on purpose: the point of these is that the RULE is right - this many
objects, this threshold, this minimum area - not that it segments microscopy
well. Nothing here has met a real section, and the first study that uses
`segment: own` will find things these cannot.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_segment as SG                                     # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(56) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


def field(objects, shape=(200, 200), bg=100, noise=0):
    """A flat background with bright rectangles painted on it."""
    img = np.full(shape, bg, dtype=np.float64)
    if noise:
        img += np.random.default_rng(0).normal(0, noise, shape)
    for (y0, x0, h, w, v) in objects:
        img[y0:y0 + h, x0:x0 + w] = v
    return img


print("--- the threshold itself ---")

flat = field([])
chk("a flat field has a MAD of zero", SG.mad(flat), 0.0)
cut = SG.cut_for(flat, k=3.0)
chk("...so its cut is its median", cut, 100.0)

noisy = field([], noise=10)
chk("the cut sits above the background", SG.cut_for(noisy, k=3.0) > 100, True)

print()
print("--- objects found ---")

two = field([(10, 10, 20, 20, 5000), (100, 100, 20, 20, 5000)])
labels = SG.threshold_labels(two, k=3.0, min_area_px=10)
chk("two bright squares are two objects", int(labels.max()), 2)
chk("...and the background is label 0", int(labels[0, 0]), 0)

chk("an empty field finds nothing",
    int(SG.threshold_labels(flat, k=3.0, min_area_px=10).max()), 0)

print()
print("--- the minimum area is what stops noise being an object ---")

speck = field([(10, 10, 20, 20, 5000), (150, 150, 2, 2, 5000)])
chk("a 4 px speck is dropped at min_area_px=10",
    int(SG.threshold_labels(speck, k=3.0, min_area_px=10).max()), 1)
chk("...and kept at min_area_px=1",
    int(SG.threshold_labels(speck, k=3.0, min_area_px=1).max()), 2)

print()
print("--- touching objects are ONE object, and that is the honest answer ---")

# Connected components cannot split what is connected. A threshold backend that
# claimed to separate touching objects would be inventing a boundary; the spec
# chose this backend for things that are not nucleus-shaped, where "one stained
# region" is the truthful count.
joined = field([(10, 10, 20, 40, 5000)])
chk("one wide region is one object",
    int(SG.threshold_labels(joined, k=3.0, min_area_px=10).max()), 1)

print()
print("--- the dispatch ---")

chk("threshold is a known backend", "threshold" in SG.BACKENDS, True)
chk("stardist is a known backend", "stardist" in SG.BACKENDS, True)
try:
    SG.segment(two, "nope", min_area_px=10)
    chk("an unknown backend is refused", False, True)
except SG.SegmentError as e:
    chk("an unknown backend is refused", "nope" in str(e), True)

chk("dispatch reaches the threshold backend",
    int(SG.segment(two, "threshold", min_area_px=10).max()), 2)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_segment.py
```

Expected: `ModuleNotFoundError: No module named 'ls_segment'`.

- [ ] **Step 3: Write `scripts/ls_segment.py`**

```python
"""How a channel becomes objects.

Two backends, because two different things get counted.

`stardist` is what this pipeline has always used, and it is the right answer for
anything nucleus-shaped: it separates touching nuclei, which a threshold cannot.
05c's docstring records why watershed was rejected for that job.

`threshold` is for everything else - fibre staining, processes, plaques. It
finds stained REGIONS and does not pretend they are cells. Connected components
cannot split what is connected, so two touching objects are one object here;
that is a limitation of the method and it is the honest count for the things
this backend is meant for.

The rule is the same one `06a` uses for positivity - median + k * 1.4826 * MAD -
so the pipeline has one definition of "above background" rather than two. It is
applied to a different sample, though: 06a measures the operator's curated
background discs, while this measures the frame being segmented, because 05c
runs before 06a and cannot read a file 06a has not written yet. In a
fluorescence frame most pixels are background, so the median estimates it.

1.4826 makes the MAD a consistent estimator of the standard deviation for
normally distributed data. The median and the MAD are used rather than the mean
and the SD because the objects themselves are in the sample: a bright object
drags a mean up and inflates an SD, and would raise the very cut that is
supposed to find it.
"""

import numpy as np

BACKENDS = ("stardist", "threshold")


class SegmentError(Exception):
    """A backend could not be run, or does not exist."""


def mad(image):
    """Median absolute deviation. Not scaled - `cut_for` applies the 1.4826."""
    a = np.asarray(image, dtype=np.float64).ravel()
    if a.size == 0:
        return 0.0
    m = float(np.median(a))
    return float(np.median(np.abs(a - m)))


def cut_for(image, k=3.0):
    """The intensity above which a pixel counts as signal."""
    a = np.asarray(image, dtype=np.float64)
    return float(np.median(a)) + float(k) * 1.4826 * mad(image)


def threshold_labels(image, k=3.0, min_area_px=10):
    """Connected components above the cut, with the small ones dropped.

    `min_area_px` is not tidying: at k=3 over a large frame, thousands of
    single-pixel excursions clear the cut by chance, and each one would be
    counted as an object. The minimum is what makes the count mean "a stained
    region" rather than "a pixel that was noisy".
    """
    from scipy import ndimage

    a = np.asarray(image, dtype=np.float64)
    mask = a > cut_for(a, k=k)
    labels, n = ndimage.label(mask)
    if n == 0:
        return labels.astype(np.int32)
    # Index 0 is the background's own count and must not be tested.
    areas = np.bincount(labels.ravel())
    too_small = np.flatnonzero(areas < int(min_area_px))
    too_small = too_small[too_small != 0]
    if too_small.size:
        labels[np.isin(labels, too_small)] = 0
        # Relabel so the ids are 1..n with no holes; downstream code takes
        # labels.max() as the object count.
        kept = np.unique(labels)
        kept = kept[kept != 0]
        remap = np.zeros(labels.max() + 1, dtype=np.int32)
        remap[kept] = np.arange(1, kept.size + 1, dtype=np.int32)
        labels = remap[labels]
    return labels.astype(np.int32)


def stardist_labels(image, model, n_tiles=None):
    """StarDist's instance segmentation, tiled.

    The tiling is not optional and is not a tuning knob - see 05c's comment: at
    n_tiles=(2,2) a 1.22 Mpx ROI takes 4.1 s against 121 s untiled and returns
    the identical 1177 nuclei. The model is passed in rather than loaded here so
    that one process loads it once.
    """
    from csbdeep.utils import normalize

    a = np.asarray(image)
    if n_tiles is None:
        nt = max(2, int(np.ceil(np.sqrt(a.size / 300_000))))
        n_tiles = (nt, nt)
    labels, _ = model.predict_instances(
        normalize(a, 1, 99.8), n_tiles=n_tiles,
        verbose=False, show_tile_progress=False)
    return labels


def segment(image, backend, model=None, k=3.0, min_area_px=10):
    """Dispatch to a backend by name."""
    if backend == "threshold":
        return threshold_labels(image, k=k, min_area_px=min_area_px)
    if backend == "stardist":
        if model is None:
            raise SegmentError(
                "the stardist backend needs a loaded model; 05c loads one per "
                "process so the weights are read once.")
        return stardist_labels(image, model)
    raise SegmentError(
        f"unknown segmentation backend {backend!r}. Known backends are "
        f"{', '.join(BACKENDS)}.")
```

- [ ] **Step 4: Run the test**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_segment.py
```

Expected: `ALL PASS`.

- [ ] **Step 5: Both libraries are present — prefer the one 05c already uses**

`scipy` imports fine here, but **05c does not use it**: at `:413` and `:509` it
uses `skimage.measure.regionprops`. Confirm and follow that:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "from skimage.measure import label, regionprops; print('skimage ok')" && grep -n "skimage" scripts/05c_detect_rois.py | head -3
```

Use `skimage.measure.label` in `threshold_labels` rather than
`scipy.ndimage.label`, so the one stage that will call this module does not pull
in a second imaging library for one function. Adjust the code in Step 3
accordingly — `skimage.measure.label(mask)` returns just the array, not a
`(labels, n)` pair, so take `labels.max()` for the count.

- [ ] **Step 6: Prove nothing moved, then commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py && git add scripts/ls_segment.py tests/test_ls_segment.py && git status --short
```

Commit; the body must say the backend is unexercised by any real study, and why
median+MAD rather than mean+SD. End with:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

---

## Task 2: refuse the contradiction the spec names as a risk

The spec's stated risk: "A cytoplasmic marker segmented by `stardist` would find
few objects and report no error. Validation refuses `backend: stardist` together
with `nucleus_shaped: false`, so the contradiction is caught in settings rather
than in a result."

**Files:**
- Modify: `scripts/ls_channels.py` (`validate`)
- Test: `tests/test_ls_channels.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ls_channels.py`, matching its existing helper style (read
the top of the file — it has `errs()` / `warns()` helpers and a `block_of()`
builder added by an earlier task):

```python
print()
print("--- a backend that contradicts the object's shape is refused ---")

CONTRA = [{"name": "DAPI", "role": "nuclear", "index": 0},
          {"name": "GFAP", "role": "marker", "index": 1, "segment": "own",
           "backend": "stardist", "nucleus_shaped": False}]
chk("stardist on a marker that is not nucleus-shaped is an error",
    any("stardist" in e and "nucleus_shaped" in e
        for e in errs(CONTRA, layout="multiplex")), True)

OK_OWN = [{"name": "DAPI", "role": "nuclear", "index": 0},
          {"name": "GFAP", "role": "marker", "index": 1, "segment": "own",
           "backend": "threshold", "nucleus_shaped": False}]
chk("threshold on the same marker is fine",
    errs(OK_OWN, layout="multiplex"), [])

OK_STAR = [{"name": "DAPI", "role": "nuclear", "index": 0},
           {"name": "pERK", "role": "marker", "index": 1, "segment": "own",
            "backend": "stardist", "nucleus_shaped": True}]
chk("stardist on a nucleus-shaped marker is fine",
    errs(OK_STAR, layout="multiplex"), [])

print()
print("--- a study may declare no nuclear channel ---")

NO_NUC = [{"name": "GFAP", "role": "marker", "index": 0, "segment": "own",
           "backend": "threshold", "nucleus_shaped": False}]
chk("no nuclear channel is allowed", errs(NO_NUC, layout="multiplex"), [])
chk("...and its markers default to segmenting themselves",
    [c.segment for c in CH.markers(CH.parse(NO_NUC))], ["own"])

NUC_ONLY = [{"name": "DAPI", "role": "nuclear", "index": 0}]
chk("a nuclear channel and no marker is still nothing to measure",
    any("measure" in e.lower() or "marker" in e.lower()
        for e in errs(NUC_ONLY, layout="multiplex")), True)
```

**Check the real helper names before writing this.** If `errs()` takes the
acquisition block rather than the channel list, use `block_of(...)`. Follow what
the file actually does.

- [ ] **Step 2: Run it and watch the first check fail**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_channels.py
```

Expected: FAIL on `stardist on a marker that is not nucleus-shaped is an error`.

- [ ] **Step 3: Add the rule to `validate()`**

`ls_channels.validate` accumulates all faults and never raises — a prior review
fixed a version that short-circuited, so do not reintroduce that. Add to the
per-channel loop:

```python
        if (c.segment == SEGMENT_OWN and c.backend == "stardist"
                and not c.nucleus_shaped):
            errors.append(
                f"channel {c.name!r} asks for the `stardist` backend but "
                f"declares `nucleus_shaped: false`. StarDist segments "
                f"star-convex, nucleus-shaped objects; on fibre or process "
                f"staining it finds few objects and reports no error at all. "
                f"Use `backend: threshold` for objects that are not "
                f"nucleus-shaped.")
```

Note the failure this prevents is a **quiet undercount**, which is why it is an
error at settings time rather than a warning: there is no later point at which
it announces itself.

- [ ] **Step 4: Run the test, prove nothing moved, commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_channels.py && work/appenv/Scripts/python.exe tests/test_ls_config.py && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Commit `scripts/ls_channels.py tests/test_ls_channels.py`.

---

## Task 3: the threshold backend's two settings

**Files:**
- Modify: `scripts/ls_config.py` (SPEC)
- Test: `tests/test_config_example.py` (regenerated, not hand-edited)

- [ ] **Step 1: Add two Keys to `SPEC`**

Place them beside the existing `detection.*` keys, matching the surrounding
`Key(...)` style exactly:

```python
    Key("detection.threshold.mad_k", "num",
        "How many robust standard deviations above the background median a "
        "pixel must be to count as signal, for the `threshold` backend.",
        default=3.0, label="Threshold: MAD multiplier",
        note="3.0 is the same multiplier 06a uses for the positivity cut, so "
             "the pipeline has one definition of `above background` rather "
             "than two. Raising it finds fewer, brighter objects. It is "
             "applied to the frame being segmented rather than to curated "
             "background discs, because 05c runs before 06a and cannot read a "
             "file 06a has not written.",
        consumers=["05c_detect_rois"]),

    Key("detection.threshold.min_area_um2", "num",
        "The smallest object the `threshold` backend will report, in square "
        "micrometres.",
        default=5.0, label="Threshold: minimum object area",
        note="Not tidying. At k=3 over a whole frame, thousands of "
             "single-pixel excursions clear the cut by chance and each one "
             "would be counted as an object. This is what makes the count "
             "mean `a stained region` rather than `a pixel that was noisy`. "
             "5 um2 is well below a nucleus (a 7 um nucleus is ~38 um2) and "
             "well above sensor noise; a study counting something smaller "
             "must lower it deliberately.",
        consumers=["05c_detect_rois"]),
```

- [ ] **Step 2: Regenerate and verify**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/ls_config.py --write-example && work/appenv/Scripts/python.exe scripts/ls_config.py --docs docs/config-reference.md && work/appenv/Scripts/python.exe tests/test_config_example.py && work/appenv/Scripts/python.exe scripts/ls_config.py --check
```

`--check` on the live config must show no errors. Both keys have defaults, so
the live config needs no edit — **unlike `acquisition.markers`, which had a
layout-dependent rule.** Confirm that by running `--check` before assuming it.

- [ ] **Step 3: Prove nothing moved, commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Zero differences — no stage reads these yet. Commit `scripts/ls_config.py
config.example.json docs/config-reference.md`.

---

## Task 4: 05c segments each marker the way the study declares

**Files:**
- Modify: `scripts/05c_detect_rois.py`
- Test: `tests/test_detect_backends.py` (create)

Read `scripts/05c_detect_rois.py` around lines 400-545 first. Today it loads one
StarDist model, reads the DAPI plane per ROI, calls `model.predict_instances`,
maps centroids back to the grid to decide ROI membership, then measures the
marker channel inside each nuclear mask.

- [ ] **Step 1: Write the failing test**

Create `tests/test_detect_backends.py`:

```python
"""05c segments each marker the way the study declares it.

Synthetic: no multiplex study exists and none declares `segment: own`, so this
drives the dispatch and the recorded provenance, not the segmentation quality.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from _fixture import use_temp_study, load_stage             # noqa: E402

STUDY = use_temp_study(acquisition={"layout": "multiplex", "channels": [
    {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
    {"name": "pERK", "role": "marker", "czi_name": "AF568", "index": 1,
     "segment": "nuclear"},
    {"name": "GFAP", "role": "marker", "czi_name": "AF647", "index": 2,
     "segment": "own", "backend": "threshold", "nucleus_shaped": False}]})
D5 = load_stage("05c_detect_rois.py")

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


print("--- which channel each marker is segmented on ---")

chk("a nuclear-segmented marker uses the nuclear plane",
    D5.segment_plane_for("pERK"), "DAPI")
chk("an own-segmented marker uses its own plane",
    D5.segment_plane_for("GFAP"), "GFAP")

print()
print("--- which backend each marker gets ---")

chk("a nuclear-segmented marker inherits stardist",
    D5.backend_for("pERK"), "stardist")
chk("an own-segmented marker takes its declared backend",
    D5.backend_for("GFAP"), "threshold")

print()
print("--- provenance is recorded on every row ---")

for col in ("segmented_on", "backend", "nucleus_shaped"):
    chk(f"{col} is an output column", col in D5.COLUMNS, True)

print()
print("--- a study with no nuclear channel ---")

# Every marker segments itself; nothing asks for a plane that is not there.
print("(covered by test_ls_channels.py's parse defaults; here we only check "
      "05c does not require a nuclear channel to exist)")
chk("05c does not assume a nuclear channel exists",
    D5.NUCLEAR_NAME, "DAPI")

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it and watch it fail**

Expected: `AttributeError: module ... has no attribute 'segment_plane_for'`.

- [ ] **Step 3: Add the three helpers to `05c_detect_rois.py`**

At module level, beside the existing config-derived constants:

```python
import ls_channels as CH
import ls_segment as SG

_ACQ = CONFIG.get("acquisition") or {}
_CHANNELS = CH.parse(_ACQ.get("channels"))
_NUCLEAR = CH.nuclear(_CHANNELS)
NUCLEAR_NAME = _NUCLEAR.name if _NUCLEAR else None
_BY_NAME = {c.name: c for c in _CHANNELS}

THRESH = (CONFIG.get("detection") or {}).get("threshold") or {}
MAD_K = float(THRESH.get("mad_k", 3.0))
MIN_AREA_UM2 = float(THRESH.get("min_area_um2", 5.0))


def segment_plane_for(marker):
    """Which channel's pixels this marker's objects come from.

    `segment: nuclear` measures a marker inside the nuclear mask, so the
    objects are the nuclear channel's. `segment: own` segments the marker's own
    channel. A study with no nuclear channel has every marker on `own`, which
    ls_channels.parse already defaults for it.
    """
    c = _BY_NAME.get(marker)
    if c is None or c.segment == CH.SEGMENT_NUCLEAR:
        return NUCLEAR_NAME
    return marker


def backend_for(marker):
    """Which backend produces this marker's objects.

    A nuclear-segmented marker inherits the nuclear channel's segmentation,
    which is StarDist - that is the route this pipeline has always taken and
    the one the LS numbers came from.
    """
    c = _BY_NAME.get(marker)
    if c is None or c.segment == CH.SEGMENT_NUCLEAR:
        return "stardist"
    return c.backend or "stardist"


def nucleus_shaped_for(marker):
    """Whether this marker's objects are nucleus-shaped.

    Nuclear-segmented objects ARE nuclei, whatever the marker declares about
    itself - the shape belongs to the mask, not to the antibody.
    """
    c = _BY_NAME.get(marker)
    if c is None or c.segment == CH.SEGMENT_NUCLEAR:
        return True
    return bool(c.nucleus_shaped)
```

- [ ] **Step 4: Add the three provenance columns**

`COLUMNS` is at `scripts/05c_detect_rois.py:78`. Append:

```python
           "censored", "artifact", "off_tissue",
           # How this object was produced. Recorded per row rather than left to
           # be re-derived from config, because a dataset outlives the config
           # that made it and 06a's Abercrombie gate depends on the answer.
           "segmented_on", "backend", "nucleus_shaped"]
```

Then find the `rows.append([...])` around line 529 and append the three values
in the same order, using the helpers. **The row is a positional list, so a value
appended in the wrong order silently mislabels every object** — count the
entries against `COLUMNS` after editing.

- [ ] **Step 5: Dispatch on the backend at the segmentation call site**

Replace the direct `model.predict_instances(...)` call (around line 488) with a
call through `SG.segment`, passing the model for stardist and the pixel-area
conversion for threshold:

```python
                backend = backend_for(b["marker"])
                plane = segment_plane_for(b["marker"])
                img = dapi if plane == NUCLEAR_NAME else marker_img
                min_area_px = max(1, int(round(MIN_AREA_UM2 / px_area)))
                labels = SG.segment(img, backend, model=model,
                                    k=MAD_K, min_area_px=min_area_px)
                if labels.max() == 0:
                    continue
```

**`marker_img` may not exist yet** — under `segment: own` the marker's own plane
must be read. 05c already reads two planes via `CR.read_planes`; extend that
read to include the segmentation plane when it differs. Read the surrounding
code and do this properly; do not guess at variable names.

Keep the tiling comment where it is — it records a measured 30× speed finding
and belongs with the stardist path, now in `ls_segment.stardist_labels`.

- [ ] **Step 6: Verify**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_detect_backends.py && work/appenv/Scripts/python.exe tests/test_detect_resume.py && work/appenv/Scripts/python.exe tests/test_roi_geometry.py && work/appenv/Scripts/python.exe scripts/05c_detect_rois.py --help > /dev/null && echo "05c --help ok" && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

**The probe will report three NEW constants** (`NUCLEAR_NAME`, `MAD_K`,
`MIN_AREA_UM2`) — new is fine. Any CHANGED constant is not.

`tests/test_detect_resume.py` drives 05c's read path against a fake reader; if
it breaks, your plane-reading change is wrong. Fix the code, not the test.

- [ ] **Step 7: Commit**

Body must say the `segment: own` path is unexercised by any study. Commit
`scripts/05c_detect_rois.py tests/test_detect_backends.py`.

---

## Task 5: co-localisation

**A is co-localised with B when A's centroid falls inside B's mask.** That is
asymmetric — a small object's centroid can sit inside a large one while the
reverse is false — so both directions are computed and both are recorded. There
is no threshold, so there is no threshold to tune wrongly.

**Files:**
- Create: `scripts/ls_coloc.py`
- Modify: `scripts/05c_detect_rois.py`
- Test: `tests/test_colocalisation.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_colocalisation.py`:

```python
"""Centroid-in-mask, both ways.

The asymmetric case is the point: a small object's centroid can fall inside a
large one while the large one's centroid falls outside the small one. Overlap
fractions are not comparable when the objects came from different segmentations
- one a nuclear mask, one a threshold region - so containment is what gets
reported, in both directions, with the direction named.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_coloc as CO                                       # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


def labelled(boxes, shape=(100, 100)):
    """An int label image: boxes is [(label, y0, x0, h, w), ...]."""
    a = np.zeros(shape, dtype=np.int32)
    for (lab, y0, x0, h, w) in boxes:
        a[y0:y0 + h, x0:x0 + w] = lab
    return a


print("--- the symmetric case ---")

# Two squares sitting exactly on each other: each centroid is in the other.
same_a = labelled([(1, 10, 10, 20, 20)])
same_b = labelled([(1, 10, 10, 20, 20)])
pairs = CO.pairs(same_a, same_b)
chk("one pair found", len(pairs), 1)
chk("A's centroid is in B", pairs[0]["a_centroid_in_b"], True)
chk("B's centroid is in A", pairs[0]["b_centroid_in_a"], True)

print()
print("--- the asymmetric case, which is why both are reported ---")

# A big region and a small one near its edge but inside it.
big = labelled([(1, 10, 10, 40, 40)])
small = labelled([(1, 12, 12, 4, 4)])
p = CO.pairs(small, big)[0]
chk("the small object's centroid is inside the big one",
    p["a_centroid_in_b"], True)
chk("...but the big one's centroid is NOT inside the small one",
    p["b_centroid_in_a"], False)

print()
print("--- no relation at all ---")

far_a = labelled([(1, 5, 5, 6, 6)])
far_b = labelled([(1, 80, 80, 6, 6)])
chk("objects that do not touch produce no pair",
    CO.pairs(far_a, far_b), [])

print()
print("--- every object is considered, not just the first ---")

many_a = labelled([(1, 10, 10, 8, 8), (2, 40, 40, 8, 8)])
many_b = labelled([(1, 10, 10, 8, 8), (2, 40, 40, 8, 8)])
got = CO.pairs(many_a, many_b)
chk("two overlapping objects give two pairs", len(got), 2)
chk("...and the labels are carried through, not renumbered",
    sorted((r["object_a"], r["object_b"]) for r in got), [(1, 1), (2, 2)])

print()
print("--- an empty side ---")

chk("nothing segmented on one side gives no pairs",
    CO.pairs(many_a, np.zeros((100, 100), dtype=np.int32)), [])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it and watch it fail**

Expected: `ModuleNotFoundError: No module named 'ls_coloc'`.

- [ ] **Step 3: Write `scripts/ls_coloc.py`**

```python
"""Relating objects of one marker to objects of another.

**A is co-localised with B when A's centroid falls inside B's mask.**

Not an overlap fraction. Objects from different markers are not the same
shapes - one may have come from a nuclear mask and another from a threshold
region on its own channel - so an overlap fraction is not comparable between
pairs, and a fraction needs a cutoff, which would be a second uncalibrated
parameter in a pipeline that already carries one in the detection threshold.

Containment is asymmetric: a small object's centroid can sit inside a large one
while the large one's centroid sits outside the small one. So BOTH directions
are computed and both are recorded, and the reader is told which is which
rather than being handed one number called "co-localisation".
"""

import numpy as np


def centroids(labels):
    """{label: (row, col)} for every object in an int label image."""
    from scipy import ndimage

    a = np.asarray(labels)
    ids = np.unique(a)
    ids = ids[ids != 0]
    if ids.size == 0:
        return {}
    cens = ndimage.center_of_mass(np.ones_like(a, dtype=np.float64), a, ids)
    return {int(i): (float(c[0]), float(c[1])) for i, c in zip(ids, cens)}


def _label_at(labels, point):
    """The object id under a centroid, or 0 for background / off-image."""
    r, c = int(round(point[0])), int(round(point[1]))
    if r < 0 or c < 0 or r >= labels.shape[0] or c >= labels.shape[1]:
        return 0
    return int(labels[r, c])


def pairs(labels_a, labels_b):
    """Every related (a, b) pair, with both directions recorded.

    A pair is emitted when EITHER direction holds, so a relation is never
    dropped for being one-way - which is the whole reason both are computed.
    """
    a_cen = centroids(labels_a)
    b_cen = centroids(labels_b)
    if not a_cen or not b_cen:
        return []

    found = {}
    for a_id, point in a_cen.items():
        b_id = _label_at(labels_b, point)
        if b_id:
            found[(a_id, b_id)] = {"object_a": a_id, "object_b": b_id,
                                   "a_centroid_in_b": True,
                                   "b_centroid_in_a": False}
    for b_id, point in b_cen.items():
        a_id = _label_at(labels_a, point)
        if a_id:
            row = found.get((a_id, b_id))
            if row is None:
                found[(a_id, b_id)] = {"object_a": a_id, "object_b": b_id,
                                       "a_centroid_in_b": False,
                                       "b_centroid_in_a": True}
            else:
                row["b_centroid_in_a"] = True
    return [found[k] for k in sorted(found)]
```

- [ ] **Step 4: Run the test**

Expected: `ALL PASS`.

- [ ] **Step 5: Write the join table from 05c**

Add to `scripts/05c_detect_rois.py`:

```python
COLOC_CSV = os.path.join(RESULTS, "roi_colocalisation.csv")
COLOC_COLUMNS = ["scene_uid", "roi_index", "marker_a", "object_a",
                 "marker_b", "object_b", "a_centroid_in_b", "b_centroid_in_a"]
```

`RESULTS` is 05c's own constant at `:64`; `NUCLEI_CSV` at `:65` is
built from it the same way.

Compute pairs for each unordered pair of markers whose objects are DISTINCT.
Skip, with a recorded reason:

- **any `paired` study** — its markers are separate physical scans of different
  sections, so their objects are not in one coordinate frame and relating them
  would be meaningless. Do not write the file at all; an empty
  `roi_colocalisation.csv` would read as "nothing overlaps".
- **two markers that are both `segment: nuclear`** — they share the same nuclear
  objects, so every object contains itself and the table would be a diagonal.

```python
def coloc_applies(marker_a, marker_b):
    """Whether relating these two markers' objects means anything."""
    if LAYOUT != CH.LAYOUT_MULTIPLEX:
        return False
    return not (segment_plane_for(marker_a) == segment_plane_for(marker_b))
```

- [ ] **Step 6: Verify and commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_colocalisation.py && work/appenv/Scripts/python.exe tests/test_detect_backends.py && work/appenv/Scripts/python.exe tests/test_ls_regression.py && work/appenv/Scripts/python.exe scripts/05c_detect_rois.py --help > /dev/null && echo "05c --help ok"
```

Confirm the live paired study writes **no** `roi_colocalisation.csv` — check
`coloc_applies` returns False for it under the real config.

Commit `scripts/ls_coloc.py scripts/05c_detect_rois.py tests/test_colocalisation.py`.

---

## Task 6: Abercrombie applies only where the objects are nuclear

`N = n × T/(T+h)` assumes spherical, randomly positioned objects. Fibre staining
is not that. `06a_roi_dataset.py` currently applies the correction to every row.

**Files:**
- Modify: `scripts/06a_roi_dataset.py` (around lines 283-345)
- Test: `tests/test_abercrombie_gate.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_abercrombie_gate.py`:

```python
"""Abercrombie is applied where the objects are nuclei, and withheld elsewhere.

N = n * T/(T+h) assumes spherical, randomly positioned objects. A threshold
region on a fibre-stained channel is neither. Raw and corrected stay side by
side either way, and when the correction is withheld the reason is a value in
the output rather than something a reader has to infer from the config.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from _fixture import use_temp_study, load_stage             # noqa: E402

STUDY = use_temp_study()
A6 = load_stage("06a_roi_dataset.py")

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


print("--- the gate itself ---")

chk("nuclear-segmented objects get the correction",
    A6.abercrombie_reason(segmented_on="DAPI", nucleus_shaped=True), "")
chk("own-segmented but nucleus-shaped objects get it too",
    A6.abercrombie_reason(segmented_on="pERK", nucleus_shaped=True), "")

why = A6.abercrombie_reason(segmented_on="GFAP", nucleus_shaped=False)
chk("objects that are not nucleus-shaped do not", bool(why), True)
chk("...and the reason names the assumption",
    "spherical" in why or "nucleus" in why.lower(), True)

print()
print("--- what the factor becomes when it is withheld ---")

chk("a withheld correction is 1.0, not blank",
    A6.abercrombie_factor(h=8.0, apply=False), 1.0)
chk("...so the corrected column equals the raw one",
    A6.abercrombie_factor(h=8.0, apply=True) < 1.0, True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
```

**`06a` has no `COLUMNS` constant — do not assert on one.** At `:390` it does
`IO.atomic_write_csv(path, data, list(data[0].keys()))`: the header comes from
the **first emitted row's keys**. Two consequences the implementer must handle:

1. Adding `abercrombie_withheld_reason` to the emitted dict adds the column
   automatically — but **every row must carry the key**, not just the ones where
   the correction was withheld. A row missing it will either be dropped from the
   header (if it is the first row) or raise in the writer. Emit `""` for the
   applied case, which is what `abercrombie_reason` already returns.
2. A column-presence assertion therefore has to go through the emit path. If you
   want one, drive `06a.main()` over a small fixture and read the header off the
   written CSV — that tests the thing that actually reaches the file. Do not
   assert against a constant that does not exist.

- [ ] **Step 2: Run it and watch it fail**

Expected: `AttributeError: ... has no attribute 'abercrombie_reason'`.

- [ ] **Step 3: Add the gate to `06a_roi_dataset.py`**

```python
def abercrombie_reason(segmented_on, nucleus_shaped):
    """Why the correction is withheld, or "" when it applies.

    A string rather than a boolean, because the output has to say WHY. A reader
    six months from now finds a density that is not corrected and needs to know
    whether that was a decision or an omission.
    """
    if nucleus_shaped:
        return ""
    return (f"objects segmented on {segmented_on} are not nucleus-shaped; "
            f"Abercrombie assumes spherical, randomly positioned objects and "
            f"does not hold for them, so counts here are raw")


def abercrombie_factor(h, apply=True):
    """T/(T+h), or 1.0 when the correction does not apply.

    1.0 rather than blank so that the corrected column is always a number and
    always comparable; the withheld_reason column is what says it was not
    corrected. A blank would make every consumer handle a missing value, and
    the ones that forgot would silently drop the row.
    """
    if not apply or not h:
        return 1.0
    return T_UM / (T_UM + float(h))
```

Then, in the emit loop (around line 330), replace the unconditional
`"abercrombie_factor": round(ab, 4)` with the gated pair. The objects' shape
comes from the `segmented_on` / `nucleus_shaped` columns that Task 4 added to
`roi_nuclei.csv` — read them off the nucleus rows for that (uid, marker), and
fall back to nucleus-shaped when the column is absent, which is what every row
written before this task is.

**That fallback is the LS compatibility rule** and must be commented as such: an
existing `roi_nuclei.csv` has no `nucleus_shaped` column, and every object in it
came from the nuclear channel, so `True` is the correct reading of its silence.

- [ ] **Step 4: Verify the live study is untouched**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_abercrombie_gate.py && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Then run 06a in-process over the live study with its outputs redirected to the
scratchpad, and diff against the current `results/roi_dataset.csv`. **Every
`abercrombie_factor` must be unchanged** — LS's objects are all nuclear, so the
gate must never fire for it. Do NOT run the stage normally; redirect its output
constants first, as an earlier task did for 06a.

- [ ] **Step 5: Commit**

Commit `scripts/06a_roi_dataset.py tests/test_abercrombie_gate.py`.

---

## Task 7: the reason reaches the workbook

A withheld correction that only appears in a CSV nobody opens is not reported.

**Files:**
- Modify: `scripts/06c_excel_dataset.py`
- Test: `tests/test_join_metadata.py` is UNRELATED and already failing — ignore it

- [ ] **Step 1: Find where 06c reads the factor**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && grep -n "abercrombie" scripts/06c_excel_dataset.py
```

`:275` does `ab_by[key] = num(r["abercrombie_factor"]) or 1.0`. Carry the reason
alongside it and emit it as a column on the per-ROI sheet.

- [ ] **Step 2: Add the column and a note**

06c's docstring already says it is the one place each number is computed once.
Add the reason as a column next to the corrected density, and — where the sheet
has a header note — say that a blank reason means the correction was applied.

- [ ] **Step 3: Verify**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py && bash tests/run.sh 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

Commit `scripts/06c_excel_dataset.py`.

---

## Task 8: docs

**Files:**
- Modify: `docs/config-reference.md` (generated — regenerate, do not hand-edit)
- Modify: `docs/setting-up-a-study.md`

- [ ] **Step 1: Regenerate the config reference**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/ls_config.py --write-example && work/appenv/Scripts/python.exe scripts/ls_config.py --docs docs/config-reference.md && work/appenv/Scripts/python.exe tests/test_config_example.py
```

- [ ] **Step 2: Add a "choosing a segmentation backend" section to `docs/setting-up-a-study.md`**

It must cover, in prose an operator can act on: what `segment: nuclear` and
`segment: own` mean; that `stardist` is for nucleus-shaped objects and
`threshold` for everything else; that declaring `stardist` with
`nucleus_shaped: false` is refused and why (a quiet undercount); what
`nucleus_shaped` controls downstream (the Abercrombie correction, and that
withholding it is recorded in the output); and that co-localisation is
centroid-in-mask, asymmetric, reported both ways, and computed only under
`multiplex`.

- [ ] **Step 3: Commit**

Commit `docs/config-reference.md docs/setting-up-a-study.md config.example.json`.

---

## Verification

After every task:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh
```

58 suites plus the ones this plan adds; exactly ONE failure,
`test_join_metadata.py`, pre-existing. `test_small_fixes.py` prints `all ok`
(exit 0) — a pass.

And:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

New constants are expected; **changed** constants are not.

---

## Self-review

**Spec coverage.** `segment: nuclear` / `segment: own` → Task 4. The `stardist`
and `threshold` backends → Task 1, dispatched in Task 4. The threshold rule
(median + 3×1.4826×MAD, connected components above a minimum area) → Task 1,
settings in Task 3. A study with no nuclear channel → Task 2. Abercrombie
applied only where objects are nuclear, with the reason recorded → Task 6,
carried to the workbook in Task 7. Co-localisation by centroid containment, both
directions, in `results/roi_colocalisation.csv` → Task 5. The risk the spec names
(`stardist` + `nucleus_shaped: false`) → Task 2.

**Two spec gaps closed.** What "per-section background" samples (the frame, not
06a's curated discs, because 05c runs first) and where co-localisation is
computed (in 05c, where both label images exist; not at all under `paired`,
where the markers are different sections).

**Names used consistently.** `ls_segment.segment/threshold_labels/stardist_labels/
cut_for/mad/BACKENDS/SegmentError`; `ls_coloc.pairs/centroids`;
`05c.segment_plane_for/backend_for/nucleus_shaped_for/coloc_applies/
NUCLEAR_NAME/MAD_K/MIN_AREA_UM2`; `06a.abercrombie_reason/abercrombie_factor`.

**Not in this plan, deliberately.** The genericisation leftovers the plan-2 final
review catalogued — `04l`'s page JavaScript (six sites still saying pERK/PCNA,
including one that picks the red-vs-green SVG filter), `05a.build()`/`verify()`,
and `04m`/`04n`/`04p`/`04q`/`06e`/`06g`. Those are mechanical genericisation, not
detection, and mixing them in would make it impossible to review either half
properly. They need their own short plan, and until they are done a second study
still gets some wrong output — that is the honest state.

**The risk this plan does not remove, and cannot.** None of it has met real data.
LS is paired with two nuclear-segmented markers, so it exercises exactly the
route that already existed; the threshold backend, the `own` segmentation path,
every co-localisation pair and every withheld Abercrombie factor are guaranteed
only against synthetic fixtures. The fixtures check that the rules are what the
spec says. They cannot check that the threshold backend segments a real fibre
stain usefully, and nothing in this plan should be read as claiming they do.
