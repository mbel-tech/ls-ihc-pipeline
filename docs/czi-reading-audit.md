---
title: "How this pipeline reads CZI, and where that diverges from what libCZI documents"
subtitle: "An audit of the pylibCZIrw call sites against the ZEISS libCZI specification"
date: 2026-09-03
---

# Why this document exists

Every pixel whose value reaches a figure or a table in this pipeline is read by
`pylibCZIrw` 6.1.0, ZEISS's own Python binding over libCZI. That decision is
recorded in `requirements-czi.txt` and enforced per stage in `app/stages.py`.
What has never been checked is whether the *calls* the pipeline makes to that
library mean what the downstream numbers assume they mean.

This document is that check. Each call site was compared against the libCZI
documentation — the Image Document Concept, Coordinate Systems, Accessors and
Valid-Pixel Mask chapters, and the accessor `Options` structures in
`libCZI_Compositor.h` — and against the pylibCZIrw API reference. Where a
divergence depended on a property of *these particular files*, it was settled by
probing all 222 CZIs read-only rather than by argument. The probe results are
reported alongside each finding, and the probes themselves are described at the
end so they can be re-run.

Three findings change published numbers. Three more that looked dangerous on the
documentation turned out not to apply to this dataset, and that is recorded here
too, because "we checked and it is fine" is worth as much to a reader as a defect
is.

# Summary

| # | Finding | Status | Effect on published numbers |
|---|---------|--------|------------------------------|
| 1 | `read()` is never given `scene=` | **Confirmed, widespread** | Clipped fraction inflated up to 2.6x; overview pixels wrong for 87% of sections |
| 2 | Clipping measured on pyramid-downsampled pixels | **Confirmed** | Clipping understated 1.1x to 23x, section-dependent |
| 3 | Coverage not used as the saturation denominator | **Confirmed** | Clipped fraction understated ~14% |
| 4 | Clip ceiling hardcoded to 65535 | Correct here, fragile | None on this dataset |
| 5 | `scenes_bounding_rectangle` includes pyramid layers | Benign here | None — origins are identical |
| 6 | Scaled output shape assumed rather than read | Not manifesting | None |
| 7 | Scene rectangle re-derived rather than recorded | Latent risk | None yet |
| 8 | `np.squeeze()` assumes grayscale | Latent risk | None on this dataset |
| 9 | `czi_meta.summarise()` omits bit depth and per-channel type | Hygiene | None |
| 10 | Assorted loose ends | Hygiene | None |

# What the pipeline gets right

Stated first, because most of the reading is correct and the corrections below
should not be read as a verdict on the whole.

**The reader architecture is deliberate and holds.** Three readers exist and
each has exactly one job: `pylibCZIrw` for every value that reaches a result,
`czifile` confined to instrument characterisation in `01h_tilefield_raw.py`, and
Bio-Formats retired from the data path after the Memoizer incident. Nothing in
the audit found a pixel crossing that boundary.

**The "highest M wins" rule is applied correctly.** `01h_tilefield_raw.py`
derives its stitch map by resolving overlapping tiles in favour of the highest
M-index, grouped per scene. That is exactly what libCZI does: `Options::Clear()`
sets `sortByM = true` by default, documented as "tile with highest M-index will
be 'on top'", and the pylibCZIrw notes scope that rule to within a single scene.
The pipeline reimplemented the rule from the specification and got it right.

**Negative and non-zero origins are handled.** libCZI's raw subblock coordinate
system has an arbitrary origin, and these files use it: X runs from about
-86,000 to -14,000. Every call site takes its ROI from `rect.x`/`rect.y` rather
than assuming `(0, 0)`, which is the correct handling of a coordinate system the
library explicitly declines to normalise for you.

**Reads are batched per file and never threaded.** One `open_czi` per file with
all that file's scenes read inside it; `06f_recensor_nuclei.py` avoids reopening
the 222 files entirely by replaying rectangles recorded earlier. No CZI read is
ever threaded or multiprocessed, so libCZI's reader thread-safety caveats do not
apply.

**Clipping is measured before flat-field correction.** A multiplicative
correction would move the clip ceiling; measuring first is the right order.

**The metadata reader is justified.** `czi_meta.py` hand-parses the
`ZISRAWMETADATA` segment so the manifest can read headers straight out of STORED
transfer zips without decoding pixels. The offsets are right, both segment magics
are validated, and no library offers the same thing over a zip member.

# Finding 1 — every read composites all scenes

## What the library documents

`CziReader.read()` takes a `scene` argument. pylibCZIrw documents its default as
*all scenes considered*, and it is the parameter that restricts which subblocks
contribute; internally it is libCZI's `sceneFilter` accessor option. An ROI does
not filter by scene. Separately, libCZI's Image Document Concept states that
scene bounding boxes *may* overlap, even where the layer-0 subblocks inside them
may not.

## What the pipeline does

Four call sites — `01_overviews.py:155`, `01k_saturation_raw.py:145` and `:149`,
`05a_roi_geometry.py:685`, `05c_detect_rois.py:421-422` — all follow one shape:

```python
rects = czidoc.scenes_bounding_rectangle
arr = czidoc.read(roi=(rects[s].x, rects[s].y, rects[s].w, rects[s].h),
                  plane={"C": channel}, zoom=zoom)
```

The scene index is used to *look up a rectangle* and then discarded. `scene=` is
passed nowhere in the repository.

## What the probe found

Scene rectangles in this dataset overlap heavily, and not as a pyramid artefact —
the same overlaps are present when only layer 0 is considered.

| Measure | Value |
|---|---|
| Files with at least one overlapping scene-rectangle pair | 219 of 222 |
| Scenes involved in at least one overlap | 2241 of 2572 (87.1%) |
| Overlapping pairs, total | 2815 |
| Pairs overlapping >1% / >5% / >10% of the smaller scene | 2249 / 646 / 560 |
| Largest single overlap | 41.3% (LS136_2b, scenes 6 and 8) |

Reading nine high-overlap sections both ways confirms that the overlap is not
merely geometric — it puts a neighbouring section's tissue into the array:

| Section | Pixels differing | Foreign pixels | Clipped fraction, all scenes | Clipped fraction, `scene=` |
|---|---|---|---|---|
| LS87_7a s6 | 50.1% | 18.5% | 0.001166 | 0.000653 |
| LS22_9b s7 | 41.5% | 20.6% | 0.000104 | 0.000104 |
| LS136_2b s6 | 30.0% | 15.6% | 0 | 0 |
| LS69_8a s4 | 23.1% | 10.6% | 0.258927 | 0.227126 |
| LS105_8b s0 | 13.7% | 7.5% | 0.000017 | 0.000017 |
| LS37_9b s2 | 12.1% | 10.7% | 0.000031 | 0.000012 |
| LS105_1a s3 | 0.0% | 0.0% | 0.258218 | 0.258218 |

"Foreign" counts pixels that are empty under scene filtering and non-empty
without it — unambiguously another section's tissue. The reported clipped
fraction is overstated by up to 2.6x, and by 14% on LS69_8a s4, which sits at
exactly the magnitude where the 04j gate operates.

One detail deserves emphasis. On LS136_2b s6 the maximum pixel value *rises*
from 55,731 to 56,124 once the scene filter is applied. Neighbouring tiles do not
merely fill empty space; where the rectangles overlap they can win the
composition and overwrite the section's own brighter pixels. The corruption runs
in both directions.

## What is affected

Everything downstream of `01_overviews.py` and `01k_saturation_raw.py`: the
overview PNGs used for curation, reformatting and the artifact mask; the tissue
and `scanned` masks; the dataset-wide display ranges sampled at
`01_overviews.py:232-239`; `focus.csv`; `saturation_raw.csv` and the censor masks
that feed the 04j gate and `06f_recensor_nuclei.py`.

## Fix

Pass `scene=s`. One argument per call site. The ROI may stay as it is, or be
dropped entirely — with `scene=` supplied, pylibCZIrw defaults the ROI to that
scene's own bounding box.

**This changes published numbers.**

# Finding 2 — clipping is measured on pyramid tiles

## What the library documents

At `zoom < 1`, `read()` routes through `ISingleChannelScalingTileAccessor`, which
selects a pyramid layer and scales. Averaging is precisely the operation that
destroys the property being measured: a clipped pixel survives downsampling only
if its whole neighbourhood was clipped.

## What the pipeline does

`01_overviews.py:295-296` and `01k_saturation_raw.py:146` compute the clipped
fraction from an array read at `zoom = BASE_PX_UM / TARGET_UM` = 0.125.

`01k_saturation_raw.py:110-165` already recognises the problem and measures the
dilution ratio empirically — the right instinct — but then applies a single
global ratio derived from 30 AF568 sections to every section and marker.

## What the probe found

These files carry a full pyramid. Every one of the 222 stores minification
factors 1, 2, 4, 8 and 16; 146 of them also store 32, and three store 64, the
depth following the size of the largest scene (LS105_1a, which stops at 16:
972 / 1048 / 304 / 108 / 28 subblocks per level).

*Corrected 2026-09-03.* This paragraph originally reported 1 to 16 as the whole
range, generalised from enumerating two files by hand. `00d_czi_selftest.py`
enumerates all 222 and found the deeper levels. Nothing downstream of the claim
changes — the three configured read scales are 1/2, 1/4 and 1/8, and those exist
in every file — but the range as first stated was a two-file sample presented as
a dataset fact.

All three configured read scales land exactly on a stored level: 5.2 µm/px is
zoom 1/8, 2.6 µm/px is 1/4, 1.3 µm/px is 1/2. So `01_overviews.py:370`, which
prints the zoom as "exact, not a pyramid level", and the module docstring at
`:15-18`, which says sections come out at 5.20 µm/px "instead of 'nearest stored
pyramid level'", are both wrong. The output *pixel size* is right; the claim
about where the pixels came from is not. They are ZEISS-generated pyramid tiles.

Measuring six sections at native resolution — tiled in 4096-row strips, with
`scene=` applied so finding 1 does not contaminate the result — reproduces the
recorded ratios and confirms the magnitude:

| Section | at zoom 0.125 | at native | ratio |
|---|---|---|---|
| LS22_s08a_sc03 | 0.000977 | 0.001668 | 1.71 |
| LS22_s08a_sc00 | 0.000652 | 0.001105 | 1.70 |
| LS22_s08a_sc05 | 0.000145 | 0.000253 | 1.75 |
| LS22_s08a_sc09 | 0.000638 | 0.001127 | 1.77 |
| LS22_s08a_sc01 | 0.000054 | 0.000109 | 2.03 |

Across the 30-section sample the pipeline already recorded in
`saturation_raw_native.csv`, the ratio has a median of 1.73 but a range of
**1.08 to 22.99**. That spread is the finding. A per-section dilution factor
spanning a factor of 21 cannot be replaced by one global constant, and a 1%
tolerance applied to the diluted number is not the same test on any two sections.

## Fix

Measure clipping at `zoom=1.0`, reading each scene in strips so a full-resolution
section never lands in memory at once — the probe does exactly this and runs in
seconds per section. Retire the global dilution factor. Keep the 0.125 read for
the overview PNG, which is what it is actually for.

**This changes published numbers, and it bears directly on the 04j tolerance.**

# Finding 3 — the coverage mask is computed but not used as the denominator

`background_pixel` is never passed to `read()`, so it defaults to 0 and pixels
not covered by any subblock come back as genuine zeros.

`01_overviews.py:306` already turns that into a real coverage mask
(`scanned = (dapi > 0) | (mark > 0)`), which is the right idea. But the clipped
fraction at `:295` is a `.mean()` over the *whole rectangle*, background included.
A scene bounding box is an axis-aligned rectangle around irregular tissue, so the
denominator carries a large empty margin.

Measured on the same six sections, switching to the coverage denominator raises
the native clipped fraction by roughly 14% — for example LS22_s08a_sc03 goes from
0.001668 to 0.001899.

libCZI's Valid-Pixel Mask chapter is the principled version of this, but
`maskAware` is not exposed through pylibCZIrw, so the coverage mask the pipeline
already builds is the available route.

Note that this correction pushes the clipped fraction *up* while finding 1 pushes
it *down*. They are independent and do not cancel.

Scope: this changes `saturated_fraction_raw` and its siblings as reported. It
does not change the 04j gate, which already divides by tissue rather than by the
frame (`04j_censor_clipped.py:230` and `:324-325`).

**This changes published numbers.**

# Finding 4 — the 65535 ceiling is correct here, but hardcoded

`CEILING = 65535` at `01k_saturation_raw.py:73`, repeated as a literal at
`01_overviews.py:295-296` and `:340`, and quoted onward through
`01g_saturation_map.py` and `04j_censor_clipped.py`.

The concern was that `pixel_types` reports the *container* (`Gray16`), not the
sensor depth. CZI carries the real depth per channel in `ComponentBitCount`, and a
12- or 14-bit camera left-shifted into a 16-bit container would clip well below
65535. A second concern was that ZEN's online shading correction, if enabled,
would make the ceiling per-pixel rather than a single value.

**Neither applies to this dataset.** Across all 222 files:

- `ComponentBitCount` is 16 at image level and 16 on every channel (DAPI in 222
  files, AF488 in 117, AF568 in 105);
- every `BitCountRange` in the display settings is 16;
- `pixel_types` is `Gray16` for both channels in every file;
- `SelectedShadingReferenceMode` is `None` in all 222 files;
- `IsOnlineStitchingEnabled` is `false` in all 222 files.

So 65535 is the correct ceiling, the clip is a genuine hard clip at a single
value, and online shading is not a candidate explanation for anything.

The remaining objection is only robustness: the value is correct by circumstance,
not by derivation, and nothing in the pipeline reads `ComponentBitCount` at all.
A future 12- or 14-bit dataset would silently measure zero clipping. Deriving the
ceiling once at manifest time and recording it costs almost nothing and removes
the literal from three files.

**This changes no published number.**

# Finding 5 — the pyramid-inclusive rectangle is benign here

`scenes_bounding_rectangle` includes pyramid layers; pylibCZIrw also offers
`scenes_bounding_rectangle_no_pyramid`, restricted to layer 0. The pipeline uses
the pyramid-inclusive form everywhere. libCZI's Coordinate Systems chapter defines
CZI-pixel coordinates by subtracting the top-left of `boundingBoxLayer0Only`,
which made this look like a coordinate-origin risk.

It is not, on these files. Across all 222 files the total bounding rectangle's
*origin* is identical in both frames, and across **all 2572 scene rectangles**
the origin delta is exactly `(0, 0)`. Only the extents differ — a few tiles'
worth of pyramid padding at the far edge, at most 40 px, with a per-file median
of 20 px and 28 files above 28 px.

*Corrected 2026-09-04.* This paragraph first reported 496 scenes and a 0–28 px
extent range, from a hand probe over the first 40 files.
`00d_czi_selftest.py` measures all 2572 and finds the range runs to 40 px. The
finding itself is unchanged and if anything better supported: the origin, which
is the only thing every stored ROI coordinate is anchored to, is identical in
every scene of every file.

Since every coordinate mapping in `05a_roi_geometry.py` is anchored on the origin,
nothing is misplaced. Switching to the `_no_pyramid` form would be marginally more
correct and would shave a few pixels off the right and bottom margins, but it is
not worth the migration on its own.

**This changes no published number.**

# Finding 6 — scaled output shapes are exact here

libCZI documents that a scaled bitmap's size "is subject to rounding errors" and
that `CalcSize` must be used when the exact size matters; pylibCZIrw notes the
allocation takes two calls for this reason. `05a_roi_geometry.py:449-455` already
carries a ±2 pixel tolerance over exactly this concern.

Checked at all three configured zooms on nine sections — 27 reads — the returned
shape equalled `round(h * zoom), round(w * zoom)` every time, with no mismatches.
The scene rectangles and the zoom factors here are clean powers of two, which is
why. The ±2 tolerance is harmless and can stay.

**This changes no published number.**

# Finding 7 — the scene rectangle is re-derived rather than recorded

`05a_roi_geometry.py:308-318` reopens each CZI to recover the rectangle the
overview export used, and its docstring says why: the export "read
`czidoc.scenes_bounding_rectangle` at the time and did not record it."

Every curated ROI coordinate is therefore anchored to a value recomputed from the
library on demand. A pylibCZIrw upgrade, or the switch contemplated in finding 5,
would move that anchor and silently invalidate curated coordinates with no error
raised — the ±2 pixel check would pass and the ROIs would simply be in the wrong
place.

`01k_saturation_raw.py:87-89` and `:277-278` already do the right thing, storing
`rect_x`, `rect_y`, `rect_w` and `rect_h` in `saturation_raw.csv` so that `06f`
can map a nucleus back without reopening 222 files. The overview export should
record the same four numbers, plus the zoom, the property name used and the array
shape actually returned.

This is the cheapest insurance in this document.

**This changes no published number.**

# Finding 8 — `np.squeeze()` assumes a grayscale channel

`read()` returns `[y, x, 1]` for a grayscale channel and `[y, x, 3]` for BGR.
Every call site applies `np.squeeze`, which is correct for the former and silently
wrong for the latter. `05c_detect_rois.py:423` guards with `dapi.ndim != 2`, but
`continue`s past the failure rather than raising, so a pixel-type surprise would
quietly drop ROIs rather than stop the run.

All channels in all 222 files are `Gray16`, so nothing is wrong today.
`arr[..., 0]` with an assertion against `czidoc.pixel_types` is the honest form
and costs one line in the shared `read_scene()` helper.

**This changes no published number.**

# Finding 9 — `czi_meta.summarise()` omits fields the pipeline needs

- No `ComponentBitCount`, which is what finding 4 wants recorded.
- Image-level `PixelType` only, though CZI permits per-channel pixel types and
  pylibCZIrw surfaces them as `pixel_types`. The captured value is written to
  `manifest_files.csv` but never drives a decode or bit-depth decision anywhere.
- Scene geometry is taken from `CenterPosition` and `ContourSize` in micrometre
  stage coordinates — a different frame from the pixel rectangles every read uses,
  and not convertible without the stage-to-pixel transform.
- `.//` matches anywhere in the tree, so `.//Objectives/Objective/...` and
  `.//CameraName` take the first match in document order, which can come from a
  hardware-settings block rather than the instrument block.

# Finding 10 — loose ends

**A supported call is already known and still unused.** `LOGS.md:2772-2775`
records that `enumerate_subblocks_subset(..., only_layer0=True)` independently
confirmed the hand-rolled binary parser in `01e_tile_geometry.py`, and concludes
"the parser can now be replaced with the supported call". It never was. The probes
in this audit used `enumerate_subblocks` successfully, so the call works as
documented in 6.1.0.

**`01e` detects pyramid entries heuristically.** `01e_tile_geometry.py:94` uses
`x["size"] // x["stored"] != 1` — integer division, so a hypothetical 2041/2040
entry would read as layer 0. libCZI's definition is physical size *not equal to*
logical size, and `DirectoryEntryDV` carries an explicit `PyramidType` byte the
parser skips over.

**The Groovy path assumes 16 bits without checking.**
`01_overviews.groovy:189-199` reads two bytes per pixel unconditionally.
`01a_flatfield.groovy:112` is the only place in the repository that checks a pixel
type at all. The Groovy path is retired from the data path but is still step 4 of
`run_all.sh`.

**A subblock cache is available and unused.** `open_czi()` accepts `cache_options`,
exposing libCZI's `subBlockCache`. `05c_detect_rois.py` issues many small reads
per file and is the one stage that might benefit; worth benchmarking before
adopting.

**Version pin drift.** `README.md:33` and `requirements.txt:13` pin czifile at
`2026.6.12`; `docs/software_versions.md:5` and `docs/pipeline-methods.md:643`
report `2026.8.16`, which is what is actually installed. `software_versions.md` is
a methods artefact, so the two should agree.

# Recommended order of work

**Ready to apply — no published number moves.**

1. Record the scene rectangle, zoom, property name and returned shape in the
   overview export, and have `05a` read them (finding 7).
2. Derive the clip ceiling from `ComponentBitCount` at manifest time and read it
   from there instead of three literals (findings 4 and 9).
3. Replace `np.squeeze` with `arr[..., 0]` plus a pixel-type assertion (finding 8).
4. Correct the two "not a pyramid level" claims in `01_overviews.py` (finding 2).
5. Tidy the loose ends in finding 10.

**Requires a decision, because published numbers move.**

6. Pass `scene=` at all four call sites (finding 1). This is the largest single
   correctness gain in this document.
7. Measure clipping at native resolution in strips and retire the global dilution
   factor (finding 2).
8. Use the coverage mask as the saturation denominator (finding 3).

Items 6 and 7 feed `saturation_raw.csv` and the censor masks, and therefore the
04j gate. Item 8 changes the reported `saturated_fraction_raw` columns but not
the gate itself, which `04j_censor_clipped.py:230,324-325` already computes
against a tissue denominator rather than the frame. All three should be done
together, and the tolerance revisited afterwards against the corrected
distribution rather than before.

# Reproducing the probes

Three read-only scripts, run under `work/appenv/Scripts/python.exe`, which has
pylibCZIrw 6.1.0 installed. None writes to the source directory or to
`D:\LS-analysis`.

- **Probe A** — all 222 files, header and metadata only, about two minutes.
  Pairwise-intersects `scenes_bounding_rectangle`; compares every bounding-box
  property against its `_no_pyramid` counterpart; extracts `ComponentBitCount`,
  `BitCountRange`, `SelectedShadingReferenceMode` and `IsOnlineStitchingEnabled`
  from `raw_metadata`.
- **Probe B** — nine high-overlap sections. Reads each ROI with and without
  `scene=` and classifies the differing pixels; checks the returned shape at zoom
  0.125, 0.25 and 0.5 against `round(w * zoom)`; enumerates subblocks to tally the
  stored pyramid minification factors. Note that the pyramid tally was run on two
  files only, which is how the level range came to be understated — see the
  correction under finding 2. Probes A and B are now both folded into
  `scripts/00d_czi_selftest.py`, which runs the tally over every file.
- **Probe C** — six sections that the existing run recorded as clipping. Reads each
  scene at native resolution in 4096-row strips and compares the clipped fraction
  against the 0.125 read, with and without the coverage denominator. Both reads use
  `scene=` so finding 1 does not contaminate finding 2.

Two independent checks confirm the probes read the same reality the pipeline
does. Scene counts from probe A match the `size_s` recorded in
`manifest_files.csv` on all 444 rows checked, with no mismatches. Enumerating
layer-0 subblocks returns 2040 px tiles on an 1836 px pitch — the geometry
`01_overviews.py:64-67` and `01f_tilefield.py:51-68` already depend on, derived
here by a different route.

Probe C reproduces the `native_over_overview` ratios already in
`saturation_raw_native.csv` to three decimal places on five of the six sections.
It differs on the sixth (LS22_s08a_sc08: 1.598 against the recorded 1.637),
which is the expected direction for a section whose recorded value was measured
without the scene filter, though the audit did not decompose that difference
further.
