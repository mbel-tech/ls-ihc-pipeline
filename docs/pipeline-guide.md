---
title: "A guide to the LS whole-brain IHC pipeline"
subtitle: "What happens to a brain section, step by step"
---

# Before you start

## What this document is

This is a walkthrough. It follows a single brain section from the moment it is scanned to the
moment it becomes a number in a spreadsheet, and it explains every step in between in plain
language. It assumes you know the biology and nothing at all about image file formats or Python.

It is not the only document, and it is deliberately not the others:

| If you want to know | Read |
|---|---|
| what happens, and why, in plain language | **this document** |
| the same thing written as a paper's Methods section, with citations | `docs/pipeline-methods.md` |
| how far the pipeline has actually been run, and the current counts | `docs/pipeline-methods.md` §1.1 |
| how to install it, run it, or change it | `README.md` |

Under most steps there is a short block headed **In the code**. That block exists so you do not
have to take the description on trust: it names the file that does the work and quotes the line
that does it. You can skip every one of those blocks and the document still reads straight
through. They are evidence, not instructions.

## No counts in this document

The pipeline is still running, so counts grow between runs. Any figure printed here would be
wrong by the time you read it, and a copy of this file mailed last month would quietly contradict
the repository. So this guide carries **no counts at all** — it says "most sections reach the
curator" rather than a number. `docs/pipeline-methods.md` §1.1 states how far the pipeline has
been run, and a script checks those figures against the actual data.

Fixed properties of the instrument are not counts and do appear: sections are 14 µm, the scanner
samples at 0.65 µm per pixel through a 10×/0.45 objective, overviews are written at 5.20 µm per
pixel, camera samples are 16-bit, and tiles are 2040 px square on an 1836 px pitch.

## The experiment, in a paragraph

Brains from twelve juvenile salmon were sectioned transversely at 14 µm and mounted as
consecutive series. Each slide was immunolabelled twice, in two separate passes over the same
physical tissue: once for phosphorylated ERK (pERK), a marker of recent neural activity,
visualised with Alexa Fluor 568; and once for PCNA, a marker of cell proliferation, visualised
with Alexa Fluor 488. Both passes were counterstained with DAPI, which stains every cell nucleus
regardless of either marker. The slides were scanned on a Zeiss slide scanner.

The question is where in the brain each marker is elevated, and whether that differs between
treatment groups. The obstacle is volume: there are far more sections than anyone can open by
hand, so the pipeline exists to survey all of them, find where the signal is, and reduce it to
per-region densities.

## Words this guide uses

Several of these are ordinary words used in a narrow sense. They are worth fixing before Part 1.

**Slide** — the physical glass. **Scan** or **pass** — one trip through the scanner for one
marker; each slide was scanned twice. **Scene** — one region the scanner operator drew a box
around; in practice one scene is one brain section. **Section** — one 14 µm slice of tissue.

**Channel** — one colour recorded by the camera. Every scan has two: DAPI, and one marker.
**Marker** — pERK or PCNA, the thing being measured. **Counterstain** — DAPI, which is not being
measured but is what every shape is found on.

**Tile** — the scanner cannot see a whole section at once, so it photographs it as a grid of
overlapping squares and stitches them. **CZI** — Zeiss's file format, holding all of the above
for one slide: a couple of gigabytes, several sections, both channels, every tile.

**Overview** — a small, quick picture of one section, made once so nothing has to reopen the
giant file to look at it. **Reformat** — the normalised picture of a section: debris removed,
rotated upright, centred, and resized to a fixed 256-pixel square. **ROI** — region of interest,
an anatomical area an operator outlined on a section. **Plate** — one labelled page of the brain
atlas; assigning a plate to a section says how far back in the brain it is.

**Blinding** — no step is allowed to know which treatment group an animal belongs to until the
measurements are finished. **Operator** — a person, making a decision the program deliberately
does not make.

## The map

![**Figure 1. The pipeline.** Steps run top to bottom. This guide walks the same path.](img/workflow.png)

Three things in the figure carry meaning and none of them are decoration.

**Fill colour says which software read the pixels.** Blue is pylibCZIrw, Zeiss's own library; the
rule throughout is that if a number derived from a pixel ends up in a figure or a table, that
pixel was read by pylibCZIrw. Yellow is czifile, a third-party library used *only* to characterise
the instrument — how the lamp illuminates a tile, where the tile edges fall — and never to measure
tissue. Grey means no pixel was decoded at all: the step is working on headers, tables or
coordinates.

**A bold red outline is a step where a person decides.** There are four of them, and they are the
reason the whole middle of the pipeline cannot simply be run as a batch job.

**The dashed red line is where blinding ends.** Everything above it is keyed by animal
identifier alone. The treatment group is first read below it.

The right-hand column names the file each step leaves behind. One of them is in red:
`roi_nuclei.csv`, the table of individual nuclei. Everything after that file is arithmetic on a
table, which means a change of mind about what counts as positive costs a re-run of one cheap
step rather than a re-read of every scan.

## Three ideas that shape everything

**One library owns the measured pixels.** Three ways of reading a CZI were tested. The fastest
was not chosen. pylibCZIrw is slower per section but is maintained by Zeiss, whereas the fast
third-party option reimplements a file format specification the vendor calls confidential. For
data that ends up in a paper, provenance beat a fraction of a second per section. The third
option, Bio-Formats, was retired from the data path outright after it silently exported a batch
of sections as single tiles instead of whole sections — producing plausible-looking images and no
error at all. Every step records which library it used, in the output, so this is auditable rather
than remembered.

**The program proposes and a person decides.** Wherever a judgement is genuinely difficult, the
pipeline narrows the field and hands it to an operator rather than guessing. This is not
timidity: automatic assignment of atlas level was implemented twice and measured to fail on these
data, and expert-versus-expert agreement on this kind of annotation has been measured to be poor
enough that treating any single automatic pass as ground truth would be indefensible.

**Nothing is deleted and everything is reversible.** A section that is set aside is recorded with
a flag saying so and why, not removed. Every long step can be interrupted and resumed without
losing finished work.


## How to read a stage entry

The pipeline calls its steps by number — 00, 01, 04j, 05c — and this guide uses the same names, so
a step here is the same step on the app's sidebar and in the code. Each entry gives the step's
name, then a line in italics saying what runs and what it leaves behind, then plain paragraphs,
and sometimes an **In the code** block.

The figure divides the pipeline into five bands. This guide uses a slightly finer six-part
division — the one the application's sidebar uses — which splits instrument characterisation and
the atlas into parts of their own, because each is a self-contained argument worth reading in one
go. The order of the steps is identical.

\newpage

# Part 1 — Ingest and QC

Nothing is measured in this part. Its job is to establish that the files are what we think they
are, that we know which section is which, and that the two passes have been matched to the same
piece of tissue. If any of that is wrong, everything downstream is wrong in a way that is very
hard to see later.

One picture of each section is also produced here — the *overview* — and it matters much more than
a preview normally would. Every tissue outline, every area, and every exclusion decision in the
rest of the pipeline is computed on these overviews rather than on the original scans, because
reopening the scans repeatedly is not affordable. The overview is not a convenience copy; it is
the working image.

## 00  Read slide headers {#stage-manifest}

*`scripts/00_manifest.py` → `manifest/manifest_files.csv`, `manifest/manifest_scenes.csv`*

Every scan file is opened and its header read — the settings, the channels, the exposures, the list
of scenes and where each sits on the glass — without decoding a single pixel. This is fast because
it touches only the file's index, and it produces the two tables the whole pipeline is built on:
one row per file, one row per scanned section.

It also solves a problem that is easy to miss. **Nothing in the file says how the sections were
laid out on the slide.** The scanner records where each scan region sits in millimetres, but not
whether the person mounting the slide worked left to right, top to bottom, in columns, or in the
order the scanner happened to visit them. Serial order along the brain is the whole basis of "this
section is rostral to that one", so guessing would silently reorder every animal's series.

Instead the step reconstructs the slide grid from the stage coordinates and renders the slide five
times, once under each plausible mounting convention, with the implied section number printed on
each. A person looks at those pictures once and says which is right; the answer is recorded in the
configuration and every later step reads it from there. For this dataset the answer is scan order —
the sections were scanned in the order they sit in the brain.

> **In the code** — `scripts/00_manifest.py`
>
> The rule is stated in the module docstring, and enforced by there being no default:
>
> ```
> Nothing downstream may assume a mounting convention until the user picks one.
> ```
>
> ```python
> ORDER_CONVENTION = CONFIG["section_order_convention"]
> ```
>
> Reading it from the configuration rather than hard-coding it is what keeps the choice visible.

## 00b  Verify extraction {#stage-verify}

*`scripts/00b_verify_extraction.py` → `qc/extraction_status.csv`*

Part of the dataset arrived as archives. This checks every extracted file against the archive's own
directory, so a file that was truncated or half-written is caught here rather than quietly measured
later. With `--crc` it verifies the contents rather than just the size.

## 00d  CZI self-test {#stage-czi_selftest}

*`scripts/00d_czi_selftest.py` → `qc/czi_selftest.csv`*

Every step that reads a pixel makes four assumptions about the scan files. This step checks all four
and writes down the answers, which is the honest response to "how do you know the files are what you
think they are".

Two of the four are **structural** — they are about what the file actually contains — and failing
them stops the pipeline: that the sensor's bit depth is recorded correctly, and that the downscaled
preview copies inside the file share an origin with the full-resolution image. The second matters
because if those coordinate frames have drifted apart, a region measured at low resolution lands
somewhere else at full resolution, and the pictures still look entirely plausible.

The other two — how the scan regions overlap, and how many downscaled levels are stored — are
**reported but not enforced**, because they are properties of this dataset rather than requirements.
Gating on them would let a cosmetic quirk block a run for no reason.

## 01  Export section overviews {#stage-overviews}

*`scripts/01_overviews.py` → `overviews/`, `qc/focus.csv`*

Each section is written out once as a manageable picture, at exactly 5.20 µm per pixel, together
with per-section quality measurements: how much tissue there is, how sharply it is focused, and how
many pixels the camera pinned at its maximum.

Three details here are load-bearing.

**The scale is exact, not approximate.** Scan files store a pyramid of pre-shrunk copies — full
size, half, quarter, and so on — and the quick way to get a small picture is to grab the nearest
one. But "nearest" differs from file to file, so the actual pixel size would differ too, and any
area measured from those pictures would be measuring the choice of pyramid level rather than the
tissue. When that was done, apparent tissue area within a single brain ranged over two orders of
magnitude. Asking instead for a continuous zoom gives every section the same scale, so an area in
square millimetres means the same thing everywhere.

**The brightness range is computed once and frozen across the whole dataset.** The obvious
alternative — brightening each section to fill its own range — would make a faint section look
exactly as bright as a strong one, destroying the only thing the overviews exist for. With the range
frozen, a difference in brightness between two sections is a real difference in signal.

**That range is computed from tissue pixels only.** On many pERK sections the background *outside*
the tissue is brighter than the brain itself. Sampling the whole frame therefore pinned the top of
the range at the sensor maximum and left the actual tissue rendering almost black.

Finding the tissue is itself not trivial. These channels are extremely lopsided — DAPI runs a median
around 500 against a 99.9th percentile in the tens of thousands — and the standard automatic
threshold chases that bright tail and returns a value above almost every pixel, marking the section
as empty. Taking the logarithm first, thresholding there, and mapping the answer back gives a mask
of the actual section. The same log-space threshold is used for every tissue outline in the pipeline.

> **In the code** — `scripts/01_overviews.py`
>
> The tissue threshold, in one line:
>
> ```python
> return float(np.expm1(otsu(np.log1p(positive))))
> ```
>
> `log1p` compresses the bright tail, `otsu` finds the split, `expm1` converts the answer back to
> real intensities. And the scale is asked for as a continuous zoom rather than a pyramid level:
>
> ```python
> plane={"C": channel}, zoom=zoom
> ```

## 01d  Contact sheets and gallery {#stage-contactsheets}

*`scripts/01d_contactsheets.py` → `contactsheets/`*

The overviews are assembled into per-animal montages in rostro-caudal order, plus a browsable
gallery. This is the first time anybody sees the whole dataset at once. Because the brightness range
was frozen in the previous step, differences across a sheet are real. Sections flagged by quality
control are marked rather than dropped, so a gap in a series is never silently invented.

## 02  Pair the two marker passes {#stage-pair}

*`scripts/02_pair_passes.py` → `pairs.csv`*

Both passes imaged the same physical slides, but the scan regions were drawn fresh for each pass —
one slide has ten scan regions in one pass and twelve in the other — so scene numbers do not
correspond between them. Matching therefore goes through position on the glass rather than through
numbering.

The slide sits in a holder that repositions it almost, but not exactly, the same way each time, so
the second pass is offset from the first by a small shift. That shift is recovered by voting: every
possible pairing proposes the shift it would imply, and the shift proposed by the most pairings
wins. Since sections sit millimetres apart and the reload offset is far smaller, the vote is
unambiguous.

Once the offset is known, the pairing is solved as a whole rather than section by section, so one
badly matched section cannot cascade into its neighbours. Sections that find no partner are listed
explicitly rather than dropped. This step produces the section identity every later step keys on.

> **In the code** — `scripts/02_pair_passes.py`
>
> ```python
> rows_i, cols_i = linear_sum_assignment(cost)
> ```
>
> That is the optimal-assignment solver: it minimises total cost across all pairings at once, rather
> than giving each section its nearest partner in turn.

## 00c  Infer marker identity {#stage-channel_identity}

*`scripts/00c_channel_identity.py` → `qc/channel_identity/`*

The scan file records *fluorophores* — AF568, AF488 — but not which antibody each one carried.
Nothing in the metadata says which channel is pERK and which is PCNA, and getting it backwards would
invert every result.

Rather than trust a filename, this step separates the two markers by how their signal is *arranged*,
using two measures that need neither marker named in advance. The first is clustering: how close
labelled objects sit to their neighbours, compared with what you would expect if the same number of
objects were scattered at random over the same tissue. The second is edge affinity: how close
objects sit to the tissue boundary. Proliferating cells sit in the germinal zones lining the
ventricles, so PCNA scores low on both. Activity-dependent signal is spread through the parenchyma,
so pERK scores near the random expectation.

The step reports its call and writes the evidence, but **does not commit it**. The identification
was confirmed by the operator and recorded in the configuration — a machine-checkable argument that
a person then signs off, rather than an assumption nobody revisits.

\newpage

# Part 2 — Instrument characterisation

This whole part describes the microscope rather than the fish.

The scanner photographs a section as a grid of overlapping square tiles and stitches them together.
No shading reference was acquired at the time of scanning, and the tiles were never blended, so the
lamp's uneven illumination across a single tile repeats across every section like wallpaper. Left
alone, a fixed brightness threshold finds materially more objects near tile centres than near tile
edges — a pattern that has nothing to do with the brain but would appear in the results looking like
anatomy.

Two boundaries are worth stating before the steps. **No number measured in this part reaches a
result.** And this is the only part where the fast third-party reader is allowed to decode pixels,
because it is the only one that can hand back the individual raw tiles this work needs; Zeiss's own
library deliberately hides them.

## 01e  Tile geometry from the CZI directory {#stage-tile_geometry}

*`scripts/01e_tile_geometry.py` → `qc/tile_geometry.csv`*

Before the illumination can be folded at the tile pitch, the pitch has to be known exactly. It is
read straight out of the file's own index of tiles — 2040-pixel tiles on an 1836-pixel pitch, a
nominal ten per cent overlap — without decoding an image.

Reading it rather than measuring it matters. Estimating the same quantity from the picture, by
looking for the repeating pattern's frequency, came out one to three per cent off, which sounds
small but accumulates to a fifth of a tile across a whole section — enough to smear the correction
into uselessness.

## 01b  Pick the tile-field sample {#stage-pick_sections}

*`scripts/01b_pick_sections.py --n 96 --scenes-per-file 4` → `qc/tilefield_sample.csv`*

Chooses the sample of sections the illumination measurement will use, spread across files and
animals so that no single brain dominates it.

## 01b  Export the sample at 2.6 µm/px (Fiji) {#stage-fiji_export}

*`scripts/01b_export_section.groovy` → `qc/test_sections/`*

Exports the sampled sections at higher resolution for the illumination build. This is the one step
that runs in Fiji rather than Python, and the one step the desktop application does not drive. It is
a one-time characterisation: it has already been done for this dataset and only needs repeating for
a new one.

## 01f  Build the tile-correction field {#stage-tilefield_build}

*`scripts/01f_tilefield.py build` → `qc/flatfield/tilefield_c0.npy`, `tilefield_c1.npy`*

This is the central argument of the part.

The obvious way to correct uneven illumination is to correct each raw tile and re-stitch the
section. That was rejected for two reasons. It would cost something like twenty-seven hours across
the dataset against about two for reading the copy the scanner already stitched — and, more
seriously, it would leave undetermined which tile the stitcher actually kept in each overlapping
strip, so the correction would be applied to pixels that may have come from the neighbour.

The alternative used here works on the stitched image and never touches a raw tile. Because the tile
grid is exactly regular and the stitched image starts at the mosaic origin, tile boundaries fall at
exact multiples of the pitch. So the section can be cut into pitch-sized cells and stacked — folded
— and **every cell in that stack sees the same illumination pattern, whatever the stitcher did.**

Taking the middle value at each position across thousands of such cells, drawn from sections whose
tissue falls at random positions relative to the grid, leaves the anatomy behind and recovers the
illumination alone. Anatomy varies far too slowly to survive being averaged across cells that
sampled it at random offsets; the lamp's pattern, being identical in every cell, survives intact.

> **In the code** — `scripts/01f_tilefield.py`
>
> The fold needs no alignment search, because the phase is known to be zero:
>
> ```python
> def fold_indices(length, downsample):
> ```

## 01f  Apply the field to the sample {#stage-tilefield_verify}

*`scripts/01f_tilefield.py verify` → `qc/test_sections_corrected/`*

The same script, run again to write corrected copies of the sample so the artifact can be measured
after correction as well as before. The comparison is the result.

## 01c  Measure the tile artifact before correction {#stage-artifact_before}

*`scripts/01c_measure_tile_artifact.py` → `qc/tile_artifact/`*

This step defines what "the artifact" actually is, so that the claim of having corrected it can be
checked rather than asserted.

The artifact is periodic at the tile pitch, so it shows up as a single sharp spike in the
spatial-frequency spectrum of the section's brightness profile. Real anatomy varies far more slowly
than the 1.19 mm pitch, which is what makes the two separable. The amplitude is then reported in the
terms that actually matter for detection: peak-to-trough of the folded tile profile as a percentage
of mean signal — that is, **how much more signal an object near a tile centre sees than an identical
object near a tile edge.**

## 01c  Measure the tile artifact after correction {#stage-artifact_after}

*`scripts/01c_measure_tile_artifact.py` on the corrected sample → `qc/tile_artifact/`*

The same measurement on the corrected copies. The before-and-after pair is the evidence that the
correction did what it claims.

## 01h  Illumination field from raw tiles {#stage-tilefield_raw}

*`scripts/01h_tilefield_raw.py` → `qc/flatfield/`*

An independent estimate of the same illumination profile, built the other way round: from thousands
of genuinely raw, unstitched tiles, then mapped onto the stitched geometry. This is the only place in
the pipeline where the third-party reader decodes pixels.

The interesting thing is what happens to the result. **It is not automatically promoted over the
folded field of 01f.** It is a cross-check — two independent routes to the same quantity — and
adopting it would be a decision a person makes and records, not something a script does quietly.

## 01k  Clipping on the raw plane {#stage-saturation_raw}

*`scripts/01k_saturation_raw.py` → `qc/saturation_raw.csv`, `qc/censor_raw/`*

A pixel that was brighter than the camera could record stops at the sensor's ceiling. Its true value
is gone, and no correction recovers it — this is lost information, not miscalibration. This step
finds those pixels and writes a mask of them for every section.

**It measures them before the illumination correction is applied, and that ordering is the entire
point.** The correction works by dividing by a gain, and over more than half of its area that gain is
greater than one. Dividing a pixel sitting exactly at the ceiling by a number greater than one lifts
it off the ceiling, so it stops *reading* as clipped while its value is exactly as lost. The earlier
version of this measurement ran after correction and consequently found only about half the clipped
pixels — and every one it missed carried a plausible-looking number that then entered the analysis
as if it were a measurement.

The masks this step writes are what the censoring steps later read.

> **In the code** — `scripts/01k_saturation_raw.py`
>
> ```python
> CEILING = 65535
> ```
>
> That is a fallback only. The real ceiling is read per file from the manifest, because not every
> file's camera reports the same one, and assuming the 16-bit maximum would be wrong for some.

## 01g  Where the clipping falls {#stage-saturation_map}

*`scripts/01g_saturation_map.py` → `qc/saturation/saturation_AF568.csv`*

Knowing how *much* clipping a section has is not enough, because clipping outside the tissue costs
nothing while clipping in the middle of the parenchyma destroys measurements. This step separates
cosmetic clipping from consequential clipping with four measurements: what fraction of the clipping
lies inside the tissue at all, how close it sits to the tissue edge, how large the connected clipped
patches are, and how much of the tissue it covers.

The patch size does real work. At 5.20 µm per pixel a 7 µm nucleus is smaller than a single pixel, so
a large connected clipped blob cannot possibly be nuclei — it is debris, a bubble, or an edge
artifact.

\newpage

# Part 3 — The atlas

Region names come from a published salmon brain atlas, and that is a deliberate division of
authority: **the anatomy stays the atlas author's statement, not this pipeline's.** Region names are
recorded exactly as the atlas writes them.

The atlas arrived as a PDF, which sounds like an obstacle and is actually the opposite. It is a
working vector document rather than a scan, so every region marker is a real drawn dot with its own
colour, and every page carries a legend mapping colours to region names. The document is machine
readable.

What it does not contain is plates. It contains *pages*, holding *figures*, which are themselves
stored as several horizontal strips, and a single figure may show several brain sections side by
side. Four steps turn that into a set of plates where one plate is one section with its regions
marked. That is what this part is: unpacking a PDF into something a curator can scrub through.

At the end of it, the labelled regions cover the telencephalon and preoptic area, the raphe, and —
added in a 2026-09 revision — four tuberal regions. Roughly half the plates still carry no region
labels at all, which is what bounds regional quantification to the forebrain and tuberal
hypothalamus. That limit is revisited in Part 7.

## 04a  Extract atlas plates and seeds {#stage-atlas_extract}

*`scripts/04a_atlas_extract.py` → `atlas/plates/plates.csv`, `atlas/plates/seeds.csv`*

Pulls every plate image and every region marker out of the PDF.

**Markers are found by size, not by colour**, and that choice has already saved the extraction once.
In the atlas as it stood before the 2026-09 revision, one region was drawn in black and another was
a hatched pattern fill that also reported as black — so filtering on colour discarded both and
silently removed every labelled plate behind a certain point in the brain. The revision redrew both
in solid colour, so neither case is live any more, but the size rule is kept precisely because it
does not depend on that staying true.

Markers are also grouped by overlap, because a marker is not one drawn shape. The revision was
re-exported from PowerPoint, which draws each dot as three stacked paths spread slightly apart,
where the previous export drew two almost exactly on top of each other. Grouping paths whose centres
fall within half the larger one's diameter recovers one marker per dot.

That re-export also flattened parts of some pages into bitmaps, taking a substantial share of the
telencephalic markers with them. Those are recovered by looking for the page's own legend colours,
at marker size, inside the flattened areas — a recovery deliberately restricted to colours the page
already names, so it **can restore a marker the export lost but cannot invent a region.**

> **In the code** — `scripts/04a_atlas_extract.py`
>
> ```
> Selected by size, not by colour - see MARKER_SIZE. One marker is drawn as
> ```

## 04a2  Merge image strips into whole figures {#stage-atlas_remerge}

*`scripts/04a2_atlas_remerge.py --dpi 300` → `atlas/plates_merged/plates.csv`*

The PDF stores one figure as several horizontal strips, so counting embedded images counts strips
rather than figures — roughly twice as many. This step renders each figure whole and remaps every
region marker onto the merged image exactly, so no seed drifts in the process.

## 04a3  Reframe figures into plates {#stage-atlas_reframe}

*`scripts/04a3_plate_reframe.py` → `atlas/plate_reframe.html`* · **an operator decides here**

A figure is still not a plate: some figures show two, three or more sections side by side, and the
curator needs one section per plate to scrub through. This step draws a box around each section on
each figure.

The boxes are proposed automatically from the bands of tissue the program can see, so the operator's
job is checking rather than drawing — and only the multi-section figures need a look at all. It runs
as a page in a browser, which is how all three curation tools in this pipeline work.

## 04a3b  Enforce the declared section counts {#stage-atlas_enforce}

*`scripts/04a3b_enforce_sections.py --apply` → `atlas/plate_boxes.prev.csv`*

The automatic band detector miscounts in two situations it cannot see its way out of: when two
sections touch, and when a single section has a white band running through it. For those figures the
configuration states how many sections there really are, and that is treated as the authority — the
boxes are merged or split to match it.

## 04a4  Render the final plate set {#stage-atlas_rebuild}

*`scripts/04a4_plate_rebuild.py --dpi 300` → `atlas/plates_final/plates.csv`, `seeds.csv`*

Re-renders each box straight from the PDF at full resolution and carries the region markers across.
This is the plate set the ROI curator actually shows.

## 04w  Build the Wullimann plate set {#stage-atlas_wullimann_plates}

*`scripts/04w_wullimann_plates.py` → `atlas/plates_wullimann/plates.csv`*

Only for the alternative atlas (`atlas_source: wullimann1996`). The Wullimann 1996 zebrafish cross
sections were already cut out of the book, so this arranges them into the same layout the curators
read. Plate ids are zero-padded section numbers so that they sort rostral to caudal; the real section
number is kept alongside, because the sections are not evenly spaced. Each plate is a line drawing of
one hemisphere beside a micrograph of the other, and the step records where they meet.

## 04x  Region outlines to numbered polygons {#stage-atlas_wullimann_polygons}

*`scripts/04x_wullimann_polygons.py` → `atlas/plates_wullimann/polygons.csv`*

The Wullimann plates carry no coloured dots; each region is drawn as a closed outline, so the outline
is the area. This step finds the enclosed regions in each drawing and writes them as polygons,
numbered in the order the pipeline already numbers regions in. The region curator then shows them as
the numbered guide when you draw the region on a section.

The names are read from the printed labels by OCR and are guesses until a person has checked them, so
the curator shows only polygons marked reviewed. `--review` writes the page where that happens.

\newpage

# Part 4 — Normalisation and curation

This is the largest part and it carries most of the pipeline's judgement, so it is worth having its
shape in mind before meeting the steps.

Three things happen here. First, every section is put into **one common frame** — rotated upright,
centred, cropped, resized to the same 256-pixel square — so that a coordinate means the same thing
on every section. Second, unmeasurable data is removed by **three separate mechanisms** that are
deliberately kept apart because they mean different things: a whole section can be unusable, a
patch inside an otherwise good section can be unusable, or an individual pixel's value can be lost.
Third, an operator places the **anatomical regions**.

The order of the steps reflects one more thing. Every curation decision is made on the **PCNA pass**,
and then carried across onto the pERK pass. So the part runs: prepare PCNA, curate PCNA, clean PCNA,
propagate to pERK, clean pERK, then build the tables and pages the region curator reads. That is
why the reformatting step appears repeatedly — it is re-run each time a new decision needs folding
in — and why the two markers are not treated symmetrically.

Three of the pipeline's four operator steps are in this part.

## 04a  Reformat PCNA sections {#stage-reformat_pcna}

*`scripts/04a_reformat.py` → `reformatted/reformat_index.csv`*

Every section is normalised into a common frame before anything is compared. The section is reduced
to a tissue outline; small fragments well below the size of the largest are discarded, so a fleck of
debris cannot drag the centre or the angle; the section is rotated so the long axis of the tissue
lies horizontal, regardless of how it happened to be mounted; it is centred, cropped to the tissue,
padded to a square and resized to 256 pixels.

**The reason is that the alternative was tried first and failed.** Matching sections to atlas plates
originally compared raw, hand-drawn scan regions against arbitrarily cropped plates, which left
position, scale, rotation and surrounding debris all free at once. That is why it needed an
eight-way orientation search, and why the search returned nothing useful. Normalising removes those
unknowns instead of searching over them.

**All of this geometry is computed on DAPI, never on the marker channel**, because the marker is a
sparse signal and makes a poor silhouette. That choice turns out to protect the measurement in a way
nobody designed for. The marker channel carries a PAP pen stroke around the tissue on the great
majority of sampled pERK sections — often brighter than the brain itself, and absent from PCNA.
Nothing masks it. What removes it is this crop: the stroke lies outside the DAPI silhouette, so
cropping to the DAPI tissue discards it. Measured on reformatted sections, mean intensity outside
the tissue is a fraction of a unit against tens of units inside. **The safeguard holds only as long
as no geometry is ever computed on the marker channel.**

This same script runs six times across the pipeline, each time folding in whatever has been decided
since. The other five entries below are short because they are this step with different flags:

| Step | Flags | What it adds |
|---|---|---|
| `04a` reformat PCNA | — | the first pass, before any curation |
| `04a` reformat PCNA curated | `--apply-overrides` | the operator's rotations and exclusions |
| `04a` reformat PCNA final | `+ --mask-artifacts --censor` | the PCNA analysis frame |
| `04a` reformat pERK | `--marker AF568 --apply-overrides` | the pERK pass, with propagated curation |
| `04a` reformat pERK final | `+ --mask-artifacts --censor` | the pERK analysis frame |
| `04a` render excluded pERK | `--render-excluded` | pictures only, no index row |

> **In the code** — `scripts/04a_reformat.py`
>
> ```python
> GRID = 256                  # normalised output is GRID x GRID
> ```
>
> and the silhouette rule, from the function that computes the frame:
>
> ```
> is DAPI for a section, because the marker channel is a sparse signal and a
> poor silhouette.
> ```

## 04f  Propose unmeasurable sections {#stage-exclusion}

*`scripts/04f_exclusion_candidates.py` → `reformatted/exclusion_candidates.csv`*

Some sections cannot be measured: the tissue tore, or fell off, or never made it onto the slide.
Judging them all by eye is slow and, worse, inconsistent — the twelfth animal gets judged by a more
tired standard than the first.

So this step proposes, and a person disposes. **It proposes only the unambiguous cases**, which
turns the manual pass from a search into an adjudication.

The conservatism is deliberate and asymmetric. A wrongly *included* section adds a little noise to a
group mean and stays visible in the data, where anyone can find it. A wrongly *excluded* section
vanishes silently and takes its evidence with it. Given that asymmetry, only sections with no tissue
worth the name are proposed at all; torn-but-substantial sections are left to the eye.

The threshold is a **physical size, not a fraction of the frame**: the largest connected piece of
tissue below 2.5 mm², measured on the overview at a known 5.20 µm per pixel. On hand-labelled
examples the separation was clean — debris-only frames came in at around 1 mm², real tissue at four
times that and up. Every proposal carries the numbers that produced it, and every one is reversible.

> **In the code** — `scripts/04f_exclusion_candidates.py`
>
> ```python
> UM_PX = 5.20e-3        # mm per pixel in the overviews
> LARGEST_MIN_MM2 = 2.5
> ```
>
> The threshold is in square millimetres because the pixel size is fixed and known, which is what
> makes it a statement about tissue rather than about image size.

## 04h  Propose symmetry-axis rotations {#stage-symmetry}

*`scripts/04h_symmetry_axis.py` → `reformatted/symmetry_proposals.csv`*

Reformatting rotates each section by the long axis of its tissue, which gets it approximately
upright but not reliably so — a transverse brain section is not much longer than it is wide, so the
long axis is a weak cue. This step proposes a small extra rotation that puts each section's midline
vertical, using the brain's own left-right symmetry, which is a far stronger signal.

The proposals are pre-applied in the curator that follows, so the operator's manual pass is spent
correcting the failures rather than rotating everything from scratch.

## 04d  Rotation and exclusion curator {#stage-rotation_curator}

*`scripts/04d_rotation_curator.py` → `reformatted/rotation_curator.html`* · **an operator decides here**

The first of the pipeline's four operator steps, and it settles two questions per section: is this
section upright, and is it measurable at all.

It runs as a page in an ordinary web browser. Each section appears already rotated by the automatic
proposals of 04a and 04h, with an atlas plate underlaid for reference, and the operator drags it to
correct anything the proposals got wrong. Alongside that, each exclusion proposal from 04f is shown
with the numbers that produced it, to be accepted or overruled.

The visual vocabulary is worth knowing because the ROI curator later reuses it: **a dashed amber
border is a proposal the program made; a solid red one is a decision a person made.** The two are
never confused, and the distinction survives into the exported files.

Exclusions decided here drop a section out of everything downstream, which is why the step exports
its decisions to a file rather than editing anything in place: the decisions are data, they are
reviewable, and they can be re-applied or revised without re-deriving them.

## 04a  Reformat PCNA with the curation applied {#stage-reformat_pcna_curated}

*`scripts/04a_reformat.py --apply-overrides` → `reformatted/excluded_sections.csv`*

The reformat again, now folding in the operator's manual rotations. Exclusions are recorded as flags
in a file, not by deleting anything — so an excluded section can be reinstated later without
re-reading a single scan.

## 04g  Mask artifacts — PCNA {#stage-artifact_pcna}

*`scripts/04g_artifact_mask.py --include-excluded` → `artifacts/artifact_summary.csv`*

The second removal mechanism. Some sections are fine overall but carry bubbles, antibody aggregates
or stray fibres sitting inside otherwise good tissue. Dropping the whole section would throw away
good data; the answer is to mask the offending patch and keep the rest.

This is not a rare problem — the large majority of sections carry at least one bright artifact
strictly inside the tissue. The masked area is small on most sections, but it reaches several per
cent at worst, and **these are by construction the brightest pixels in the section.** For a count per
square millimetre that is a minor correction. For anything driven by intensity it is not, which is
why the mask is applied *before* the intensity normalisation rather than after: artifact-inflated
intensities have been shown to skew normalisation badly enough to change cell labels well outside
the artifact itself.

Two design points keep the mask honest. **Detection runs on DAPI only**, so the mask is identical for
both marker passes and cannot encode anything about the marker being measured. And the tissue rim is
protected: the outer edge of a section is genuinely DAPI-bright — the pial surface, the ventricular
lining — so a plain brightness rule would mask the whole border. The edge is eroded away before
anything is seeded, and any growth that escapes along the bright rim is abandoned.

> **In the code** — `scripts/04g_artifact_mask.py`
>
> ```python
> core = ndimage.binary_erosion(tis, np.ones((2 * RIM_ERODE_PX + 1,) * 2))
> ```
>
> `core` is the tissue with its rim eroded away. Artifacts are sought there, so the bright edge of
> the section can never seed one.

## 04j  Censor clipped pixels — PCNA {#stage-censor_pcna}

*`scripts/04j_censor_clipped.py --marker AF488` → `reformatted/pcna_analysis_set.csv`*

The same censoring described under the pERK entry below, run for PCNA.

This step is worth a note, because it corrects an earlier assumption. Censoring used to be run for
pERK only, on the stated grounds that the AF488 channel could not clip. That was **an inference from
a broken test rather than a measurement**: the check had been made on the 8-bit overview, whose top
value means "at or above the display maximum" and cannot distinguish a bright pixel from a clipped
one, so the question had been unanswerable rather than answered. Measured properly on the raw 16-bit
plane, AF488 does clip — very little on most sections, but not nothing, and more than a per cent on
the worst. A clipped PCNA pixel is lost for exactly the same reasons a clipped pERK pixel is.

## 04a  Reformat PCNA — masked and censored {#stage-reformat_pcna_final}

*`scripts/04a_reformat.py --apply-overrides --mask-artifacts --censor` → `reformatted/sections/`*

The PCNA analysis frame: curation applied, artifact pixels blanked, and the clipping masks carried
into the 256-pixel frame. Re-run whenever a mask or a curation decision changes.

## 04i  Carry the curation onto the pERK scans {#stage-propagate_perk}

*`scripts/04i_propagate_to_perk.py` → `reformatted/perk_overrides.csv`*

Every decision so far was made on the PCNA pass. This step carries them onto the pERK pass, and the
two kinds of decision travel very differently.

**Exclusions transfer directly.** A section excluded in one pass is the same physical tissue in the
other, and 02 already established which pERK scene is which PCNA scene, so this is a lookup.

**Rotations have to be re-derived.** The scan regions were drawn separately for each pass, so a pERK
section sits in a differently shaped box from its PCNA partner, and the reformat squeezes each into
a square differently. An angle that puts the PCNA section upright will not put the pERK section
upright. So instead of copying the angle, the step aligns the pERK tissue outline onto the curated
PCNA one and reads off the angle that does it. The quality of that alignment is reported per
section, so a failure is visible rather than silent.

> **In the code** — `scripts/04i_propagate_to_perk.py`
>
> ```python
> PAIRS_CSV = os.path.join(OUT_ROOT, "pairs.csv")
> ```
>
> The pairing from step 02 is what makes the exclusion transfer a lookup rather than a guess.

## 04a  Reformat pERK sections {#stage-reformat_perk}

*`scripts/04a_reformat.py --marker AF568 --apply-overrides` → `reformatted/reformat_index_AF568.csv`*

The pERK pass put into the same 256-pixel frame, with the propagated curation applied.

## 04g  Mask artifacts — pERK {#stage-artifact_perk}

*`scripts/04g_artifact_mask.py --marker AF568 --include-excluded` → `artifacts/artifact_summary_AF568.csv`*

The same artifact detector, run on the pERK scan's own DAPI channel. Artifacts are **not** propagated
from the PCNA pass: the two scans imaged different fields of the same slide, so a bubble sitting in
one scan's frame may be outside the other's.

## 04j  Censor clipped pixels — pERK {#stage-censor_perk}

*`scripts/04j_censor_clipped.py` → `reformatted/perk_analysis_set.csv`, `censor/`*

The third removal mechanism, and the one whose logic most needs stating, because it is not masking.

The pERK exposure is more than three times the PCNA exposure, and it pins pixels at the sensor
ceiling on a substantial share of sections. Two things then happen, and they are deliberately
distinct.

**At section level, a section with one per cent or more of its *tissue* pixels at the ceiling is set
aside.** Set aside, not deleted: it is recorded with a flag, so the decision is visible and can be
reversed. Note that the gate is on tissue pixels rather than on the whole frame — clipping out on
the glass says nothing about whether the brain was measurable.

**Within the sections that survive, clipped pixels are marked *right-censored*.** That is a precise
statement and a different one from the artifact mask. A masked pixel is simply not measured. A
censored pixel *was* measured, and what is known about it is that its true value is **at least** the
ceiling. It cannot enter a mean or a median, because it would drag both downward toward a value the
pixel certainly exceeded — but it also cannot simply be dropped, because a pixel at the ceiling is
unambiguously positive, and discarding it would bias the positive count downward.

The cost of getting this wrong was measured. The pERK data appeared to contain two staining batches
with a nearly two-fold difference in background between them. Restricted to sections with no
clipping at all, the two are identical: **the entire apparent batch effect was clipped pixels
dragging the mean up**, not a gain difference. An artifact of the sensor had been about to be read as
a property of the experiment.

> **In the code** — `scripts/04j_censor_clipped.py`
>
> The gate, from the module docstring:
>
> ```
> **Section level - a 1% tolerance, on tissue.** Sections with 1% or more of
> their *tissue* pixels at the ceiling are set aside. Not deleted: recorded in
> ```

## 04a  Reformat pERK — masked and censored {#stage-reformat_perk_final}

*`scripts/04a_reformat.py --marker AF568 --apply-overrides --mask-artifacts --censor` → `reformatted/sections_AF568/`*

The pERK analysis frame. The nuclei detection step reads the artifact and censor masks this writes.

## 04a  Render excluded pERK sections for Review {#stage-render_excluded_perk}

*`scripts/04a_reformat.py --marker AF568 --apply-overrides --render-excluded` → `reformatted/sections_AF568/`*

pERK exclusions were applied *before* reformatting, so excluded sections had no picture at all and
could not be looked at. This renders them. It writes an image but deliberately **no index row** — and
the index, not the image, is what puts a section into the analysis — so the sections become
reviewable without becoming measurable.

## 04m  Every pERK section and its fate {#stage-sections_dataset}

*`scripts/04m_sections_dataset.py` → `reformatted/perk_sections_dataset.csv`*

One row per pERK section, saying which of three things happened to it — in the analysis set,
censored out, or excluded and why — joined to its PCNA partner.

This exists so that the removals are auditable as a set rather than section by section. It also
produces something that has to be checked later: **the exclusion rate per animal is itself a
result.** If sections were lost unevenly across animals, and that unevenness lines up with treatment
group, then the analysis set is not a fair sample. That check cannot be made until unblinding, so
the table is built now and read then.

A section that was never measured is recorded as unmeasured, never as censored. The two are
different statements and collapsing them would overstate what is known.

## 04n  Order the ROI queue {#stage-worklist}

*`scripts/04n_roi_worklist.py` → `reformatted/roi_worklist.csv`*

Region curation is manual and slow, and it will realistically be stopped part-way. This step decides
the order it happens in, so that **any prefix of the queue is a usable dataset.**

That is not a small point. Worked through in animal order, curating half the queue would finish
several animals completely and leave the rest untouched — which supports no comparison at all. The
work would be half done and worth nothing.

Two orderings prevent that. Across animals, the queue advances every animal in proportion to the
length of its own series, so after any number of sections every animal sits at roughly the same
fraction of its brain. Within an animal, it takes the two ends of the series first and then
repeatedly whichever section is furthest from everything already taken, so the first handful span
the brain rather than clustering at one end.

The sections are the same either way. What changes is what stopping early is worth.

## 04o  Colour composites — pERK {#stage-rgb_perk}

*`scripts/04o_section_rgb.py --marker AF568 --all` → `reformatted/sections_AF568_rgb/`*

The curator has to show the channel being quantified, not just the counterstain, so this writes a
colour composite of DAPI plus the marker for each section.

The constraint that shapes it: the composite must sit in **exactly** the same frame as the
reformatted section, pixel for pixel, because ROIs drawn on one are measured on the other. So the
marker is not reformatted separately — it is passed through the same reformat as a passenger,
carried by the same rotation and crop that the DAPI silhouette determined.

## 04o  Colour composites — PCNA {#stage-rgb_pcna}

*`scripts/04o_section_rgb.py --marker AF488 --all` → `reformatted/sections_rgb/`*

The same for the PCNA channel.

## 04o  Review thumbnails — pERK {#stage-thumbs_perk}

*`scripts/04o_section_rgb.py --marker AF568 --thumbs` → `reformatted/sections_AF568_rgb_thumb/`*

Small colour thumbnails, so the curator's review grid can show every section at once without loading
full-size images.

## 04o  Review thumbnails — PCNA {#stage-thumbs_pcna}

*`scripts/04o_section_rgb.py --marker AF488 --thumbs` → `reformatted/sections_rgb_thumb/`*

The same for PCNA.

## 04p  Trace every scanned section {#stage-provenance}

*`scripts/04p_section_provenance.py --tissue-masks` → `reformatted/section_provenance.csv`*

Four steps decide a section's fate before it ever reaches the region curator, and the curator loads
only the survivors. So every exclusion and every artifact mask was, for a long time, **invisible from
the tool the operator actually works in.**

This step fixes that by building one row for every scanned section — including the excluded ones no
other table carries — joining what 04f proposed, what the operator decided, what 04g masked and what
04j censored. It is a join rather than a measurement, and it is what the curator's Review mode reads.

In that Review mode, every scanned section is visible, grouped by animal and slide. Clicking one
shows its whole chain of decisions, and three actions are available, each requiring a reason:
reinstate a section the pipeline excluded, drop one it kept, or reject a mask where the detector was
wrong. Reinstating changes the analysis set, so the measurement step has to run again for whatever
it adds — and the export says so before it writes.

## 04l  ROI curator {#stage-roi_curator}

*`scripts/04l_roi_curator.py --marker AF568 --worklist --rgb` → `reformatted/roi_curator.html`* · **an operator decides here**

The centrepiece of the pipeline. This is where anatomy is actually placed on tissue, and it is a
page in a browser where a person does the work.

The division of labour follows a published tool for the same task, which automates the registration
and the counting but leaves two things to its user: scrolling to the correct level by eye, and
clicking corresponding points between the section and the atlas. That division is kept here.

**Assigning the level is done by hand because automation was tried and measured to fail — twice.**
The first attempt compared section outlines against plate outlines; the second registered
intensities. Across animals, the correlation between a section's true serial position and its
best-matching plate came out near zero in both, sometimes negative. The reason is in the data rather
than the algorithm, and it is documented elsewhere in the literature: DAPI-stained sections and
Nissl-stained atlas plates simply do not correspond well morphologically. So the operator scrubs a
plate slider until the plate matches the section.

**Landmarks, and the gate between two kinds of fit.** The operator then clicks matching points,
alternately on the section and on the plate. Three or more pairs determine an affine transform — a
uniform stretch, rotation and shear — by least squares. From **six** pairs the tool switches to a
thin-plate spline, and the header says which is currently live.

That gate is the whole argument. A thin-plate spline passes exactly through every landmark and
invents deformation in between, which is powerful and needs enough real correspondences to be worth
having; below six it would be confidently interpolating from almost nothing. An affine, meanwhile,
genuinely cannot follow the local distortion that sectioning and mounting introduce. Each landmark's
own residual is displayed, so a mis-clicked pair shows up as a large error rather than quietly
degrading the fit.

**Nothing is warped onto the section.** An earlier version drew every atlas seed through the fit,
which turned ten placed regions into thirty on screen and twenty-seven in the export — and the ones
nobody had touched were extrapolation past the edge of the landmarks, which read on screen as
measurement. The landmarks now exist for the plate assignment and the residual, not for placing
anything.

**A region is an area, and the atlas numbers the areas.** The atlas marks each region with several
dots — well over a hundred for a large region across all its plates, five or six per lobe on a given
plate — and an early version measured each dot as its own small circle, which measured circles
rather than regions. Instead, the dots of one region on one side of the brain are grouped into a
single region of interest, every dot carries that region's number, and **the operator outlines the
area as a polygon**, clicking each corner in turn. The atlas plate shows each region as a shaded
shape in the atlas's own colour for it, so what is being asked for is visible rather than inferred
from a scatter of numbered dots.

Grouping splits a region's dots **by lobe** before shaping them, because these regions are bilateral
and one shape spanning both lobes would cross the midline gap. Without the split the widest shape
covered most of a plate; with it, a fifth of one. Numbering follows the reading order the dots
already had, so a region's number is stable across runs and across every export.

Circles are no longer used for anatomy at all. The disc survives only for the **background reference
regions** — patches of tissue the operator judges to hold no signal — which are measured by exactly
the same detector and are what later gives both the positivity threshold and the detector's own
false-positive rate. They are a different quantity, not a different shape of the same one.

Sections are exported with their plate assignment, their landmark pairs and residuals, and their
regions as vertex lists, all in the normalised 256-pixel frame.

> **In the code** — `scripts/04l_roi_curator.py`
>
> ```
> Three or more pairs determine an **affine** by least squares. From **six** pairs
> the tool switches to a **thin-plate spline**, and the header says which is live.
> ```

## 04q  Import the curator's exports {#stage-import_curation}

*`scripts/04q_import_curation.py --plates ... --landmarks ... --regions ... --write` → `curation/ls_roi_curator_v1.json`*

The curator runs in a browser, and a browser's local storage belongs to that browser alone — it does
not travel between machines, profiles, or between the browser and the desktop application. The
exported files are therefore the only route the work takes, and a drawn polygon exists in no other
file anywhere.

This step reads the three exported tables back and rebuilds the curator's working state from them,
so work done in any browser reaches the application. The previous state is backed up before anything
is written.

## 04k  Level curator (superseded) {#stage-level_curator}

*`scripts/04k_level_curator.py` → `reformatted/level_curator.html`* · **an operator decides here**

An earlier tool for assigning atlas levels: anchor a few sections to plates and interpolate the rest.
It was superseded by the plate slider built into the ROI curator, which does the same job in the
place the operator is already working.

It is listed rather than deleted because hiding it would turn "we chose not to use this" into "this
does not exist", and the distinction matters when someone asks later how levels were assigned.

\newpage

# Part 5 — Quantification

This is where numbers are finally produced, and it is still entirely blind: no step in this part
reads a treatment group.

Only one step in the pipeline reads full-resolution pixels for measurement, and it is here. It
produces a table with one row per nucleus, and **everything after that table is arithmetic on a
table.** That is a deliberate architectural choice: changing one's mind about where positivity falls
costs a re-run of one cheap step, not a re-read of hundreds of gigabytes of scans.

## 05a  Verify the inverse transform {#stage-roi_geometry_verify}

*`scripts/05a_roi_geometry.py --verify`*

A check rather than a product. It pushes whole coordinate planes through the real reformatting
operations and compares the result against what the single matrix predicts, over every pixel of the
frame. The agreement is a fraction of a pixel — and that residual is the image library's own
downscaling filter rather than an error in the inversion, since the same filter deviates by about
the same amount on a plain linear ramp with no composition involved at all.

## 05a  Place the ROIs on the slide {#stage-roi_geometry}

*`scripts/05a_roi_geometry.py` → `reformatted/roi_geometry_AF568.csv`, `roi_boxes_AF568.csv`*

The operator drew regions on a 256-pixel square in which one pixel spans about 25 µm. A nucleus is
7 µm. **Nothing can be counted in that frame.** Detection has to read the original scan at its native
0.65 µm per pixel, so every region has to be brought back out of the normalised frame and landed on
real slide coordinates.

That means undoing the reformat, which was a chain of six operations — export, resize, rotate, flip,
crop to the tissue, pad to a square, resize again. Every one of them is affine, so the whole
composition is affine and collapses to a single small matrix per section.

Rather than expand that algebra by hand — six chances to transpose an axis, and a wrong answer that
still looks plausible — the matrix is obtained by **running the real transform on three points and
reading off the result.** The actual reformatting function is imported and re-run rather than
reimplemented, so the very same operations that built the curation frame produce the parameters being
inverted. There is no second implementation to drift.

Two consequences affect the areas that get reported. **A circle drawn in the curator is an ellipse on
the slide**, because the composed transform is not uniform in both directions, so a disc's area is
computed from the two semi-axes the matrix implies and never from πr² in curator pixels. A drawn
region is a polygon on the slide, and its area comes from its mapped corners. Neither shape is
mapped by its radius: a disc is turned into a many-sided outline first and then mapped, precisely
because mapping a radius would assume the transform preserves shape.

Sections whose geometry cannot be reconstructed, and regions carrying neither a radius nor a corner
list, are refused rather than guessed at.

> **In the code** — `scripts/05a_roi_geometry.py`
>
> ```python
> def affine_from(fn):
>     """The 2x3 matrix of an affine map, read off by evaluating it three times.
> ```
>
> and the semi-axes, which is why an area is never πr²:
>
> ```python
> s = np.linalg.svd(np.asarray(M, float)[:, :2], compute_uv=False)
> ```

## 05c  Detect and measure nuclei {#stage-detect}

*`scripts/05c_detect_rois.py` → `results/roi_nuclei.csv`*

The measurement step. For each region, it reads that region's box out of the original scan at full
resolution — a few hundred kilobytes out of a one-to-two gigabyte file, which is what makes several
thousand regions tractable at all — finds the nuclei, and measures the marker in each one.

**Nuclei are found on DAPI and never on the marker.** This is the single most important choice in the
step. Detecting on the marker channel would define the number of marker-positive cells by a
threshold twice over: once to find the object, and again to call it positive. The count and the cut
could then never be varied independently, and any apparent difference between groups would be
partly a property of the threshold. Here the counterstain finds the objects, the marker is measured
afterwards, and positivity is decided later still — in a different step, changeable without
re-reading a single scan.

The region is not a rectangle but the box is, so a nucleus found inside the box is kept only if it
falls inside the actual region. That is decided by mapping the nucleus back to the 256-pixel frame
and testing it there, against the polygon the operator drew.

**Segmentation uses StarDist, and the reason is bias rather than preference.** The conventional
alternative, thresholding followed by watershed, under-segments where nuclei touch — it merges two
touching nuclei into one. Several of the regions being measured here are periventricular, where
cells are densely packed, while others are not. The counting error would therefore be worst in
exactly some regions and mild in others, and **a region-correlated counting bias survives into the
results looking like an anatomical finding.** StarDist instead proposes each nucleus as a whole shape,
so two nuclei in contact become two shapes rather than one blob to be split by guesswork. It is used
pretrained, with its own default thresholds, without retraining or per-dataset tuning.

**The DAPI crop is normalised before segmentation; the marker channel never is.** DAPI is normalised
because the pretrained network expects its input in a particular range, and a dim region and a
bright region must both arrive looking like that. The marker is not normalised because it is never
segmented on — its raw values go straight into the output table, which is what makes the positivity
cut later a decision about real intensities rather than about a rescaling.

**Measurement is done twice on the same objects.** The per-object measurement routine is called once
with the marker image and once with the counterstain, over the identical set of object outlines, so
the DAPI and marker statistics describe exactly the same pixels of exactly the same nucleus.
Intensities are taken from the pixels under the nucleus's own outline, not its bounding box — a
nucleus is not a rectangle, and averaging over the box would mix in whatever sits in the corners.

**Background reference discs are measured identically to real regions** — same read, same
segmentation, same statistics — and are distinguished only by a label. That yields two things: a
reference level measured rather than assumed, and a false-positive rate, because the same detector
is run over tissue the operator called empty.

The step is resumable per section and writes atomically, so an interrupted run costs one section
rather than the whole run. It takes hours.

> **In the code** — `scripts/05c_detect_rois.py`
>
> ```python
> return StarDist2D.from_pretrained("2D_versatile_fluo")
> ```
>
> Pretrained and unmodified — the model's published defaults, not values tuned until this dataset
> gave a pleasing answer.

## 06f  Recompute the censored flag {#stage-recensor}

*`scripts/06f_recensor_nuclei.py` → `results/_pre_06f_backup/`*

When the clipping measurement moved to the raw plane (01k), every nucleus already measured carried a
censoring flag derived from the old, under-counting mask. This step re-samples each stored nucleus
position against the corrected mask and rewrites the flag.

It does **not** re-run the segmentation, and does not need to: nuclei are found on DAPI, and DAPI
essentially does not clip — its clipping was measured at a few parts in a hundred thousand at the
median. So the objects are unchanged and only their flags need revisiting. The original table is
backed up first.

## 06g  Flag nuclei off the section {#stage-off_tissue}

*`scripts/06g_flag_off_tissue.py` → `results/_pre_06g_backup/`*

Marks nuclei that fall outside the DAPI silhouette — objects the detector found on glass rather than
on tissue.

These matter more than their number suggests, because of where they land. Objects on bare glass are
dim, and a background reference disc that includes some of them has its measured level and spread
pulled **down**. Since that level sets the positivity threshold for the whole section, a few
off-tissue objects make the entire section look more positive than it is. This step backfills the
flag onto tables written before the detection step recorded it itself.

## 06h  Backfill segmentation provenance {#stage-seg_provenance}

*`scripts/06h_backfill_provenance.py` → `results/_pre_06h_backup/`*

Records, on every row of a table written before the detection step said so, which channel the object
was found on, which method found it, and whether it is a nucleus.

Newer runs write that down per object, because a table outlives the settings that produced it and
the later correction for counting the same nucleus twice is only valid for objects that really are
nuclei. On an older table the three answers are not unknown — the pipeline had one way of finding an
object back then, and it was the counterstain — so this step writes that reading in rather than
leaving a reader to assume it. It reads the whole table, adds the three columns to every row at once,
and refuses a table whose columns it does not recognise. Running it twice changes nothing.

## 06a  Per-ROI dataset {#stage-roi_dataset}

*`scripts/06a_roi_dataset.py` → `results/roi_measurements.csv`, `results/detector_specificity.csv`*

Reduces the per-nucleus table to one row per region. It reads no group label and is still blind.
**One step owns every per-region number**; later steps group and format this output, they do not
re-derive it. They used to, and the two implementations had drifted apart with nothing comparing
them, which is now prevented by a test.

**Where the positivity cut comes from.** Each section's own background discs give a robust upper
bound on what the detector sees where the operator judged there to be no signal. The cut is the
median of the background plus three times its spread, where the spread is the median absolute
deviation scaled by the constant that makes it comparable to a standard deviation. It is computed
**per section**, because this is a high-baseline marker and the background level moves from section
to section.

**A spread and not a percentile, deliberately.** Taking the top few per cent of background objects as
the cut would fix the false-positive rate by construction — and destroy the only independent check
available. With a spread-based cut, how many background nuclei land above it is a *measurement*. On
this dataset it is a low single-digit percentage, and — the number that decides whether positivity
is usable at all — **it is not correlated with treatment group.** Positivity inside the anatomical
regions is several-fold higher than that background rate.

**Two densities are reported side by side.** One counts every nucleus; the other counts the subset
above that section's own cut. Both are divided by the region's area as computed in 05a.

**A censored nucleus is counted as positive by construction.** Its true intensity is unknown but is
at least the sensor ceiling, which is above any cut, so calling it anything else would be a statement
the data does not support. On this dataset the rule is currently inert — no measured nucleus falls
under a censored pixel, because the sections where clipping was severe were removed and what
survives does not reach the curated regions. The rule is stated because it governs, not because it
has acted.

**The Abercrombie correction.** These are single-plane images of a 14 µm section, so what is counted
is nuclear *profiles*, not nuclei: a nucleus cut by the blade appears in the section it falls into,
and because sections here are consecutive rather than sampled at intervals, the same nucleus can be
counted twice. The correction scales the count by the section thickness divided by the thickness
plus the object's mean diameter.

That diameter is **measured, not assumed** — taken per marker and region from the segmentation
itself — because the correction is sensitive to it and an assumed value would put an unmeasured
constant into every density. The measured diameters land in the range one would expect for nuclei,
from a model that was told nothing about expected size, which is itself a check that the
segmentation is finding what it claims.

The limits are worth stating plainly: Abercrombie assumes spherical, randomly positioned objects and
applies no correction for lost caps. The unbiased alternative needs image stacks through the depth
of the section, which this dataset does not have. Raw and corrected counts are therefore both
reported. Because the measured diameter is similar between groups, the correction acts close to a
constant multiplier and barely moves the group contrast — **it is a reporting fix, not a statistical
one.** What it changes is whether a density can honestly be quoted as cells per square millimetre at
all.

Alongside the per-region table, the step writes a per-section detector specificity table carrying the
background count, area, false-positive count and rate, the background level and spread, and the cut
applied — so the threshold used on each section and the evidence for it travel together.

> **In the code** — `scripts/06a_roi_dataset.py`
>
> ```python
> m, s = st.median(bg), mad(bg) * 1.4826
> ```
>
> `bg` is that section's own background nuclei. The scale factor is what makes the median absolute
> deviation comparable to a standard deviation.

\newpage

# Part 6 — Beyond blinding

Everything up to here was keyed by animal identifier alone. This is where the treatment group is
joined, and nothing before it is permitted to read one.

Two steps earlier in the pipeline do read the group key, both deliberately, both recorded in the
configuration, and neither in a way that touches a measurement. The detection step uses it to choose
the **order** sections are measured in, so that any prefix of a long run is a balanced dataset — an
option restores blind ordering, and the finished file is identical either way. The ROI curator uses
it to lay out a slide deck by treatment, which is not something a group comparison figure can be
built without. Leaving the key empty in the configuration disables both.

## 06b  Join the experiment {#stage-join_sampling}

*`scripts/06b_join_sampling.py` → `results/roi_dataset.csv`, `results/animal_metadata.csv`* · **the unblinding step**

The first step permitted to read a group label. It joins each animal identifier to the experimental
sampling workbook.

The join validates itself rather than trusting the spreadsheet: the cohort it produces is checked
against an independent column in the workbook recording which animals were sliced for this
experiment, and a disagreement is reported loudly. A run that mis-assigns animals to groups should
fail obviously rather than produce a plausible and wrong result.

> **In the code** — `scripts/06b_join_sampling.py`
>
> ```
> `config.blinding` says "no stage before 06b may read a group label", which is
> ```

## 06c  Spreadsheet — per sample {#stage-excel_sample}

*`scripts/06c_excel_dataset.py` → `results/roi_dataset.xlsx`*

One row per region per sample, plus per-disc, per-section and coverage sheets. It formats; it does
not re-derive any number. Buildable part-way through a run.

**The per-ROI figures read this workbook**, because one row here is one animal — the unit the
treatment comparison is made on. The pooling happens in this stage and is weighted by area
measured: an animal's nuclei summed over its discs, over the area those discs covered.

## 06d  Spreadsheet — per slide {#stage-excel_slide}

*`scripts/06d_excel_by_slide.py` → `results/roi_dataset_by_slide.xlsx`*

The same table one level finer, so that spread *within* an animal is visible rather than averaged
away.

Worth being precise about the level: a slide is not a section. A slide carries several sections, so
grouping by slide is coarser than grouping by section and finer than grouping by animal.

`plot_by_slide.R` reads this workbook, and it is a picture of variability rather than a bigger
sample: slides from one animal are not independent replicates of a treatment. The per-ROI figures
and every test on them read 06c's per-animal sheet instead.

## 06e  Refresh datasets and figures hourly {#stage-refresh_loop}

*`scripts/06e_refresh_loop.py` → `results/ROI_plots/`*

Detection takes many hours, so this rebuilds both spreadsheets and redraws the figures once an hour
while it runs, and stops when every section has been measured. It is a long-running loop rather than
a one-shot step, which is why the desktop application does not run it — it would hold the app's
runner open for hours.

\newpage

# Part 7 — What this pipeline cannot tell you

Every limitation, collected in one place. Some are properties of the tissue and the scanning and
cannot be fixed by any amount of analysis; others are honest boundaries on what the current design
supports.

**There are no no-primary controls for this dataset.** This is the most important item on the list.
Without them, non-specific secondary binding cannot be separated from genuine low-level specific
signal, and so **absolute positivity rates are not defensible**: "X per cent of cells in region R are
marker-positive" is not a claim these data support. Relative comparisons between groups at matched
anatomical levels are supported, because the non-specific component is shared between them. Three
internal references stand in — off-tissue glass, nuclei-poor fibre tracts within the same section,
and background around each object — but none of them is a no-primary control, and the background
reference discs are not negative controls either: the primary antibody is on that tissue too.

**Tiles are JPEG-XR compressed, and typically lossily.** This was fixed at acquisition and cannot be
undone.

**No shading reference was acquired and tiles were never blended**, so the illumination profile
repeats across every section. It is corrected as described in Part 2, but a correction estimated from
the data is not the same thing as a reference acquired on the instrument.

**Clipping is very unevenly distributed across animals** — some lose nothing, one loses the majority
of its sections — which splits the animals along an axis that has nothing to do with biology. Two
animals yield too few measurable sections to support a per-animal estimate at all. This has to be
checked against treatment group at unblinding.

**The one per cent clipping tolerance is a convention rather than a derived cutoff.** It was
originally chosen because the distribution of clipped fraction was bimodal and one per cent fell in
the trough between the two modes. That bimodality is not present in the current data, so the number
no longer has the justification it was given. It is kept because changing it would change which
sections are analysed, not because one per cent is defensible on its own terms. The step that
characterises *where* clipping falls (01g) is the natural replacement for a bare fraction, but it
cannot take over the gate until its own contrast handling is corrected.

**The atlas covers the forebrain and the tuberal hypothalamus.** Roughly half the plates still carry
no region labels, and the periaqueductal grey remains unlabelled, so extending regional
quantification further caudally requires labelling that does not yet exist. The 2026-09 atlas
revision that added four tuberal regions post-dates the curated region set, so those regions are not
in the quantification reported so far.

**Counts are Abercrombie-corrected, not stereological.** See 06a. The unbiased alternative needs
image stacks this dataset does not have.

**Atlas level assignment is an expert judgement, not a measurement.** It is done by hand because
automation was tried twice and failed. That is worth stating plainly, because expert-versus-expert
agreement on brain section annotation has been measured to be poor — which is the argument for the
propose-then-adjudicate design used throughout this pipeline, and against treating any single expert
pass as ground truth, including this one.

**Adjacent sections are not independent tissue.** Sections were cut consecutively rather than sampled
at an interval, so neighbouring sections sample overlapping cells. This is why the Abercrombie
correction is applied rather than offered as an option, and it constrains how sections may be
treated as replicates.

\newpage

# What this guide does not cover

**The statistics and the figures.** Model choice, contrasts and the figure deck are downstream of
everything described here and live in the R layer under `analysis/`. `docs/pipeline-methods.md` §14
summarises the approach.

**How the software is built and run.** Installation, the two Python environments, the desktop
application, the tests and the packaged executable are in `README.md`.

**The detailed nuclei-detection walkthrough.** `docs/nuclei-detection-after-roi-curation.md` covers
steps 05a and 05c in considerably more depth than Part 5 does.

**Why the CZI reading is done the way it is.** `docs/czi-reading-audit.md` documents the audit whose
findings became the self-test of step 00d.

**What went wrong and when.** `LOGS.md` is the running record. Several of the arguments in this guide
— the clipping measured after correction, the nuclei counted off the section, the batch effect that
was not one — are there in full, with the numbers.

# Where the numbers live

This guide states settings and structure, not results. Where a number is a measurement, it has been
left in `docs/pipeline-methods.md`, which `docs/check_methods_claims.py` verifies against the actual
data every time it is run, reporting pass or fail for each claim.

The reason is simple: detection is still running, and re-running the censoring step on an improved
clipping mask moves sections between the measurable and censored sets. A count copied into this
document would be a second copy that nobody checks, and it would disagree with the repository the
moment either changed. `docs/pipeline-methods.md` §1.1 states how far the pipeline has been run and
is dated.

The numbers that *do* appear here — 14 µm sections, 0.65 and 5.20 µm per pixel, 2040-pixel tiles on
an 1836-pixel pitch, the one per cent clipping tolerance, the 2.5 mm² tissue floor, the 256-pixel
frame — are settings and instrument constants. They change only if the pipeline is deliberately
changed, and they are checked against the configuration and the file headers by the same script.
