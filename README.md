# LS whole-brain IHC pipeline

Automated screening of pERK and PCNA immunofluorescence across whole-brain transverse sections
of a salmonid, from Zeiss CZI whole-slide scans.

**392.7 GB · 222 CZI files · 2,572 sections · 12 animals · 2 markers**

The goal is qualitative: survey every section, find *where* the signal is, and nominate regions
worth quantifying properly. Opening 2,572 sections by hand is not viable, so the pipeline turns
the dataset into browsable contact sheets, then adds hotspot detection, then propagates named
anatomical regions from an atlas.

Analysis is **blinded by construction** — every output is keyed by animal ID, and the group key
is joined only in the final step.

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

---

## Desktop app

```bash
pip install -r requirements.txt
run_app.bat                            # or: python -m app
```

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
