# LS whole-brain IHC pipeline

Automated screening of pERK and PCNA immunofluorescence across whole-brain transverse sections
of a salmonid, from Zeiss CZI whole-slide scans.

**392.7 GB · 222 CZI files · 2,572 sections · 12 animals · 2 markers**

The goal is qualitative: survey every section, find *where* the signal is, and nominate regions
worth quantifying properly. Opening 2,572 sections by hand is not viable, so the pipeline turns
the dataset into browsable contact sheets, then adds hotspot detection, then propagates named
anatomical regions from an atlas.

Analysis is **blinded by construction** — every output is keyed by animal ID, and the group key
reaches the numbers only at 06b.

Two stages read it earlier, both deliberately and neither in a way that touches a measurement:
`05c` uses it to choose the ORDER sections are measured in, so any prefix of a long run is a
balanced dataset (`--order uid` makes it blind again, and the finished file is identical either
way), and `04l`'s Shotgun deck uses it to lay slides out by treatment, which is not something a
group comparison figure can be built without. Both are documented at `config.groups`, and
leaving `by_animal` empty disables both.

---

## Reader architecture

Three CZI readers were benchmarked. **The ranking on speed is not the ranking that matters.**

| | open | per section | raw tiles | Python |
|---|---|---|---|---|
| Bio-Formats (Fiji) | ~56 s | ~9 s | yes | JVM |
| **pylibCZIrw** 6.1.0 — Zeiss, official | 0.25 s | 0.26 s | no | 3.13 |
| czifile 2026.6.12 — Gohlke, third-party | 0.00 s | 0.04 s | yes | 3.14 |

> **The rule: if a number derived from a pixel appears in a figure or table, that pixel was read
> by pylibCZIrw.** czifile characterises the *instrument* — illumination profile, tile geometry —
> never the *specimen*.

czifile is faster and is the only library exposing raw per-tile pixels, but it reimplements a
format specification its own documentation describes as confidential. pylibCZIrw is
vendor-maintained. For data that ends up in a paper, provenance outranks 0.2 s per section.

czifile is retained because pylibCZIrw deliberately abstracts subblocks away, and per-tile
illumination correction needs raw tiles. The only other route to them is the Bio-Formats path
that silently corrupted 238 sections (see `LOGS.md`).

Every script records its reader in a `reader` column, so provenance is auditable rather than
remembered. Bio-Formats is retired from the data path; it survives only for bUnwarpJ/BigWarp
registration, which operate on overview PNGs.

### Environments

```bash
# main (Python 3.14)
python -m pip install -r requirements.txt

# pylibCZIrw needs its own environment: no cp314 wheel exists yet
py -3.13 -m venv work/czienv
work/czienv/Scripts/python -m pip install -r requirements-czi.txt
```

---

## Pipeline

```bash
cp config.example.json config.json     # fill in the three absolute paths
bash scripts/run_all.sh                # or: bash scripts/run_all.sh from 9
```

Every stage is resumable — re-running skips completed work.

| Stage | Script | What it does |
|---|---|---|
| 0 | `00_manifest.py` | Parses all CZI headers **without extracting**, reconstructs the slide layout, renders slide maps under five candidate mounting conventions |
| 0b | `00b_verify_extraction.py` | Verifies extracted CZIs against the zip central directories; `--crc` checks content, not just size |
| 0c | `00c_channel_identity.py` | Infers which fluorophore carries which marker from spatial signature |
| 1 | `01_overviews.py` | Exports every section at exactly 5.20 µm/px with a frozen display range, plus per-section QC |
| 1b | `01e`, `01f`, `01c`, `01g` | Tile geometry, illumination field, artifact measurement, saturation mapping |
| 1c | `01d_contactsheets.py` | Per-animal montages in rostro-caudal order, plus an HTML gallery |
| 2 | `02_pair_passes.py` | Pairs the two marker passes onto the same physical sections via stage coordinates |
| 4a | `04a_atlas_extract.py` | Extracts labelled plates and region seed points from the atlas PDF |

The 04-series curation chain is not in `run_all.sh`: it needs the operator between the steps —
assigning plates, placing ROIs — so there is nothing to batch.

---

## Quantification

What runs after a curation pass is exported. `docs/nuclei-detection-after-roi-curation.md` is
the full guide; this is the shape of it.

| Stage | Script | What it does |
|---|---|---|
| 5a | `05a_roi_geometry.py` | Puts each curated ROI back on the slide — one affine matrix per section, one CZI pixel box per ROI |
| 5c | `05c_detect_rois.py` | Reads those boxes at native 0.65 µm/px, segments nuclei on DAPI with StarDist, measures the marker inside each mask |
| 6a | `06a_roi_dataset.py` | The positivity cut, the detector's false-positive rate, and Abercrombie. **Still blind** |
| 6b | `06b_join_sampling.py` | Joins the sampling workbook — **the unblinding step** |
| 6c / 6d | `06c_excel_dataset.py`, `06d_excel_by_slide.py` | The spreadsheets, per sample and per slide |
| 6e | `06e_refresh_loop.py` | Rebuilds 6a→6d and every figure hourly while 5c is still running, once per measured marker |

Figures come from `analysis/`: `plot_roi_figures.R` (per-ROI, with statistics, plus the pptx) and
`plot_by_sample.R` / `plot_by_slide.R` (the two overview panels). 6e runs all three, so running it
is how they stay in step with the workbooks.

```bash
python scripts/05a_roi_geometry.py --verify     # check the map first: 0.04-0.15 px
python scripts/05a_roi_geometry.py
work/appenv/Scripts/python.exe scripts/05c_detect_rois.py     # hours; resumable
python scripts/06a_roi_dataset.py
python scripts/06c_excel_dataset.py
python scripts/06d_excel_by_slide.py     # the figures read THIS workbook
Rscript analysis/plot_roi_figures.R                           # LS_MARKER=AF488 for PCNA
```

**`results/roi_nuclei.csv` is the artefact that matters** — one row per nucleus, with the
marker's mean, median and 90th percentile over that nucleus's own pixels. Everything after it is
arithmetic on a table, so changing your mind about where positivity falls costs a re-run of 06a,
not a re-read of 130 CZI scenes.

**06a owns every per-ROI number.** 6c and 6d group and format its output; they do not re-derive
it. They used to, and the two implementations had drifted — 06a computes Abercrombie's `h` per
(marker, region) as `config` declares, the copy in 06c computed it per (animal, region), and
nothing compared them. `tests/test_roi_dataset.py` now does.

**Two measures, side by side.** `cells_per_mm2` is every DAPI nucleus; `positive_cells_per_mm2`
is the subset over that section's own cut, taken from its own background discs as
`median + 3 × 1.4826 × MAD`. A spread and not a percentile, deliberately: a percentile would fix
the false-positive rate by construction and destroy the only independent check the background
discs exist to provide. Measured here at **2.1% median**, and — the number that decides whether
positivity is usable at all — **not group-correlated** (control 2.2%, exercise 2.0%). Pooled ROI
positivity is 13.3% against that, a 5.9x separation.

**One marker per figure.** The sheets carry both, keyed by `(sample, marker, ROI)`, but a
figure draws one — `LS_MARKER` selects it and defaults to `AF568`. Two markers in one panel
would share a mean bar, an SEM bar and a significance test, and `roi_stats.R` picks `lm` or a
mixed model on whether an animal has more than one row, so a second antibody would read as a
second slide. Non-default markers write to suffixed folders and their own pptx.

`05c --qc` writes one overlay PNG per ROI to `qc/roi_detections/`: the DAPI crop with nucleus
boundaries, green counted and red found-but-outside-the-disc. Nuclear diameter says the
segmentation is finding objects of the right size; only the overlay says they are in the right
places.

---

## Desktop app

```bash
run_app.bat
```

`run_app.bat` prefers `work/appenv`, the same Python 3.13 venv `build_app.bat` freezes the exe
from. Running `python -m app` against an interpreter without PySide6 now says which interpreter
it is and how to fix it, rather than writing a bare traceback to `lsapp-crash.log`.

One window: the pipeline down the left with status read from disk, a log pane,
and the three HTML curators embedded. The curator pages themselves are unchanged
— the app hosts them, it does not reimplement them, and opening the same file in
a browser still works exactly as before.

**Add slides** takes a folder, or individual `.czi` files. A folder sets
`source_dir` and moves nothing. Picking individual files from one folder writes
an allowlist to `source_files` in config, which `00_manifest.discover_sources()`
honours — so "process these, not the whole folder" costs no copying. Files
genuinely scattered across folders are hardlinked where the filesystem allows it;
the slide drive here is exFAT, which supports neither hardlinks nor symlinks, so
that case offers a copy and states the size first. The screen flags any filename
that does not match the manifest's grammar, because such a file is invisible to
every stage and is otherwise dropped in silence.

**Curation state.** Decisions made in the app are written to
`<out_root>/curation/<key>.json`, one file per curator, atomically. The app seeds
the page's `localStorage` from those files before the page's own script runs, and
mirrors every write back. Curation done earlier in a web browser lives in that
browser's storage, which no other application can read: open
`<out_root>/reformatted/export_curation_state.html` in that browser, save the
JSON, then use **Pipeline → Import curation state**.

### What the app does not run

The Fiji tile-field chain — steps 3–8 of `run_all.sh`. Those are a one-time
instrument characterisation, they are already complete for this dataset
(`qc/flatfield/tilefield_c*.npy`), and `01_overviews` applies the field it finds
and works without one. They stay in `run_all.sh`, and the app lists them greyed
out with the reason rather than hiding them.

### Python version

The app runs the stages **in-process**, so one interpreter has to satisfy all of
them. `pylibCZIrw` publishes no cp314 wheel, so the overview stage needs Python
**3.13 or earlier**. Running from source on 3.14 works for everything except that
stage.

### Building the .exe

```bash
build_app.bat
```

It creates a Python 3.13 venv under `work/appenv` on first run and reuses it
afterwards. **3.13, not 3.14**: `pylibCZIrw` publishes no cp314 wheel, and since
the app runs its stages in-process, the interpreter that freezes the app is the
one that has to be able to read CZIs.

`config.json` is read from **beside the executable**, not from inside the bundle,
so it stays visible and editable. On first run, with no config there, the setup
dialog asks for the three paths and writes it.

One-folder, roughly 500 MB. Not one-file: QtWebEngine runs a helper process that
must find its resources on disk, and a one-file build leaves the curator panes
blank.

### Checking a build

```bash
"LS pipeline.exe" --self-test
```

Opens the window, starts the local server and loads a curator, then reports
PASS/FAIL per check and exits. Results go to `lsapp-selftest.log` beside the
executable as well as to stdout, because a windowed build has no console. This
is how to confirm a copy works on a machine you are not sitting at — a window
appearing proves nothing about whether QtWebEngine actually renders.

---

## Tests

```bash
bash tests/run.sh
```

Node suites over the ROI curator's own JavaScript, evaluated against a small DOM
stub. They cover seed ordering, guided placement, the landmark radius, both
markers in one page, the filters, rotation, and what reaches the exports — 70-odd
assertions, most of which exist because they caught something.

`run.sh` regenerates the curator with `--no-seed` first and extracts its script.
That matters: the page normally embeds whatever curation is in
`out_root/curation`, and a suite reading that would start with hundreds of
sections it knows nothing about, with counts that changed every time someone
curated. The page is regenerated *with* the seed afterwards, so running the tests
does not quietly downgrade the file you use.

**They check logic, not rendering.** Canvas calls are swallowed by the stub, so
nothing here says anything about what is drawn — that is checked in a real
browser, by reading pixels back off the canvas.

---

## Design notes

Things that are non-obvious, and that took measurement to get right.

**Display ranges are frozen dataset-wide, computed from tissue pixels only.** Per-image
auto-contrast would make every section look equally bright and destroy the cross-animal
comparison that is the entire point. Sampling the whole frame is also wrong here: one channel's
background is brighter than the brain, which pinned the top of the range at the sensor ceiling.

**All tissue thresholding is Otsu in log space.** These channels are extremely skewed — DAPI runs
a median near 500 against a 99.9th percentile near 30,000. Plain Otsu chases that tail and
returns a threshold above nearly every pixel.

**Section pairing tolerances are fractions of section spacing, never absolute.** Scan boxes are
hand-drawn, so a box centre sits 1–2.5 mm from the section centre even on identical slides. What
distinguishes same-slide from different-slide is the residual *relative to how far apart sections
are*.

**Detection is designed to ignore background level.** Difference-of-Gaussians matched to nucleus
diameter is a band-pass that rejects everything varying more slowly than a cell — illumination
gradients, autofluorescence and non-specific binding at once. Candidates are then scored by local
contrast (peak ÷ surrounding annulus median), which is dimensionless, so a 15% illumination
gradient cancels.

**Tile geometry is read from the file, not estimated from the image.** 2040 px tiles on an
1836 px pitch (1193.40 µm), 10% overlap — confirmed independently by pylibCZIrw's subblock
enumeration and by parsing the CZI directory directly. The power-spectrum estimate was 1–3% off,
which accumulates to a fifth of a tile across a section.

**Long-running stages checkpoint per item, atomically.** This runs against an external drive that
has dropped writes; a crash must cost one file, not five hours.

---

## Limitations

**No no-primary controls exist for this dataset.** Non-specific secondary binding cannot be
separated from genuine low-level specific signal, so **absolute positivity rates are not
defensible** — "X% of cells in region R are marker-positive" is not a claim these data support.
Relative comparisons between groups at matched anatomical levels are, because the non-specific
component is shared. Three internal references stand in: optical zero from off-tissue glass, a
tissue-negative floor from nuclei-poor fibre tracts within the same section, and object-level
annulus background.

**Tiles are JPEG-XR compressed** — typically lossy, and fixed at acquisition.

**No shading correction was applied at acquisition**, and tiles were never blended, so the
illumination profile repeats at the tile pitch across every section. Uncorrected, a fixed
threshold detects materially more objects near tile centres.

**The atlas covers the telencephalon and preoptic area only.** 77 of 101 plates carry no region
identification, so the caudal two-thirds of the brain needs labelling before regional
quantification extends there.

---

## Repository contents

Code only. Nothing derived from the imaging data is committed, and neither are the atlas plates —
they are extracted from a PDF that is not ours to redistribute. Run `04a_atlas_extract.py`
against your own copy.

See **`LOGS.md`** for the change history: what changed, why, what it cost, and which earlier
decisions it reversed.
