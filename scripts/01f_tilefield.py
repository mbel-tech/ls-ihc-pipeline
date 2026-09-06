"""Stage 1b - build and apply the stitched-domain tile correction.

Why not correct the raw tiles? Because reading 78 full-resolution tiles per
section and re-stitching them costs ~27 hours across the dataset, against ~2
hours for reading the pyramid level the scanner already stored. And correcting
raw tiles still leaves the question of which tile Bio-Formats kept in each
overlap region, which is not recorded anywhere.

Folding in the stitched domain sidesteps both problems. The tile grid is exactly
regular - 2040 px tiles on an 1836 px pitch, measured from the CZI subblock
directory and identical across all 131 scenes checked - and the stitched image
starts at the mosaic origin. So tile boundaries land at exact multiples of the
pitch in stitched coordinates, and every pitch x pitch cell sees the same
illumination pattern, whatever the stitcher did in the overlaps.

Taking the median across thousands of such cells, spanning sections whose tissue
falls at random positions relative to the grid, leaves illumination alone.

  build   fold exported sections into a correction field
  verify  apply the field and re-measure the artifact

Run:  python 01f_tilefield.py build
      python 01f_tilefield.py verify
"""

import argparse
import glob
import json
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tifffile
from scipy.ndimage import gaussian_filter, zoom

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
BASE_PX_UM = CONFIG["pixel_size_um"]
TEST_DIR = os.path.join(OUT_ROOT, "qc", "test_sections")
FIELD_DIR = os.path.join(OUT_ROOT, "qc", "flatfield")

# Exact geometry from 01e_tile_geometry.py - 131 scenes, zero spread.
TILE_PX = 2040
PITCH_PX = 1836

# The field is stored on this grid, a whole-number division of the pitch so
# folding is exact. Vignetting is smooth, so a coarse grid is not a loss - and
# it is what makes each cell well sampled. 1836 / 12 = 153.
FIELD_DIVISOR = 12
FIELD_N = PITCH_PX // FIELD_DIVISOR

# Anatomy varies far more slowly than the pitch; this removes it before folding.
BASELINE_SIGMA_PITCHES = 1.5
MIN_TISSUE_FRACTION = 0.02
# Illumination gain cannot plausibly fall outside this. Anything beyond it is
# an edge artifact or a bright speck, not vignetting, and must not be averaged in.
RATIO_CLIP = (0.4, 2.5)
# Below this many samples a cell is not trusted and gets filled from neighbours.
MIN_SAMPLES_PER_CELL = 30


def um_px_of(path):
    m = re.search(r"_([0-9.]+)um", os.path.basename(path))
    return float(m.group(1)) if m else BASE_PX_UM


def channel_of(path):
    m = re.search(r"_c(\d)_", os.path.basename(path))
    return int(m.group(1)) if m else 0


def otsu(values):
    hist, edges = np.histogram(values, bins=256)
    hist = hist.astype(float)
    centres = (edges[:-1] + edges[1:]) / 2.0
    w1 = np.cumsum(hist)
    w2 = np.cumsum(hist[::-1])[::-1]
    valid = (w1 > 0) & (w2 > 0)
    m1 = np.cumsum(hist * centres) / np.maximum(w1, 1e-9)
    m2 = (np.cumsum((hist * centres)[::-1]) / np.maximum(w2[::-1], 1e-9))[::-1]
    var = w1 * w2 * (m1 - m2) ** 2
    var[~valid] = -1
    return centres[int(np.argmax(var))]


def tissue_mask(image):
    """Log-space Otsu - these channels are far too skewed for the plain form."""
    sample = image[::4, ::4].ravel().astype(np.float64)
    positive = sample[sample > 0]
    if positive.size < 100:
        return np.zeros_like(image, dtype=bool)
    return image > float(np.expm1(otsu(np.log1p(positive))))


def gaussian_blur(arr, sigma):
    return gaussian_filter(arr.astype(np.float64), sigma, mode="nearest")


# Above this the blur is done at reduced scale. A Gaussian kernel's cost grows
# with sigma, and the baseline sigma here is ~690 px, which on a 3264x4641
# section is tens of billions of operations. The baseline is smooth by
# definition, so computing it small and expanding it back is exact enough and
# a couple of hundred times cheaper.
MAX_DIRECT_SIGMA = 32.0


def _block_mean(arr, factor):
    h = arr.shape[0] // factor * factor
    w = arr.shape[1] // factor * factor
    return arr[:h, :w].reshape(h // factor, factor, w // factor, factor).mean(axis=(1, 3))


def _smooth_large(arr, sigma):
    if sigma <= MAX_DIRECT_SIGMA:
        return gaussian_blur(arr, sigma)
    factor = int(np.ceil(sigma / MAX_DIRECT_SIGMA))
    small = gaussian_blur(_block_mean(arr, factor), sigma / factor)
    return zoom(small, (arr.shape[0] / small.shape[0], arr.shape[1] / small.shape[1]), order=1)


def masked_baseline(data, mask, sigma):
    """Smooth estimate of local anatomy using tissue pixels only.

    Filling non-tissue with a constant and then blurring drags the baseline
    toward that constant near every tissue edge, which is exactly where the
    ratio then explodes. Normalised convolution - blur(signal) / blur(mask) -
    interpolates across the gaps instead of contaminating them.
    """
    weight = mask.astype(np.float64)
    numerator = _smooth_large(np.where(mask, data, 0.0), sigma)
    denominator = _smooth_large(weight, sigma)
    # Where almost no tissue contributed, the estimate is meaningless.
    trusted = denominator > 0.05
    with np.errstate(divide="ignore", invalid="ignore"):
        baseline = np.where(trusted, numerator / np.maximum(denominator, 1e-9), np.nan)
    return baseline


def fold_indices(length, downsample):
    """Field-grid index for every pixel along one axis.

    Indices are computed in native resolution and then mapped onto the stored
    grid, so a working resolution whose pitch is not a whole number of pixels
    (res 3 gives 229.5) still folds correctly.
    """
    native = np.arange(length, dtype=np.float64) * downsample
    return np.round((native % PITCH_PX) / FIELD_DIVISOR).astype(np.int64) % FIELD_N


def accumulate(path, sums, counts):
    image = tifffile.imread(path)
    if image.ndim != 2:
        image = image[0]
    um_px = um_px_of(path)
    downsample = um_px / BASE_PX_UM

    mask = tissue_mask(image)
    if mask.mean() < MIN_TISSUE_FRACTION:
        return False, "too little tissue"

    # Divide out anatomy so what is left is illumination plus noise.
    sigma = BASELINE_SIGMA_PITCHES * PITCH_PX / downsample
    data = image.astype(np.float64)
    baseline = masked_baseline(data, mask, sigma)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(baseline > 0, data / baseline, np.nan)
    ratio[~mask] = np.nan

    yi = fold_indices(image.shape[0], downsample)
    xi = fold_indices(image.shape[1], downsample)
    flat = (yi[:, None] * FIELD_N + xi[None, :]).ravel()
    vals = ratio.ravel()
    good = np.isfinite(vals) & (vals >= RATIO_CLIP[0]) & (vals <= RATIO_CLIP[1])

    # bincount rather than np.add.at: the latter takes an unbuffered slow path
    # and turns a few million indices into minutes of work.
    idx = flat[good]
    size = FIELD_N * FIELD_N
    sums += np.bincount(idx, weights=vals[good], minlength=size)
    counts += np.bincount(idx, minlength=size)
    return True, f"{int(good.sum())} px"


def build(paths):
    by_channel = {}
    for path in paths:
        by_channel.setdefault(channel_of(path), []).append(path)

    os.makedirs(FIELD_DIR, exist_ok=True)
    for channel, group in sorted(by_channel.items()):
        sums = np.zeros(FIELD_N * FIELD_N, dtype=np.float64)
        counts = np.zeros(FIELD_N * FIELD_N, dtype=np.int64)
        used = 0
        for path in group:
            ok, note = accumulate(path, sums, counts)
            print(f"    {'+' if ok else '-'} {os.path.basename(path):<44} {note}")
            used += int(ok)
        if not used:
            print(f"  channel {channel}: no usable sections")
            continue

        with np.errstate(invalid="ignore", divide="ignore"):
            field = np.where(counts >= MIN_SAMPLES_PER_CELL, sums / np.maximum(counts, 1), np.nan)
        field = field.reshape(FIELD_N, FIELD_N)
        thin = int(np.isnan(field).sum())

        # Fill under-sampled cells before smoothing, then normalise to mean 1
        # so the field is a pure multiplicative gain.
        if thin:
            field = np.where(np.isnan(field), np.nanmedian(field), field)
        field = gaussian_blur(field, 1.5)
        field /= field.mean()

        name = f"tilefield_c{channel}"
        np.save(os.path.join(FIELD_DIR, name + ".npy"), field)
        # 32-bit TIFF twin so the Fiji stages can load the same field; Groovy
        # has no way to read .npy.
        tifffile.imwrite(os.path.join(FIELD_DIR, name + ".tif"), field.astype(np.float32))

        # Percentiles, not min/max: over 23,000 cells the extremes are noisy
        # corners rather than anything the optics actually does.
        lo, hi = (float(v) for v in np.percentile(field, [1, 99]))
        per_cell = counts.sum() / max(counts.size, 1)
        print(f"  channel {channel}: {used}/{len(group)} sections, "
              f"{per_cell:.0f} samples/cell, {thin} thin cells, "
              f"gain p1-p99 {lo:.3f}-{hi:.3f} ({(hi / lo - 1) * 100:.1f}% across a tile)")

        fig, ax = plt.subplots(1, 2, figsize=(11, 4.4))
        im = ax[0].imshow(field, cmap="viridis")
        ax[0].set_title(f"channel {channel}: tile correction field")
        fig.colorbar(im, ax=ax[0], fraction=0.046)
        ax[1].plot(field[FIELD_N // 2, :], label="horizontal through centre")
        ax[1].plot(field[:, FIELD_N // 2], label="vertical through centre")
        ax[1].axhline(1.0, color="#909090", lw=0.7)
        ax[1].set_xlabel("position within pitch (field px)")
        ax[1].legend()
        ax[1].set_title(f"p1-p99 gain {lo:.2f}-{hi:.2f}  ({(hi / lo - 1) * 100:.0f}%)")
        fig.tight_layout()
        fig.savefig(os.path.join(FIELD_DIR, name + ".png"), dpi=110)
        plt.close(fig)


def apply_field(image, field, um_px):
    """Divide out the tile pattern."""
    downsample = um_px / BASE_PX_UM
    yi = fold_indices(image.shape[0], downsample)
    xi = fold_indices(image.shape[1], downsample)
    gain = field[np.ix_(yi, xi)]
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(gain > 0, image.astype(np.float64) / gain, image)


def verify(paths):
    """Apply the field and re-measure, writing corrected copies for 01c."""
    out_dir = os.path.join(OUT_ROOT, "qc", "test_sections_corrected")
    os.makedirs(out_dir, exist_ok=True)
    written = 0
    for path in paths:
        channel = channel_of(path)
        field_path = os.path.join(FIELD_DIR, f"tilefield_c{channel}.npy")
        if not os.path.exists(field_path):
            print(f"  !! no field for channel {channel}, run build first")
            continue
        field = np.load(field_path)
        image = tifffile.imread(path)
        if image.ndim != 2:
            image = image[0]
        corrected = apply_field(image, field, um_px_of(path))
        out = os.path.join(out_dir, os.path.basename(path))
        tifffile.imwrite(out, np.clip(corrected, 0, 65535).astype(np.uint16))
        written += 1
    print(f"  wrote {written} corrected section(s) to {out_dir}")
    print("  now run: python 01c_measure_tile_artifact.py " + os.path.join(out_dir, "*.tif"))
    print("  the tile-pitch peak must drop to noise; if it does not, escalate to BaSiC.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["build", "verify"])
    ap.add_argument("paths", nargs="*")
    args = ap.parse_args()

    paths = args.paths or sorted(glob.glob(os.path.join(TEST_DIR, "*.tif")))
    if not paths:
        raise SystemExit("No sections found - run 01b_export_section.groovy first.")

    print(f"tile {TILE_PX} px, pitch {PITCH_PX} px ({PITCH_PX * BASE_PX_UM:.2f} um), "
          f"field grid {FIELD_N}x{FIELD_N}")
    print(f"{len(paths)} section(s)\n")

    if args.mode == "build":
        build(paths)
    else:
        verify(paths)


if __name__ == "__main__":
    main()
