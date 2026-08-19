# Change log

Newest first. One entry per substantive change: **what changed, why, what it cost**, and what it
reverses.

This file exists because several decisions here were reversed after measurement. The reasoning is
the part that will not be reconstructable from the code six months from now — the code only shows
where things landed, not which plausible-looking route was tried and abandoned, or why.

---

## 2026-08-13 - The atlas was 101 fragments, not 101 plates. Rebuilt to 68 real plates.

**Changed:** three new scripts - `04a2_atlas_remerge.py`, `04a3_plate_reframe.py`,
`04a4_plate_rebuild.py`. Nothing overwritten: output goes to `atlas/plates_merged/` and
`atlas/plates_final/`, alongside the originals.

**The operator reported that some atlas plates are cut through. The cause is worse than that.**
`04a_atlas_extract.py` treated every image XObject in the PDF as a plate, and PDFs routinely store
one large bitmap as several horizontal **strips**, each its own XObject. Measured on the source:
**101 XObjects, 47 actual figures.** More than half the reference set was a fragment.

Detected exactly, not by heuristic - strips of one image share their x-range to within 2 pt and
abut in y with a gap of **0.00 pt**:

    page 8:  x 106.0-507.4  y 424.1-587.2  px 1226x498
             x 106.0-507.4  y 587.2-750.1  px 1226x498     <- same image

Tissue running off an edge: **83 of 101 before, 3 of 47 after merging.**

**This is very likely a large part of why atlas matching never worked.** `04c` scored every section
against a reference set in which over half the entries were partial sections - a top-of-brain strip
and a bottom-of-brain strip presented as two independent plates. Together with the polarity bug
found yesterday, the reference set was wrong in two independent ways at once.

**One thing the merge cannot decide.** A figure often holds more than one section: of the 47, 30
hold one, 14 hold two, 2 hold three, 1 holds four - about **68 real plates**. Where one section ends
and the next begins is an anatomical judgement, not a geometric fact about the PDF, so `04a3` puts
it in front of the operator. Boxes are **proposed** from the tissue bands, so the 30 single-section
figures need no interaction and only the 17 multi-section ones do.

**Seeds are carried exactly at every step**, never re-detected: a fraction of the old strip becomes
a point in PDF page coordinates, then a fraction of the merged figure, then a fraction of the final
crop. **316 seeds, 0 unmapped, 0 orphaned** through the whole chain. Crops are **rendered from the
PDF**, not resampled from the extracted JPEGs, so the final plates are sharper than the originals
and in colour.

**Also checked for the bug that broke the ROI curator.** The reframe tool's call graph was extracted
from the generated HTML and searched for cycles before shipping: none.

Provisional `atlas/plate_boxes.csv` was written from the auto-proposals so the chain could be tested
end to end; exporting from `04a3` overwrites it.

**Not yet switched over.** `04l_roi_curator.py` still points at the original `atlas/plates/`.
Pointing it at `plates_final/` is a one-line change, to be made after the reframing is reviewed -
and `04c`/`04e` are worth revisiting against a reference set that is finally whole.

---

## 2026-08-13 - ROI curator was unusable: render/select/onSlide was an infinite cycle

**Changed:** `04l_roi_curator.py`. The render cycle is broken, interactions update one strip cell
instead of rebuilding the whole strip, and all 101 plate images are preloaded.

**The bug, and it was mine.** `render()` called `select()`, `select()` called `onSlide()`, and
`onSlide()` ended with `render(true)`. On load that recursed until the stack blew, leaving the page
half-built with dead handlers - which is exactly what the operator described: it looks like it
rendered, but no button does anything. It was there from the first version of the file; nobody had
tried to use it until now.

**Why I did not catch it.** Every check I ran on this file was static - Python-side syntax, embedded
JSON, asset paths, and ported copies of the affine and TPS maths tested in isolation. All of those
passed, because none of them ran the page's own control flow. The transform maths was verified
against ground truth and is fine; the thing that was never exercised was the part only a browser
runs.

Fixed and verified by extracting the call graph from the generated HTML, stripping comments, and
searching it for cycles: **NONE**.

**Two performance faults found alongside it, both real.**

*Every interaction rebuilt the entire strip* - up to 87 cells with their images - via
`el("strip").innerHTML = ...`. Placing one landmark did a full DOM rebuild. Now `paintCell(uid)`
updates the single affected cell and `counts()` updates the header; the full rebuild happens only
on load and on animal change. Landmark click now triggers **0** strip rebuilds.

*Every slider step reloaded a plate JPEG from disk.* Scrubbing across the 101 plates meant 101 file
reads and decodes. All plates total **7.4 MB**, median 71 KB, so they are now preloaded as decoded
`Image` objects at startup and changing plate is just a canvas draw.

---

## 2026-08-13 - ROI curator records plate assignments independently of landmarks

**Changed:** `04l_roi_curator.py` gains an explicit `assigned` state, a **No ROI here** marker, and
a third output. Export now writes `roi_plates.csv`, `roi_landmarks.csv` and `roi_regions.csv`.

**The gap it closes.** The export wrote nothing for a section carrying fewer than three landmarks -
which discarded precisely the case where the operator had looked at a section, decided which plate
it was, and decided it was not worth landmarking. A plate assignment is a judgement in its own
right and now survives on its own.

`roi_plates.csv` carries a `status` per section:

  `registered`  3+ landmark pairs, regions warped
  `plate_only`  a plate was chosen deliberately, no landmarks placed
  `no_roi`      explicitly marked as having nothing to measure

**The trap avoided.** Selecting a section creates its state object, so a naive "has state" test
would have recorded a plate_001 assignment for every section merely clicked through in the strip.
`assigned` is set only by a real slider move - `oninput` fires on user interaction and not when
`.value` is set from script - or by the explicit **Assign plate** button. Verified across six
states: never touched, selected-but-not-moved, slider moved with no landmarks, marked no-ROI, two
landmarks, four landmarks. Only the last four produce rows, and only the last produces landmark and
region rows.

The strip now shows three states rather than two: purple registered, blue plate-only, faded no-ROI.

---

## 2026-08-13 - The two stages linked: 04l's landmarks now seed 04e's registration

**Changed:** `04e_register_elastix.py --from-landmarks`. Reads `roi_landmarks.csv` from the ROI
curator, uses the operator's clicked pairs to initialise **and** constrain an elastix registration,
and carries the atlas region seeds onto the section through the composed transform. Output:
`registered/roi_regions_refined.csv`.

**What it adds over the curator alone.** `04l` interpolates through the clicked points - an affine,
or a thin-plate spline from six up. That is exact *at* the landmarks and guesswork *between* them.
This seeds elastix with the same pairs and then lets mutual information use the **image content
between** the landmarks, which is the part no interpolation through a handful of points can know.
Each stage optimises MI and the Euclidean distance between the pairs, weighted by
`--landmark-weight` (default 1.0, equal - the honest starting point, not a tuned one).

**Three things had to be got right, and two of them failed first.**

*The direction.* Plate **fixed**, section **moving**, so elastix's transform maps plate coordinates
into section coordinates and transformix carries the seeds the right way. Verified on a synthetic
case with a known affine: seeds landed within **0.01 px** of ground truth.

*Multi-metric needs per-metric components.* The first run died with an opaque
`Internal elastix error`. The log showed the landmarks loading correctly, so the failure looked
unrelated to them; the real cause was `the fixed pyramid schedule is not fully specified` -
`MultiMetricMultiResolutionRegistration` needs one pyramid, interpolator and sampler entry **per
metric**, not one in total.

*Scale.* With that fixed it failed again: `Too many samples map outside moving image buffer:
289 / 4234`. A 1095 px plate against a 256 px section is a 4x scale difference no rigid stage
absorbs. The landmarks already contain that scale, so they are now used as the coarse
initialisation - the plate is resampled into the section frame by the landmark affine first, and
elastix is left with only the residual. Composition is then simply affine-then-elastix, and the
seeds go through both.

**Also fixed: `load_seeds` was dead code with a false docstring.** It claimed to carry seeds through
the reformat geometry and only rescaled by the original plate size, and nothing called it. Now it
is called, and correct, because `--from-landmarks` registers against the **original** plate - so
original-plate pixels are the right frame and no geometry has to be re-run. Same reasoning `04l`
uses for displaying the original plate.

**Tested end to end on real images with synthetic landmarks** (tissue-extreme correspondences -
enough to exercise the path, not the anatomy): 3 sections, 66 seed positions, 0 failures, **100% of
seeds landing inside the section frame**, moved a median of 18.7 px from the landmark-affine
position. Those test artifacts were **deleted** afterwards so they cannot be mistaken for real
curation; `--from-landmarks` correctly refuses to run and points at `04l` when the file is absent.

---

## 2026-08-13 - Registration handout: three things acted on, one already right, one still to do

**Changed:** `04e_register_elastix.py` gains a rigid pre-stage and sets its metric explicitly;
`04l_roi_curator.py` gains a thin-plate spline above six landmarks.

The handout independently reaches the same conclusions this project reached by measurement - no
salmon volume so ABBA/QuickNII/DeepSlice/brainreg are out, level assignment is manual, the task is
2D-to-2D cross-modality registration per plate, QuPath downstream. Agreement from an independent
source is worth recording; the useful part is the four specifics.

**1. Mutual information - already right, verified rather than assumed.** The handout says a
cross-modality metric is essential and to set it explicitly. Checked: elastix's default parameter
maps already use `AdvancedMattesMutualInformation` for rigid, affine and B-spline. Now set
explicitly anyway, so the intent survives a change in elastix defaults.

**2. Rigid before affine - was missing, added, and the gain is small.** Measured on 8 sections:
median post-registration IoU **0.639 -> 0.647**, better on 4, marginally worse on 3. Kept because
it is the right ladder and costs one cheap stage, not because it transformed anything.

**3. Thin-plate spline above six landmarks - added, reversing my own earlier argument.** I had
rejected a TPS on the grounds that it invents deformation between landmarks. That is true at 3-4
points and false at 8-12, and the handout is right that an affine cannot follow the local
distortion sectioning puts into a slice. `04l` now uses an affine from 3 pairs and switches to a
TPS at 6, showing which is live.

Verified against a synthetic affine-plus-local-bump ground truth: **exact at the control points**
(max error 1e-13 px) with held-out error of **4.63 px at 6 landmarks, 1.33 at 8, 0.87 at 12**. That
puts a number on the handout's "6 to 10 points" advice.

The residual display changes meaning with the transform and now says so: a TPS interpolates its
landmarks exactly, so its residual is **zero by construction and carries no information**. Read the
residual while it is an affine; read the overlay once it is a spline.

**4. Direction - checked, and 04e is correct for its purpose.** The handout says to warp the atlas
onto the section so the real data stays undistorted. `04e` registers with the plate as *fixed* and
the section as *moving*, which is what makes elastix's transform map plate coordinates into section
coordinates - the direction needed to carry region seeds onto the section. Its resampled image is
the section in plate space, which would be the wrong thing to measure on; confirmed by grep that
**nothing outside 04e reads `registered/`** - it is QC only.

**Still to do, and it is the best remaining idea in the handout:** elastix accepts manual
corresponding points to seed a registration. The landmarks the operator is already clicking in `04l`
could seed `04e` directly, so hard sections get human help instead of hand-tuned parameters. That
links the two stages and is the natural next build.

**Not pursued: BigWarp (Path 1).** `04l` is functionally that - landmarks, live warp, TPS - in the
browser, without a Fiji install or a per-section round trip.

---

## 2026-08-13 - Atlas plates were being matched in the WRONG POLARITY. Operator's catch.

**Changed:** `04a_reformat.py` inverts atlas plates before anything else, so a plate ends up in the
same polarity as a DAPI section - cell-dense bright, tracts and ventricles dark, background black.
All 101 plates regenerated.

**The operator asked whether the atlas images could be turned negative and then matched. They were
right, and my earlier test of that idea was invalid.** Nissl stains cell bodies **dark** on white
paper; DAPI is **bright** where cells are. For the two to correlate, cell-dense must be bright in
both. `04a` never inverted: it used the light-background branch to find the *mask* but stretched the
*raw* image, so every plate carried inverted contrast relative to every section. In-tissue mean of
the reformatted plates was 58 out of 255 - the cell-dense tissue was the dark part.

**Why "I already tested inversion" was wrong.** The giRAff test earlier today scored an `inverted`
polarity and found nothing, but it inverted the *already-reformatted* plate. The stretch is
asymmetric - median − MAD to median + 4 MAD - so applied in the wrong polarity it clips away the
cell-dense end before there is anything left to invert. Inverting first is not the same operation,
and the measurements differ.

**Re-measured, rank correlation between serial order and best-matching plate:**

| | LS45 | LS120 | LS22 | LS37 |
|---|---|---|---|---|
| silhouette IoU (04c) | -0.05 | 0.00 | 0.17 | -0.04 |
| intensity, wrong polarity | -0.18 | 0.00 | -0.02 | - |
| intensity, correct polarity | -0.04 | 0.02 | 0.18 | 0.15 |
| **shape + intensity, correct polarity** | **0.09** | **0.25** | **0.33** | **0.06** |
| SIFT features, correct polarity | 0.15 | 0.03 | -0.07 | - |

The combined score is **positive in all four animals** where the signs were previously random. That
is a real improvement and it is the operator's, not mine.

**It is still not enough to assign levels automatically.** A correlation of 0.33 explains about a
tenth of the variance in serial order. SIFT adds nothing - about 9 good matches per pair out of 400
keypoints each, which is noise. So `04l`'s manual plate selection stands.

**But the fix matters independently of matching, which is the more important point.**
`04e_register_elastix.py` registers each section *to* a plate, and correlation- and
mutual-information-based registration both degrade when the two images have opposite contrast. Every
registration run so far has been fighting the polarity. Anything downstream of `04e` should be
re-run.

`04l_roi_curator.py` is unaffected - it deliberately shows the **original** plate, not the
reformatted one, because the region seeds are fractions of the original.

---

## 2026-08-13 - ROI curator: SHARCQ's workflow rebuilt for the salmon atlas

**Changed:** new `04l_roi_curator.py`, writing `reformatted/roi_curator.html`. 788 sections, 101
plates, 316 region seeds across the 24 labelled plates.

**Why manual, and why that is not a retreat.** Automatic level assignment has now been measured to
fail twice - `04c` on silhouette IoU (order-vs-plate correlation -0.05 to 0.17) and giRAff's method
on registered-intensity cross-correlation (-0.18 to +0.09). SHARCQ, the peer-reviewed tool for this
exact task, **also picks the plate by hand**: its user scrolls to the AP coordinate by eye, then
clicks numbered corresponding points. What it automates is the landmark registration, the warping,
and the per-region counting. That is what this rebuilds.

**Interaction.** Scrub the plate slider, then click matching points - section first, then plate.
From three pairs the atlas region seeds are **warped live onto the section in their atlas colours**.
That overlay is the real check: it shows immediately whether Dl, Dm, Vv and POA are landing where
they belong, which a residual number cannot.

**Three decisions worth recording.**

*Affine, not a spline.* Three or more pairs determine an affine by least squares. A thin-plate
spline through 3-6 landmarks would fit them exactly and invent deformation between them that
nothing measured. SHARCQ uses the same class of transform from the same input, and
`04e_register_elastix.py` remains available for a B-spline refinement once an assignment is trusted.

*The plate is shown in its ORIGINAL form, not reformatted.* Seeds are recorded as fractions of the
original plate, so using the original avoids carrying them through the reformat's
rotate-crop-pad-resize chain - which `04e` notes is not invertible from the index alone.

*Per-landmark residuals are displayed and flagged above 25 px*, so a mis-clicked pair shows up as a
large error rather than quietly dragging the whole fit.

Affine solver verified against a known transform: exact with three clean pairs, and with clicking
noise the least-squares fit beats the noise (2.0 px click noise gives 1.97 px recovery error over
6 points; 5.0 px gives 3.13 px over 10).

**The subset selects itself.** Only 24 of 101 plates carry seeds - plate_009 to plate_032,
telencephalon and POA, 8 regions (Dl 142, Dm 114, Vv 16, POA 16, Vd 10, Vl 10, Vs 4, Vc 4). A
section assigned anywhere else has no regions to receive, so there is no reason to place landmarks
on it. That bounds the manual work without anyone having to decide a cutoff.

Output: `roi_landmarks.csv` (every pair with its residual) and `roi_regions.csv` (warped seed
positions in the reformatted section frame).

**Still outstanding:** the caudal plates carry no region labels at all, so the SBN nodes named in the
plan - vTn, TPp, PAG - cannot be reached until those are annotated.

---

## 2026-08-13 - SHARCQ, giRAff and DeepSlice assessed; giRAff's method tested and it fails here

**Changed:** REFERENCES.md gains all three. No code change - this records an assessment and a
measurement.

**None can be run against the salmon atlas.** SHARCQ is MATLAB bound to the Allen or
Franklin-Paxinos 3D atlas; DeepSlice is a CNN trained on ~920k virtual sections rendered from a
volumetric mouse template, and there is no salmon volume to render from - the atlas here is 101
discrete plates from a book; giRAff needs the Allen template volume.

**giRAff was the one genuinely untested idea, and it was tested.** It differs from `04c` in scoring
*registered image intensity* by cross-correlation rather than silhouette overlap. Built a regional
cell-density map per section - rim eroded, interior re-stretched, smoothed - and per plate, then
measured the same rank correlation between serial order and best-matching plate:

| animal | n | direct | inverted |
|---|---|---|---|
| LS45 | 87 | -0.18 | -0.06 |
| LS120 | 68 | 0.00 | -0.11 |
| LS22 | 60 | -0.02 | 0.09 |

Against `04c`'s silhouette figures of -0.05, 0.00, 0.17, -0.04. **No improvement in either
polarity.** Interior intensity carries no more level information here than shape does, so the
failure is not specific to silhouettes - it is the pairing of this DAPI with these Nissl plates.

**Two identified causes, and both are fixable in principle.** The interior *does* carry real
architecture - the periventricular cell layer is obvious in `qc/atlasmatch/interior_structure.png` -
but it is contaminated by the **uncorrected tile mosaic grid**, a strong periodic pattern identical
in every section, which adds a constant similarity floor. And DAPI at 5.20 um/px does not resolve
the lamination the Nissl plates show. Making the giRAff route viable would need the tile flat-field
fixed - open since Stage 1, where the raw-tile estimate never converged - and re-extraction at
0.65-1.3 um/px. That is a substantial piece of work with no guarantee.

**The most useful thing in the three papers is what SHARCQ does not automate.** Its user "must
scroll to the correct AP coordinate and DV/ML tilt" by eye, then clicks numbered corresponding
points between the slice and the atlas. What it automates is the landmark registration, warping the
cell-location matrix through the same transform, and counting per region. **The published tool for
this exact task selects the matching slice manually.** Automatic level assignment is not the
standard, and this project not achieving it is not unusual.

---

## 2026-08-12 - Atlas level curator: anchor a few sections, interpolate the rest

**Changed:** new `04k_level_curator.py`, writing `reformatted/level_curator.html`. 788 sections,
12 animals, 101 plates.

**Why this shape rather than better matching.** `04c` tried to read level off the silhouette and
does not work - correlation between serial order and best-matching plate is -0.05 to 0.17, and
adjacent sections score IoU 0.595 against 0.551 for sections thirty apart. Rather than keep
attacking that, this uses the constraint that is actually strong: **the sections were cut serially
at uniform thickness, so level is close to linear in section number.** Two anchors fix the line.

**Interaction.** Click a section, drag the plate slider or use the arrow keys until the red plate
behind it matches, press `a`. Everything between two anchors interpolates **live**, so the
consequence of an anchor is visible across the whole series immediately - which is the point of
doing it this way rather than section by section.

**Three design choices worth recording.**

*Interpolation is on section **order**, not list index.* Tested on a series with a gap - sections
1-5 then 40-44 - the plate assignment jumps with the gap instead of spreading evenly. Index-based
interpolation would have quietly mis-assigned every section after any missing run, and 43% of
sections have been excluded, so gaps are the normal case here, not an edge case.

*One anchor is treated as insufficient and labelled as such.* One anchor fixes an offset but not a
rate, so the curator holds the level flat and marks every other section `extrapolated` rather than
pretending to a slope it cannot know.

*Extrapolation beyond the outermost anchors is marked separately and shown faded.* It continues at
the fitted rate, which is a weaker claim than interpolating between two known points, and the export
records `source` as anchor / interp / extrap so that distinction survives into the analysis.

**Anchors are forced monotonic** - an anchor that would put a later section at an earlier plate is
rejected with the reason, because serial sections cannot run backwards.

Algorithm verified against a port of the curator's own function: zero anchors give nothing, one
gives a flat extrapolation, two give clean piecewise-linear interpolation with extrapolation
outside, three give piecewise linear throughout, and every case is monotonic.

**A limitation the curator states rather than hides:** only **24 of 101 plates carry region labels**
(plate_009-plate_032, telencephalon and POA). A section assigned outside that range gets a level but
no regions can be propagated to it. Marked in the interface per plate.

Levels are curated on the **PCNA** sections - the fuller set, 788 against 454 - and will carry to
pERK through the pairing already in `perk_overrides.csv`.

---

## 2026-08-12 - Clipped pERK pixels censored; analysis set fixed at 1% tolerance

**Changed:** new `04j_censor_clipped.py`. `04a_reformat.py` gains `--censor`, which carries the
censor mask through the same geometry as the image and **never blanks it**. Written:
`censor/<uid>_censor.png` for all 718 pERK sections, `<uid>_censor.npy` in the reformatted frame,
and `reformatted/perk_analysis_set.csv`.

**Censored is not masked, and the distinction is the point.** An artifact pixel is not tissue and
leaves the analysis. A clipped pixel is real signal whose value is lost, so it is **right-censored**:
true value unknown but at least the ceiling. Therefore

* **exclude it from every intensity statistic** - mean, median, and the negative peak UniFORM
  aligns on - because a floor value biases all of them downward;
* **keep it for detection and positivity**, because a pixel at the ceiling is unambiguously
  positive.

Getting that backwards would bias positive rates *down* in exactly the animals with the brightest
staining - turning a data-quality problem into a group difference. The script says so where someone
would otherwise reach for the artifact mask by analogy.

**The mask comes free, and only because of a coincidence worth recording.** `display_ranges.json`
gives AF568 as `lo 1070, hi 65535` - the display high **is** the 16-bit ceiling - so in the exported
8-bit marker overview, 255 means 16-bit >= 65535, exactly the clipped set. Verified against
`saturated_fraction`, computed independently on 16-bit data at export: **median absolute difference
0.00000** over 12 random sections. This does **not** generalise: DAPI (hi 27993) and AF488
(hi 37263) have display highs below the ceiling, so 255 there means "at or above the display high",
not "clipped".

**Section level, 1% tolerance as instructed:** 454 of 718 pERK sections (63%) are in the analysis
set; 264 set aside, recorded rather than deleted. Within the set the censored fraction is tiny -
median 0.00003, p95 0.00078, max 0.00952 - and 183 sections have no censored pixels at all.

**The cost, per animal:**

| | LS22 | LS37 | LS45 | LS53 | LS61 | LS69 | LS85 | LS87 | LS105 | LS120 | LS136 | LS138 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PCNA | 60 | 81 | 87 | 73 | 72 | 66 | 60 | 51 | 75 | 68 | 45 | 50 |
| pERK | 62 | 67 | 55 | **0** | 53 | 24 | **3** | 49 | 28 | 70 | 27 | 16 |

**788 sections for PCNA against 454 for pERK.** LS53 contributes nothing to pERK at this tolerance
and LS85 contributes three, so the pERK comparison is effectively **ten animals, two of them
thin** (LS138 16, LS69 24). That is a statement about achievable n, not about thresholds - no
tolerance recovers LS53, whose sections are all clipped.

Verified that adding the censor layer leaves the reformatted image and tissue mask **bit-identical**,
and that censored pixels are not blanked.

---

## 2026-08-12 - UniFORM assessed, and it led to a correction of our own AF568 diagnosis

**Changed:** REFERENCES.md gains UniFORM (Wang et al. 2025, *Cell Rep Methods* 5:101172). No code
change. What changed is the **diagnosis of the AF568 problem**, and it needed correcting.

**The method.** Normalise by aligning the **negative population** - the leftmost mode of the
log-intensity histogram - across samples by maximum cross-correlation. Non-parametric, feature and
pixel level, Python, open source. It answers the hardest open problem here: with no tERK and no
negative control, *the non-expressing population within each image is the control*. Its critique of
mean division - unstable on right-skewed heterogeneous data - applies to this dataset directly.

**Testing its premise produced a finding that contradicts what this log said earlier.** Measuring
background level per animal on AF568 showed what looked like a clean two-group batch effect:

| group | animals | background | clipping |
|---|---|---|---|
| LOW | LS45, LS61, LS37, LS22, LS120, LS136, LS87 | 10,661-12,305 | median 0.00004 |
| HIGH | LS85, LS105, LS69, LS53, LS138 | 21,037-22,215 | median 0.10136 |

The gap between groups is **8,732** against within-group spreads of 1,643 and 1,178 - binary, not a
gradient. It looked like five animals stained or imaged at roughly double the gain.

**That reading is wrong, and the check that showed it was restricting to clip-free sections:**

| | LOW | HIGH |
|---|---|---|
| background | 10,844 | 12,300 |
| tissue | 5,542 | 5,494 |
| tissue / background | 0.52 | 0.50 |

**On sections that do not clip, the two groups are the same.** The 1.86x background gap across all
sections is produced *by the clipping* - pixels pinned at 65,535 drag the measured mean up. There is
no gain difference to correct, and therefore nothing for UniFORM's multiplicative factor to remove.

**So the AF568 problem is information loss, not miscalibration, and that is worse.** A gain
difference is correctable; clipped pixels have lost their value permanently. Restated honestly: the
contrast inversion is real and universal, but the five-animal split previously described as a
staining-batch difference is a *consequence of clipping*, not a separate effect.

**The number that now matters - clip-free pERK sections among the curated 718:**

| | LS22 | LS37 | LS45 | LS53 | LS61 | LS69 | LS85 | LS87 | LS105 | LS120 | LS136 | LS138 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| curated | 62 | 85 | 80 | 13 | 53 | 65 | 68 | 51 | 68 | 70 | 50 | 53 |
| clip-free | 22 | 32 | 23 | **0** | 16 | 14 | **1** | 16 | 8 | 27 | 15 | 9 |
| under 1% clipped | 62 | 67 | 55 | **0** | 53 | 24 | **3** | 49 | 28 | 70 | 27 | 16 |

**183 of 718 (25%) are clip-free; 454 (63%) are under 1% clipped.** LS53 has none and LS85 has one,
so a strictly clip-free pERK analysis loses two animals outright. A 1% tolerance keeps ten animals
but still excludes LS53 and LS85.

**Recommendation:** treat clipped pixels as censored rather than dropping whole sections, and adopt
UniFORM's *method* - align the negative population, do not divide by a mean - at Stage 5/6 on raw
16-bit per-object intensities. It cannot run on the overviews, which are 8-bit and display-ranged
per section, destroying the very comparability it operates on.

---

## 2026-08-12 - AF568 path added to 04a and 04g; both channels now cleaned

**Changed:** `--marker AF568` through `04a_reformat.py` and `04g_artifact_mask.py`, and both run.
The two markers now have separate section directories, indexes and summaries, because scene uids
differ (`_s03b_` vs `_s03a_`) but a shared index would let one run silently overwrite the other's.

**Both channels, final:**

| | PCNA (AF488) | pERK (AF568) |
|---|---|---|
| sections | **788** | **718** |
| with >= 1 artifact | 725 (92%) | 652 (91%) |
| tissue masked, median | 0.751% | 0.871% |
| tissue -> measurable | 20,810 -> 20,639 mm² | 16,952 -> 16,793 mm² |

Artifact burden is near-identical between the two channels (92% vs 91%, 0.75% vs 0.87% of tissue),
which is what should happen: bubbles and fibres are in the mounting medium and affect both.

**Two mistakes of mine, both caught by guards rather than by luck.**

*The accounting block I added last entry had never been executed.* It did `excluded & universe`
where `excluded` is a dict, not a set - a `TypeError` on the first real run. I added a verification
check and did not exercise it, which is the same class of error the check exists to catch. Fixed;
it now reports `1191 sections = 718 kept + 473 excluded + 0 unaccounted`.

*The `--marker` patch to `04g` silently did not apply.* I matched on an `--montage` argument that
exists in `04f`, not `04g`, so the string replacement did nothing and reported success. The failure
surfaced two steps later as `unrecognized arguments: --marker AF568`, and then as
`WARNING: 718 section(s) had no 04g artifact mask and were left unmasked` from the guard added
earlier in the day. Without that warning the pERK sections would have gone through unmasked and
looked fine.

**57 pERK sections have no curation at all** - AF568 scans with no AF488 partner in `pairs.csv`, so
there was nothing to propagate. Kept under the standing rule that only explicit exclusions remove a
section, but their orientation is `04a`'s automatic angle rather than the operator's. Spread:
LS136 11, LS85 10, LS120 7, LS69 7, LS37 5, LS105 4, and 1-3 elsewhere.

**Housekeeping, not done:** `reformatted/sections/` holds 1,381 PNGs against 788 in the index - 593
orphans from before the exclusions. The index is authoritative and nothing reads the directory
listing, so they are inert, but they are misleading to a human browsing the folder.

---

## 2026-08-12 - Curation propagated from the PCNA scans to the paired pERK scans

**Changed:** new `04i_propagate_to_perk.py`. Writes `reformatted/perk_overrides.csv`: 473
exclusions transferred and **661 rotations re-derived**, with an alignment IoU per section.

**The three kinds of decision transfer differently and were handled separately.** Exclusions are a
property of the physical section, so they go straight through `pairs.csv`. Rotations cannot be
copied - `extra_rotation` is a correction on top of `04a`'s automatic angle, and that angle differs
between the two scans because the scan boxes differ - so they are re-derived by alignment.
Artifacts are properties of the imaged field and the two scans image different fields, so they are
not propagated at all; `04g` should be run on the pERK overviews directly.

**A first attempt failed, and the reason is worth keeping.** Aligning the two *reformatted* masks
gave a median IoU of **0.548** with flips winning a third of the time. The reformat crops each scan
to its own tissue bounding box and resizes to 256x256, so when the two scan boxes contain different
amounts of debris the tissue ends up at **different scales** - and no rotation can fix a scale
mismatch. Rebuilt to align on a shared **physical** grid instead: both overviews are at a verified
5.20 um/px, so downsampling both by 4 leaves only rotation and translation free. Translation is
handled for every offset at once by the same FFT identity used in `04h`. Median IoU **0.548 ->
0.785**, p90 0.930, p99 0.970.

**Flipping is measured and deliberately never applied.** Scored during development it won on 18.5%
of sections, which tripped the script's own warning. Investigated rather than accepted: the flip
advantage is a median of **0.0056 IoU**, with 96% of wins under 0.05 - coin tosses on
near-symmetric shapes. Two scans of one section on one slide cannot be mirror images, and a
spurious flip would **swap left and right hemispheres in the pERK data relative to PCNA**, which is
precisely what a lateralisation result would be read off. The margin is kept as a reported column;
the correction is not applied.

**Result:** median alignment IoU 0.785, **87% at or above 0.55**. Per-animal medians run 0.653
(LS136) to 0.876 (LS22). Checked by eye at each animal's median - the orientations match. The worst
cases (IoU 0.16-0.23) are sections where the pERK scan caught only wisps against substantial tissue
in the PCNA scan; those are either bad pairings or genuinely different captures and need a human.

**Coverage, unchanged:** 127 of the 788 curated sections have no pERK partner at all, so the pERK
analysis starts from **661 sections** against 788 for PCNA - and LS53 contributes 13.

**Still to do for a pERK measurement:** reformat the pERK scans with these overrides, then run
`04g` on them for their own artifact masks. Both need a `--marker AF568` path through `04a` and
`04g`, which currently default to AF488.

---

## 2026-08-12 - Marker identity resolved: AF568 = pERK, AF488 = PCNA. The damaged channel is pERK.

**Changed:** `config.json` `marker_identity` filled in on the operator's confirmation - **AF568 =
pERK, AF488 = PCNA**, DAPI 358 nm excitation / 461 nm emission. This was the longest-open question
in the project and every downstream stage was blocked on it.

**It resolves the wrong way round.** Every optical problem measured over the past weeks is on
AF568, which is now known to be **pERK - the activity marker, and presumably the primary readout**:

| | AF488 = **PCNA** | AF568 = **pERK** |
|---|---|---|
| sections | 1,381 | 1,191 |
| median contrast (tissue / background) | **2.97** | **0.48** |
| sections with contrast inverted (< 1) | **0%** | **93%** |
| sections with any clipped pixels | 59% | **73%** |
| median clipped fraction | 0.0000 | 0.0002, but ~10% in five animals |

Clipping is severe and animal-specific: LS53 100% of sections with a median **11.8% of pixels
clipped**, LS85 95% / 10.0%, LS105 90% / 10.5%, LS138 89% / 10.1%, LS69 81% / 9.9%. The other seven
animals clip on 55-68% of sections but at a median fraction of ~0.

**So the proliferation readout is in good shape and the activity readout is not.** PCNA has clean,
correctly-signed contrast on every section. pERK has background outshining tissue 2x on 93% of
sections, and in five of twelve animals a tenth of the pixels are at the ceiling - inside the
tissue, not just on background.

**This compounds with two limitations already recorded, and the stack matters more than any one:**

1. **No tERK channel.** Randlett et al. 2015 uses the same pERK primary (CST #4370) and normalises
   every measurement to total ERK, explicitly because *"high baseline pERK staining makes finding
   stimulus- or behavior-dependent changes in staining challenging."* That control does not exist
   here.
2. **No negative control**, so an unknown additive background cannot be subtracted.

A marker with a documented high baseline, no normaliser, no negative control, inverted contrast on
93% of sections and ceiling clipping in five animals. **Relative comparisons at matched anatomical
levels remain defensible; absolute pERK positivity does not, and the write-up has to say so.**

**Coverage: 127 of the 788 curated sections have no pERK scan at all.**

| | curated (PCNA n) | with pERK | % |
|---|---|---|---|
| LS22 | 60 | 60 | 100% |
| LS37 | 81 | 80 | 99% |
| LS45 | 87 | 77 | 89% |
| **LS53** | **73** | **13** | **18%** |
| LS61 | 72 | 50 | 69% |
| LS69 | 66 | 58 | 88% |
| LS85 | 60 | 58 | 97% |
| LS87 | 51 | 49 | 96% |
| LS105 | 75 | 64 | 85% |
| LS120 | 68 | 63 | 93% |
| LS136 | 45 | 39 | 87% |
| LS138 | 50 | 50 | 100% |
| **total** | **788** | **661** | **84%** |

**LS53 effectively has no pERK data** - 13 usable sections against 73 for PCNA - and its AF568 scans
are also the worst clipped in the dataset. It should probably be dropped from the pERK analysis
entirely, which is a decision for the operator, not for this pipeline.

**A consequence that needs acting on before any pERK measurement.** All curation so far - rotations,
exclusions, artifact masks - was done on the **DAPI channel of the AF488 (PCNA) scan**. The AF568
scan of the same physical section is a *separate* acquisition with its own hand-drawn scan box, so
it has different framing and therefore a different reformat geometry. Stage 2's pairing links the
two, but **the rotations and artifact masks do not transfer automatically**. Either the curation has
to be propagated through the pairing, or the pERK scans need their own pass.

---

## 2026-08-12 - Second curation pass MERGED, not replaced: 788 sections

**Changed:** the operator's second pass applied. **The two passes were combined rather than the
second replacing the first**, and `04a_reformat.py` now performs a full accounting on every run.

**Applying the new file as-is would have silently destroyed the first pass.** The curator was
rebuilt on images that already had pass-1 rotations baked in, and the curator's slider starts every
untouched section at zero. So the exported angles are **residuals relative to already-rotated
images**, not absolute corrections. `04a` adds `extra_angle` to the *automatic* angle, so writing
the new file straight over the old would have given `auto + pass2` instead of
`auto + pass1 + pass2`.

**500 sections had a rotation in both passes and would have lost the first.** Examples:

| section | pass 1 | pass 2 | correct total |
|---|---|---|---|
| LS105_s01b_sc00 | 266 | 163 | **69** |
| LS105_s01b_sc10 | 215 | 58 | **273** |
| LS105_s02b_sc03 | 208 | 47 | **255** |

Merged as `(pass1 + pass2) mod 360`, exclusions unioned, flips XORed. Both source files are kept:
`rotation_overrides_pass1.csv` and `rotation_overrides_pass2_raw.csv`.

**Result:** 43 new exclusions (none previously excluded), 593 total, **788 sections kept**, 770
carrying a rotation.

**"Everything not explicitly excluded is kept" - verified exhaustively, against the full universe
rather than the CSV rows:**

| check | result |
|---|---|
| universe (AF488 sections in focus.csv) | 1,381 |
| kept + excluded | 788 + 593 = **1,381** |
| in neither | **0** |
| not explicitly excluded but not kept | **0** |
| explicitly excluded but still kept | **0** |
| sections with no row in the overrides at all | 18, **all 18 kept** |

That check is now built into `04a` and prints on every run, because `lost_sections.csv` only catches
sections that reached the loop and failed - it would not have caught a section dropped before that.

**Re-run on the 788:** `04f` proposes **0** exclusions and no section lacks a piece above 0.5 mm².
`04g` finds artifacts in 725 of 788 (92%), 1,948 compact and 790 elongated objects, median 0.751% of
tissue masked; of 20,810 mm² of tissue, **20,639 mm² measurable (0.82% removed)**.

**Exclusion is now 43% overall and the per-animal spread has widened:** LS37 30% to LS136 61%.
Kept counts: LS22 60, LS37 81, LS45 87, LS53 73, LS61 72, LS69 66, LS85 60, LS87 51, LS105 75,
LS120 68, LS136 45, LS138 50. LS136 and LS87 are now down to 45 and 51 sections. This must be
checked against experimental group at unblinding - a 31-point spread in exclusion rate is large
enough to matter if it correlates with treatment.

---

## 2026-08-12 - Artifacts carried into the reformatted images, so curation happens on masked sections

**Changed:** `04a_reformat.py` gains `--mask-artifacts`. `04g`'s mask rides the same geometry as
the image - rotation, flip, crop, square pad, resize - so it stays registered, and artifact pixels
are blanked in the reformatted output. A per-section `<uid>_artifact.npy` is saved alongside the
tissue mask. `04g` gains a second growth pass.

**Why:** the operator asked to re-curate on sections that already have the artefacts masked, which
is the right order - a bright blob is exactly the thing that draws the eye when judging whether a
section is usable.

**Geometry is deliberately untouched.** The tissue mask is still computed on the *unmasked* image,
so the principal angle, the 180 decision and the bounding box are bit-identical with and without
masking - verified on 8 sections. Masking the image before computing geometry would have been
defensible, but it would have shifted every frame and invalidated the rotations already curated.
What is masked is the measurement and the picture, not the outline.

For the same reason the tissue mask is **not** reduced by the artifact mask. It is the section's
silhouette, used for orientation and matching, and punching holes in it would change the shape
those depend on.

**Two defects found by looking at the output rather than the summary.**

*Artifact pixels reappeared after the resize.* Blanking before the bilinear downsample to 256x256
is not enough - interpolation smears bright neighbours straight back into the hole, at up to full
intensity on a 190 px artifact. The output is now blanked again *after* the resize, using the
resized mask.

*The masks were donuts.* `04g`'s single growth pass stops at the 95th percentile, and on large
artifacts the outer glow falls below it, so the mask came out as a black hole ringed by the
brightest part of the thing it was meant to remove. Measured: the pixels immediately outside the
base mask have a median brightness of **37-49 against a tissue median of 5**. Unambiguously still
artifact. Added a second, gentler pass - 90th percentile, 10 dilations, constrained to inside the
tissue - with new pixels inheriting the nearest existing label so nothing changes class by growing.
p85/15 and p80/20 were swept too and kept adding area without a reason to.

Effect across the 831: median masked fraction **0.641% -> 0.756%**, p95 1.598 -> 1.936, max
3.91 -> 5.74. Of 21,904 mm² of tissue, 21,723 mm² measurable - **0.82% removed**.

**Two stale inputs moved aside rather than left to mislead:**

* `symmetry_proposals.csv` - computed on pre-rotation masks. The curator would have applied it on
  top of rotations that are now baked into the images, double-rotating every section.
* `atlas_proposals_v2.csv` - the previous entry establishes that assignment carries no level
  information, so the reference underlay would have shown a meaningless plate behind each section.
  Renamed `atlas_proposals_v2_NOT_VALID_see_LOGS.csv`.

The curator therefore opens with **831 sections, no auto-rotation, no exclusion proposals and no
underlay** - the operator's own rotations, with artefacts blanked.

---

## 2026-08-12 - The last 10 flagged sections dropped: 831 sections, screen now fully clean

**Changed:** the 10 sections that passed manual curation but still tripped `04f` are now excluded
on the operator's instruction. `reformat_index.csv` holds **831**. `04a`, `04f` and `04g` re-run.

**All 10 were exactly the ones the operator had restored.** They had `decision = restored` in the
curated export - proposals the operator overruled on the first pass - and `04f`, re-run on the
curated set, flagged the same ten again. Shown as a montage, they were dropped. The overrule rate
on automatic proposals goes **24% (10 of 41) to 0%**: every automatic proposal now stands.

**The screen is now clean, and that is a real check rather than a tautology.** `04f` measures the
source overviews and has no knowledge of which sections were kept:

| | 1,381 (all) | 841 (curated) | 831 (final) |
|---|---|---|---|
| proposed for exclusion | 154 (11.2%) | 10 (1.2%) | **0 (0.0%)** |
| p0.5 of largest tissue piece | 0.16 mm² | 1.54 mm² | **3.21 mm²** |
| sections with no piece >= 0.5 mm² | 31 | 2 | **0** |

**Final artifact state:** 764 of 831 sections (92%) carry at least one, 2,029 compact and 822
elongated objects, median **0.641%** of tissue masked, p95 1.598%, max 3.91%. Of **21,904 mm² of
tissue, 21,752 mm² survives masking**. The maximum fell from 4.44% because the worst-affected
section, `LS53_s01b_sc01`, was one of the ten.

**Kept per animal:** LS22 61, LS37 83, LS45 94, LS53 73, LS61 75, LS69 68, LS85 66, LS87 58,
LS105 80, LS120 73, LS136 48, LS138 52. The 28-59% exclusion spread noted previously is essentially
unchanged - ten sections do not move it - and still needs checking against group at unblinding.

`excluded_sections.csv`: 550 rows, 509 manual and 41 auto. Nothing was dropped silently -
`lost_sections.csv` was not written. The operator's pre-drop file is preserved as
`rotation_overrides_before_10drop.csv`.

**Unchanged and still outstanding:** the 15 physical sections appearing under two scan variants,
and the atlas assignment, which the previous entry establishes does not work.

---

## 2026-08-12 - 04c re-run, and it does not work: silhouette matching carries no level information

**Changed:** `04c_atlas_match.py` re-run on the curated 841. `best_path` gained a step cost, and
both docstrings were rewritten to state what was measured rather than what was hoped.

**The re-run looked like an improvement and was not.** Median score rose 0.635 -> 0.688, every
animal matched, plate spans looked plausible. Three measurements say the assignments are **not
informative about rostro-caudal level**:

| measurement | result |
|---|---|
| corr(section serial order, best-matching plate) | **-0.05, 0.00, 0.17, -0.04** across four animals |
| plates tying within 0.02 of the best | only 2-3 of 101 |
| best plate's margin over a typical plate | 0.185 |
| spread of unconstrained best plates | 71-87 of 101 |

So each section picks a plate *confidently and distinctly*, those picks spread across nearly the
whole atlas, and they bear **no relationship to where the section actually came from**. A
confident-looking match on a signal that is not there.

**The direct evidence.** In LS45 the median silhouette IoU between *adjacent* sections is 0.595;
between sections *thirty apart* it is 0.551. A 0.044 gap over thirty sections is nothing a matcher
can exploit. Rendered to `qc/atlasmatch/no_shape_signal.png`.

**The DP collapse was a symptom, not the bug.** LS120 put 74 sections on 8 plates with 43 on one;
LS37 put 53 of 83 on a single plate. That looks like a dynamic-programming defect, and I wrote a
step-cost prior expecting it to be the fix - **it was not**. Swept over 0 to 0.08: LS120 went from
8 plates to 12, and LS37 got slightly *worse*, 18 plates to 16. With no ordering signal, forcing
monotonicity onto noise has no good solution. The step cost is kept because it is the right prior
and free, and its docstring now says plainly that it does not fix anything.

**What the normalisation costs, measured.** `04a` square-pads and resizes every section to 256x256,
deleting absolute size - and size *does* track position: correlation between section order and
tissue area is **0.45 median** across animals (LS138 0.84, LS37 0.72, LS136 0.57). A real cue,
discarded. At 0.45 it is too weak alone to place a section to +/-1 plate, but it should not have
been thrown away.

**This is consistent with prior art already cited here**, not a surprise in hindsight: AnNoBrainer
states that *DAPI is unlikely to register well against an H&E/Nissl atlas due to data sparsity and
poor morphological correspondence*. The earlier IoU ceiling near 0.51 was this same problem being
read as a tuning failure.

**Recommended route, not yet built.** Stop trying to identify level from images. The sections are
already in known serial order at uniform thickness, which is a far stronger constraint than their
outlines. Anchor a few levels per animal by eye and interpolate the rest by section number - the
QUINT/VisuAlign shape of workflow, already listed in REFERENCES.md. A few minutes of curation per
brain instead of an unsolved vision problem. **`atlas_proposals_v2.csv` should not be used for
anything until that is done.**

**Also found: 15 physical sections still appear under two scan variants** (LS45_s08b/_s08c,
LS45_s09b/_s09c and others), so the same tissue is matched and would be counted twice. Stage 2
chose a variant per section; 04c does not filter to it. Small, but it needs fixing before counting.

---

## 2026-08-12 - 04f and 04g re-run on the curated 841: the manual pass validates cleanly

**Changed:** nothing in the code. `04f_exclusion_candidates.py` and `04g_artifact_mask.py` re-run
now that `reformat_index.csv` holds the curated 841, so both outputs describe the sections actually
in play rather than a superset.

**The manual curation holds up against the automatic screen.** Of 841 kept sections, **10 (1.2%)**
still trip `04f`'s rules - down from 154 of 1,381 (11.2%). The whole size distribution moved up:

| percentile | before (1,381) | after (841) |
|---|---|---|
| p0.5 | 0.16 mm² | 1.54 mm² |
| p5 | 1.49 mm² | 4.98 mm² |
| p50 | 19.12 mm² | 24.14 mm² |

Sections with no piece at all above 0.5 mm²: **31 → 2**.

This is not the screen agreeing with itself - `04f` measures the source overviews and knows nothing
about which sections were kept. It is independent evidence that the manual pass removed the
fragments and the unmeasurable frames.

**The 10 residuals are worth a second look, listed rather than acted on.** Five fail on tissue
amount alone (1.0-2.4 mm², plus `LS69_s06b_sc10` at 0.13 mm² which is specks), three fail on both,
and two fail on focus alone - including **`LS22_s05b_sc06`, 54.15 mm² of tissue at focus 0.066**,
which is a large intact-looking section with no resolvable nuclear detail. Rendered to
`qc/exclusion/kept_but_flagged.png`. These stay in unless the operator says otherwise.

**Artifacts on the curated set:** 768 of 841 (91%) carry at least one, 2,034 compact and 826
elongated objects, median **0.640%** of tissue masked, p95 1.611%, max 4.44%. The affected fraction
rose from 83% to 91% because the sections that had no detectable artifacts were largely the empty
and fragmentary ones now excluded.

**Housekeeping, not done:** `artifacts/` still holds 1,381 mask PNGs, 540 of them orphans from
excluded sections. Left in place - they are regenerable and nothing reads them, since
`artifact_summary.csv` has 841 rows.

---

## 2026-08-12 - Curated rotations and exclusions applied: 841 sections kept, 540 excluded

**Changed:** the operator's curated `rotation_overrides.csv` applied via
`04a_reformat.py --apply-overrides`. 806 rotations, 540 exclusions. `reformat_index.csv` now holds
**841 sections**. Separately, `04a` now records sections that were *not* excluded but failed to
survive anyway.

**Why that last change.** Two paths in the reformat loop were silent `continue`s - a missing
overview PNG, and a mask that could not be formed. Either removed a section from the analysis with
no record, indistinguishable from a deliberate exclusion. The operator's instruction was that
everything not excluded must be kept, which is exactly the guarantee those two lines could break.
They now append to `lost_sections.csv` and print a block that is hard to miss. **This run: zero
lost**, and the file was not written.

**Verified rather than assumed:**

| check | result |
|---|---|
| sections in index | 841 = 1381 − 540 |
| excluded sections still present | 0 |
| kept-in-CSV sections missing | 0 |
| silently dropped | 0 |

**The operator excluded far more than the machine proposed: 509 manual against 154 proposed.** That
is the conservative design working as intended - `04f` only ever flagged sections with no
measurable tissue or no resolvable detail, and left "how much damage is too much" to the eye, which
is where it belongs. Of the automatic proposals that were reviewed, **10 of 41 were overruled
(24%)**, which is the honest false-positive rate for that rule on reviewed cases.

**Exclusion is not uniform across animals and this needs watching.** Rates run from 28% (LS37) to
59% (LS136), a 31-point spread:

| | LS22 | LS37 | LS45 | LS53 | LS61 | LS69 | LS85 | LS87 | LS105 | LS120 | LS136 | LS138 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| kept | 64 | 83 | 95 | 74 | 75 | 69 | 66 | 58 | 82 | 74 | 48 | 53 |
| % excluded | 37 | 28 | 33 | 36 | 47 | 38 | 36 | 47 | 32 | 33 | 59 | 44 |

Every animal retains 48-95 sections, so nothing is lost outright. But if exclusion rate turns out
to correlate with experimental group at unblinding, that is a bias in the comparison, not a
curiosity - it goes on the list with the AF568 saturation split to check the moment the key is
joined.

**Now stale and needing a re-run:** `04c_atlas_match.py` and anything downstream of it, because the
reformatted masks and the section set both changed. `04h`'s symmetry proposals are moot - the
rotations are now decided. `04f` and `04g` outputs are still *correct* per section, since they
measure the original overviews, but they now describe a superset of the sections in play.

---

## 2026-08-12 - Colab GPU notebook for the cleaning stages, with delete-after-verify

**Changed:** new `colab/` — `ls_gpu_preprocess.py` (the module), `build_notebook.py` (generates the
notebook from it, so the two cannot drift) and `LS_preprocess_gpu.ipynb`. Runs 04f, 04g and 04h in
**one pass per section** instead of three, on GPU via CuPy with a transparent scipy fallback.

**Why one pass matters more than the GPU.** The three local scripts each re-derive the same tissue
mask from the same PNG. Merging them removes that duplication regardless of hardware.

**Drive space, as asked.** Each section produces `<uid>_clean.png` (the overview with artifact
pixels zeroed - the processed copy, same size as the input), `<uid>_artifact.png` (the label mask,
mostly zeros so nearly free) and one CSV row. The input is then deleted, so usage stays flat.
`DELETE_INPUTS` defaults to **False**, and deletion happens only after every output exists and
exceeds 512 bytes. Tested: a truncated write fails verification and the input is kept.

**Parity checking caught a real bug before it shipped.** The first version measured the symmetry
residual on an unrotated mask, while `04h` measures it on top of `04a`'s principal-axis rotation.
A residual is only meaningful relative to what it is a residual *from*: the two disagreed by a
median of **12.5 degrees and a maximum of 35**. After reproducing `04a`'s full geometry (principal
angle, 180 degree resolution, crop, square pad, resize), parity on 14 sections is:

| quantity | agreement |
|---|---|
| `largest_mm2` | exact, 0.0000 mm2 |
| symmetry residual | exact, 0 degrees, 100% within 1 |
| artifact % of tissue | median 0.012 pp, max 0.216 pp |

**The artifact residual is a pre-existing inconsistency, now documented.** `04g` builds its tissue
mask by resizing the *float* array; `04a` resizes the *8-bit image*. PIL's F-mode and L-mode
resampling differ slightly. The module follows `04a`, the canonical path. `04g` is worth aligning.

**An algorithmic win that is not about hardware.** Intersection under a circular shift is a
cross-correlation, and |A| and |B| do not change with the shift, so
`IoU(s) = I(s) / (|A| + |B| - I(s))` gives **every** offset from one FFT. That replaces `04h`'s loop
*and* its `SHIFT_STEP = 2` approximation - every integer offset is now evaluated rather than every
second one. `selftest()` checks it against the loop it replaces and against scipy's tissue mask;
both pass exactly.

**One quantity genuinely cannot be reproduced, and it is flagged rather than fudged.**
`focus_score` in `qc/focus.csv` was computed on the **16-bit** DAPI at export; the notebook sees
the display-ranged 8-bit PNG. The ratio (edge energy / mean) survives a scale but not a
scale-plus-offset, and the PNG is also clipped. So `focus_png` is a different quantity with the
same shape, and `calibrate_focus()` transfers the 0.070 cut by matching **what fraction of sections
it removes**, not its value. The notebook says so where a user would otherwise compare them.

**No speedup is claimed here.** There is no CUDA on this machine, so the notebook ships a benchmark
cell that measures GPU against CPU on the user's own data instead. Local reference for the same
work, done separately: 04f ~10 min, 04g 14.7 min, 04h ~25 min.

---

## 2026-08-12 - Symmetry-axis auto-rotation; the published SIFT method measured at 24 deg error

**Changed:** new `04h_symmetry_axis.py` proposes the residual rotation that puts each section's
bilateral symmetry axis vertical. The curator pre-applies it (purple border, `N deg auto` tag) and
the export gains a `rotation_source` column (`auto_symmetry` / `manual` / `manual_overrode_auto`).
1,227 proposals over 1,381 sections, 903 (74%) high confidence.

**Why:** the user's observation, and it is correct. `04a` orients each section by the **principal
axis** of its tissue mask, which is a property of *elongation*, not of symmetry - it drifts on
nearly round sections and is dragged off by a damaged lobe. Measuring the symmetry directly is the
right cue. Only **23% of sections were already within 2 deg**; 42% needed 3-10 deg and 29% needed
11-29 deg. That is a real manual workload being removed.

**Wu et al. 2013 was implemented in full and does not work on this data.** SIFT keypoints matched
within one image by a symmetric similarity metric (relative scale, mirrored orientation, flipped
descriptor - including the 128-bin reindexing that mirrors a SIFT descriptor), each pair voting for
the perpendicular bisector in a Hough space. Measured against synthetic ground truth on 24 sections:
**median error 24.1 deg, 12% within 5 deg**, against 0.34 deg and 83% for shape reflection on the
same sections and the same rotations.

**The reason is a property of the data, not of the implementation, and it rules out a whole family.**
Their method assumes local features have genuine mirror counterparts, which holds in MRI. In DAPI
fluorescence at 5.20 um/px the internal texture is nuclear speckle: an individual nucleus on the
left has no mirror twin on the right, because cellular detail is not bilaterally symmetric even
though the anatomy is. Confirmed independently by scoring the *same* candidate axes two ways -
intensity cross-correlation put 59% of sections within 2 deg, shape overlap put 91%. **Symmetry here
lives in shape and gross anatomy, not in local image features.** That also rules out Wu et al. 2021,
whose CNN learns a better patch-similarity metric for a signal that is not present. Willemse et al.
2020 solves a different problem - local symmetry *centres* of small objects, not one global axis.

`opencv-python-headless` was installed (cv2 5.0.0) to do this properly rather than dismissing the
SIFT approach untested. It stays installed; SIFT may be useful for the Stage 4 template alignment.

**The search is restricted to +/-30 deg deliberately.** Searching the full 180 deg produced ~90 deg
failures on a third of sections, because a roughly elliptical section is also near-symmetric about
its *long* axis. This refines rather than searches. 71 proposals (5.8%) sit at the +/-30 boundary
and are therefore probably incomplete - those need the human.

**A confidence signal that was nearly shipped wrong.** The natural choice was the peak's *margin*
over the rest of the sweep. Measured, it was **anti-correlated** with correctness: failures had a
higher median margin (0.0140) than correct proposals (0.0099). Shipping it would have labelled bad
proposals good. Peak sharpness and IoU-versus-distance-transform agreement each caught only ~50% of
failures. The peak IoU is the best available - but it is **not** a clean gate, and the code says so:
on three held-out samples of 28 sections it caught 100% of failures in two and **0% in the third**,
where a failure scored higher than that sample's median correct proposal. Some sections are
genuinely near-symmetric about more than one axis inside the window and no score separates those.

**Honest performance, held out:** median error 0.20-0.45 deg, 86-96% within 5 deg. Roughly one
proposal in ten is wrong. The curator showing each section already rotated is what actually verifies
them - which is why the proposal is applied but stays visibly a proposal.

---

## 2026-08-12 - Artifacts masked: new 04g, built at overview resolution on the DIAGNijmegen finding

**Changed:** new `04g_artifact_mask.py`. Detects bright artifacts inside the tissue and writes a
per-section label mask (`artifacts/<uid>_artifact.png`: 0 clean, 1 compact bubble/aggregate,
2 elongated fibre/debris) plus `artifact_summary.csv` carrying `measurable_mm2` - tissue minus
artifacts, the denominator any later density should use. `load_artifact_mask()` and `measurable()`
are the public entry points for Stages 3 and 5.

**Why it runs on the overviews, which is the whole reason this was cheap.** DIAGNijmegen's
`pathology-artifact-detection` runs at **4.0 µm/px**. The overviews here are at **5.20 µm/px** -
the same scale. Artifact detection does not need full resolution. That turned a ~730,000-tile
Colab job into a local run over PNGs that already existed.

Neither repository could be run. DIAGNijmegen's DeepLabV3+/EfficientNet-B2 is trained on
brightfield H&E and chromogenic IHC and wants an 11 GB GPU; this is fluorescence on a machine with
11.8 GB of system RAM and no CUDA. The IAWG repository is a **hackathon challenge with no method** -
it ships `roc.py` and `pr.py` for scoring submissions and reports no results. What transferred was
the working resolution, the class vocabulary, and QUALIFAI's channel-agnostic/channel-specific
split.

**Two bugs found by looking at crops, not at summary statistics.**

*The mask covered only the centre of each artifact.* The smoothness test finds the flat interior of
a bubble but fails at its edge, where the intensity gradient is steep and the texture measure is
therefore high. The result masked each artifact's core and left its bright halo - which defeats the
purpose entirely, since the halo is still among the brightest pixels in the section and still skews
normalisation. Fixed with hysteresis: seed on bright AND smooth AND away from the rim, then grow
into the merely-bright region. Masked areas roughly doubled (43,291 -> 109,512 µm² on one object).
Growth is capped at 25 dilations because the tissue rim is bright and connected all the way round a
section, and unbounded propagation from a seed touching it would flood the whole outline; an object
that still exceeds 1.2 mm² falls back to its seed rather than being dropped.

*The shape classifier called curved fibres "compact".* Bounding-box aspect ratio is near 1 for a
C-shaped worm. Fixed by also testing fill (area / bbox area): a disc packs its box, a worm does not.

**The tissue rim is eroded by 6 px (31 µm) before anything is decided.** The edge of a section is
genuinely DAPI-bright - pial surface, ventricular lining - and a brightness rule without this step
masks real anatomy.

**State the size of the effect honestly.** Full run, all 1,381 sections: **1,147 (83%) carry at
least one artifact**, 2,894 compact and 1,268 elongated objects, and the masked area is **median
0.615% of tissue, p95 1.79%, max 4.44%**.

Those figures are ~4x the ones measured before the hysteresis fix (median 0.134%, p95 0.478%) and
the difference is the fix, not a change of threshold: the earlier numbers counted only the flat
cores that the smoothness test could reach. The halo was always there and always unmasked.

Even at 0.6%, for a density per mm² this is nearly nothing. The reason to do it is
intensity: these are by construction the brightest pixels in the section, and Andhari et al. 2024
showed artifact-inflated intensities skewing normalisation so badly that cell labels changed
*outside* the artifact regions. Apply the mask **before** normalising.

**Not masked, and said plainly rather than implied:** tissue folds (named by all three sources; a
fold in fluorescence is doubled tissue - brighter but with normal granularity, so the smoothness
test that finds bubbles cannot find it) and channel-specific antibody aggregates (would require the
marker channel, which would break the blinding). Very large artifacts are masked only partially,
where the 25-dilation cap truncates them.

---

## 2026-08-12 - QUALIFAI assessed: 91% of sections carry bright artifacts our rules cannot see

**Changed:** REFERENCES.md gains QUALIFAI (Andhari et al. 2024, *Cell Rep Phys Sci* 5:102220). No
code change yet - this entry records an assessment and a measurement that should shape Stage 3/5.

**Why it outranks everything else read so far:** their MILAN training set was acquired on a **Zeiss
Axioscan Z1 at 0.65 µm/px**. That is this study's acquisition. Every other tool assessed targets
brightfield histopathology or the mouse Allen CCF.

**The measurement that decides whether it is worth running.** Random sample of 250 sections,
looking for bright, compact, texture-free objects inside the tissue - the signature of a bubble or
an antibody aggregate rather than bright tissue:

| | |
|---|---|
| sections with >= 1 such object | **227 / 250 (91%)** |
| objects per affected section | median 3, max 15 |
| total area per affected section | median 0.028 mm², max 0.16 mm² |
| per-animal rate | 68-100%, all twelve animals |

Uniform across animals, so not obviously a group confound - **but that has to be re-checked the
moment the key is joined**, alongside the saturation split.

**These are invisible to everything built so far.** `04f` asks whether there is enough tissue and
whether it is in focus. Both pass on a section carrying fifteen bright blobs, because the blobs sit
*inside* good tissue. This is a detection-stage quality mask, not a section-level exclusion, and it
belongs in Stage 3 rather than the curator.

**The finding that touches the analysis plan, not just QC.** On a DLBCL TMA, removing artifacts
changed one core's cytotoxic-T-cell fraction by **46.28%** against a 10.12% maximum in unaffected
cores - and **cells outside the artifact areas changed label too**, because artifact-inflated
intensities skew normalisation, which shifts clustering. The plan here makes DAPI-normalised and
reference-region metrics the primary readouts. Those are exactly what a bright artifact corrupts
globally. **Artifacts must be masked before normalising, not after.**

**Not run, and why not.** Keras/TensorFlow is not in this stack, and 1,381 sections at 0.65 µm/px
in 512 px tiles is ~730,000 tiles through a VGG19 classifier plus a U-Net. Infeasible on this CPU.
It is a Colab GPU job, which is what Stage 5b already reserves Colab for. Proposed order: run the
aggregate and bubble models on a stratified sample of ~100 sections first, and compare against the
cheap bright-smooth-blob detector used for the measurement above. If they agree, keep the cheap
rule and cite QUALIFAI as its validation; if the models find substantially more, the Colab job is
justified.

**Nothing is retracted from the previous entry.** The `out_of_focus` class was set from this
dataset's own montages, not on Jurgas's authority, and QUALIFAI independently lists OOF as one of
its five classes - so it is corroborated, not undermined. What changes is the ranking: QUALIFAI is
the reference to follow for artifact QC, and Jurgas's contribution reduces to having named a class
that was missing.

**Still not detected by anything here:** tissue folds.

---

## 2026-08-12 - An artifact taxonomy from the literature found 51 unmeasurable sections we were keeping

**Changed:** `04f_exclusion_candidates.py` gains a second, independent proposal class,
`out_of_focus` (focus_score < 0.070), alongside `no_tissue` (largest piece < 2.5 mm²). Proposals go
from 103 to 154 of 1,381. `artifact_class` and `focus_score` are now columns in
`exclusion_candidates.csv`.

**Why:** reading Jurgas et al. 2024 (*Sci Rep* 14:17847), whose six-class WSI artifact taxonomy is
air / dust / tissue-fold / ink / marker / **focus**. The exclusion rule here had only a
tissue-amount test. Focus was not on the list because nobody had thought to put it there.

**What the check found.** `focus_score` has been computed in `qc/focus.csv` since Stage 1 and was
never used for anything. Two tests:

*Test 1, per-animal robust z:* **zero** sections more than 3.5 MADs below their animal's median
that were not already proposed. That result reads as "no blur problem" and is misleading - the
distribution is smooth and continuous, so a MAD-outlier test finds nothing even when the bottom of
the range is unusable.

*Test 2, render the extremes:* decisive. The lowest-focus sections are smooth and textureless with
the tile mosaic showing through where nuclei should be. **Looking at the images contradicted the
statistic.**

Threshold placed by rendering 0.01-wide bands and asking where nuclear granularity appears:
0.050-0.060 and 0.060-0.070 are smooth with no visible nuclei; 0.070-0.080 and above plainly have
it. Cut at **0.070**, flagging 51 sections *that the area rule keeps* - large, complete-looking
sections, up to **54 mm² of tissue**, with no measurable cellular detail. All 51 were headed for
cell counting.

The two classes overlap on only 8 sections, so they are genuinely independent failure modes and
are reported separately rather than merged into one exclusion count.

**Not adopted from the paper: its actual method.** The augmentation pipeline blends annotated
artifacts into H&E and chromogenic IHC using Reinhard colour normalisation and a ResNet50 over RGB
patches - all of which assume colour, where this is 16-bit fluorescence on black. Their Table 3
reports the model *"does not generalize well to a new dataset"* with Wilcoxon tests confirming the
lack of significance, and salmonid fluorescence is a far larger domain shift than the one that
already failed. Gains are 0.01-0.10 AUROC and they trained on A100s; this machine has no CUDA.

**Cost:** none in runtime - `focus_score` was already computed and sitting unused.

**Worth noting for the write-up:** ink and marker, two of the paper's six classes, cannot occur in
this dataset. Of the remaining four, air bubbles and debris are visible in the montages and are
currently caught only indirectly, when they leave too little real tissue behind. Folds are not
detected at all and remain a manual judgement.

---

## 2026-08-12 - Pre-select empty sections; two plausible measures thrown away first

**Changed:** new `04f_exclusion_candidates.py` proposes sections with no measurable tissue;
the curator pre-marks them (dashed amber, "PROPOSED") and right-click reverts. 103 of 1381
sections (7.5%) are proposed.

**Why:** the user asked for it - "can't you pre-select the one that look empty and i have the
option to right-click to revert". Right shape for the task: adjudicating 103 proposals is minutes,
searching 1,381 sections by eye is an hour and gets less consistent as it goes.

**Three measures were tried. Two were wrong, and only the montage showed it.**

*Solidity* (mask area / convex hull area) looked principled and was actively harmful. A transverse
brain section at telencephalic level is **two bilaterally separated lobes**, so its hull spans the
midline gap and solidity collapses. It proposed excluding **334 sections, 24% of the dataset**, and
the montage showed them to be good telencephalon - the region of interest. It punished precisely
the anatomy the study is about.

*In-mask median intensity* is a **constant by construction**. The reformat stretches every section
on its own median +/- MAD, so the in-mask median always lands near 51/255: p1 47, median 51, p95 55
across all 1,381. Zero information, and it would have been easy to report as a working filter.

*Largest connected tissue component in mm2* survived - but the first implementation of it was also
wrong. Thresholding the source directly returns a thin bright rim, because sections are bright at
the edge and dim inside; it reported **0.83 mm2 for a frame holding two intact, obviously textured
lobes**. Fixed by using `04a_reformat.tissue_mask`, which closes and fills, and by importing that
function rather than copying it so the two stages cannot drift. Remeasured on the same
hand-labelled sections: good tissue 4.0-11.6 mm2, debris-only frames 0.8-1.9 mm2. The cut sits at
**2.5 mm2**, inside that gap.

**`tissue_area_mm2` in `qc/focus.csv` is not comparable between sections** and nothing should treat
it as if it were. It is computed per image with its own auto-threshold, and those thresholds span
**27 to 2274 within a single slide**. It reported 59.4 mm2 of "tissue" for a frame containing only
specks (threshold collapsed to 37, calling 82% of the frame tissue) and 2.6 mm2 for a frame with
two intact lobes. This weakens the plan's verification step 2, which used its range as a check.

**The proposals are not uniform along the brain, and that is reported rather than tuned away:**

| position | proposed | rate |
|---|---|---|
| rostral | 51/281 | 18.1% |
| | 27/275 | 9.8% |
| mid | 9/277 | 3.2% |
| | 7/275 | 2.5% |
| caudal | 9/273 | 3.3% |

A **6x gradient**. Probably real - rostral tips are genuinely small and often fragmentary - but it
means accepting all 103 trims *rostral coverage specifically*, not a random sample. The curator
prints this before you start clicking. Making the threshold position-aware was considered and
rejected: it would start keeping rostral debris on the grounds that rostral is expected to be
small, and "under 2.5 mm2 of contiguous tissue" is an honest statement about measurability at any
position.

**A proposal is not a decision, and the state model keeps them apart.** The curator stores a
tri-state - no decision, explicitly excluded, explicitly kept - so an unreviewed proposal never
looks like a confirmed one. The export records `decision` as auto / manual / restored, and
`04a_reformat.py` prints what fraction of proposals were overruled. Without that split, "how often
was the automatic rule wrong" would be unanswerable.

**Cost:** localStorage key bumped to v3, with a migration. v2 wrote `x:false` on every touched
section, which under the tri-state rule would read as "explicitly kept" and silently suppress the
proposal on every section that had ever been rotated. The migration drops those and keeps the
rotations.

---

## 2026-08-12 - Manual exclusion of damaged sections; free-angle overrides were being discarded

**Changed:** `04d_rotation_curator.py` gains right-click (or `x`) exclusion, an excluded counter
and a hide toggle; the export grows an `excluded` column. `04a_reformat.py` skips excluded
sections entirely and writes `reformatted/excluded_sections.csv`. Separately, the override
*application* path was rewritten.

**Why exclusion:** the user asked for it directly - "there are still some section that are too
ruined and might only skew the data if included". Correct call: a torn or folded section is not a
rotation problem, and averaging it into a group comparison adds noise dressed as evidence.

**Where the exclusion is enforced matters.** It would have been easier to filter excluded sections
at the point of quantification. Instead they are dropped in `04a`, so they never enter
`reformat_index.csv` and therefore cannot reach matching, registration or counting - the later
stages need no exclusion logic at all and cannot forget to apply it. `excluded_sections.csv` is
written as the canonical list for stages that do not read the reformat index.

**The bug this uncovered.** `apply_override()` did `k = (rotation // 90) % 4` and `np.rot90`. That
was correct for the *previous* curator, which offered 90 degree steps. The curator has since gone
free-angle at 1 degree resolution, and nothing updated this: a manual 37 degree correction would
have been floored to 0 and **silently discarded**. Not an error, not a warning - the section would
simply come back unrotated, and the user would have re-done the same work and watched it vanish
again.

Fixed by folding the manual angle into the automatic one and applying both in a single rotation,
*after* the 180 degree resolution (so a manual 180 is not cancelled by the automatic one) and
*before* the crop (so rotating by 37 degrees cannot push tissue corners outside the frame - the
bounding box is recomputed afterwards). One interpolation instead of two, and no clipping.

Verified on a real section: +37 gives mean |diff| 30.2 against the base render with tissue fill
0.3335 -> 0.3542 and no new frame contact; +90 is bit-stable in fill, as an exact quadrant
rotation should be.

**Cost:** one extra mask rotation per section, at `order=0` on a binary array - negligible next to
the image rotation it replaces.

**Reverses:** the 90-degree-quantised `apply_override()` from the 2026-08-12 rotation curator
entry, which was already stale when it was written.

---

## 2026-08-12 - Robust intensity stretch; a removal sweep avoided

**Changed:** `04a_reformat.py` stretches on median +/- MAD of in-tissue pixels instead of
percentiles. `04d_rotation_curator.py` gains free-angle drag and an atlas reference underlay.

**Why:** the user reported that some reformatted sections looked blank - "completely dark ...
meaning that even if they were marked they dont contain tissue" - and asked for a sweep to remove
them from the dataset.

**They were not blank.** Rendering the darkest sections at three scalings showed clear brain
tissue with visible structure in every one. The sections were fine; the *display stretch* was
broken. Bright specks - debris, saturated flecks - were setting the top of the range and crushing
the tissue underneath. **The proposed sweep would have deleted good data.**

**Third time for this same trap.** min/max let one saturated pixel set the ceiling. The 1st/99th
percentile was not enough either, because debris routinely exceeds 1% of the mask, so p99 still
landed on it. Measured on the same sections, in-mask mean out of 255:

| stretch | in-mask mean |
|---|---|
| min/max | crushed |
| p1-p99 | 8-9 |
| p1-p95 | 64-79 |
| median +/- MAD | 74-85 |

MAD is outlier-resistant by construction, so unlike a percentile it does not care what fraction
of the mask the specks occupy. After the fix: p1 55, p5 63, median 73, and **0 of 1381 sections
below 20**, where before 5% were under 12.

**The masks were never affected** - they come from log-space Otsu, not the display stretch - so
atlas matching results were correct throughout. Only visibility changed.

**Also:** rotation is now free-angle by drag at 1 degree resolution rather than 90 degree steps,
because matching to an atlas plate needs the section at the plate's actual angle. The proposed
plate can be shown behind the section in red, with only the section rotating, so alignment is a
direct comparison rather than a judgement from memory.

**Atlas matching extended to all 12 animals:** 1,381 sections, median score 0.635. The flip call
remains too close to call on 58% - not a code problem, and the reference underlay is the practical
answer to it.

---

## 2026-08-12 - Section-division curation retired; rotation curation added

**Changed:** `01i_multisection_review.py` and `01j_build_curator.py` removed. New
`04d_rotation_curator.py`, and `04a_reformat.py --apply-overrides`.

**Why:** the user confirmed the hand-drawn scan regions are already one-section-accurate, so
section *division* needs no adjudication. The tooling built to ask about it was solving a problem
that does not exist.

**The measurement was right; the interpretation was wrong.** 23% of scenes do contain two or more
large tissue blobs - that finding stands. But those are the bilateral lobes of a single
telencephalic section, not two sections. This is exactly the ambiguity flagged when the tool was
built ("a rostral telencephalic section is naturally two separate lobes"), and the resolution came
from asking rather than from more geometry. Worth keeping as a reminder that a correct measurement
can still support a wrong conclusion.

**What does need adjudication is orientation.** `04a_reformat.py` rotates each section by the
principal axis of its mask, which gets the long axis horizontal but cannot know which quadrant is
correct - for a roughly symmetric outline the axis is right and the direction is a guess.

**Design:** a clickable wall, not a queue. Most sections are already correct and the task is to
*spot* the wrong ones, so showing many at once beats stepping through 2,572. Click rotates 90
degrees, shift-click flips, alt-click resets. Corrections are stored as a delta *on top of* the
automatic angle, so improving the auto-rotation later does not invalidate the manual work.

**One loose end:** `LS136_s05b_sc10` still looks like two complete stacked sections rather than
two lobes - 180.7 mm2 of tissue in a 235.8 mm2 frame. Left flagged for a human eye rather than
silently dropped with the rest of the multi-section work.

---

## 2026-08-12 - Implemented the four adopted methods; matching 0.24 -> 0.61

**Changed:** `04a_reformat.py` (new), `04c_atlas_match.py` (new, replaces the matcher in 04b),
`04e_register_elastix.py` (new). itk-elastix installed - an abi3 wheel, so it works on 3.14 with
no venv and no separate elastix binary.

**1. Reformat before matching (BrainJ).** Sections and plates are centred, rotated horizontal by
the mask's principal axis, stripped of debris and rescaled to a common grid. The matcher had been
comparing raw hand-drawn scan regions against arbitrarily cropped plates, leaving position, scale
and rotation as free parameters to search over. Tissue fill is now comparable between the two
populations - sections 0.40, plates 0.46 - which it was not before.

The 180-degree ambiguity in a principal axis is resolved by putting the heavier half consistently
on one side. Left-right mirroring is deliberately NOT resolved here; see below.

**2. Per-section flip (BrainJ).** Free-floating sections land face up or face down, so flipping is
a per-section property rather than the single global transform previously assumed. Both
hypotheses are scored per section.

**Honest result: the evidence is usually too thin to decide.** 77 of 141 sections score better
flipped, but the margin is under 0.02 on **55%** of them - a coin toss. That is not a defect in
the implementation; a bilaterally near-symmetric section simply carries little shape evidence of
which face is up, which is why BrainJ makes flipping a manual step. The margin is now reported so
the curator can see which calls are arbitrary.

**3. Synthetic augmentation (DeepSlice).** Each plate is expanded into a bank of variants -
small rotations, scale jitter, smooth elastic warps - and a section scores against its best
variant. A real section is a deformed, obliquely-cut version of the plate, so matching only
against the pristine plate systematically under-scores the correct one. 101 plates become 1,010
variants.

**4. Elastix (BrainJ, and AirLab in AnNoBrainer).** Affine then B-spline, via itk-elastix.
Direction is the classic trap: elastix computes T mapping *fixed* coordinates into *moving*
coordinates, so to carry atlas seeds from plate space into section space the **plate must be
fixed and the section moving**. Registering the intuitive way round produces a transform that
maps the points backwards. Written down in the module docstring because it is invisible in the
output when wrong.

**Measured, on LS45, 141 sections:**

| stage | mean IoU |
|---|---|
| original silhouettes (broken) | 0.242 |
| silhouettes fixed | 0.510 |
| + reformatting + augmentation | **0.614** (median 0.665) |
| + elastix registration | **0.628** from 0.528 on the same subset |

**Known gap:** the matcher does not yet filter to the variant Stage 2 chose, so superseded
re-scans (LS45_s08c) still appear. Cosmetic for proposals, wrong for final counts.

---

## 2026-08-12 - Reviewed prior art; four method changes and two documented limitations

**Changed:** added `REFERENCES.md`. Stage 4 gains section reformatting, per-section flip
detection, synthetic training data, and Elastix over bUnwarpJ.

**Why:** four prior tools were reviewed - AnNoBrainer (Peter et al. 2024, Neuroinformatics,
MIT-licensed), DeepSlice (Carey et al. 2023, Nat Commun), BrainJ (Hammond, Fiji), and a review of
automated FISH/IHC analysis (Theodosiou et al. 2007, Cytometry A). All three tools target the
mouse Allen CCF, so none is usable directly on a salmonid - but their methods transfer.

**Taken:**
- *Reformat before matching* (BrainJ): centre, rotate horizontal, strip debris. The current
  matcher compares raw hand-drawn scan regions, which is why it needed an orientation search.
- *Per-section flips* (BrainJ): free-floating sections land face up or face down, so flipping is
  per-section, not the single global transform currently assumed.
- *Synthetic training data* (DeepSlice): they rendered ~920k virtual sections from the template
  with stochastic angles and noise. The same trick turns 101 salmon plates into a training set,
  removing the need to hand-label thousands of reals.
- *Elastix* over bUnwarpJ: scriptable, standard, used by BrainJ and paralleled by AirLab in
  AnNoBrainer.

**Two findings here are corroborated by the literature rather than being local defects:**
- AnNoBrainer states DAPI registers poorly against an H&E/Nissl atlas due to data sparsity and
  poor morphological correspondence. That is exactly the DAPI-to-Nissl-plate pairing here, and it
  explains the silhouette IoU ceiling near 0.51.
- DeepSlice reports underperformance where anatomical landmarks are obscured by low background
  staining or extreme contrast - which describes the AF568 channel measured here.

**Expectations recalibrated:** AnNoBrainer's layer classifier reaches 59% exact, 86% within one
layer, 94% within two. Exact match is not the standard. And two expert neuroscientists scoring the
same annotations agreed at Kappa 0.17 - there is no single human ground truth to converge on,
which is the strongest argument for the propose-then-adjudicate curators.

**Convergent, worth noting:** AnNoBrainer uses Hungarian assignment to link detected brains to a
metadata grid. `02_pair_passes.py` independently used the same algorithm for cross-marker section
pairing.

---

## 2026-08-12 — Curation GUIs: the pipeline proposes, the user adjudicates

**Changed:** two local HTML curators, on the working pattern agreed with the user.
`01j_build_curator.py` asks how many brain sections are in each ambiguous scene;
`04b_atlas_match.py` proposes a rostro-caudal atlas plate per section and offers the top
candidates side by side.

**Why:** several judgements here are anatomical, not computational. Whether two blobs are one
telencephalic section's lobes or two stacked sections cannot be settled by geometry without
encoding a guess about salmonid neuroanatomy. Better to propose, let the user decide, and
calibrate the rule on their answers.

**Design points that matter:** both order the queue **most-ambiguous-first**, so attention goes
where it changes the outcome. Both autosave to localStorage, so a closed tab costs nothing. Data
is embedded in the HTML rather than fetched, because a browser on a `file://` page will not fetch
a sibling JSON. Atlas assignment is constrained **monotonic** via dynamic programming — serial
sections cannot run backwards along the brain, so a correction improves its neighbours too.

**Two silhouette bugs, both found only by rendering what the code actually saw:**

*Atlas plates came out as thin rims.* They are dark tissue on a light background; inverting and
taking a high percentile selects the darkest pixels, which are the section's *edges*, discarding
the body. Fixed by treating anything meaningfully darker than the background as tissue, then
filling.

*Sections came out as scattered speckle.* Those DAPI overviews are faint against black, and a
percentile threshold on a mostly-black frame picks bright specks. Fixed with log-space Otsu, as
everywhere else in this pipeline, then filling and dropping small components.

**How it was caught:** the orientation search reported all eight dihedral transforms scoring
within 0.014 of each other. That is not a weak signal — if rotation changes nothing, there is no
shape to rotate. Mean best IoU went 0.284 → **0.563** once fixed, and weak matches fell from
141/141 to 57/141.

**Worth noting:** the aspect statistics had suggested a real 90° mounting mismatch (plates 2.07,
sections 0.86). After the fix, `identity` wins the orientation search — the mismatch was an
artifact of the broken silhouettes. Solving for the transform rather than hardcoding the
plausible-looking `rot90` is what kept that from becoming a permanent silent error.

---

## 2026-08-12 — Normalised metrics promoted to primary; raw pERK demoted

**Changed:** the Stage 6 hierarchy is now explicit. **DAPI-normalised and reference-region
metrics are the primary readouts; raw density is a sensitivity check.** Previously all three were
to be reported side by side with the choice left open.

**Why:** Randlett et al. 2015 (*Nat Methods*, the MAP-mapping paper) uses the same pERK primary
this study does — Cell Signaling #4370 — and normalises every measurement to **total ERK**
(CST #4696) acquired in a parallel channel. Their stated reason: *"High baseline pERK staining
makes finding stimulus- or behavior-dependent changes in staining challenging."*

This dataset has **no tERK channel**. So the field's standard control for pERK's high, variable
baseline is unavailable, and something has to stand in for it. DAPI density normalises for cell
number and section thickness; a reference region normalises for staining batch. Neither is as
good as tERK, and saying so is part of the result.

**Cost:** none computationally. It constrains how findings may be phrased, which is the point.

**Compounding factor:** if AF568 turns out to be pERK, the universal contrast inversion measured
across 2,572 sections (AF568 median contrast 0.48, 93% inverted; AF488 2.97, 0% inverted) sits
directly on top of a marker already known for a high baseline. Those two problems multiply rather
than add.

---

## 2026-08-12 — Illumination field measured from raw tiles

**Changed:** new `01h_tilefield_raw.py`. Samples raw per-tile pixels via czifile, takes a
per-pixel median across thousands of them, then maps that tile-domain field into the stitched
domain by reading the real tile rectangles and M indices and applying the documented overlap rule
(highest M wins).

**Why:** `01f_tilefield.py` could only fold *stitched* sections, so anatomy had to be divided out
first and the stitcher's overlap behaviour was baked in. It got the artifact from 18% to 14.7% —
real, but short of the 6% target. A median across raw tiles *is* the illumination profile, with
no baseline model and no folding assumption, because tissue sits at a random position relative to
the tile frame.

**Cost:** czifile, and a geometry derivation to relate a 2040 px tile field to an 1836 px pitch.
The derivation checks out: it reports 11% of a pitch cell coming from a tile's trailing region,
and 204/1836 = 11.1%.

**Not yet promoted.** Written as `tilefield_raw_<CHANNEL>.npy`, deliberately not under the
`tilefield_c{0,1}` names the apply path reads. At 60 tiles the AF568 field spans 0.44–2.53, which
is not an illumination profile — it is an unconverged median. AF568's background outshines its
tissue, so individual tiles are dominated by whatever sits behind the section. Needs far more
tiles before it is trustworthy, and must pass `01c` at prominence < 2.0× before replacing
anything.

**Bug found while doing this:** the apply path loads `tilefield_c1` as "the marker channel of
this file", which silently gives AF568 and AF488 files the *same* correction despite measurably
different fields. The new script names fields by channel so that cannot happen.

---

## 2026-08-12 — Made every path portable

**Changed:** `run_all.sh` derives `SCRIPTS`, `ROOT` and `LOGS` from its own location, with
environment overrides; it exports `LS_CONFIG`, which the Groovy scripts now read because Groovy
cannot resolve its own script path.

**Why:** five files carried hardcoded `D:/LS-analysis` and `C:/Users` paths, which made the
published repository unusable by anyone else.

**How it was nearly missed:** the first verification grep used broken shell escaping and reported
clean. The check was only trustworthy once re-run with a pattern that demonstrably matched.

---

## 2026-08-12 — Split CZI readers by provenance, not speed

**Changed:** `pylibCZIrw` is the reader for every pixel whose value reaches a result. `czifile`
is used only for instrument characterisation — illumination profile, tile geometry — and for
bulk QC scans whose numbers inform decisions but are never reported. Each script records its
reader in a `reader` column.

**Why:** czifile benchmarks 6.5× faster than pylibCZIrw and is the only library exposing raw
per-tile pixels. But it reimplements a format specification its own README describes as
confidential, whereas pylibCZIrw is Zeiss's own. For data that ends up in a paper, vendor
provenance outranks 0.2 s per section. czifile is kept because pylibCZIrw deliberately abstracts
subblocks away, and the only other route to raw tiles is the Bio-Formats path that corrupted 238
sections.

**Cost:** a Python 3.13 virtualenv at `work/czienv`, because pylibCZIrw ships no cp314 wheel and
the system Python is 3.14.5rc1. Two environments to keep in step.

**Reverses:** the proposal, made the same day, to consolidate on czifile alone.

---

## 2026-08-12 — Ported Stage 1 from Bio-Formats to pylibCZIrw

**Changed:** `01_overviews.groovy` → `01_overviews.py`. Bio-Formats retired from the data path;
it survives only for bUnwarpJ/BigWarp registration in Stage 4, which operate on overview PNGs.

**Why:** three separate reasons, in increasing order of importance.
*Speed* — 0.25 s to open a file and 0.26 s per section, against ~56 s and ~9 s. The full export
drops from ~306 min to ~36 min.
*Correctness* — no Memoizer, so the tile-mode bug below cannot recur.
*Exactness* — `zoom` is continuous, so every section lands at exactly 5.20 µm/px rather than
snapping to the nearest stored pyramid level.

**Cost:** a second Python environment. Groovy version retained for reference, not for use.

**Immediately proved its worth:** with tissue-only display ranging, AF568's 99.5th percentile
came back as 65535 — showing the clipping is *inside the brain*, not confined to background, and
contradicting the "largely cosmetic" verdict that had been reported two hours earlier.

---

## 2026-08-12 — Display range computed from tissue pixels only

**Changed:** the Stage 1 sampling pass histograms pixels inside the DAPI mask instead of the
whole frame. Percentiles pulled in from 0.1/99.9 to 1.0/99.5.

**Why:** AF568's background is brighter than the brain on most sections, so it set the 99.9th
percentile of the whole frame to 65535. The display range then spanned the full 16 bits and real
tissue rendered around 20/255 — which is why the first contact sheets looked washed out. The
percentile change stops a handful of clipped pixels *inside* the mask dragging the top back up.

**Cost:** every AF568 overview had to be re-exported.

---

## 2026-08-12 — Separate Bio-Formats memo caches per reader configuration

**Changed:** `work/bfmemo` split into `bfmemo_stitched` and `bfmemo_tiles`. Poisoned cache
deleted; 238 sections and 714 PNGs removed and re-exported.

**Why:** the Memoizer keys its cache on **file path alone**, not on reader options. The
flat-field script opened files with `autostitch=false` into the shared cache; the overview
exporter then asked for stitched mode and got a tile-mode reader back, reading "series N" as a
single 2040×2040 tile instead of a whole section. 238 sections (9%) exported as raw tiles.

**How it was caught:** `tissue_area_mm2` ranged 0.18–28.83 mm² within one brain, which is
biologically impossible. The `resolution` column was empty on exactly those rows.

**Cost:** ~40 min of re-export. The bug was silent — the images looked plausible in isolation.

---

## 2026-08-12 — `pipefail` in run_all.sh, and per-file checkpointing

**Changed:** the `fiji()` helper sets `pipefail`; `01_overviews` writes `focus.csv` after every
file, atomically via a temp file and rename.

**Why:** the runner piped Fiji through `grep` to drop JVM noise, so bash saw grep's exit status.
A crash 306 minutes into step 9 was reported as success. Separately, `focus.csv` was written only
at the very end, so that crash discarded five hours of completed work rather than one file's.

**Cost:** none. Both were straightforward.

**Context:** the crash was not a code fault — the external drive dropped writes (see below).

---

## 2026-08-12 — D: drive dropped writes mid-run

**Changed:** nothing in the code. Git repository placed on C: rather than D:.

**Why:** Windows logged `{Delayed Write Failed} ... the data has been lost` against
`D:\LS-analysis\overviews\...` at 16:26, and against the volume two minutes later. D: is a
Seagate Expansion 4.6 TB USB drive formatted exFAT. This also explains the "working directory was
deleted" shell errors and the 0-byte step logs.

**Verified:** all 222 CZIs CRC-checked byte-for-byte against the zip central directories — zero
mismatches. Size matching had already passed, but size cannot detect a dropped write *inside* a
file. The source data is intact; the dropout cost one PNG.

**Standing risk:** a corrupted `.git` on that drive would be worse than a corrupted output file.

---

## 2026-08-12 — Saturation module: contrast checked before clipping location

**Changed:** `01g_saturation_map.py` measures tissue-versus-background contrast on **every**
section, clipped or not, and `classify()` checks it before anything about where clipping sits.

**Why:** the module's first version asked only "is the clipping inside the tissue mask?" and
answered correctly — then concluded "largely cosmetic". But the real problem was that the AF568
background outshines the tissue 2–5×, which a clipping-location test cannot see. The summary and
its own per-section rows then contradicted each other.

**Cost:** two retracted verdicts, both caught by looking at the diagnostic figure rather than the
summary line.

**Lesson worth keeping:** a verdict from a test that never measured the thing that matters is
worse than no verdict. The measurement now lives in Stage 1 as a `contrast` column, so every
section gets it, rather than in a module that only examined sections which happened to clip.

---

## 2026-08-11 — Tile-artifact test targets the known pitch

**Changed:** `01c_measure_tile_artifact.py` measures power at the **known 1836 px pitch** instead
of reporting the strongest period in a search band.

**Why:** the scan-for-strongest version always returns something. On a *corrected* section it
dutifully reported "20.9% artifact" at an unrelated period — an unfalsifiable test. Scanning was
right while the pitch was unknown; once measured, the test must target it.

**Cost:** none.

---

## 2026-08-11 — Tile geometry read from the CZI, not estimated from the image

**Changed:** `01e_tile_geometry.py` parses the CZI subblock directory for exact tile origins.

**Why:** the power-spectrum estimate gave ~1206–1227 µm. The true pitch is **1836 px = 1193.40 µm**
with 10% overlap, identical across all 131 scenes checked. A 1–3% error accumulates to a fifth of
a tile across a 7-tile-wide section, which would smear any correction built on it.

**Later corroborated:** pylibCZIrw's `enumerate_subblocks_subset(..., only_layer0=True)` returns
2040 px tiles on an 1836 px pitch, 7×10 grid — an exact independent confirmation of the
hand-rolled binary parser. The parser can now be replaced with the supported call.

---

## 2026-08-11 — Log-space Otsu for every tissue mask

**Changed:** all tissue thresholding uses Otsu on `log1p(intensity)`.

**Why:** DAPI runs a median near 500 against a 99.9th percentile near 30,000. Plain Otsu
maximises between-class variance by chasing that tail and returns a threshold above nearly every
pixel — tissue fraction came back under 2% on images that are ~20% tissue. Logs make the two
populations comparably wide so the split lands between them.

**Cost:** none. Affects every downstream mask.

---

## 2026-08-11 — Marker pairing tolerances made scale-free

**Changed:** `02_pair_passes.py` expresses all tolerances as fractions of the nearest-neighbour
section spacing, never as absolute distances. Offset search constrained to ±3 mm.

**Why:** two failures in sequence. First, an unconstrained vote recovered "slide reload offsets"
of ±12 mm — it was locking onto a one-section shift, which scores nearly as well on a regular
grid. Then an 800 µm absolute tolerance rejected LS45, which visibly matches. The cause of the
second: **scan boxes are hand-drawn**, so a box centre sits 1–2.5 mm from the section centre even
on identical slides. What distinguishes same-slide from different-slide is the residual
*relative to how far apart sections are*.

**Result:** 82.5% matched overall, LS45 at 93.4%.

**Also corrected:** LS136 slide 1 was called "different physical slides" on a superficial reading
of x-ranges and row counts. It is the same slide — its AF568 column at x≈−47 has sections at
y = 6.1, 12.9, 18.8 mm, three rows, same as AF488.

---

## 2026-08-11 — Section order taken from scan order, not a fitted grid

**Changed:** `section_order` derives from scene index as acquired, confirmed against slide-map
figures.

**Why:** three grid-fitting attempts failed on real layouts. Scene *size* is a bad clustering
scale; LS105_8a's two rows are staggered ~3 mm in X, which a column model cannot represent; and a
single-row slide got split one-scene-per-row by an ambiguous gap distribution. The operator draws
scan regions systematically, so scan order tracks the physical layout on slides where no grid
model fits at all.

**Cost:** the grid detection is retained for diagnostics and for the alternative conventions
shown on the slide maps.

---

## 2026-08-11 — `a`/`b`/`c` suffixes are markers, not re-scans

**Changed:** the manifest treats variant letters as marker channels: `a` → AF568, `b`/`c` → AF488.

**Why:** they were initially read as duplicate scans to be deduplicated. They are two different
markers on the same physical sections. Only 5 genuine duplicate pairs exist (`LS45_8b/8c`,
`LS45_9b/9c`, `LS61_2b/2c`, `LS61_4b/4c`, `LS85_7a/7b-`). The 13 loose CZIs on D: are
byte-identical copies of zip entries.

**Consequence:** scene indices do **not** correspond between passes — scan regions were redrawn
each time, so `LS45_8a` has 10 scenes and `LS45_8b` has 12. Pairing must go through stage
coordinates, which is why Stage 2 exists at all.

## 2026-08-19 - atlas plate set switched to `plates_final`, section counts enforced

**The two plate sets collide.** `plates/` (101), `plates_merged/` (47) and
`plates_final/` all name their plates `plate_NNN`, and 68 ids existed in two sets
pointing at different images. A landmark file could therefore be matched against
the wrong plates with nothing to show it had happened. Fixed by making the choice
a single declared value, `atlas_plate_set.dir` in `config.json`, read by both
`04l_roi_curator.py` and `04e_register_elastix.py`, and by stamping `plate_set`
into all three curator exports.

**Operator knowledge: merged figures 31-47 carry two sections each.** Recorded in
`config.json` as `atlas_figure_sections`. Geometry disagreed on five figures, in
two different ways, and geometry was wrong both times:

  * **34, 35 under-split.** The two sections *touch* - the upper section's
    pituitary sits in the notch between the lower section's dorsal humps, so they
    are one connected component - and the legend text runs across the contact
    zone, so no row is empty either. Confirmed by measurement: a single component
    of area 0.40 spanning y 0.001-0.999, and no empty row anywhere in the middle
    40% for x in 0.40-0.70.
  * **45, 46, 47 over-split.** A section crossed by an internal white band -
    stained brainstem above, pale cerebellum below - counted as two. Figure 46
    had it on both sections, giving four boxes for two.

`04a3b_enforce_sections.py` takes the declared count as the authority and decides
only *where* to cut. Merging unions the closest pair repeatedly. Splitting
produces **overlapping** boxes, matching the 0.005-0.015 overlap figures 31-44
already had, because a single cut through touching sections would take the
pituitary off one plate or the humps off the other. 34 and 35 are flagged
`review=1`; the cut there is an estimate.

**Separately, figures 20 and 21 were not two sections.** The second box was a
detached "Optic Chiasm" callout - figure 22 shows the same structure attached and
labelled OC inside the section. An inset is not a plate. Both dropped; neither
held a seed.

68 boxes -> 64 (30 single-section figures + 17 x 2), 40 figures untouched.
`plate_boxes.prev.csv` keeps the previous export. Rebuild carried **all 316 seeds
onto 17 plates with 0 orphans** - no seed lies on figures 31-47, so none of this
could put an ROI at risk.

### ROI curator - one screen, and z/x to step sections

Layout is now a flex column pinned to the viewport: header and footer fixed,
the panes take what is left, and only the side card and the thumbnail strip
scroll - inside themselves. Verified at 1280x720: `scrollHeight` 720 against a
720 viewport, no vertical page scroll.

**The canvases now use `object-fit: contain`, and that silently breaks clicks
unless the mapping is fixed.** `contain` fits the bitmap inside the element and
centres it, so the element box is not the drawn area - a 1098x643 plate in a
493x501 box gets a 106 px letterbox top and bottom. The old `canvasXY` scaled by
width alone, which would have put every landmark off by that band. It now undoes
the fit explicitly. Measured end to end by dispatching clicks at known canvas
coordinates and reading back the recorded pair: worst error 1.95 canvas px on the
1098 px plate, under one CSS pixel.

Section stepping moved from `n`/`p` to **`z` previous / `x` next**. Keydown now
ignores events from a focused `SELECT`/`INPUT`/`TEXTAREA`, because the plate
slider is a range input that already steps itself on the arrows - without the
guard it moved two plates per press - and the animal select does type-ahead on
letters and would have swallowed `x`. Both controls blur themselves once used.
