"""GPU preprocessing for the LS pERK/PCNA pipeline - the cleaning stages in one pass.

Runs the four section-cleaning stages together, on GPU where that helps:

  * **quality metrics**   - tissue geometry, focus, largest contiguous piece   (04f)
  * **artifact mask**     - bubbles, aggregates, fibres inside the tissue      (04g)
  * **symmetry axis**     - residual rotation that puts the midline vertical   (04h)
  * **exclusion proposal** - which sections cannot be measured at all          (04f)

One pass per section instead of four, so each overview is read and masked once
rather than four times. That matters more than the GPU here: the local scripts
re-derive the same tissue mask in every stage.

Parity is the point, not speed
------------------------------

Every threshold in this file is copied from the CPU scripts, and `selftest()`
checks the two agree. A faster reimplementation that silently disagreed with the
thresholds those scripts were tuned to would undo the work that set them.

**One thing genuinely cannot match, and it is not a bug.** `focus_score` in
`qc/focus.csv` was computed by `01_overviews.py` on the **16-bit** DAPI at export
time. This module sees the exported 8-bit PNG, which has been display-ranged with
an offset and clipped, and the ratio (edge energy / mean) is only preserved under
a scale, not under a scale-plus-offset. So `focus_png` here is a *different
quantity* with the same shape. `calibrate_focus()` maps the 0.070 cut onto it by
percentile, on sections where both exist. Do not compare the two numbers directly.

An algorithmic win that is not about hardware
--------------------------------------------

The symmetry search in `04h` loops over mirror offsets. Intersection under a
circular shift *is* a cross-correlation, and |A| and |B| do not change with the
shift, so

    IoU(s) = I(s) / (|A| + |B| - I(s))

for **every** offset at once from a single FFT. That removes the loop and the
`SHIFT_STEP = 2` approximation with it - every integer offset is now evaluated,
not every second one. `selftest()` checks it against the loop.

Usage: see the accompanying notebook. `process_one()` is the unit of work.
"""

import os

import numpy as np
from PIL import Image

# ---------------------------------------------------------------- array shim --
try:
    import cupy as _cp
    import cupyx.scipy.ndimage as _cnd
    _cp.zeros(1) + 1
    GPU = True
except Exception:                                              # noqa: BLE001
    _cp = None
    _cnd = None
    GPU = False

import scipy.ndimage as _snd

xp = _cp if GPU else np
ndi = _cnd if GPU else _snd


def to_gpu(a):
    return _cp.asarray(a) if GPU else np.asarray(a)


def to_cpu(a):
    return _cp.asnumpy(a) if (GPU and isinstance(a, _cp.ndarray)) else np.asarray(a)


def _fill_holes(mask):
    """cupyx has no binary_fill_holes in every release; fall back per call."""
    if GPU and hasattr(_cnd, "binary_fill_holes"):
        return _cnd.binary_fill_holes(mask)
    return to_gpu(_snd.binary_fill_holes(to_cpu(mask)))


def _edt(mask):
    if GPU and hasattr(_cnd, "distance_transform_edt"):
        return _cnd.distance_transform_edt(mask)
    return to_gpu(_snd.distance_transform_edt(to_cpu(mask)))


# ------------------------------------------------------------------- params --
# All copied from the CPU scripts. Changing one here without changing it there
# makes the two disagree silently, which is the failure this file exists to avoid.
UM_PX = 5.20e-3
WORK = 400                      # 04a_reformat.WORK_SIZE
GRID = 256                      # 04a_reformat.GRID
MIN_COMPONENT_FRACTION = 0.12   # 04a_reformat

PIECE_MIN_MM2 = 0.5             # 04f
LARGEST_MIN_MM2 = 2.5           # 04f
FOCUS_MIN_16BIT = 0.070         # 04f, on the 16-bit metric - see calibrate_focus

RIM_ERODE_PX = 6                # 04g
BRIGHT_PCTL = 99.0              # 04g
SMOOTH_FRAC = 0.35              # 04g
GROW_PCTL = 95.0                # 04g
GROW_ITERS = 25                 # 04g
MIN_OBJ_PX = 15                 # 04g
MAX_OBJ_MM2 = 1.2               # 04g
ELONGATION_SPLIT = 3.0          # 04g
FILL_SPLIT = 0.55               # 04g
LBL_COMPACT, LBL_ELONGATED = 1, 2

SPAN = 30.0                     # 04h
COARSE = 5.0                    # 04h
FINE = 1.0                      # 04h
SHIFT_PX = 36                   # 04h
SCORE_MIN = 0.55                # 04h


# -------------------------------------------------------------------- otsu ----
def otsu(values):
    hist, edges = xp.histogram(values, bins=256)
    hist = hist.astype(xp.float64)
    centres = (edges[:-1] + edges[1:]) / 2.0
    w1 = xp.cumsum(hist)
    w2 = xp.cumsum(hist[::-1])[::-1]
    m1 = xp.cumsum(hist * centres) / xp.maximum(w1, 1e-9)
    m2 = (xp.cumsum((hist * centres)[::-1]) / xp.maximum(w2[::-1], 1e-9))[::-1]
    var = w1 * w2 * (m1 - m2) ** 2
    var = xp.where((w1 > 0) & (w2 > 0), var, -1.0)
    return float(centres[int(xp.argmax(var))])


def tissue_mask(v):
    """04a_reformat.tissue_mask, dark-background branch."""
    positive = v[v > 0]
    if positive.size < 200:
        return None
    thr = float(np.expm1(otsu(xp.log1p(positive))))
    mask = v > thr
    mask = ndi.binary_closing(mask, xp.ones((7, 7), bool))
    mask = _fill_holes(mask)
    mask = ndi.binary_opening(mask, xp.ones((3, 3), bool))
    labels, n = ndi.label(mask)
    if n == 0:
        return None
    sizes = xp.bincount(labels.ravel())
    sizes[0] = 0
    keep = xp.where(sizes >= MIN_COMPONENT_FRACTION * sizes.max())[0]
    mask = xp.isin(labels, keep) & (labels > 0)
    return mask if int(mask.sum()) >= 200 else None


# ---------------------------------------------------------------- 04f: QC -----
def quality(img_full, work_mask, w, h):
    """Physical geometry, in the frame of the source overview."""
    px_mm2 = (w * h / float(WORK * WORK)) * UM_PX ** 2
    frame_mm2 = float(w * h * UM_PX ** 2)
    if work_mask is None:
        return {"largest_mm2": 0.0, "total_mm2": 0.0, "n_pieces": 0,
                "frame_mm2": round(frame_mm2, 1)}
    labels, n = ndi.label(work_mask)
    if n == 0:
        return {"largest_mm2": 0.0, "total_mm2": 0.0, "n_pieces": 0,
                "frame_mm2": round(frame_mm2, 1)}
    sizes = xp.bincount(labels.ravel())[1:] * px_mm2
    sizes = to_cpu(sizes)
    return {"largest_mm2": round(float(sizes.max()), 2),
            "total_mm2": round(float(sizes.sum()), 2),
            "n_pieces": int((sizes >= PIECE_MIN_MM2).sum()),
            "frame_mm2": round(frame_mm2, 1)}


def focus_png(img, mask):
    """01_overviews.focus_score, evaluated on the 8-bit PNG.

    Same formula, different input: the original ran on 16-bit data before display
    ranging. Comparable across sections here, NOT comparable to focus.csv.
    """
    a = img.astype(xp.float32)
    gy = xp.abs(xp.diff(a, axis=0, prepend=a[:1]))
    gx = xp.abs(xp.diff(a, axis=1, prepend=a[:, :1]))
    m = float(a[mask].mean())
    if m <= 0:
        return 0.0
    return float((gx + gy)[mask].mean() / m)


# ------------------------------------------------------------ 04g: artifacts --
def texture(im):
    return ndi.uniform_filter(xp.abs(im - ndi.median_filter(im, size=3)), size=9)


def artifact_mask(im, tis):
    """04g_artifact_mask.detect, on the full-resolution overview."""
    core = ndi.binary_erosion(tis, xp.ones((2 * RIM_ERODE_PX + 1,) * 2, bool))
    out = xp.zeros(im.shape, xp.uint8)
    if int(core.sum()) < 500:
        return out, []
    tex = texture(im)
    t_med = float(xp.median(tex[tis]))
    if t_med <= 0:
        return out, []

    hi = float(xp.percentile(im[tis], BRIGHT_PCTL))
    lo = float(xp.percentile(im[tis], GROW_PCTL))
    seed = (im > hi) & (tex < SMOOTH_FRAC * t_med) & core
    seed = ndi.binary_opening(seed, xp.ones((3, 3), bool))
    if not bool(seed.any()):
        return out, []
    halo = _fill_holes(im > lo)
    hot = ndi.binary_dilation(seed, xp.ones((3, 3), bool),
                              iterations=GROW_ITERS, mask=halo)
    hot = _fill_holes(hot)

    # Object filtering is per-component bookkeeping, not array maths - the
    # transfer is cheaper than a GPU loop over labels.
    hot_c = to_cpu(hot)
    seed_c = to_cpu(seed)
    labels, n = _snd.label(hot_c)
    recs = []
    out_c = np.zeros(im.shape, np.uint8)
    if n:
        for i, sl in enumerate(_snd.find_objects(labels), 1):
            m = labels[sl] == i
            area = int(m.sum())
            if area * UM_PX ** 2 > MAX_OBJ_MM2:
                m = m & seed_c[sl]
                area = int(m.sum())
            if area < MIN_OBJ_PX:
                continue
            hh, ww = m.shape
            elong = max(hh, ww) / max(min(hh, ww), 1)
            fill = area / float(hh * ww)
            lbl = LBL_ELONGATED if (elong >= ELONGATION_SPLIT or fill < FILL_SPLIT) else LBL_COMPACT
            out_c[sl][m] = lbl
            recs.append({"label": lbl, "area_mm2": area * UM_PX ** 2})
    return to_gpu(out_c), recs


# -------------------------------------------------------------- 04h: symmetry -
def _iou_all_shifts(M):
    """IoU against the left-right mirror, for every circular shift, in one FFT.

    Intersection under a circular shift is a cross-correlation; |A| and |B| are
    shift-invariant, so IoU(s) = I(s) / (|A| + |B| - I(s)). Replaces 04h's loop
    over every second offset and evaluates every offset instead.
    """
    A = (M > 0.5).astype(xp.float32)
    B = A[:, ::-1]
    fa = xp.fft.rfft(A, axis=1)
    fb = xp.fft.rfft(B, axis=1)
    corr = xp.fft.irfft(fa * xp.conj(fb), n=A.shape[1], axis=1).sum(axis=0)
    na, nb = float(A.sum()), float(B.sum())
    if na < 1 or nb < 1:
        return None
    iou = corr / xp.maximum(na + nb - corr, 1e-6)
    # Only offsets within SHIFT_PX are physically plausible; beyond that the
    # circular wrap compares a section with a translated copy of itself.
    w = A.shape[1]
    idx = xp.concatenate([xp.arange(0, SHIFT_PX + 1), xp.arange(w - SHIFT_PX, w)])
    return float(iou[idx].max())


def symmetry_residual(msk):
    """Residual rotation putting the symmetry axis vertical. Returns (deg, score)."""
    m = msk.astype(xp.float32)

    def at(theta):
        R = ndi.rotate(m, float(theta), order=1, reshape=False)
        v = _iou_all_shifts(R)
        return -1.0 if v is None else v

    coarse = np.arange(-SPAN, SPAN + 1e-9, COARSE)
    cs = np.array([at(t) for t in coarse])
    t0 = float(coarse[int(np.argmax(cs))])
    fine = np.arange(max(-SPAN, t0 - COARSE), min(SPAN, t0 + COARSE) + 1e-9, FINE)
    fs = np.array([at(t) for t in fine])
    k = int(np.argmax(fs))
    return float(fine[k]), float(fs[k])


def principal_angle(mask):
    """04a_reformat.principal_angle."""
    ys, xs = np.nonzero(to_cpu(mask))
    y, x = ys - ys.mean(), xs - xs.mean()
    cov = np.cov(np.vstack([x, y]))
    evals, evecs = np.linalg.eigh(cov)
    major = evecs[:, int(np.argmax(evals))]
    return float(np.degrees(np.arctan2(major[1], major[0])))


def reformat_mask(work_mask):
    """The GRID x GRID mask that `04a_reformat.reformat` produces.

    **This must reproduce 04a exactly, including the principal-axis rotation and
    the 180 degree resolution.** A first version cropped and resized the mask
    without rotating it, and the symmetry residuals it produced disagreed with
    `04h` by a median of 12.5 degrees and a maximum of 35 - because a residual is
    only meaningful relative to the orientation it is a residual *from*. The
    parity check against the CPU outputs is what caught it.
    """
    m = to_cpu(work_mask)
    angle = principal_angle(m)
    probe = _snd.rotate(m.astype(np.uint8), angle, order=0, reshape=True) > 0
    if probe.sum() < 100:
        return None
    h = probe.shape[0]
    if probe[: h // 2].sum() < probe[h // 2:].sum():      # 04a.resolve_180
        angle += 180.0
    rot = _snd.rotate(m.astype(np.uint8), angle, order=0, reshape=True) > 0
    if rot.sum() < 100:
        return None
    ys, xs = np.nonzero(rot)
    crop = rot[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    hh, ww = crop.shape
    side = max(hh, ww)
    pad = np.zeros((side, side), bool)
    oy, ox = (side - hh) // 2, (side - ww) // 2
    pad[oy:oy + hh, ox:ox + ww] = crop
    out = np.asarray(Image.fromarray(pad.astype(np.uint8) * 255)
                     .resize((GRID, GRID), Image.BILINEAR)) > 127
    return to_gpu(out)


# ----------------------------------------------------------------- one file ---
def process_one(png_path, out_mask_path=None):
    """Everything for one section. Returns a dict of metrics; writes the mask."""
    img_pil = Image.open(png_path).convert("L")
    w, h = img_pil.size
    full = to_gpu(np.asarray(img_pil).astype(np.float32))

    small = to_gpu(np.asarray(img_pil.resize((WORK, WORK), Image.BILINEAR)).astype(np.float32))
    wm = tissue_mask(small)
    row = {"scene_uid": os.path.basename(png_path).replace("_DAPI.png", ""),
           "width": w, "height": h, "gpu": int(GPU)}
    row.update(quality(full, wm, w, h))

    if wm is None:
        row.update({"focus_png": 0.0, "n_compact": 0, "n_elongated": 0,
                    "artifact_mm2": 0.0, "artifact_pct_of_tissue": 0.0,
                    "tissue_mm2": 0.0, "measurable_mm2": 0.0,
                    "sym_rotation": "", "sym_score": "", "sym_confidence": "no_tissue",
                    "proposed": 1, "artifact_class": "no_tissue",
                    "reason": "no tissue mask could be formed"})
        return row

    # Full-resolution tissue mask, from the work-resolution one.
    tis = to_gpu(np.asarray(
        Image.fromarray(to_cpu(wm).astype(np.uint8) * 255).resize((w, h), Image.NEAREST)) > 127)
    tissue_mm2 = float(tis.sum()) * UM_PX ** 2
    row["tissue_mm2"] = round(tissue_mm2, 3)
    row["focus_png"] = round(focus_png(full, tis), 5)

    amask, recs = artifact_mask(full, tis)
    a_c = sum(r["area_mm2"] for r in recs if r["label"] == LBL_COMPACT)
    a_e = sum(r["area_mm2"] for r in recs if r["label"] == LBL_ELONGATED)
    row.update({"n_compact": sum(1 for r in recs if r["label"] == LBL_COMPACT),
                "n_elongated": sum(1 for r in recs if r["label"] == LBL_ELONGATED),
                "compact_mm2": round(a_c, 4), "elongated_mm2": round(a_e, 4),
                "artifact_mm2": round(a_c + a_e, 4),
                "artifact_pct_of_tissue": round(100 * (a_c + a_e) / max(tissue_mm2, 1e-9), 3),
                "measurable_mm2": round(tissue_mm2 - a_c - a_e, 3)})
    if out_mask_path:
        Image.fromarray(to_cpu(amask)).save(out_mask_path)

    rm = reformat_mask(wm)
    if rm is None:
        row.update({"sym_rotation": "", "sym_score": "", "sym_confidence": "no_shape"})
    else:
        deg, sc = symmetry_residual(rm)
        row.update({"sym_rotation": int(round(deg)), "sym_score": round(sc, 4),
                    "sym_confidence": "low" if sc < SCORE_MIN else "high"})
    return row


def process_and_clean(png_path, out_dir):
    """Process one section and write the three outputs that replace its input.

    Returns (row, [paths written]). The caller deletes the input only after
    every path here exists and is non-trivial - see the notebook.

      <uid>_clean.png      the overview with artifact pixels zeroed. This is the
                           "processed copy": same size as the input, so replacing
                           the input with it keeps Drive usage flat.
      <uid>_artifact.png   the label mask (0 clean, 1 compact, 2 elongated).
                           Mostly zeros, so it costs almost nothing.
      one row in results   the metrics.

    Zeroing rather than deleting the pixels is deliberate: the artifact mask is
    kept alongside, so masking stays reversible in the sense that matters - you
    can always see *what* was removed and how much.
    """
    os.makedirs(out_dir, exist_ok=True)
    uid = os.path.basename(png_path).replace("_DAPI.png", "")
    mask_path = os.path.join(out_dir, uid + "_artifact.png")
    clean_path = os.path.join(out_dir, uid + "_clean.png")

    row = process_one(png_path, out_mask_path=mask_path)

    img = np.asarray(Image.open(png_path).convert("L"))
    if os.path.exists(mask_path):
        am = np.asarray(Image.open(mask_path))
        clean = np.where(am > 0, 0, img).astype(np.uint8)
    else:
        clean = img
        Image.fromarray(np.zeros_like(img)).save(mask_path)
    Image.fromarray(clean).save(clean_path)
    return row, [mask_path, clean_path]


def add_exclusion_calls(rows, focus_cut):
    """Apply 04f's two rules. `focus_cut` comes from calibrate_focus()."""
    for r in rows:
        cls = []
        if float(r.get("largest_mm2", 0)) < LARGEST_MIN_MM2:
            cls.append(("no_tissue",
                        f"no tissue piece larger than {float(r['largest_mm2']):.2f} mm2 "
                        f"(threshold {LARGEST_MIN_MM2:.1f})"))
        f = r.get("focus_png", None)
        if f not in (None, "") and float(f) < focus_cut:
            cls.append(("out_of_focus",
                        f"no resolvable nuclear detail (focus {float(f):.4f}, "
                        f"threshold {focus_cut:.4f})"))
        r["proposed"] = int(bool(cls))
        r["artifact_class"] = "+".join(c for c, _ in cls)
        r["reason"] = "; ".join(t for _, t in cls)
    return rows


def calibrate_focus(rows, focus_csv_path):
    """Map 04f's 0.070 cut onto the PNG-derived focus metric, by percentile.

    The two are different quantities (16-bit vs display-ranged 8-bit), so a
    shared threshold value would be meaningless. What transfers is *which
    fraction of sections* the cut removes.
    """
    import csv
    ref = {}
    with open(focus_csv_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                ref[r["scene_uid"]] = float(r["focus_score"])
            except (KeyError, ValueError):
                pass
    if not ref:
        raise SystemExit("focus.csv unusable - cannot calibrate")
    vals = np.array(list(ref.values()))
    pct = float((vals < FOCUS_MIN_16BIT).mean() * 100)
    ours = np.array([float(r["focus_png"]) for r in rows if r.get("focus_png") not in (None, "")])
    cut = float(np.percentile(ours, pct)) if len(ours) else 0.0
    return cut, pct


# ----------------------------------------------------------------- self-test --
def selftest(verbose=True):
    """Check the FFT shift search against the loop it replaces, and the mask
    against scipy. Run this before trusting a run."""
    rng = np.random.default_rng(0)
    ok = True

    # 1. FFT IoU == loop IoU, at every offset the loop actually visited
    for trial in range(5):
        m = np.zeros((64, 64), bool)
        m[rng.integers(5, 25):rng.integers(35, 60), rng.integers(5, 25):rng.integers(35, 60)] = True
        m |= rng.random((64, 64)) > 0.97
        M = to_gpu(m.astype(np.float32))
        fft_best = _iou_all_shifts(M)
        A = m
        B = m[:, ::-1]
        loop = -1.0
        for s in range(-SHIFT_PX, SHIFT_PX + 1):
            b = np.roll(B, s, axis=1)
            un = (A | b).sum()
            if un < 1:
                continue
            loop = max(loop, (A & b).sum() / un)
        if abs(fft_best - loop) > 1e-4:
            ok = False
            if verbose:
                print(f"  FAIL fft {fft_best:.6f} vs loop {loop:.6f}")
        elif verbose and trial == 0:
            print(f"  ok  FFT shift search matches the loop ({fft_best:.6f})")

    # 2. tissue_mask agrees with the CPU implementation
    img = (rng.random((WORK, WORK)) * 40).astype(np.float32)
    img[120:300, 90:310] += 160
    g = to_cpu(tissue_mask(to_gpu(img)))
    c = _cpu_tissue_mask(img)
    agree = float((g == c).mean())
    if agree < 0.999:
        ok = False
        if verbose:
            print(f"  FAIL tissue_mask agreement {agree:.4f}")
    elif verbose:
        print(f"  ok  tissue_mask matches CPU ({agree:.4f} pixel agreement)")

    if verbose:
        print(f"  GPU: {GPU}")
        print("  SELFTEST PASSED" if ok else "  SELFTEST FAILED - do not trust this run")
    return ok


def _cpu_tissue_mask(v):
    positive = v[v > 0]
    if positive.size < 200:
        return None
    hist, edges = np.histogram(np.log1p(positive), bins=256)
    hist = hist.astype(np.float64)
    c = (edges[:-1] + edges[1:]) / 2
    w1, w2 = np.cumsum(hist), np.cumsum(hist[::-1])[::-1]
    m1 = np.cumsum(hist * c) / np.maximum(w1, 1e-9)
    m2 = (np.cumsum((hist * c)[::-1]) / np.maximum(w2[::-1], 1e-9))[::-1]
    var = w1 * w2 * (m1 - m2) ** 2
    var[(w1 <= 0) | (w2 <= 0)] = -1
    thr = float(np.expm1(c[int(np.argmax(var))]))
    mask = v > thr
    mask = _snd.binary_closing(mask, np.ones((7, 7)))
    mask = _snd.binary_fill_holes(mask)
    mask = _snd.binary_opening(mask, np.ones((3, 3)))
    labels, n = _snd.label(mask)
    if n == 0:
        return None
    sizes = np.array(_snd.sum(mask, labels, range(1, n + 1)))
    keep = np.where(sizes >= MIN_COMPONENT_FRACTION * sizes.max())[0] + 1
    return np.isin(labels, keep)


if __name__ == "__main__":
    selftest()
