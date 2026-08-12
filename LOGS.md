# Change log

Newest first. One entry per substantive change: **what changed, why, what it cost**, and what it
reverses.

This file exists because several decisions here were reversed after measurement. The reasoning is
the part that will not be reconstructable from the code six months from now — the code only shows
where things landed, not which plausible-looking route was tried and abandoned, or why.

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
