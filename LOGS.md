# Change log

Newest first. One entry per substantive change: **what changed, why, what it cost**, and what it
reverses.

This file exists because several decisions here were reversed after measurement. The reasoning is
the part that will not be reconstructable from the code six months from now — the code only shows
where things landed, not which plausible-looking route was tried and abandoned, or why.

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
