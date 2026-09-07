# Channels and markers

2026-09-07

## Why

The pipeline can be pointed at any folder of CZIs now, and read any filename
grammar, but it can still only measure one thing: a DAPI channel and one marker,
in two separate scans, called `AF568` and `AF488`. Those two names appear at 197
load-bearing sites across 36 files — as `argparse` choices, as path segments, as
CSV column names, and as `if marker == "AF568"` branches that select different
files. A second lab cannot use this.

Two assumptions run deeper than the names.

**Arity.** `02_pair_passes.py` hardcodes `marker_a, marker_b = "AF568", "AF488"`
and every `chosen.get((animal, slide, "AF568"))` returns `[]` for anything else —
a whole-pipeline-empty failure that reports nothing.

**Layout.** Each marker is a separate physical scan, so `scene_uid` differs per
marker and `(scene_uid, roi_index)` is unique. `05a.all_boxes()` raises
`SystemExit` if uids ever collide across markers, because every downstream join
depends on it. A multiplex scan collides them by construction.

This was originally split into genericisation now and new detection modes later.
The operator chose to take both together, so this one spec covers the whole of
it.

## What a study declares

```json
"acquisition": {
  "layout": "multiplex",
  "channels": [
    {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI",  "index": 0},
    {"name": "pERK", "role": "marker",  "czi_name": "AF568", "index": 1,
     "segment": "nuclear"},
    {"name": "PCNA", "role": "marker",  "czi_name": "AF488", "index": 2,
     "segment": "nuclear"},
    {"name": "GFAP", "role": "marker",  "czi_name": "AF647", "index": 3,
     "segment": "own", "backend": "threshold", "nucleus_shaped": false}
  ]
}
```

pERK and PCNA are both nuclear here, which is what they are; GFAP is in the
example only to show what a marker that is not gets declared as.

Roles are `nuclear`, `marker`, `registration` (aligned to the atlas, never
counted) and `ignore`.

**A channel resolves by `czi_name` first**, falling back to `index`, and fails
loudly if neither resolves. Reading the wrong plane must never be something that
happens quietly. The app proposes the table from the CZI's own channel metadata
— `czi_meta.py` already extracts name, dye, excitation, emission and exposure
per channel — and the operator confirms it; the stored table is what stages
read, so a later file with reordered channels is still read correctly.

**The marker's identity is the name the operator gives it.** `pERK`, not
`AF568`: it is the `marker` column, the directory name, the workbook sheet and
the figure label. The fluorophore and CZI channel name ride along as provenance.
The LS study names its two channels `AF568` and `AF488`, so every existing path
and column stays byte-identical.

`layout: paired` is the legacy route and declares **no** channel table, because
it cannot: each LS scan carries DAPI plus whichever marker that pass used, so
the marker is read per file from the manifest exactly as today.

## What the marker dimension becomes

Under `multiplex` there is **one frame per scene**. `04a_reformat` runs once, not
once per marker: rotation, cropping, the artifact mask and clipping censorship
are decided once for pixels that are the same pixels. ROI discs are curated once
and every marker is measured inside them.

That deletes the reason `04i_propagate_to_perk` exists — it carries PCNA curation
onto the paired pERK scan — and leaves `02_pair_passes` nothing to pair. Neither
is removed: both become `paired`-only, so LS keeps working and the code that
built that dataset stays readable.

`marker` is already a column on `roi_nuclei.csv`. What changes is that
`(scene_uid, roi_index)` stops being unique, so `05a.all_boxes()`'s
uid-collision guard becomes layout-aware rather than unconditional — under
multiplex a collision is the expected state, not the error it is under paired.

Under `paired`, every output path keeps its current name, including the
asymmetry where `AF488` is the unsuffixed default. It is not tidy, but tidying it
would move real data on a drive holding 130 curated sections for no gain.

## Reading the CZI

One helper replaces the `plane={"C": 0}` / `{"C": 1}` literals in
`01_overviews`, `01k_saturation_raw`, `05a_roi_geometry` and `05c_detect_rois`.
It takes a scene and a channel role, and it **passes `scene=`**.

That closes finding 1 of `czi-reading-audit.md`, which is the same helper the
audit's own Task 4 was going to build. Writing it twice would mean the second
version replacing the first before it had been used.

**This deliberately moves LS's numbers.** 219 of 222 files have overlapping
scene rectangles and 2241 of 2572 scenes composite a neighbour's tissue, so
clipped fractions are currently overstated by up to 2.6×. Clipping and
censorship outputs will change. That is the fix working, not a regression, and
it must be reported rather than asserted away.

## Detection

Each marker declares how it is segmented.

- `segment: nuclear` — segment the nuclear channel, measure this marker inside
  those masks. LS's current route, unchanged.
- `segment: own` — segment this marker's own channel, with a backend:
  - `stardist`, for anything nucleus-shaped;
  - `threshold`, for anything else: per-section background by the same
    median + 3 × 1.4826 × MAD rule `06a` already uses for positivity, then
    connected components above a minimum area. No new dependency, and a rule
    already validated on this data. It finds stained objects and does not
    pretend they are cells.

A study may declare **no nuclear channel**, in which case every marker is
segmented on its own.

**Abercrombie applies only where the objects are nuclear.** Markers segmented on
the nuclear channel get the correction with `h` measured as now. A marker
segmented on its own channel gets it only if it declares `nucleus_shaped: true`;
otherwise counts are raw and the reason is recorded in the output rather than
left for a reader to infer. `N = n × T/(T+h)` assumes spherical, randomly
positioned objects, which fibre staining is not. Raw and corrected stay side by
side, as they do today.

## Co-localisation

Objects from different markers are not the same shapes — one may have come from
a nuclear mask and another from its own channel — so overlap fractions are not
comparable between pairs.

**A is co-localised with B when A's centroid falls inside B's mask.** That is
asymmetric, so both directions are computed and recorded, and the report states
which it used. There is no threshold, so there is no threshold to tune wrongly;
this pipeline already carries one uncalibrated parameter in the detection
threshold and does not need a second.

Written to a new `results/roi_colocalisation.csv`, keyed by
`(scene_uid, roi_index, marker_a, object_a, marker_b, object_b)`, rather than
widening `roi_nuclei.csv` — the objects being related are rows in it, and a
join table is the honest shape for a many-to-many relation.

## The stage list

`Stage` gains a `layouts` field, defaulting to both. `02_pair_passes` and
`04i_propagate_to_perk` become `paired`-only. The sidebar shows what applies to
the open study and `run_all.sh` skips the rest.

`tests/test_stages.py` checks every numbered script is listed for **at least
one** layout, so a stage cannot disappear by being listed for none.

## The composite

`04o_section_rgb` maps the first marker to red, the second to green and the
nuclear channel to blue, overridable by a `display.composite` list of channel
names. The defaults reproduce LS's current output exactly. Beyond three channels
the operator needs a channel picker in the ROI curator; that is follow-up, not
part of this.

## Testing

The constants probe from `tests/_stage_probe.py` still applies: under a `paired`
LS config, no path, threshold or index may move. That covers the restructuring.

It cannot cover the `scene=` fix, which changes measured values on purpose. That
gets a **measured before/after report** on the real data — how far clipped and
censored fractions moved, per animal — produced once at implementation time for
review. Asserting it away would defeat the fix.

New suites cover: channel resolution by name, by index, and the failure when
neither resolves; the read helper passing `scene=`; the threshold backend
against a synthetic field with known objects; centroid-containment both ways
including the asymmetric case; Abercrombie applied and withheld, with the
recorded reason; and the layout-aware stage list.

## Risks

**Silent under-detection.** A cytoplasmic marker segmented by `stardist` would
find few objects and report no error. Validation refuses `backend: stardist`
together with `nucleus_shaped: false`, so the contradiction is caught in
settings rather than in a result.

**The uid-collision guard.** It exists because every downstream join depends on
`(scene_uid, roi_index)`. Making it layout-aware is the one change in this spec
that could corrupt a join rather than fail, so it needs its own test with a
deliberately colliding fixture under both layouts.

**Blocked at implementation time:** the `layouts` field touches `app/stages.py`
and `tests/test_stages.py`, both of which carry uncommitted work. Everything
else here is independent of those two files.
