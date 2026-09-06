---
title: "Automated regional quantification of nuclei and marker immunofluorescence in salmon whole-brain sections"
subtitle: "Image-analysis methods, from Zeiss CZI whole-slide scans to a per-nucleus measurement table"
---

# Overview

This document describes the image-analysis workflow implemented for the LS whole-brain
immunofluorescence dataset, from the moment a Zeiss CZI whole-slide scan is opened to the moment
a table of individual nuclei with their marker intensities exists and has been reduced to
per-region densities. It is written to be read as the Methods section of a paper: every step is
described once, in the order it runs, and every external library is named at the point where it
does the work. A full reference list follows at the end.

The workflow has four properties that shape everything below and are stated here once.

**One reader owns the measured pixels.** Three CZI readers were benchmarked and each is used for
exactly one purpose. If a number derived from a pixel appears in a figure or a table, that pixel
was read by pylibCZIrw, Zeiss's own library.

**The pipeline proposes and an operator adjudicates.** Three steps cannot be batched — the
adjudication of excluded sections, the assignment of an atlas level, and the placement of the
regions of interest. Automatic level assignment was implemented twice and measured to fail on
these data, so it is done by hand, as the published tool for the same task also does.

**Analysis is blinded by construction.** Every intermediate file is keyed by animal identifier
alone. The treatment group is first read at stage 06b, which is beyond the scope of this
document.

**Every stage is resumable and every decision is reversible.** Long stages checkpoint per item
and atomically; exclusions are recorded as flags rather than deletions, so a section that was
set aside can be reinstated without re-reading anything.

![**Figure 1. The workflow.** Stages run top to bottom. Fill colour records which reader
decoded the pixels; a bold red outline marks a step where an operator decides; the right-hand
column names the file each stage leaves behind. The dashed line is the blinding
boundary.](img/workflow.png)

\newpage

# 1. Dataset and image acquisition

Brains from twelve juvenile salmon were sectioned transversely at 14 µm and mounted as
consecutive series. Sections were immunolabelled for two markers in two separate passes over the
same slides: phosphorylated ERK (pERK), visualised with Alexa Fluor 568, and PCNA, visualised
with Alexa Fluor 488. Both passes were counterstained with DAPI.

Slides were scanned on a Zeiss slide scanner as two-channel (counterstain plus one marker) tiled
mosaics, written as CZI. Acquisition settings were identical across the dataset and were read
back from the file headers rather than transcribed: a 10× objective of numerical aperture 0.45,
a Hamamatsu ORCA-Flash4.0 camera, a pixel size of 0.65 µm, and 16-bit unsigned samples. Exposure
was 5 ms for DAPI, 1000 ms for AF568 and 300 ms for AF488. Tiles are 2040 × 2040 px on an
1836 px pitch — 1193.40 µm, a nominal 10 % overlap — read from the CZI subblock directory rather
than estimated from the image. No shading reference was acquired and tiles were not blended at
acquisition; tile compression is JPEG-XR, which is typically lossy and was fixed when the files
were written. Both limitations are consequences of the acquisition and are addressed in §5 and
§15.

The dataset comprises 222 CZI files totalling approximately 393 GB, carrying 2,572 scanned brain
sections — 1,191 in the pERK pass and 1,381 in the PCNA pass. Because sections are consecutive
rather than sampled at an interval, the section index multiplied by 14 µm gives rostro-caudal
position within the block. Animals carry a median of 106 pERK and 113 PCNA sections, so each
series spans roughly 1.5 mm of forebrain, which is consistent with every region quantified
here being telencephalic or preoptic. It also
means adjacent sections are not independent tissue, which is why the Abercrombie correction in
§12 is applied rather than offered as an option.

## 1.1 What has been measured so far

The document above describes the workflow; this subsection states how far it has been run, so
that the two are not confused. **Detection is still running, so these counts grow**; they are
stated as of 2 September 2026.

The pERK (AF568) arm has been carried through stage 06a. Nuclei have been detected and measured
in 130 of its 450 currently measurable sections, from 11 animals, across 2,069 regions of interest — 1,483
anatomical ROIs and 586 background reference discs — yielding 892,025 individually segmented and
measured nuclei, of which 619,300 fall in the anatomical ROIs and the remainder in the
background discs. Eleven atlas regions are represented, of which Dl (575 ROIs) and Dm (489)
dominate, with POA, Vv, Vd, Vl, Vs, Vc, the anterior tuberal nucleus, the posterior tuberculum
and Rm contributing the remainder.

The PCNA (AF488) arm has been curated but detection has not been started. Its scope is the full
788 curatable sections rather than the pERK partners, because the clipped-pixel censoring of §8
is specific to the AF568 exposure and does not define a PCNA subset.

# 2. Reading the CZI files

Three readers were benchmarked on this dataset, and the ranking on speed is not the ranking that
decided the architecture.

| Reader | Open a file | Per section | Raw tiles | Runtime |
|---|---|---|---|---|
| Bio-Formats (Fiji) | ~56 s | ~9 s | yes | JVM |
| pylibCZIrw (Zeiss, vendor-maintained) | 0.25 s | 0.26 s | no | Python |
| czifile (third-party) | 0.00 s | 0.04 s | yes | Python |

**pylibCZIrw reads every pixel whose value reaches a result.** It is slower than czifile by
about 0.2 s per section, and that is accepted: czifile reimplements a format specification the
vendor describes as confidential, and for data that ends up in a paper, provenance outranks the
time.

**czifile is retained for instrument characterisation only.** pylibCZIrw deliberately abstracts
subblocks away, and the per-tile illumination work of §5 needs raw, unstitched tiles. czifile
therefore describes the instrument — the illumination profile and the tile geometry — and never
the specimen.

**Bio-Formats is retired from the data path.** Bio-Formats (Linkert et al., 2010) is reached
through Fiji (Schindelin et al., 2012), whose Memoizer caches reader state keyed on file path
alone. A reader saved in tile mode by another script was therefore handed back in tile mode
here, and 238 sections were silently exported as single 2040 × 2040 tiles instead of whole
sections. The failure produced plausible images and no error, which is why the rule above is a
rule rather than a preference. Bio-Formats survives only for registration utilities that operate
on exported PNGs, never on CZIs.

Every stage records which reader it used in a `reader` column, so provenance is auditable in the
output rather than remembered.

# 3. Manifest, verification and channel identity

**Stage 00 — manifest and slide reconstruction.** Every CZI header is parsed without decoding a
single pixel, producing one row per file and one row per scanned section. Because the physical
arrangement of sections on a slide is not recorded anywhere in the file, the slide grid is
reconstructed from scene stage coordinates and rendered under five candidate mounting
conventions, and no downstream stage is permitted to assume one until the convention has been
confirmed by eye. For this dataset the confirmed convention is scan order: the serial order of
sections equals the scene index as acquired.

**Stage 00b — extraction verification.** Part of the dataset arrived as archives. Extracted
files are verified against the archive central directories, optionally by CRC rather than by
size alone, so a truncated or partially written file is caught before it is measured.

**Stage 00c — channel identity.** The CZI records fluorophores, not antibodies, so nothing in
the metadata says which channel carries which marker. The two markers are separated by two
scale-free spatial statistics computed on detected objects, neither of which requires either
marker to be named in advance: a clustering index — mean nearest-neighbour distance divided by
the value expected for the same number of objects scattered at random over the same tissue area
— and an edge affinity, the median distance from an object to the nearest tissue boundary as a
fraction of the tissue half-width. Proliferating cells sit in the periventricular germinal zones
and therefore score low on both; activity-dependent signal is distributed through the parenchyma
and scores near the random expectation. The stage reports the call and writes the evidence
figure but does not commit the assignment; the identification of AF568 as pERK and AF488 as PCNA
was confirmed by the operator and recorded in the configuration.

# 4. Overview export

**Stage 01.** Every section is exported once as a browsable overview at exactly 5.20 µm/px,
using pylibCZIrw with a continuous zoom rather than snapping to the nearest stored pyramid
level. The exactness matters: with pyramid snapping, measured tissue area ranged from 0.18 to
28.83 mm² within a single brain, which is a resolution artefact and not anatomy.

**The display range is computed once and frozen across the whole dataset.** Per-image
auto-contrast would make every section look equally bright and destroy the cross-animal
comparison the overviews exist to support. The range is computed from tissue pixels only, not
from the whole frame: on many sections the AF568 background outside the tissue is brighter than
the brain itself, and sampling the frame pinned the top of the range at the 16-bit ceiling,
leaving real tissue rendering at around 20/255.

**Tissue is segmented by Otsu's method applied in log space** (Otsu, 1979). These channels are
extremely skewed — DAPI runs a median near 500 against a 99.9th percentile near 30,000 — and
plain Otsu maximises between-class variance by chasing that tail, returning a threshold above
nearly every pixel. Thresholding `log1p` of the intensity and mapping back with `expm1` gives a
mask of the actual section. The same log-space Otsu is used for every tissue mask in the
pipeline.

Per-section quality control is written alongside each overview: tissue area, focus, and the
fraction of pixels at the sensor ceiling.

# 5. Instrument characterisation

Because no shading reference was acquired and tiles were never blended, the illumination profile
repeats at the tile pitch across every section. Uncorrected, a fixed threshold detects
materially more objects near tile centres than near tile edges. Four stages measure this and
build a correction; all of them read raw tiles with czifile and none of them touch a measured
value.

**Tile geometry is read from the file, not estimated from the image.** The 2040 px tile on an
1836 px pitch was confirmed independently by pylibCZIrw's subblock enumeration and by parsing
the CZI directory directly. A power-spectrum estimate of the same quantity was 1–3 % off, which
accumulates to a fifth of a tile across a section.

**The correction field is built by folding in the stitched domain.** Correcting raw tiles and
re-stitching would cost roughly 27 hours across the dataset against about two for reading the
pyramid level the scanner already stored, and would still leave undetermined which tile the
stitcher kept in each overlap region. Because the tile grid is exactly regular and the stitched
image starts at the mosaic origin, tile boundaries fall at exact multiples of the pitch in
stitched coordinates, and every pitch × pitch cell sees the same illumination pattern whatever
the stitcher did. Taking the per-pixel median across thousands of such cells, spanning sections
whose tissue falls at random positions relative to the grid, leaves anatomy alone and recovers
illumination.

**The artifact is measured before and after correction.** It is multiplicative and periodic at
the tile pitch, so it appears as a single sharp peak in the spatial-frequency spectrum of the
tissue-mean profile along each axis; detrending first removes real anatomy, which varies far
more slowly than the 1.19 mm pitch. Amplitude is reported as peak-to-trough of the folded tile
profile as a percentage of mean signal — that is, how much more signal a detection near a tile
centre sees than one near a tile edge.

**Saturation is mapped separately, because clipping is not correctable.** 35 % of AF568 sections
have more than 2 % of pixels pinned at 65,535, up to 47 %, and the pattern is animal-specific
rather than uniform. Four measurements separate cosmetic clipping from consequential clipping:
what fraction of the clipping lies inside the tissue mask at all, how close it sits to the
tissue boundary, how large the connected clipped regions are — at 5.20 µm/px a 7 µm nucleus is
under one pixel, so a large clipped blob cannot be nuclei — and where it falls anatomically.
What this measurement leads to is described in §8.

# 6. Contact sheets and pairing the two marker passes

**Stage 01d — contact sheets.** The 2,572 overviews are assembled into per-animal montages
ordered rostro-caudally, plus a browsable HTML gallery. Because the display range was frozen
dataset-wide in §4, brightness differences between sections on a sheet are real differences in
signal rather than auto-contrast artefacts, which is what makes the sheets worth looking at.
Sections flagged by quality control are marked rather than dropped, so a gap in a series is
never silently invented.

**Stage 02 — pairing the passes.** Both passes imaged the same physical slides, but the scan
regions were redrawn for each pass, so scene indices do not correspond — one slide has 10 scenes
in the first pass and 12 in the second. Matching therefore goes through stage coordinates. The
slide sits in a kinematic holder, so a reload displaces it by a small rigid translation; that
offset is recovered by voting, in which every candidate pairing votes for the translation it
implies and the translation with the most inliers wins. With sections 7–10 mm apart and reload
offsets far smaller, the vote is unambiguous. Assignment under the winning offset is then solved
optimally rather than greedily, using the Jonker–Volgenant variant of the Hungarian algorithm
(Kuhn, 1955; Crouse, 2016) as implemented in SciPy (Virtanen et al., 2020), so one badly matched
section cannot cascade into its neighbours. Unmatched sections are listed explicitly rather than
dropped. This stage produces the canonical section identifier that every later stage keys on.

# 7. Atlas extraction and section reformatting

## 7.1 Atlas plates and region seeds

Region identities come from a salmon brain atlas supplied as a PDF. The atlas is a working
vector document rather than a scan: every region marker is a vector dot with a distinct fill
colour, and each page carries a legend mapping colours to region names, which makes the whole
document machine-readable. Plates and region markers were extracted with PyMuPDF.

Markers are located by size rather than by colour, which is the non-obvious part: two of the
atlas's own region colours defeat a colour filter, because black is used for the posterior
tuberculum and the hatched anterior tuberal nucleus is a pattern fill that also reports as
black. Filtering on colour discarded both, which removed every labelled plate caudal to a
certain point.

Extraction yields 101 raw plates from 31 pages. After merging figures that carry more than one
section and reframing plate boundaries, the working set is 64 plates carrying 356 region seed
points across 11 named regions, on 30 of those plates. The atlas labels the telencephalon and
preoptic area; the majority of plates carry no region identification, which bounds regional
quantification to the forebrain (§15). Extending the labelling caudally to the remaining
social-behaviour-network nodes is guided by Wullimann et al. (1996) and Nieuwenhuys (1982),
which are the comparative references the atlas itself is read against.

## 7.2 Section reformatting

Sections are normalised into a common frame before anything is compared, an approach adopted
from BrainJ (Hammond), whose second pipeline step likewise centres each section, rotates it
horizontal and removes surrounding debris before any analysis.

The reason is that the alternative was tried first. Atlas matching originally compared raw,
hand-drawn scan regions against arbitrarily cropped atlas plates, leaving position, scale,
rotation and debris all free — which is why it needed an eight-way orientation search, and why
the search returned nothing useful. Normalising removes those parameters instead of searching
over them.

Each section is reduced to a tissue mask and then: connected components below a fraction of the
largest are discarded, so a fleck of tissue cannot drag the centroid or the principal axis;
the section is rotated so the principal axis of the mask lies along x, regardless of how it was
mounted; it is centred and cropped to the tissue bounding box; padded square; and resized to a
256 px frame. Robust statistics are used throughout — the intensity rescaling uses the median
and the median absolute deviation rather than extremes or percentiles, so bright debris left in
the frame cannot darken the real tissue.

**All of this geometry is computed on DAPI, never on the marker channel**, because the marker is
a sparse signal and a poor silhouette. That choice turns out to protect the measurement in a way
nobody designed for: the marker channel carries a PAP pen stroke around the tissue in 54 of 60
sampled pERK sections — median 7.5 % of the frame, up to 28 %, often brighter than the tissue,
and absent from PCNA. Nothing masks it. What removes it is this crop: the stroke lies outside
the DAPI silhouette, and measured on 40 reformatted sections the mean intensity outside the
tissue mask is 0.51 against 74.0 inside, with no pixel exceeding half scale. The safeguard holds
only as long as no geometry is computed on the marker channel.

# 8. Exclusion, artifact masking and censoring

Three separate mechanisms remove unmeasurable data, and they are kept separate because they mean
different things: a whole section can be unusable, a region inside an otherwise good section can
be unusable, or an individual pixel value can be lost.

**Stage 04f — section exclusion, proposed conservatively and adjudicated by hand.** Judging
1,381 sections by eye is slow and, worse, inconsistent, because the twelfth animal is judged by
a more tired standard than the first. This stage proposes only the unambiguous cases so the
manual pass becomes adjudication rather than search. The asymmetry is deliberate: a wrongly
included section adds a little noise to a group mean and remains visible in the data, whereas a
wrongly excluded section vanishes silently and takes its evidence with it. Only sections with no
tissue worth the name are proposed — the largest connected tissue component below 2.5 mm²,
measured at a known 5.20 µm/px so the criterion is a physical size — and torn-but-substantial
sections are left to the eye. Every proposal carries the numbers that produced it and every one
is reversible. Across the whole dataset 1,066 of 2,572 sections were ultimately excluded.

**Stage 04g — artifact masking.** Sections that are fine overall but carry bubbles, antibody
aggregates or fibres inside otherwise good tissue cannot be dropped, only masked. The scale of
the problem was measured before anything was built, in 139 randomly sampled sections, and the
finished run over all 2,572 agrees with that sample closely: **2,226 sections, 86.5 %, carry at
least one bright artifact strictly inside the tissue**, a median of 3 objects on an affected
section and up to 19. The masked area is small in most sections — median 0.79 % of tissue area,
95th percentile 2.2 % — but reaches 7.4 % at worst. For a density per mm² that is a minor
correction; for anything driven by intensity it is not, because these are by construction the
brightest pixels in the section. Andhari et al. (2024) showed artifact-inflated intensities
skewing normalisation badly enough to change cell labels outside the artifact regions, which is
why the mask is applied before normalisation rather than after. Detection runs on DAPI only, so
the mask is the same for both marker passes and cannot encode anything about the marker; the
tissue rim is protected by eroding before seeding and aborting any growth that escapes along the
bright edge.

**Stages 04j and 06f — clipped-pixel censoring.** A pixel pinned at the 16-bit ceiling has lost
its value, and no normalisation recovers it; this is information loss rather than
miscalibration. Two mechanisms are applied and are deliberately distinct. At section level, a
section with 1 % or more of its pixels at the ceiling is set aside — recorded with a flag rather
than deleted, so the decision is visible and reversible. Within the sections that remain,
clipped pixels are marked **right-censored**: the true value is unknown but is at least the
ceiling. That is a different statement from the artifact mask, where the pixel is simply not
measured.

**Censoring applies to the pERK pass only.** It is the AF568 exposure of 1000 ms, against 300 ms
for AF488, whose pixels pin at the ceiling; PCNA clipping has not been measured and no censor
masks exist for it. Every PCNA nucleus therefore carries an unset censoring flag, and the rule
in §12 that treats a censored nucleus as positive by construction is inert for that marker. If
PCNA turns out to clip, this stage has to be run for it before that rule means anything.

The consequence of getting this wrong was measured. Restricted to clip-free sections, two
apparent "staining batches" in the pERK data turn out to be identical, so the entire 1.86-fold
background gap between them is produced by clipped pixels dragging the mean up, not by a gain
difference. Stage 06f later recomputed the per-nucleus censoring flag from the raw clipping
mask rather than from the corrected 8-bit export: dividing by an illumination gain above 1 lifts
a pixel off the ceiling so it stops reading as clipped while its value is exactly as lost, and
the correction field exceeds 1.0 over 54 % of its area, so the earlier mask held only about 46 %
of the clipped pixels. Recomputation does not require re-segmentation, because segmentation runs
on DAPI, which does not clip — raw DAPI clipping was measured at a median of 0.00004 and a
corpus maximum of 0.0007.

For the pERK pass these three mechanisms partition the 1,191 scanned sections into 450
measurable, 268 reformatted but censored out, and 473 excluded; for the PCNA pass, 788 measurable
against 593 excluded, with no censoring for the reason given above. **The first two of those
numbers move**, because re-running the censoring stage on an improved clipping mask reclassifies
sections between them — the counts here are those of 2 September 2026, and the invariant that
does not move is that the three sum to 1,191 with 473 excluded.

Censoring is very unevenly distributed across animals — three animals lose nothing, one loses 65
of 110 — which splits the animals on an axis unrelated to biology and must be checked against
experimental group at unblinding.

# 9. Regional ROI curation

Anatomical regions are placed on sections by an operator, following the workflow of SHARCQ
(Lauridsen et al., 2022) rebuilt for this atlas. SHARCQ itself cannot be used here — it is
MATLAB and is bound to the Allen or Franklin–Paxinos 3D atlases, and no digital atlas exists for
a salmonid — but its division of labour is the right one, and the important thing about it is
what it does *not* automate: its user scrolls to the correct antero-posterior level by eye and
clicks numbered corresponding points between the slice and the atlas. What it automates is the
landmark registration, the warping and the per-region counting.

**Automatic level assignment was implemented and measured to fail, twice.** Silhouette
intersection-over-union between reformatted sections and atlas plates gave correlations between
serial order and best-matching plate of −0.05, 0.00, 0.17 and −0.04 across animals; a
registered-intensity cross-correlation approach after giRAff (Piluso et al., 2024) gave −0.18 to
+0.09 in both polarities. The reason lies in the data rather than the algorithm, and is
documented in the literature: DAPI sections and Nissl-stained atlas plates have poor
morphological correspondence, a limitation AnNoBrainer (Peter et al., 2024) states explicitly
and DeepSlice (Carey et al., 2023) reports as underperformance where neuroanatomical landmarks
are obscured. Silhouette IoU on this dataset tops out near 0.51.

Curation therefore runs in a browser tool. The operator scrubs an atlas plate slider until the
plate matches the section, then clicks matching points alternately on the section and on the
plate. **Three or more pairs determine an affine by least squares; from six pairs the tool
switches to a thin-plate spline** (Bookstein, 1989), and the header states which is live. The
gate is the whole argument: a thin-plate spline interpolates its landmarks exactly and invents
deformation between them, which needs enough real correspondences to be worth having, while an
affine genuinely cannot follow the local distortion that sectioning and mounting introduce.
BigWarp and VisuAlign use a thin-plate spline for exactly this task.

From three pairs onward the atlas region seeds are warped live onto the section in their atlas
colours. That display is the actual deliverable of the stage — it shows immediately whether the
registration is placing Dl, Dm, Vv and POA where they belong, which is the only check that
matters — and the per-landmark residual is shown so a mis-clicked pair is visible as a large
error rather than quietly degrading the fit. The operator then places circular regions of
interest, and additionally places background reference discs on tissue judged to carry no real
signal; §11 explains what those are for. Sections are exported with their plate assignment,
their landmark pairs and residuals, and their ROIs in the normalised 256 px frame.

**An affine and B-spline registration with elastix** (Klein et al., 2010), following BrainJ and
paralleling AnNoBrainer's registration stage, is implemented and was evaluated, including a
variant seeded and constrained by the operator's own landmarks. It registers the plate as fixed
and the section as moving, so that the resulting transform carries atlas seed points into
section space rather than the reverse. **It is not on the data path.** Its outputs are quality
control only and nothing downstream reads them; the region seeds that reach the measurements
come from the curator's landmark transform.

**The curation queue is ordered so that stopping early still yields a usable dataset.** Worked
through in animal order, curating half the queue would finish five animals entirely and leave
six untouched, which supports no comparison at all. The worklist instead advances every animal
in proportion to the length of its own series, so after any number of sections every animal sits
at about the same fraction of its series; and within an animal it uses farthest-point ordering
over section index, taking the two ends first and then repeatedly whichever section is furthest
from everything already taken, so the first handful span the brain rather than clustering at one
end. The sections are the same either way; what changes is what a prefix of the queue is worth.

# 10. ROI geometry

The operator draws regions of interest on a 256 px normalised frame in which one pixel spans
about 25 µm, while a nucleus is 7 µm. Nothing can be counted there. Detection has to read the
CZI at its native 0.65 µm/px, so every ROI has to come back out of the normalised frame and land
on real slide pixels.

Stage 05a inverts the reformat. That transformation composed six operations — overview PNG,
resize into a square grid, rotate, flip, crop to the tissue bounding box, pad square, resize to
256 px — and every one of them is affine, so the composition is affine and reduces to a single
2 × 3 matrix per section. Rather than expand that algebra by hand, which offers six chances to
transpose an axis and a wrong answer that still looks plausible, the matrix is obtained by
evaluating the composition at three points and reading off its columns. The reformat function
itself is imported and re-run rather than reimplemented, so the same Pillow resize and SciPy
rotation that built the curation frame produce the parameters being inverted.

A verification mode checks the matrix against the real thing by pushing two coordinate planes
through the same rotate, flip, crop, pad and resize and comparing with what the matrix predicts,
over every pixel of the frame. Agreement is 0.04 to 0.15 px, and that residual is Pillow's own
downscale filter rather than an error in the inverse: the same filter deviates from an ideal
centre-aligned mapping by 0.12 px on a plain linear ramp with no composition involved at all.

One consequence is worth stating because it affects the reported areas: a circle drawn in the
curator is an **ellipse** on the slide, because the composed transform is not isotropic. ROI
area is therefore computed from the two semi-axes the affine implies, never from πr² in curator
pixels. The stage writes one affine matrix per section and one bounding box in native CZI pixels
per ROI, refusing sections whose geometry cannot be reconstructed rather than guessing at them.

# 11. Nuclei detection and marker measurement

This is the quantification step. For each region of interest, stage 05c reads the corresponding
box out of the CZI at native 0.65 µm/px with pylibCZIrw, one read per channel, requesting only
that box — a few hundred kilobytes out of a 1–2 GB file, which is what makes several thousand
ROIs tractable. There is no downsampling and no pyramid-level snapping.

**Nuclei are segmented on DAPI and never on the marker.** Detecting on the marker channel would
define the number of marker-positive cells by the threshold twice over — once to find the object
and again to call it positive — so the count and the cut could never be varied independently.
The counterstain finds the objects; the marker is measured afterwards; positivity is decided
last, in a later stage, and can be changed without re-reading a single CZI.

**Normalisation.** The DAPI crop is normalised with csbdeep (Weigert et al., 2018) by mapping
its 1st percentile to 0 and its 99.8th to 1, linearly, leaving values outside that range where
they fall. Percentiles rather than min and max, because one hot or dead pixel would otherwise
set the whole scale; and per ROI rather than per section or per dataset, because the pretrained
network expects input in roughly this range and a disc in dim tissue and a disc in bright tissue
must both arrive looking like that. This is deliberately not the frozen dataset-wide display
range of §4, which exists for visual comparison. **The marker channel is never normalised**,
because it is never segmented on; its raw 16-bit values go straight into the output table, which
is what makes the positivity cut a decision about real intensities rather than about a
rescaling.

**Segmentation.** Nuclei are segmented with StarDist (Schmidt et al., 2018) running on
TensorFlow (Abadi et al., 2016), using the pretrained `2D_versatile_fluo` model without
retraining or per-dataset tuning. StarDist predicts, for every pixel, an object probability and
the distances to the object boundary along a fixed set of radial directions — a star-convex
polygon — and non-maximum suppression keeps the best non-overlapping polygons. The decisive
property for this dataset is that each nucleus is proposed as a whole shape, so two nuclei in
contact become two polygons rather than one region a watershed has to guess how to split. The
model's own parameters, read from its shipped configuration, are 32 rays per object, a U-Net
backbone of depth 3, a 2 × 2 prediction grid, single-channel input, 256 × 256 training patches,
a probability threshold of 0.479 and a non-maximum-suppression threshold of 0.3. Both thresholds
are the model's optimised defaults and are not overridden. Large ROIs are processed in tiles,
with the tile count chosen as the smallest square grid keeping each tile near 300,000 pixels;
tiling changes runtime by more than an order of magnitude and does not change the result.

**The choice of StarDist over threshold-and-watershed is a bias argument, not a preference.**
Watershed under-segments where nuclei touch, and Vv, Vd and POA are periventricular. The error
would therefore be worst in exactly those regions and mild in Dm and Dl, and a region-correlated
counting bias survives into the results looking like an anatomical finding.

**Measurement.** Object measurement uses `regionprops` from scikit-image (van der Walt et al.,
2014), called twice on the same label image with two different intensity images — once with the
marker channel and once with the counterstain — so that the DAPI and marker statistics describe
exactly the same pixels of exactly the same nucleus. For each nucleus the table records its
centroid in both CZI stage pixels and normalised section coordinates, its area in µm² from the
pixel count and the known pixel size, its equivalent circular diameter computed from that area,
the mean DAPI intensity, and the mean, median and 90th percentile of the marker. Intensities are
taken from the pixels under the region's **mask**, not its bounding box: a nucleus is not a
rectangle, and averaging over the box would mix in whatever sits in the corners. Each nucleus is
also flagged for whether it falls under an artifact mask or a censored region from §8.

**Background reference discs are measured identically to real ROIs** — same read, same
segmentation, same statistics — and are distinguished only by a kind label. Two things come out
of that. The first is a per-section reference level that is measured rather than assumed. The
second is a false-positive rate, because the same detector is run over tissue the operator
called empty. **A background disc is not a negative control**: the primary antibody is on that
tissue too, so it measures non-specific binding plus genuine low-level signal, and the
distinction matters for what can be claimed (§15).

The stage is resumable per section and writes atomically, so an interrupted run costs one
section rather than the whole run. Optional overlay images are written per ROI showing the DAPI
crop with nucleus boundaries drawn, counted objects in one colour and objects found outside the
disc in another; nuclear diameter says the segmentation is finding objects of the right size,
but only the overlay says they are in the right places.

**The resulting per-nucleus table is the artefact everything downstream depends on.** Everything
after it is arithmetic on a table, so changing one's mind about where positivity falls costs a
re-run of the next stage rather than a re-read of the CZI scenes.

# 12. Per-ROI quantification

Stage 06a reduces the per-nucleus table to one row per region of interest. It reads no group
label and is still blind.

**Where the positivity cut comes from.** Each section's own background discs give a robust upper
bound on what the detector sees where the operator judged there to be no signal:

$$\text{cut} = \operatorname{median}(\text{background}) + 3 \times 1.4826 \times \operatorname{MAD}(\text{background})$$

The scale factor 1.4826 makes the median absolute deviation a consistent estimator of the
standard deviation under normality (Rousseeuw and Croux, 1993). The cut is computed **per
section**, because this is a high-baseline marker and the background level moves from section to
section.

**A spread and not a percentile, deliberately.** A percentile cut would fix the false-positive
rate by construction and destroy the only independent check available. With a spread-based cut,
how many background nuclei land above it is a *measurement*. On this dataset that measurement is
a median false-positive rate of 2.10 % across the 130 sections measured so far — and, the number that decides whether
positivity is usable at all, it is not correlated with treatment group (2.2 % control against
2.0 % exercise). Pooled positivity inside the anatomical ROIs is 13.2 % against that — 82,016 of 619,300 nuclei — a
5.9-fold separation.

**Two densities are reported side by side.** One counts every DAPI nucleus; the other counts the
subset above that section's own cut. Both are divided by the ROI area computed from the elliptic
semi-axes of §10.

**A censored nucleus is counted as positive by construction.** Its true intensity is unknown but
is at least the 16-bit ceiling, which is above any cut, so calling it anything else would be a
statement the data does not support. On this dataset the rule is inert: of the 892,025 nuclei
measured so far, **none** falls under a censored pixel, because §8 removed the sections where
clipping was severe and what survives does not reach the curated ROIs. The rule is stated
because it governs, not because it acted.

**Abercrombie correction.** These are single-plane images of a 14 µm section, so what is counted
is nuclear *profiles*, not nuclei: a nucleus straddling the cut face appears in the section it is
cut into, and since sections here are consecutive, the same nucleus can appear in two of them.
The correction (Abercrombie, 1946) is

$$N = n \times \frac{T}{T + h}$$

with $T$ the section thickness, 14 µm, and $h$ the mean diameter of the counted object along the
axis perpendicular to the section. **$h$ is measured, not assumed**: it is taken per marker and
region from the DAPI segmentation itself, because the correction is sensitive to it and using an
assumed value would put an unmeasured constant into every density. Measured values of $h$ range
from 7.8 to 9.4 µm across the twelve marker-region combinations, giving correction factors of
0.597 to 0.642. That the segmentation independently returns a diameter of this order, from a
model told nothing about expected size, is also the check that it is finding nuclei: the
configuration assumed 7.0 µm on separate grounds.

Abercrombie assumes spherical, randomly positioned objects and applies no lost-caps correction.
The unbiased alternative is the optical or physical disector, which requires z-stacks this
dataset does not have. Raw and corrected counts are therefore both reported, and which is which
is stated. Because $h$ is similar between groups, the correction acts close to a constant
multiplier and barely moves the group contrast; what it changes is whether a density can be
quoted as cells per mm² at all. It is a reporting fix, not a statistical one.

Alongside the per-ROI table the stage writes a per-section detector specificity table carrying
the background nucleus count, the background area, the false-positive count and rate, the
background level and spread, and the positivity cut — so the cut applied to each section and the
evidence for it travel together.

**One stage owns every per-ROI number.** Later stages group and format this output; they do not
re-derive it. They used to, and the two implementations had drifted — the Abercrombie $h$ was
computed per marker and region in one and per animal and region in the other, with nothing
comparing them. A regression test now does.

# 13. Blinding

No stage described in this document reads the treatment group. Every intermediate file is keyed
by animal identifier alone, and the group key is first joined at stage 06b.

Two stages read the key earlier, both deliberately, both documented in the configuration, and
neither in a way that touches a measurement. The detection stage uses it to choose the *order*
in which sections are measured, so that any prefix of a long run is a balanced dataset; an
option restores blind ordering, and the finished file is identical either way. The curation tool
uses it to lay out a slide deck by treatment, which is not something a group comparison figure
can be built without. Leaving the key empty in the configuration disables both.

# 14. What follows

Beyond the scope of this document, the per-ROI table is joined to the experimental sampling
workbook (the unblinding step), exported as per-sample and per-slide workbooks, and plotted in R
(R Core Team, 2026) with ggplot2 (Wickham, 2016). The model is chosen on whether an animal
contributes more than one row: a linear model where it does not, and a mixed model fitted with
lme4 (Bates et al., 2015) and tested with lmerTest (Kuznetsova et al., 2017) where it does,
followed by estimated marginal means and multiplicity-adjusted contrasts (Hothorn et al.,
2008), and a figure deck. A refresh loop rebuilds the workbooks and every figure while
detection is still running, once per measured marker.

# 15. Limitations

**No no-primary controls exist for this dataset.** Non-specific secondary binding therefore
cannot be separated from genuine low-level specific signal, and **absolute positivity rates are
not defensible**: "X % of cells in region R are marker-positive" is not a claim these data
support. Relative comparisons between groups at matched anatomical levels are, because the
non-specific component is shared. Three internal references stand in for the missing control —
optical zero from off-tissue glass, a tissue-negative floor from nuclei-poor fibre tracts within
the same section, and object-level annulus background — but none of them is a no-primary
control.

**Tiles are JPEG-XR compressed**, typically lossy, and this was fixed at acquisition.

**No shading correction was applied at acquisition and tiles were never blended**, so the
illumination profile repeats at the tile pitch across every section. It is corrected as
described in §5, but a correction estimated from the data is not the same as a reference
acquired on the instrument.

**Clipping is unevenly distributed across animals**, which splits the animals on an axis
unrelated to biology. Two animals yield too few measurable sections to support a per-animal
estimate at all. This must be checked against experimental group at unblinding.

**The atlas covers the telencephalon and preoptic area only.** Most of its plates carry no
region identification, so extending regional quantification caudally requires labelling that
does not yet exist.

**Counts are Abercrombie-corrected, not stereological.** See §12.

**Automatic atlas-level assignment is not solved here.** It is done by hand, and the level
assigned to a section is an expert judgement. That is worth stating plainly, because
expert-versus-expert agreement on brain-section annotation has been measured at Cohen's
κ = 0.17 (Peter et al., 2024) — which is the argument for the propose-then-adjudicate design
used throughout this pipeline, and against treating any single expert pass as ground truth.

# 16. Software

Every stage is written in Python and rests on the standard numerical stack: NumPy
(Harris et al., 2020) for arrays and the affine algebra, SciPy (Virtanen et al., 2020) for
filtering, rotation and optimal assignment, pandas (McKinney, 2010) for the tabular joins, and
matplotlib (Hunter, 2007) for every figure including Figure 1.

Versions are those installed in the analysis environment and are read from it rather than
transcribed.

<!-- BEGIN software-versions -->

| Software | Version | What it does here |
|---|---|---|
| Python | 3.13.15 | the interpreter every stage runs under |
| pylibCZIrw | 6.1.0 | reads every CZI pixel whose value reaches a result |
| czifile | 2026.8.16 | raw per-tile pixels, for instrument characterisation only |
| imagecodecs | 2026.8.16 | JPEG-XR decoding, required by czifile |
| NumPy | 2.5.2 | arrays, the affine algebra, the mask lookups |
| SciPy | 1.18.1 | rotation, filtering, optimal assignment |
| pandas | 3.0.5 | tabular joins in the dataset stages |
| Pillow | 12.3.0 | image resizing in the reformat and its inverse |
| scikit-image | 0.26.0 | per-object measurement (regionprops) |
| StarDist | 0.9.2 | nucleus segmentation |
| csbdeep | 0.8.2 | percentile intensity normalisation before segmentation |
| TensorFlow | 2.21.0 | the neural-network backend StarDist runs on |
| Keras | 3.15.1 | model API above TensorFlow |
| PyMuPDF | 1.28.2 | atlas plate and region-seed extraction from the PDF |
| itk-elastix | 0.25.4 | affine and B-spline registration (assessed, QC only) |
| OpenCV | 5.0.0.93 | connected components and morphology |
| tifffile | 2026.8.23 | TIFF interchange with Fiji |
| matplotlib | 3.11.1 | QC figures and the workflow diagram |
| openpyxl | 3.1.5 | the output workbooks |
| PySide6 | 6.11.2 | the desktop application shell |
| R | 4.6.0 | the statistics and figure layer |
| ggplot2 (R) | 4.0.3 | the figures |
| ggtext (R) | 0.1.2 | rich-text axis and panel labels |
| lme4 (R) | 2.0.1 | mixed models where an animal contributes more than one row |
| lmerTest (R) | 3.2.1 | degrees of freedom and p-values for those models |
| emmeans (R) | 2.0.3 | estimated marginal means and contrasts |
| multcomp (R) | 1.4.30 | multiplicity adjustment across contrasts |
| officer (R) | 0.7.4 | writing the figure deck |
| readxl (R) | 1.4.5 | reading the workbooks back in |

<!-- END software-versions -->

# 17. References

## Methods and prior work

Abercrombie M (1946). Estimation of nuclear population from microtome sections. *Anatomical
Record* 94(2):239–247.

Andhari MD, Rinaldi G, Nazari P, Vets J, Shankar G, Dubroja N, Ostyn T, Vanmechelen M, Decraene
B, Arnould A, Mestdagh W, De Moor B, De Smet F, Bosisio F, Antoranz A (2024). Quality control of
immunofluorescence images using artificial intelligence. *Cell Reports Physical Science*
5(10):102220. https://doi.org/10.1016/j.xcrp.2024.102220

Bookstein FL (1989). Principal warps: thin-plate splines and the decomposition of deformations.
*IEEE Transactions on Pattern Analysis and Machine Intelligence* 11(6):567–585.

Carey H, Pegios M, Martin L, Saleeba C, Turner AJ, Everett NA, Bjerke IE, Puchades MA, Bjaalie
JG, McMullan S (2023). DeepSlice: rapid fully automatic registration of mouse brain imaging to a
volumetric atlas. *Nature Communications* 14:5884. https://doi.org/10.1038/s41467-023-41645-4

Crouse DF (2016). On implementing 2D rectangular assignment algorithms. *IEEE Transactions on
Aerospace and Electronic Systems* 52(4):1679–1696.

Hammond L. *Automated Imaging and BrainJ Analysis Pipeline*, guide v9.3. Cellular Imaging
Platform. ImageJ/Fiji plugin.

Klein S, Staring M, Murphy K, Viergever MA, Pluim JPW (2010). elastix: a toolbox for
intensity-based medical image registration. *IEEE Transactions on Medical Imaging* 29(1):196–205.

Kuhn HW (1955). The Hungarian method for the assignment problem. *Naval Research Logistics
Quarterly* 2(1–2):83–97.

Lauridsen K, Ly A, Prévost ED, McNulty C, McGovern DJ, Tay JW, Dragavon J, Root DH (2022). A
semi-automated workflow for brain slice histology alignment, registration, and cell
quantification (SHARCQ). *eNeuro* 9(2):ENEURO.0483-21.2022.

Nieuwenhuys R (1982). An overview of the organization of the brain of actinopterygian fishes.
*American Zoologist* 22(2):287–310.

Otsu N (1979). A threshold selection method from gray-level histograms. *IEEE Transactions on
Systems, Man, and Cybernetics* 9(1):62–66.

Peter R, Hrobar P, Navratil J, Vagenknecht M, Soukup J, Tsuji K, Barrezueta NX, Stoll AC,
Gentzel RC, Sugam JA, Marcus J, Bitton DA (2024). AnNoBrainer, an automated annotation of mouse
brain images using deep learning. *Neuroinformatics* 22(4):719–730.
https://doi.org/10.1007/s12021-024-09679-1

Piluso S, Souedet N, Jan C, Hérard A-S, et al. (2024). giRAff: an automated atlas segmentation
tool adapted to single histological slices. *Frontiers in Neuroscience* 17:1230814.

Rousseeuw PJ, Croux C (1993). Alternatives to the median absolute deviation. *Journal of the
American Statistical Association* 88(424):1273–1283.

Schmidt U, Weigert M, Broaddus C, Myers G (2018). Cell detection with star-convex polygons.
*Medical Image Computing and Computer Assisted Intervention (MICCAI) 2018*, LNCS 11071:265–273.

Weigert M, Schmidt U, Boothe T, Müller A, Dibrov A, Jain A, Wilhelm B, Schmidt D, Broaddus C,
Culley S, Rocha-Martins M, Segovia-Miranda F, Norden C, Henriques R, Zerial M, Solimena M, Rink
J, Tomancak P, Royer L, Jug F, Myers EW (2018). Content-aware image restoration: pushing the
limits of fluorescence microscopy. *Nature Methods* 15:1090–1097.

Wullimann MF, Rupp B, Reichert H (1996). *Neuroanatomy of the Zebrafish Brain: A Topological
Atlas*. Birkhäuser Verlag, Basel.

## Software

Abadi M, Agarwal A, Barham P, et al. (2016). TensorFlow: large-scale machine learning on
heterogeneous distributed systems. arXiv:1603.04467.

Bates D, Mächler M, Bolker B, Walker S (2015). Fitting linear mixed-effects models using lme4.
*Journal of Statistical Software* 67(1):1–48.

Harris CR, Millman KJ, van der Walt SJ, et al. (2020). Array programming with NumPy. *Nature*
585:357–362.

Hothorn T, Bretz F, Westfall P (2008). Simultaneous inference in general parametric models.
*Biometrical Journal* 50(3):346–363.

Hunter JD (2007). Matplotlib: a 2D graphics environment. *Computing in Science & Engineering*
9(3):90–95.

Kuznetsova A, Brockhoff PB, Christensen RHB (2017). lmerTest package: tests in linear mixed
effects models. *Journal of Statistical Software* 82(13):1–26.

Linkert M, Rueden CT, Allan C, et al. (2010). Metadata matters: access to image data in the real
world. *Journal of Cell Biology* 189(5):777–782.

McKinney W (2010). Data structures for statistical computing in Python. *Proceedings of the 9th
Python in Science Conference*, 56–61.

R Core Team (2026). *R: A Language and Environment for Statistical Computing*. R Foundation for
Statistical Computing, Vienna, Austria.

Schindelin J, Arganda-Carreras I, Frise E, et al. (2012). Fiji: an open-source platform for
biological-image analysis. *Nature Methods* 9:676–682.

van der Walt S, Schönberger JL, Nunez-Iglesias J, Boulogne F, Warner JD, Yager N, Gouillart E,
Yu T (2014). scikit-image: image processing in Python. *PeerJ* 2:e453.

Virtanen P, Gommers R, Oliphant TE, et al. (2020). SciPy 1.0: fundamental algorithms for
scientific computing in Python. *Nature Methods* 17:261–272.

Wickham H (2016). *ggplot2: Elegant Graphics for Data Analysis*. Springer-Verlag, New York.

*pylibCZIrw*: a Python wrapper around the libCZI library for reading and writing CZI. Carl Zeiss
Microscopy GmbH. https://pypi.org/project/pylibCZIrw/

*czifile*: read Carl Zeiss Image (CZI) files. Gohlke C. https://pypi.org/project/czifile/

*PyMuPDF*: Python bindings for the MuPDF library. Artifex Software.
https://pymupdf.readthedocs.io/
