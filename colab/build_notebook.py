"""Build LS_preprocess_gpu.ipynb from ls_gpu_preprocess.py.

One source of truth. The notebook embeds the module in a `%%writefile` cell so it
is self-contained in Colab, and this script regenerates it whenever the module
changes - otherwise the two drift and the notebook silently runs old thresholds.

Run:  python build_notebook.py
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.join(HERE, "ls_gpu_preprocess.py")
OUT = os.path.join(HERE, "LS_preprocess_gpu.ipynb")


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip().splitlines(True)}


def code(text):
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": text.strip().splitlines(True)}


with open(MODULE, encoding="utf-8") as fh:
    module_src = fh.read()

cells = []

cells.append(md(r"""
# LS pERK / PCNA — GPU preprocessing

Runs the four section-cleaning stages in **one pass per section**, on GPU:

| stage | what it decides |
|---|---|
| quality metrics | tissue geometry, focus, largest contiguous piece |
| artifact mask | bubbles, antibody aggregates, fibres *inside* the tissue |
| symmetry axis | residual rotation putting the midline vertical |
| exclusion call | which sections cannot be measured at all |

Outputs, per section, replacing the input:

* `<uid>_clean.png` — the overview with artifact pixels zeroed (**the processed copy**)
* `<uid>_artifact.png` — the label mask (0 clean, 1 compact, 2 elongated)
* one row in `results.csv`

---

## ⚠️ This notebook can delete files from your Drive

`DELETE_INPUTS` is **False** by default. Set it to `True` only once you have
confirmed a test batch looks right.

When it is on, an input is deleted **only after** every output for it exists and
is non-empty. It never touches anything outside `IN_DIR`.

**Keep the originals on D: — do not make Drive the only copy of anything.**
The overviews here are regenerable from the CZIs; the CZIs are not regenerable.

---

## Two things to know before trusting the numbers

**Parity was checked, and it caught a real bug.** An early version measured the
symmetry residual on an unrotated mask while `04h` measures it on top of `04a`'s
principal-axis rotation — they disagreed by up to 35°. After the fix, against the
CPU outputs on 14 sections: `largest_mm2` **exact**, symmetry **exact**, artifact
area within a median 0.012 percentage points.

**`focus_png` is not `focus_score`.** The original was computed on 16-bit data
before display ranging; this sees the 8-bit PNG. Same formula, different input,
so the values are not comparable. The calibration cell maps the 0.070 cut across
by matching *what fraction of sections it removes*, not its numeric value.
"""))

cells.append(md("## 1. GPU"))
cells.append(code(r"""
!nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || echo "NO GPU - Runtime > Change runtime type > T4 GPU"
import sys
try:
    import cupy, cupyx.scipy.ndimage      # preinstalled on Colab GPU runtimes
    cupy.zeros(1) + 1
    print("cupy", cupy.__version__, "- GPU path active")
except Exception as e:
    print("cupy unavailable:", e)
    print("The module falls back to scipy on CPU and still produces identical results,")
    print("just slower. Switch the runtime to a T4 GPU for the speedup.")
"""))

cells.append(md("## 2. Mount Drive and set paths"))
cells.append(code(r"""
from google.colab import drive
drive.mount('/content/drive')

import os

# --- edit these -------------------------------------------------------------
ROOT     = '/content/drive/MyDrive/LS_preprocess'
IN_DIR   = f'{ROOT}/in'          # upload <uid>_DAPI.png here
OUT_DIR  = f'{ROOT}/out'         # clean + artifact masks land here
RESULTS  = f'{ROOT}/results.csv' # one row per section, appended as it goes
DONE_LOG = f'{ROOT}/done.txt'    # resume marker - safe to delete to start over
FOCUS_CSV= f'{ROOT}/focus.csv'   # copy of qc/focus.csv, for focus calibration

DELETE_INPUTS = False   # <-- leave False for the first batch. See the warning above.
# ----------------------------------------------------------------------------

for d in (ROOT, IN_DIR, OUT_DIR):
    os.makedirs(d, exist_ok=True)

pending = sorted(f for f in os.listdir(IN_DIR) if f.endswith('_DAPI.png'))
print(f'{len(pending)} input files in {IN_DIR}')
print(f'DELETE_INPUTS = {DELETE_INPUTS}')
"""))

cells.append(md("## 3. Write the processing module\n\n"
                "Generated from `colab/ls_gpu_preprocess.py` — regenerate this notebook with "
                "`python colab/build_notebook.py` after changing it."))
cells.append(code("%%writefile ls_gpu_preprocess.py\n" + module_src))

cells.append(md("## 4. Self-test\n\nChecks the FFT shift search against the loop it replaces, "
                "and the GPU tissue mask against scipy. **Do not skip this.**"))
cells.append(code(r"""
import importlib, ls_gpu_preprocess as G
importlib.reload(G)
assert G.selftest(), "self-test failed - do not trust this run"
"""))

cells.append(md("## 5. Calibrate the focus cut\n\n"
                "Upload `qc/focus.csv` to `ROOT`. If it is missing, this falls back to the 5th "
                "percentile of this batch, which is cruder — it assumes the batch has the same "
                "proportion of blurred sections as the whole dataset."))
cells.append(code(r"""
import os
FOCUS_CUT = None
if os.path.exists(FOCUS_CSV):
    print("focus.csv found - calibration will run after the first batch of metrics")
else:
    print("focus.csv NOT found. Upload qc/focus.csv to", ROOT)
    print("Falling back to the 5th percentile of this batch.")
"""))

cells.append(md("## 6. Benchmark\n\n"
                "Measures the real speedup on your data instead of quoting one. Runs a few "
                "sections, then the same ones with the GPU path disabled."))
cells.append(code(r"""
import time, importlib, ls_gpu_preprocess as G

sample = pending[:6]
if not sample:
    print("nothing in IN_DIR to benchmark")
else:
    t0 = time.time()
    for f in sample:
        G.process_one(os.path.join(IN_DIR, f))
    gpu_t = time.time() - t0

    G.GPU, _xp, _ndi = False, G.xp, G.ndi
    import numpy as _np, scipy.ndimage as _sn
    G.xp, G.ndi = _np, _sn
    t0 = time.time()
    for f in sample:
        G.process_one(os.path.join(IN_DIR, f))
    cpu_t = time.time() - t0
    importlib.reload(G)

    print(f"{len(sample)} sections")
    print(f"  GPU path : {gpu_t:6.1f} s  ({gpu_t/len(sample):.2f} s/section)")
    print(f"  CPU path : {cpu_t:6.1f} s  ({cpu_t/len(sample):.2f} s/section)")
    print(f"  speedup  : {cpu_t/max(gpu_t,1e-9):.1f}x")
    print(f"\n  projected for 1381 sections: GPU {1381*gpu_t/len(sample)/60:.0f} min, "
          f"CPU {1381*cpu_t/len(sample)/60:.0f} min")
"""))

cells.append(md("## 7. Process\n\n"
                "Streams one section at a time. Appends to `results.csv` and `done.txt` after "
                "each, so a disconnect costs one section. **Deletes the input only after every "
                "output exists and is non-empty**, and only if `DELETE_INPUTS` is True."))
cells.append(code(r"""
import csv, os, time, importlib
import ls_gpu_preprocess as G
importlib.reload(G)

done = set()
if os.path.exists(DONE_LOG):
    done = set(open(DONE_LOG, encoding='utf-8').read().split())
todo = [f for f in sorted(os.listdir(IN_DIR)) if f.endswith('_DAPI.png')
        and f.replace('_DAPI.png','') not in done]
print(f'{len(done)} already done, {len(todo)} to go')

FIELDS = None
if os.path.exists(RESULTS):
    with open(RESULTS, newline='', encoding='utf-8') as fh:
        FIELDS = next(csv.reader(fh), None)

t_start = time.time()
deleted = kept = failed = 0
for i, fname in enumerate(todo, 1):
    uid = fname.replace('_DAPI.png', '')
    src = os.path.join(IN_DIR, fname)
    try:
        row, written = G.process_and_clean(src, OUT_DIR)
    except Exception as e:                       # noqa: BLE001
        print(f'  !! {uid}: {type(e).__name__}: {e}')
        failed += 1
        continue

    # Verify BEFORE deleting anything. An output that is missing or suspiciously
    # small means the write did not land - Drive does fail mid-run.
    ok = all(os.path.exists(p) and os.path.getsize(p) > 512 for p in written)

    if FIELDS is None:
        FIELDS = list(row.keys())
        with open(RESULTS, 'w', newline='', encoding='utf-8') as fh:
            csv.DictWriter(fh, fieldnames=FIELDS).writeheader()
    with open(RESULTS, 'a', newline='', encoding='utf-8') as fh:
        csv.DictWriter(fh, fieldnames=FIELDS, extrasaction='ignore').writerow(row)
    with open(DONE_LOG, 'a', encoding='utf-8') as fh:
        fh.write(uid + '\n')

    if ok and DELETE_INPUTS:
        os.remove(src)
        deleted += 1
    else:
        kept += 1
        if not ok:
            print(f'  !! {uid}: outputs failed verification - input KEPT')

    if i % 25 == 0 or i == len(todo):
        el = time.time() - t_start
        eta = el / i * (len(todo) - i)
        print(f'  {i}/{len(todo)}  {el/60:.1f} min elapsed, ~{eta/60:.1f} min left '
              f'| deleted {deleted}, kept {kept}, failed {failed}')

print(f'\ndone. processed {len(todo)-failed}, failed {failed}, '
      f'inputs deleted {deleted}, kept {kept}')
"""))

cells.append(md("## 8. Exclusion calls and summary\n\n"
                "Applies `04f`'s two rules using the calibrated focus cut, and writes the final "
                "table. Download `results.csv` and drop it next to the local outputs."))
cells.append(code(r"""
import csv, numpy as np, importlib
import ls_gpu_preprocess as G
importlib.reload(G)

rows = list(csv.DictReader(open(RESULTS, newline='', encoding='utf-8')))
rows = [r for r in rows if r.get('focus_png') not in (None, '')]
print(f'{len(rows)} rows')

if os.path.exists(FOCUS_CSV):
    FOCUS_CUT, pct = G.calibrate_focus(rows, FOCUS_CSV)
    print(f'focus cut calibrated to {FOCUS_CUT:.4f} '
          f'(the 16-bit cut of {G.FOCUS_MIN_16BIT} removed {pct:.1f}% of sections)')
else:
    vals = np.array([float(r['focus_png']) for r in rows])
    FOCUS_CUT = float(np.percentile(vals, 5.0))
    print(f'no focus.csv - falling back to the 5th percentile: {FOCUS_CUT:.4f}')

rows = G.add_exclusion_calls(rows, FOCUS_CUT)

out = RESULTS.replace('.csv', '_final.csv')
with open(out, 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)

prop = sum(int(r['proposed']) for r in rows)
art  = np.array([float(r['artifact_pct_of_tissue']) for r in rows])
symr = [abs(int(r['sym_rotation'])) for r in rows if r.get('sym_rotation') not in (None, '')]
hi   = sum(1 for r in rows if r.get('sym_confidence') == 'high')

print(f'\nwrote {out}')
print(f'  proposed for exclusion : {prop} ({100*prop/len(rows):.1f}%)')
for c in sorted({r['artifact_class'] for r in rows if r['artifact_class']}):
    print(f'      {c:<22} {sum(1 for r in rows if r["artifact_class"]==c)}')
print(f'  artifact % of tissue   : median {np.median(art):.3f}, p95 {np.percentile(art,95):.3f}')
if symr:
    print(f'  symmetry correction    : median {np.median(symr):.0f} deg, '
          f'p90 {np.percentile(symr,90):.0f}, {hi} high confidence')
"""))

cells.append(md("""
## 9. Bring the results home

Download `results_final.csv` and the `out/` folder, then:

```bash
# metrics slot straight into the local curator inputs
python scripts/04d_rotation_curator.py
```

The columns map onto the local files as:

| notebook column | local file |
|---|---|
| `largest_mm2`, `n_pieces`, `proposed`, `artifact_class`, `reason` | `reformatted/exclusion_candidates.csv` |
| `n_compact`, `n_elongated`, `artifact_pct_of_tissue`, `measurable_mm2` | `artifacts/artifact_summary.csv` |
| `sym_rotation`, `sym_score`, `sym_confidence` | `reformatted/symmetry_proposals.csv` |

**Known difference, not a bug:** artifact area differs from the local `04g` by a
median 0.012 percentage points, because `04g` builds its tissue mask by resizing
the float array while `04a` resizes the 8-bit image. This module follows `04a`,
which is the canonical path. Worth aligning `04g` to match.
"""))

nb = {"cells": cells,
      "metadata": {"accelerator": "GPU",
                   "colab": {"provenance": [], "gpuType": "T4"},
                   "kernelspec": {"display_name": "Python 3", "name": "python3"},
                   "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 0}

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(nb, fh, indent=1)
print(f"wrote {OUT}  ({len(cells)} cells, module {len(module_src.splitlines())} lines)")
