# Nuclei detection after ROI curation

**A user guide to stages 05a and 05c of the LS whole-brain IHC pipeline.**

This covers what happens between the moment you finish placing ROIs in the ROI curator
and the moment you have a table of individual nuclei with their marker intensities.

Two scripts do the work:

| Stage | Script | What it does |
|---|---|---|
| 05a | `scripts/05a_roi_geometry.py` | Works out where each curated ROI actually is on the slide |
| 05c | `scripts/05c_detect_rois.py` | Reads those places at full resolution, segments nuclei on DAPI, measures the marker in them |

Nothing in between is manual. Once 05a has run, 05c can be started and left alone.

---

## 1. Where this sits

```
04l_roi_curator.py   →   roi_regions.csv     (you place the discs)
                         roi_plates.csv
                                 ↓
05a_roi_geometry.py  →   roi_geometry_<MARKER>.csv  (one affine matrix per section)
                         roi_boxes_<MARKER>.csv     (one CZI pixel box per ROI)
                                 ↓
05c_detect_rois.py   →   roi_nuclei.csv      (ONE ROW PER NUCLEUS, both markers)
                                 ↓
06a                  →   roi_measurements.csv, detector_specificity.csv
                                 ↓
06c / 06d            →   the spreadsheets      06b → the unblinding join
```

**The 05a outputs are per marker, and that is load-bearing.** 05a writes with mode `w` from one
export. While both markers shared `roi_boxes.csv`, running it against a PCNA export would have
replaced the pERK boxes outright — and `roi_nuclei.csv` joins to that file by
`(scene_uid, roi_index)` in both 06a and 06c, so ~883,000 measured rows would have quietly lost
the geometry they were measured against, with nothing raising an error. Since 2026-09-01 each
marker has its own pair, and 06a/06c/06d read the **union** of both, which is safe because
AF568 and AF488 sections are separate acquisitions with disjoint `scene_uid`s.

Files written before that date have no suffix and are read as an AF568 fallback; they are never
written to again.

`roi_nuclei.csv` is the artefact that matters. Everything after it is arithmetic on a
table — including where the positivity cut falls. Changing your mind about positivity
costs a re-run of 06a, not a re-read of 128 CZI scenes.

---

## 2. Before you start

### 2.1 You need a curator export

The ROI curator runs in a browser (or in the desktop app's embedded pane) and exports
by download. You need at least:

- `roi_regions.csv` — one row per disc you placed, in the section's normalised 256 px frame
- `roi_plates.csv` — one row per section you touched, carrying `excluded`

Put them in `<out_root>/reformatted/`. If they are not there, 05a looks in
`~/Downloads/roi_regions*.csv` and takes the **newest** match — which is deliberate,
because a second export lands as `roi_regions(1).csv` and that is exactly the moment it
matters.

### 2.2 A section is only measurable if it satisfies three conditions

05a builds the "analysis set" and reports what it dropped:

1. **At least one ROI.** There is nothing to measure otherwise.
2. **At least one background disc.** The positivity cut is computed per section against
   that section's own background. A section without one has no reference of its own, and
   borrowing another section's would quietly substitute a different piece of tissue for
   the control.
3. **Not excluded.** `excluded=1` in `roi_plates.csv` is your own judgement; measuring a
   section you threw out would overrule it.

Sections that fail are listed with the reason, not silently skipped. The counts are a
result in their own right — "how many curated sections cannot be used, and why" is the
first thing anyone reading the dataset will ask.

### 2.3 Environment

05c needs **pylibCZIrw** (to read CZIs), **StarDist**, **TensorFlow**, **csbdeep** and
**scikit-image** in one interpreter. pylibCZIrw publishes no cp314 wheel, so this has to
be Python **3.13 or earlier**. In this repository that environment already exists at
`work/appenv`:

```bash
work/appenv/Scripts/python.exe -V
```

should print `Python 3.13.x`. If you are building it fresh:

```bash
py -3.13 -m venv work/czienv
work/czienv/Scripts/python -m pip install -r requirements-czi.txt
work/czienv/Scripts/python -m pip install stardist tensorflow csbdeep scikit-image
```

StarDist and TensorFlow are **not** in `requirements.txt`, and the packaged `.exe`
deliberately does not carry them. 05c is the one stage measured in hours rather than
minutes, so it is run from a terminal, not from the app.

§10 sets out what each of these tools does, at the versions actually installed.

### 2.4 Config keys 05c reads

From `config.json`:

| Key | Current value | Meaning |
|---|---|---|
| `pixel_size_um` | `0.65` | native slide resolution; every area and diameter is in these units |
| `channels.dapi_index` | `0` | the counterstain channel — what nuclei are segmented on |
| `channels.marker_index` | `1` | pERK (AF568) or PCNA (AF488) — measured, never segmented on |
| `source_dir` | the slide folder | where the `.czi` files live |
| `groups.by_animal` | 12 animals | **only** used to choose the processing order (see §4.3) |

---

## 3. Stage 05a — put the ROIs on the slide

### 3.1 Why it is needed

You draw ROIs on a 256 px normalised frame. That frame spans a whole section, so one
pixel is roughly 25 µm and a nucleus is 7 µm. Nothing can be counted there. Detection
has to read the CZI at native 0.65 µm/px, so every disc has to come back out of the
normalised frame and land on real slide pixels.

`04a_reformat` built that frame by composing six operations:

```
overview PNG → square 400 grid → rotate → flip → crop to tissue bbox → square pad → resize to 256
```

Every one is affine, so the composition is affine, and the whole thing collapses to one
2×3 matrix per section. 05a obtains that matrix by *evaluating* the composition at three
points and reading off the columns, rather than expanding the algebra by hand — six
chances to transpose an axis, each producing a wrong answer that still looks like a
matrix.

### 3.2 Run the verification first

```bash
python scripts/05a_roi_geometry.py --verify
```

This pushes two coordinate planes through the same rotate/flip/crop/pad/resize that
`reformat` applied and compares them against what the matrix predicts, over every pixel.
Expect agreement of **0.04–0.15 px**. That residual is `reformat`'s own PIL downscale,
not the inverse.

### 3.3 Then build the geometry

```bash
python scripts/05a_roi_geometry.py
python scripts/05a_roi_geometry.py path/to/roi_regions.csv    # explicit input
```

Outputs, both into `<out_root>/reformatted/`:

- **`roi_geometry.csv`** — one row per section: the six reformat parameters, the CZI
  scene rectangle, the composed matrix `m00…m12`, and an `anisotropy` column.
- **`roi_boxes.csv`** — one row per ROI: its CZI pixel bounding box (`czi_x0`, `czi_y0`,
  `czi_w`, `czi_h`) and the two semi-axes in µm.

### 3.4 A circle in the curator is an ellipse on the slide

Step one of the reformat resizes a rectangular overview onto a **square** 400 grid, and
scan boxes are hand-drawn and rarely square — 944×1404 on the first section tried, a 49%
axis ratio. Anything that carries `sec_r` forward as a radius in slide pixels is wrong.

That is why 05a writes a bounding **box** and 05c decides membership per nucleus by
mapping the centroid back to the 256 grid. No ellipse algebra, and no assumption that
the map is a similarity. `axis_a_um` and `axis_b_um` in `roi_boxes.csv` let you see at a
glance how far from circular a given ROI became.

### 3.5 Sections 05a refuses

It skips rather than guesses, and tells you which and why:

| Message | What it means |
|---|---|
| `not in focus.csv / manifest / reformat_index` | the section was never reformatted |
| `overview PNG missing` | the `_DAPI.png` overview is not on disk |
| `reformat produced no tissue mask` | the mask step found nothing to work with |
| `angle X != recorded Y` | the geometry did not reproduce — the recorded angle from the run that produced the image disagrees with the recomputed one by more than 0.06° |
| `overview WxH does not match scene rect` | the section was exported against a different scene rectangle than the one being read now; every coordinate would be silently offset |

The angle check is the one that says the geometry reproduced. The mask decides the angle
and the angle decides the crop, so a second opinion about the mask would move every ROI
on the section.

---

## 4. Stage 05c — detect the nuclei

### 4.1 Running it

```bash
work/appenv/Scripts/python.exe scripts/05c_detect_rois.py
```

Useful flags:

```bash
work/appenv/Scripts/python.exe scripts/05c_detect_rois.py --limit 5
```

```bash
work/appenv/Scripts/python.exe scripts/05c_detect_rois.py --order uid
```

```bash
work/appenv/Scripts/python.exe scripts/05c_detect_rois.py --force
```

| Flag | Effect |
|---|---|
| `--limit N` | only the first N sections — use it for a smoke test |
| `--order balanced` \| `uid` | processing order; `balanced` is the default, see §4.3 |
| `--force` | redo sections already in `roi_nuclei.csv` instead of resuming |
| `--qc` | *documented as writing overlay crops; see §8.1 — it currently only creates the directory* |

The run is **resumable per section** and safe to interrupt. A section is the unit that
costs something: one CZI open, plus one model call per ROI in it. On restart, sections
already present in `roi_nuclei.csv` are skipped and the file is appended to.

### 4.2 What it does to each ROI

For every box in `roi_boxes.csv`:

1. **Read.** Open the CZI with pylibCZIrw and read the box at native 0.65 µm/px — DAPI
   (`C=0`) and the marker (`C=1`), same rectangle, same resolution. Boxes narrower than
   8 px in either axis are skipped.
2. **Normalise.** `csbdeep.normalize(dapi, 1, 99.8)` — percentile normalisation on the
   DAPI crop only.
3. **Segment.** StarDist 2D, pretrained `2D_versatile_fluo`, always tiled (§4.4).
4. **Decide membership.** The disc is a circle on the 256 grid and an ellipse here, so
   each nucleus centroid is mapped *back* through the inverse affine and tested against
   `(gx − sec_x)² + (gy − sec_y)² ≤ sec_r²`. Nuclei inside the bounding box but outside
   the disc are dropped.
5. **Measure.** `regionprops` over the marker channel and over DAPI: area, equivalent
   diameter, and the marker's mean, median and 90th percentile over that nucleus's own
   pixels.
6. **Flag.** The nucleus centroid is looked up in the 256-frame `artifact` and `censor`
   masks, if they exist, and the two booleans are written out rather than used to filter.

### 4.3 Processing order, and the one place the group key is read

The default `--order balanced` alternates treatment and control, one section at a time,
round-robins the animals within a group, and walks sections in order within an animal.
The property this buys you: **any prefix of the run is a usable dataset**. Stop half way
and you have both arms measured to about the same depth, rather than five control animals
finished and every exercise animal untouched.

On resume it counts what a previous run already measured and takes from whichever arm is
furthest behind, so a resume *corrects* an imbalance instead of preserving it.

This does read `config.groups.by_animal`, and `config.blinding` says no stage before 06b
may. The exemption is narrow and worth stating plainly: **the group decides only the
order sections are measured in.** Nothing downstream of it depends on when a section was
processed, and the finished dataset is byte-identical whichever order was used. The run
prints which order it used, and `--order uid` makes it blind again.

If `groups.by_animal` is empty, it falls back to plain uid order and says so.

### 4.4 Tiling is not optional

StarDist is called with `n_tiles=(nt, nt)` where `nt = max(2, ceil(sqrt(pixels / 300_000)))`.

Measured on a 1.22 Mpx ROI:

| Tiling | Time | Nuclei found |
|---|---|---|
| none | 121 s | 1177 |
| **2×2** | **4.1 s** | **1177** |
| 4×4 | 5.1 s | — |
| 8×8 | 11.1 s | — |

The cost is wildly non-linear in image size, so tiling is ~30× on a typical ROI — the
difference between a 75-minute run and a 62-hour one. **Nothing about the answer
changes.** Past 2×2 the per-tile overhead takes over again, which is why the target is
roughly 300k px per tile with a 2×2 floor.

### 4.5 Two decisions worth understanding

**Segment on DAPI, never on the marker.** Detecting on the marker channel would define
"number of pERK+ cells" by the threshold twice over: once to find the object and again to
call it positive, so the count and the cut could never be varied independently. Here
nuclei come from the counterstain, the marker is measured afterwards, and positivity is
decided last — in 06a, on a table, with no CZI re-read.

**StarDist rather than threshold-and-watershed.** Not a general preference. Watershed
under-segments where nuclei touch, and Vv, Vd and POA are periventricular. The error
would be worst in exactly those ROIs and mild in Dm and Dl — a region-correlated counting
bias that survives into the results looking like an anatomical finding.

### 4.6 What a background disc is

A background disc is measured by this stage **identically** to a real ROI — same read,
same segmentation, same statistics — and is distinguished only by `roi_kind`. That gives
two things at once:

- a per-section reference level that is *measured* rather than inferred, and
- a false-positive rate, since the same detector runs over tissue you called empty.

It is **not** a negative control. The primary antibody is on that tissue too, so it
measures non-specific binding plus autofluorescence, not zero.

---

## 5. The output: `results/roi_nuclei.csv`

One row per nucleus. 20 columns:

| Column | Meaning |
|---|---|
| `scene_uid` | section identifier, e.g. `LS105_s05a_sc06` |
| `animal` | animal ID (`LS105`) — the only subject key present; no group label |
| `marker` | `AF568` (pERK) or `AF488` (PCNA) |
| `roi_kind` | `roi` or `background` — the *only* thing separating the two |
| `region` | atlas region, e.g. `Dm`, `Dl`, `Vv`; `__background__` for background discs |
| `seed_n` | which numbered atlas seed the ROI answers |
| `roi_index` | 1-based index of the ROI within its section |
| `nucleus_id` | StarDist label within that ROI (unique per ROI, not globally) |
| `czi_x`, `czi_y` | centroid in absolute CZI pixels |
| `sec_x`, `sec_y` | centroid mapped back to the 256 normalised frame |
| `area_um2` | segmented nuclear area |
| `equiv_diam_um` | `2·√(area/π)` — the diameter Abercrombie needs |
| `dapi_mean` | mean DAPI over the nucleus's own pixels |
| `marker_mean`, `marker_median`, `marker_p90` | marker statistics over the same pixels |
| `censored` | `1` if the centroid falls in the section's censor mask |
| `artifact` | `1` if the centroid falls in the section's artifact mask |

Two things to note when using it:

- **`marker_median` is what positivity is judged on** downstream, not the mean — so one
  bright speck inside a nucleus cannot carry it over the line.
- **`censored` and `artifact` are flags, not filters.** Nothing is dropped here. Deciding
  what to do with a nucleus sitting under a saturation censor is an analysis decision and
  is made downstream, where it can be changed.

### 5.1 Current state of this dataset

The pERK pass is **complete**. `roi_nuclei.csv` holds:

- **895,548 rows** across all **130** curated sections, from **11** animals — of which 947 are
  flagged `artifact` and leave the analysis in 06a, so **894,601** are analysable
- 621,906 in real ROIs, 273,642 in background discs
- all `AF568` (pERK) — the PCNA pass has not been run
- 2,069 ROI boxes in `roi_boxes.csv` (1,483 ROIs, 586 background discs)
- **0** nuclei flagged `censored` (see §5.4)

> Updated 2026-09-01. It read 883,077 over 128 sections until then, and that was 128 of
> **130**: two sections had been curated after the last 05a run, so the box set the
> measurements were built from was one export behind. 05a now archives the export it consumed
> (`reformatted/roi_regions_used.csv`), which is how the gap surfaced. The new box set was
> checked as a strict superset — all 2,036 previously measured discs keep their index, kind,
> region and position — before 05c was resumed for the two.

Eleven animals, not twelve: LS53 contributes no measured section. It has 13 curated
sections and no clip-free pERK scans, so it does not survive into the analysis set.

### 5.2 Nucleus size confirms the segmentation is finding nuclei

**Median nucleus diameter came out at 7.33 µm on the first three sections, against the
7.0 µm assumed in `config.detection.nucleus_diameter_um`.** That agreement is worth more
than it looks. Nothing in the pipeline told StarDist how big a nucleus is — the 7.0 in
config is a detection-scale assumption used elsewhere, and it is never passed to the
model. Landing within 5% of it, from segmentation alone, is independent confirmation that
what is being outlined is nuclei rather than noise, debris or merged blobs.

Over the finished run the same figure is **8.33 µm** across all nuclei and **8.68 µm**
over ROI nuclei only — the first three sections were, as it happens, slightly on the small
side. Background discs run smaller than ROIs (median 7.62 µm vs 8.68 µm), which is
consistent with them sitting in less cellular tissue.

**This measured diameter is the `h` the Abercrombie correction now uses**, replacing the
assumed value. Two details matter when quoting it:

- `06a_roi_dataset.py` uses the **mean**, not the median, and computes it **per (marker,
  region)** over ROI nuclei with `artifact = 0` — not one number for the dataset. The
  config note is explicit that this is deliberate: `nucleus_diameter_um` "is a
  detection-scale assumption", and an assumed `h` would bury an unmeasured constant in
  every density.
- On the finished run that gives `h` = **7.81 µm** (Rm) to **9.43 µm** (Dm), so with
  `T` = 14 µm the correction factor `T/(T+h)` runs **0.598 to 0.642** across regions.
  A single assumed 7.0 µm would have given a flat 0.667 everywhere — about 10% high, and
  wrong by a different amount in each region.

### 5.3 ROIs are only modestly brighter than the background discs

On the first three sections, comparing per-nucleus `marker_median`:

| | ROI nuclei | background nuclei | ratio |
|---|---|---|---|
| median `marker_median` | **3,651** | **2,971** | 1.23× |
| 90th percentile of `marker_median` | **6,662** | **5,120** | 1.30× |

*(quoted as 6,664 when first read; the 2-unit difference is percentile convention, not a
different measurement.)*

**This is the pERK problem `LOGS.md` already records, showing up in the object-level
data.** Randlett et al. 2015 uses the same primary — Cell Signaling #4370 — and normalises
every measurement to total ERK, stating that high baseline pERK staining makes
stimulus-dependent changes hard to find. This dataset has no tERK channel, so that
standard control is unavailable, and there is no no-primary control either. A 1.23×
separation between "tissue the operator picked as a region of interest" and "tissue the
operator called empty" is exactly what a high-baseline marker with no normaliser looks
like at the level of individual nuclei.

**This is why the background discs are not optional, and why the cut is built the way it
is.** With separation that modest, where the line falls decides the answer. The cut comes
from each section's own background discs as

```
cut = median(background) + 3 × 1.4826 × MAD(background)
```

— a *spread*-based cut, deliberately not a percentile. Take the top 5% of background
nuclei as "positive" and the false-positive rate is 5% by construction: you have fixed it
by definition and destroyed the only independent check the discs exist to provide. With a
spread-based cut, how many background nuclei land above the line is a **measurement**, and
`detector_specificity.csv` reports it per section and per animal.

Two things that measurement is *not*:

- It is not a negative control. The primary antibody is on the background tissue too, so
  what it measures is non-specific binding plus autofluorescence, not zero.
- It does not license absolute positivity rates. With this separation and no normaliser,
  "X% of cells in region R are pERK-positive" is not a claim these data support. Relative
  comparisons between groups at matched anatomical levels are, because the non-specific
  component is shared.

### 5.4 Clipping does not reach the curated ROIs

Every one of the 128 measured sections has a censor mask on disk, and 27 of them contain
censored pixels — but **no nucleus in the entire 883,077-row file is flagged `censored`.**

That is a real result, not a broken lookup. Of the 346 discs placed on those 27 sections,
exactly **one** overlaps a censored pixel at all, and no nucleus centroid rounds onto it.
The operator placed discs away from the clipped tissue.

The practical consequence: 06a's right-censoring logic — keep censored nuclei in the count,
drop them from the intensity statistics — is inert for this dataset. Worth knowing before
citing it as a safeguard that did something here. It did not need to.

---

## 6. Sanity checks after a run

Worth doing before trusting anything downstream:

1. **Sections finished vs. sections expected.** Compare the distinct `scene_uid` count in
   `roi_nuclei.csv` against the distinct count in `roi_boxes.csv`.
2. **Every finished section has background rows.** A section with `roi` rows but no
   `background` rows will produce no positivity cut in 06a.
3. **`equiv_diam_um` sits near the expected nuclear size.** `config.detection.nucleus_diameter_um`
   is 7.0 µm. A distribution centred far from that means the wrong channel, the wrong
   resolution, or a bad normalisation.
4. **`area_um2` has no enormous outliers.** A single 500 µm² "nucleus" is a merged blob.
5. **Nuclei per ROI is plausible** — roughly 1,000 on a typical periventricular disc, far
   fewer on a small one.

---

## 7. What happens next

| Stage | Script | What it adds |
|---|---|---|
| 6a | `06a_roi_dataset.py` | the positivity cut and the Abercrombie correction; writes `roi_measurements.csv` and `detector_specificity.csv`. **Still blind.** 6c and 6d read it rather than re-deriving — run it first |
| 6b | `06b_join_sampling.py` | joins the sampling workbook — **the unblinding step** |
| 6c | `06c_excel_dataset.py` | `roi_dataset.xlsx`, one row per ROI per sample |
| 6d | `06d_excel_by_slide.py` | the same one level finer: one row per ROI per slide |

06a sets the cut **per section**, from that section's own background discs:

```
cut = median(background) + 3 × 1.4826 × MAD(background)
```

Per section, and robust rather than a percentile. See §5.3 for why both halves of that
matter on this marker.

**One caveat on the stated reason.** The docstring of `06a_roi_dataset.py` justifies the
per-section cut by a background level that "splits the animals into two groups 8,732 units
apart", citing it as a batch effect. `LOGS.md` later overturned that reading: restricting
to clip-free sections showed the two groups are the same (background 10,844 vs 12,300;
tissue 5,542 vs 5,494), and the 1.86× gap is *produced by* clipped pixels pinned at 65,535
dragging the mean up — information loss, not a gain difference. The per-section cut is
still the right choice, but the reason is section-to-section variation in a
high-baseline marker, not a two-group staining batch.

**What the cut actually found, measured 2026-09-01 on the finished pERK run.**
`detector_specificity.csv` reports a false-positive rate of **median 2.1%, range 0.0–8.0%** over
273,332 background nuclei, with all 130 sections carrying at least the 5 background nuclei a cut
needs.

Against that, **pooled ROI positivity is 13.3%** against a pooled background of **2.2%** — a
**5.9x** separation. The median *per disc* is 7.4%; the pooled figure is the one to set beside
the false-positive rate, because that rate is itself a pooled ratio. Either way it is a wider
separation than §5.3's 1.23x intensity ratio suggests, because the cut is on a spread rather
than a level.

The number that decides whether positivity is usable at all is that it is **not
group-correlated**: control 2.2%, exercise 2.0%, and no animal's median leaves the 1.7–3.0%
band (LS105 lowest, LS45 highest). A detector that was more permissive in one arm would have made every positivity comparison
an artefact of itself. This one is not. It is still a false-positive rate and not a negative
control, so §9's limits stand unchanged.

**06c and 06d can be run while 05c is still working.** They read whatever nuclei are on
disk and report how much of the job that is.

---

## 8. Troubleshooting

### 8.1 `--qc` overlays

*Fixed 2026-09-01. It previously created the directory and wrote nothing into it.*

`--qc` writes one PNG per ROI into `<out_root>/qc/roi_detections/`, named
`<uid>_roi<NN>_<kind>_<region>.png`: the DAPI crop, percentile-stretched, with the
segmentation drawn as **boundaries** — **green** for a nucleus that was counted, **red** for one
StarDist found inside the bounding box but outside the disc.

Boundaries rather than filled labels, because a fill hides the thing being judged. The rejects
are drawn on purpose: a box that comes out mostly red means the disc is small or misplaced
relative to what was segmented, and no table shows that. §5.2's diameter check says the
segmentation is finding objects of the right size; only this says they are in the right places.

### 8.2 `WinError 1314: a required privilege is not held by the client`

StarDist's `from_pretrained` finishes by creating a **symlink** next to the extracted
weights, and Windows refuses that without Developer Mode or elevation. The download and
extraction have already succeeded by that point, so 05c catches the error and opens the
extracted folder directly:

```
~/.keras/models/StarDist2D/2D_versatile_fluo/2D_versatile_fluo_extracted/
```

Same weights, same thresholds; only the convenience link is missing. Nothing needs fixing.
That folder exists on this machine, which means the fallback path is the one in use here.

### 8.3 First run needs network access

The pretrained model is downloaded on first use into `~/.keras/models/StarDist2D/`.
Once it is there, later runs are offline.

### 8.4 `no reformatted/roi_boxes_<marker>.csv - run 05a_roi_geometry.py first`

Exactly what it says. 05c will not proceed without 05a's output *for the marker it was asked
for* — `--marker AF488` needs `roi_boxes_AF488.csv`, which needs a PCNA curation export.

### 8.5 A section keeps getting skipped by 05a

Read the skip reason (§3.5). The two that catch people out are the angle mismatch and the
scene-rectangle mismatch — both mean the geometry cannot be reproduced from what is
recorded, and both are refusals rather than failures. Re-running `04a_reformat` for that
section is the fix, not editing the check.

### 8.6 The run is slower than expected

Check that tiling is happening — segmentation should be seconds per ROI, not minutes. The
tile count is computed from the ROI's pixel count with a 2×2 floor, so it cannot be
disabled by configuration; if it is slow, suspect that the process fell back to CPU
TensorFlow on very large boxes.

### 8.7 `ModuleNotFoundError: stardist` / `pylibCZIrw`

You are running the wrong interpreter. 05c needs the one that has both — here,
`work/appenv/Scripts/python.exe`, Python 3.13. Plain `python` on this machine is 3.14 and
cannot import pylibCZIrw at all.

---

## 9. Limits to state when reporting these numbers

- **What is counted is nuclear *profiles*, not nuclei.** Sections are 14 µm and imaged in
  one plane, so a nucleus straddling the cut face appears in the section it is cut into.
  06a applies the Abercrombie correction `N = n·T/(T+h)` with `h` **measured** per region
  and marker from the segmentation — 7.81 to 9.43 µm here, factor 0.598 to 0.642 — not
  taken from the 7.0 µm in config. Report raw and corrected counts side by side and say
  which is which.
- **Abercrombie is not a disector.** It assumes spherical, randomly positioned objects and
  applies no lost-caps correction. The unbiased alternative needs z-stacks this dataset
  does not have.
- **No no-primary controls exist for this dataset, and no tERK channel.** With ROI nuclei
  only 1.23× brighter than background nuclei (§5.3), absolute positivity rates are not
  defensible; relative comparisons between groups at matched anatomical levels are,
  because the non-specific component is shared.
- **Background discs are a false-positive rate, not a zero.** See §4.6 and §5.3.
- **The atlas covers the telencephalon and preoptic area only** — 77 of 101 plates carry no
  region identification, so regional quantification does not currently extend to the
  caudal two-thirds of the brain.

---

## 10. The tools, in detail

Everything below is what actually ran, at the versions installed in `work/appenv`. The
governing rule from the README applies throughout: **if a number derived from a pixel
appears in a figure or table, that pixel was read by pylibCZIrw.**

| Tool | Version | Role in these two stages |
|---|---|---|
| Python | 3.13.15 | the interpreter both stages run under |
| pylibCZIrw | 6.1.0 | reads every pixel that becomes a number |
| StarDist | 0.9.2 | segments the nuclei |
| TensorFlow | 2.21.0 | the neural-network backend StarDist runs on |
| csbdeep | 0.8.2 | intensity normalisation before segmentation |
| scikit-image | 0.26.0 | per-object measurement (`regionprops`) |
| NumPy | 2.5.2 | arrays, the affine algebra, the mask lookups |
| Pillow | 12.3.0 | the overview resize 05a has to replay |
| SciPy | 1.18.1 | the rotation 05a has to replay |

### 10.1 pylibCZIrw 6.1.0 — reading the slide

Zeiss's own, vendor-maintained CZI library. Both stages use it, for different things:

- **05a** calls `czidoc.scenes_bounding_rectangle` — a **header read**, no pixels decoded.
  It needs the scene rectangle because the overview export read it at the time and never
  recorded it, and without it the overview-to-slide mapping has no origin.
- **05c** calls `doc.read(roi=(x0, y0, w, h), plane={"C": c})` once per channel per ROI.
  `roi` is in absolute native pixels, so it reads *only* the box — a few hundred kB out of
  a 1–2 GB file, which is why 2,036 ROIs are tractable at all. No downsampling, no pyramid
  level snapping: 0.65 µm/px as acquired.

**Why this reader and not the faster one.** `czifile` is measured at 0.04 s per section
against pylibCZIrw's 0.26 s and is the only library exposing raw per-tile pixels — but it
reimplements a format specification Zeiss describes as confidential. For pixels that end
up in a paper, provenance outranks 0.2 s. czifile stays in the pipeline for *instrument*
characterisation (illumination field, tile geometry) and never touches the specimen
measurement. Bio-Formats is retired from the data path entirely: via Fiji's Memoizer it
once silently handed back a tile-mode reader and corrupted 238 sections.

**Why the Python version is pinned.** pylibCZIrw ships no cp314 wheel, so 05c cannot run on
Python 3.14. That single constraint is why `work/appenv` is 3.13 and why the packaged
`.exe` is frozen on 3.13.

### 10.2 csbdeep 0.8.2 — `normalize(dapi, 1, 99.8)`

One line, and it decides what the network sees. It maps the 1st percentile of the DAPI
crop to 0 and the 99.8th to 1, linearly, then leaves values outside that range where they
fall.

- **Percentiles, not min/max**: one hot pixel or one dead pixel would otherwise set the
  whole scale.
- **Per ROI, not per section or per dataset**: StarDist's pretrained model expects input in
  roughly this range, and a disc in dim tissue and a disc in bright tissue both have to
  arrive looking like that. This is deliberately *not* the frozen dataset-wide display
  range used for the overviews — those exist for cross-animal visual comparison, this
  exists to put the network in its trained regime.
- **DAPI only.** The marker channel is never normalised, because it is never segmented on.
  Its raw 16-bit values go straight into the output table, which is what makes the
  positivity cut a decision about real intensities rather than about a rescaling.

### 10.3 StarDist 0.9.2 — the segmentation

StarDist (Schmidt et al., MICCAI 2018) predicts, for every pixel, an object probability and
the distances to the object boundary along a fixed set of radial directions — a
**star-convex polygon**. Non-maximum suppression then keeps the best non-overlapping
polygons. The key property for this dataset: **each nucleus is proposed as a whole shape**,
so two nuclei in contact are two polygons rather than one region that a watershed has to
guess how to split.

The pretrained model actually loaded, `2D_versatile_fluo`, as read from its own config:

| Property | Value |
|---|---|
| rays per object | 32 |
| backbone | U-Net, depth 3 |
| prediction grid | 2 × 2 |
| input channels | 1 (single-channel fluorescence) |
| training patch size | 256 × 256 |
| probability threshold | 0.479 |
| NMS threshold | 0.3 |

Both thresholds are the model's own optimised defaults, shipped in `thresholds.json`, and
05c does not override them. `predict_instances` returns a label image; nothing is
retrained, and no per-dataset tuning is applied.

**Why not threshold-and-watershed.** Not a general preference — a specific bias argument.
Watershed under-segments where nuclei touch, and Vv, Vd and POA are periventricular, so the
error would be worst in exactly those ROIs and mild in Dm and Dl. A region-correlated
counting bias survives into the results looking like an anatomical finding.

**Why the model is trusted here.** §5.2 is the check: a median nucleus diameter of 7.33 µm
on the first sections, from a model that was told nothing about expected size, against
7.0 µm assumed independently in config.

**Tiling.** `n_tiles=(nt, nt)` with `nt = max(2, ceil(sqrt(pixels / 300_000)))`. See §4.4 —
121 s to 4.1 s on a 1.22 Mpx ROI for the identical 1,177 nuclei.

**Model cache and the symlink fallback.** `from_pretrained` downloads to
`~/.keras/models/StarDist2D/2D_versatile_fluo/` on first use, then tries to create a
symlink, which Windows refuses without Developer Mode. 05c catches that and loads
`2D_versatile_fluo_extracted/` directly — same weights, same thresholds. See §8.2.

### 10.4 TensorFlow 2.21.0 — the backend

StarDist's U-Net runs on TensorFlow/Keras. 05c never calls it directly; it sets
`TF_CPP_MIN_LOG_LEVEL=3` to keep the console readable and otherwise leaves it alone. It is
the reason this stage is measured in hours and the reason the packaged `.exe` deliberately
does not carry it — a ~500 MB dependency for a stage that is run once, from a terminal.
Whether it finds a GPU changes the runtime and nothing else about the answer.

### 10.5 scikit-image 0.26.0 — `regionprops`

Called **twice** per ROI on the same label image, with two different intensity images:

```python
props  = regionprops(labels, intensity_image=mark)   # the marker
dprops = regionprops(labels, intensity_image=dapi)   # the counterstain
```

One segmentation, two sets of measurements — so `dapi_mean` and `marker_mean` describe
exactly the same pixels of exactly the same nucleus. What is read off each region:

| From `regionprops` | Written as |
|---|---|
| `p.centroid` | `czi_x`, `czi_y`, and after the inverse affine, `sec_x`, `sec_y` |
| `p.area` × 0.65² | `area_um2` |
| `2·√(area/π)` | `equiv_diam_um` — computed from area, not read from the polygon |
| `p.image_intensity[p.image]` | the nucleus's own pixels, from which `marker_mean`, `marker_median`, `marker_p90` and `dapi_mean` are taken |

`p.image_intensity[p.image]` is the part worth noting: it takes the intensity values under
the region's **mask**, not its bounding box. A nucleus is not a rectangle, and averaging
over the box would mix in whatever sits in the corners.

### 10.6 NumPy 2.5.2, Pillow 12.3.0, SciPy 1.18.1

- **NumPy** carries the affine algebra in 05a (`np.linalg.inv` for the inverse map, column
  norms for the anisotropy and the ROI semi-axes), the 128-point circle that becomes the
  bounding box, and the `.npy` artifact and censor masks 05c looks nuclei up in.
- **Pillow** and **SciPy** are there because 05a does not *recompute* the section geometry,
  it **replays** it: `04a_reformat.reformat()` is imported and re-run, so the same
  `PIL.Image.resize` and `scipy.ndimage.rotate` that built the curation frame produce the
  parameters 05a inverts. That is why the `--verify` residual — 0.04 to 0.15 px — is
  Pillow's own downscale rather than an error in the inverse.

### 10.7 The pipeline's own modules

Both stages import earlier stages **by file path**, because the filenames start with digits
and are not importable as modules:

```python
importlib.util.spec_from_file_location("_rf", ".../04a_reformat.py")   # in 05a
importlib.util.spec_from_file_location("_g5", ".../05a_roi_geometry.py")  # in 05c
```

So 05c inherits `CONFIG`, the output paths, `load_csv`, `invert_affine` and `apply_affine`
from 05a, and 05a inherits the reformat itself from 04a. One definition of the geometry,
used by the code that builds it and the code that inverts it — which is the same reasoning
behind reading the affine matrix off three evaluations instead of expanding it by hand.

---

## 10.8 Running the second marker (PCNA / AF488)

The pERK pass is done; PCNA has not been started. The chain is the same, with `--marker`
throughout, and the geometry step is the one that used to be dangerous.

```bash
python scripts/04l_roi_curator.py --marker AF488 --analysis-set
```

Curate and export as for pERK. Note the count: the 454 are **pERK** uids and 30 of them have no
PCNA partner in `perk_overrides.csv`, so this loads **424, not 454** — the shortfall prints
rather than being rounded away.

```bash
python scripts/05a_roi_geometry.py "C:/Users/you/Downloads/roi_regions.csv"
```

No `--marker` needed: 05a reads it from the export's own `marker` column and writes
`roi_boxes_AF488.csv`. `--marker` exists as an assertion — pass it and a mismatch is refused
rather than written to the wrong file. An export that mixes markers is refused outright.

```bash
work/appenv/Scripts/python.exe scripts/05c_detect_rois.py --marker AF488 --limit 2 --qc
work/appenv/Scripts/python.exe scripts/05c_detect_rois.py --marker AF488
```

Smoke-test first and check `equiv_diam_um` lands near 7–8.5 µm as it did for pERK (§5.2), and
look at a couple of the `--qc` overlays (§8.1). A distribution far from that means the wrong
channel or the wrong resolution.

`channels.marker_index = 1` holds for both markers: each CZI is one marker plus DAPI, and the
`a`/`b`/`c` filename suffixes distinguish marker passes rather than rescans.

Rows append to the **same** `roi_nuclei.csv`. The resume set and the balanced-order counter are
scoped to the marker being run, so a PCNA run does not read the pERK sections as already-measured
work when deciding which arm is behind.

```bash
python scripts/06a_roi_dataset.py        # covers both markers in one pass
```

Nothing downstream needs a flag: 06a takes the union of the box files, the cut is per section,
and `h` is per (marker, region) — so the two markers are never pooled.

**Expect it to be slow.** PCNA is roughly six times the pERK volume.

---

## 11. Command summary

```bash
python scripts/05a_roi_geometry.py --verify
```

```bash
python scripts/05a_roi_geometry.py
```

```bash
work/appenv/Scripts/python.exe scripts/05c_detect_rois.py --limit 2
```

```bash
work/appenv/Scripts/python.exe scripts/05c_detect_rois.py
```

```bash
python scripts/06a_roi_dataset.py
```

```bash
python scripts/06c_excel_dataset.py
```
