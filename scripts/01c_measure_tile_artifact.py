"""Stage 1b - measure the tile-grid artifact in a stitched section.

Decides how much correction machinery this dataset actually warrants, and later
serves as the pass/fail test for whatever correction is applied.

The artifact is multiplicative and periodic at the tile pitch, so it shows up as
a single sharp peak in the spatial-frequency spectrum of the tissue-mean profile
along each axis. Detrending first removes real anatomy, which varies far more
slowly than the ~1.3 mm tile pitch.

Reported amplitude is peak-to-trough of the folded tile profile, as a percentage
of mean signal - i.e. "detections near a tile centre see N% more signal than
detections near a tile edge".

Run:  python 01c_measure_tile_artifact.py                 # all test sections
      python 01c_measure_tile_artifact.py <file.tif> ...  # specific files
"""

import glob
import json
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tifffile

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
BASE_PX_UM = CONFIG["pixel_size_um"]
TEST_DIR = os.path.join(OUT_ROOT, "qc", "test_sections")
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "tile_artifact")

# Raw camera tile edge in native pixels, confirmed from Bio-Formats.
TILE_PX_NATIVE = 2040
# Exact pitch from the CZI subblock directory (01e_tile_geometry.py): identical
# across all 131 scenes checked. The test targets THIS period specifically.
# Scanning for whatever period happens to be strongest was right while the
# pitch was unknown, but it always returns something - on a corrected section
# it dutifully reports noise at some unrelated period and calls it an artifact.
PITCH_PX_NATIVE = 1836
# Band used only for the prominence baseline and the context scan.
PITCH_SEARCH = (0.45, 1.10)


def otsu(values):
    """Otsu threshold on a 1-D array of samples."""
    hist, edges = np.histogram(values, bins=256)
    hist = hist.astype(float)
    centres = (edges[:-1] + edges[1:]) / 2.0
    weight1 = np.cumsum(hist)
    weight2 = np.cumsum(hist[::-1])[::-1]
    valid = (weight1 > 0) & (weight2 > 0)
    mean1 = np.cumsum(hist * centres) / np.maximum(weight1, 1e-9)
    mean2 = (np.cumsum((hist * centres)[::-1]) / np.maximum(weight2[::-1], 1e-9))[::-1]
    variance = weight1 * weight2 * (mean1 - mean2) ** 2
    variance[~valid] = -1
    return centres[int(np.argmax(variance))]


def tissue_threshold(sample):
    """Split tissue from background on a fluorescence image.

    These channels are extremely skewed - DAPI runs a median of ~500 against a
    99.9th percentile of ~30000 - and plain Otsu maximises between-class
    variance by chasing that tail, returning a threshold above nearly every
    pixel. Working in log space makes the two populations comparably wide, so
    the split lands between them instead.
    """
    positive = sample[sample > 0]
    if positive.size < 100:
        return float(np.max(sample)) if sample.size else 0.0
    return float(np.expm1(otsu(np.log1p(positive))))


def smooth1d(profile, sigma):
    """Gaussian smoothing with edge padding, no scipy dependency needed."""
    radius = max(1, int(round(3 * sigma)))
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-(x ** 2) / (2.0 * sigma ** 2))
    kernel /= kernel.sum()
    padded = np.pad(profile, radius, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def axis_profile(image, mask, axis):
    """Mean signal per column (axis=0) or per row (axis=1), tissue pixels only."""
    masked = np.where(mask, image.astype(np.float64), np.nan)
    counts = mask.sum(axis=axis)
    totals = np.nansum(masked, axis=axis)
    with np.errstate(invalid="ignore", divide="ignore"):
        profile = np.where(counts > 0, totals / np.maximum(counts, 1), np.nan)
    coverage = np.mean(mask, axis=axis)
    # Positions with almost no tissue carry no illumination information.
    good = coverage > 0.15
    return profile, good


def detrend(profile, good, sigma):
    """Isolate the periodic multiplicative component from slow anatomy."""
    filled = profile.copy()
    if not good.any():
        return None
    idx = np.arange(len(profile))
    filled[~good] = np.interp(idx[~good], idx[good], profile[good])
    baseline = smooth1d(filled, sigma)
    baseline[baseline <= 0] = np.nan
    return filled / baseline


def power_at_period(signal, period, lo, hi):
    """Power at one specific period, relative to the rest of the band.

    Leakage spreads a peak over neighbouring bins, so take the best of the
    three nearest; the baseline is the band median, which stays near 1 for a
    flat spectrum regardless of overall signal level.
    """
    centred = np.nan_to_num(signal - np.nanmean(signal))
    spectrum = np.abs(np.fft.rfft(centred * np.hanning(len(centred)))) ** 2
    freqs = np.fft.rfftfreq(len(centred))
    with np.errstate(divide="ignore"):
        periods = np.where(freqs > 0, 1.0 / np.maximum(freqs, 1e-12), np.inf)

    band = (periods >= lo) & (periods <= hi)
    if not band.any():
        return 0.0
    target = int(np.argmin(np.abs(periods - period)))
    window = spectrum[max(1, target - 1): target + 2]
    baseline = np.median(spectrum[band])
    return float(np.max(window) / max(baseline, 1e-12))


def dominant_period(signal, lo, hi):
    """Strongest period within [lo, hi] samples, plus its prominence."""
    centred = signal - np.nanmean(signal)
    centred = np.nan_to_num(centred)
    window = np.hanning(len(centred))
    spectrum = np.abs(np.fft.rfft(centred * window)) ** 2
    freqs = np.fft.rfftfreq(len(centred))

    with np.errstate(divide="ignore"):
        periods = np.where(freqs > 0, 1.0 / np.maximum(freqs, 1e-12), np.inf)
    band = (periods >= lo) & (periods <= hi)
    if not band.any():
        return None, 0.0, spectrum, periods

    peak = int(np.argmax(np.where(band, spectrum, -np.inf)))
    # Prominence against the rest of the searched band, so a flat spectrum
    # (no artifact) scores near 1 regardless of overall signal level.
    others = spectrum[band].copy()
    median_power = np.median(others) if len(others) > 2 else spectrum[peak]
    return periods[peak], float(spectrum[peak] / max(median_power, 1e-12)), spectrum, periods


def fold(signal, period):
    """Average the signal over repeats of `period` to recover the tile profile."""
    period_int = int(round(period))
    if period_int < 4:
        return None
    n = len(signal) // period_int
    if n < 3:
        return None
    trimmed = np.nan_to_num(signal[: n * period_int], nan=1.0).reshape(n, period_int)
    return np.median(trimmed, axis=0)


def analyse(path):
    image = tifffile.imread(path)
    if image.ndim != 2:
        image = image[0]

    match = re.search(r"_([0-9.]+)um", os.path.basename(path))
    um_px = float(match.group(1)) if match else BASE_PX_UM
    tile_px = TILE_PX_NATIVE * (BASE_PX_UM / um_px)
    expected_pitch = PITCH_PX_NATIVE * (BASE_PX_UM / um_px)
    lo, hi = tile_px * PITCH_SEARCH[0], tile_px * PITCH_SEARCH[1]

    sample = image[::4, ::4].ravel().astype(np.float64)
    threshold = tissue_threshold(sample)
    mask = image > threshold
    tissue_fraction = float(mask.mean())

    result = {
        "file": os.path.basename(path),
        "um_px": um_px,
        "nominal_tile_px": round(tile_px, 1),
        "expected_pitch_px": round(expected_pitch, 1),
        "tissue_fraction": round(tissue_fraction, 3),
    }
    if tissue_fraction < 0.02:
        result["note"] = "too little tissue to measure"
        return result, None

    panels = {}
    for axis, label in ((0, "x"), (1, "y")):
        profile, good = axis_profile(image, mask, axis)
        ratio = detrend(profile, good, sigma=tile_px * 1.5)
        if ratio is None:
            continue
        # The real test: power and folded amplitude at the KNOWN tile pitch.
        pitch_prom = power_at_period(ratio, expected_pitch, lo, hi)
        pitch_folded = fold(ratio, expected_pitch)
        pitch_amp = 0.0
        if pitch_folded is not None and len(pitch_folded):
            pitch_amp = float((np.nanmax(pitch_folded) - np.nanmin(pitch_folded)) * 100.0)

        # Context only: whatever period happens to be strongest in the band.
        period, prominence, spectrum, periods = dominant_period(ratio, lo, hi)

        result[f"{label}_pitch_prominence"] = round(pitch_prom, 2)
        result[f"{label}_pitch_amplitude_pct"] = round(pitch_amp, 2)
        result[f"{label}_top_period_px"] = round(period, 1) if period else ""
        result[f"{label}_top_prominence"] = round(prominence, 2)
        panels[label] = (ratio, good, spectrum, periods, pitch_folded, expected_pitch, lo, hi)

    return result, panels


def plot(path, result, panels):
    os.makedirs(REPORT_DIR, exist_ok=True)
    fig, axes = plt.subplots(len(panels), 3, figsize=(15, 4 * len(panels)), squeeze=False)

    for row, (label, data) in enumerate(sorted(panels.items())):
        ratio, good, spectrum, periods, folded, period, lo, hi = data

        ax = axes[row][0]
        ax.plot(ratio, lw=0.7, color="#2060c0")
        ax.axhline(1.0, color="#909090", lw=0.7)
        ax.set_title(f"{label}: detrended tissue profile")
        ax.set_xlabel("pixel")
        ax.set_ylabel("signal / local baseline")

        ax = axes[row][1]
        band = (periods >= lo) & (periods <= hi)
        ax.plot(periods[band], spectrum[band], lw=0.9, color="#c04020")
        if period:
            ax.axvline(period, color="#209040", ls="--", lw=1.2, label=f"{period:.0f} px")
            ax.legend()
        ax.set_title(f"{label}: power in the tile-pitch band")
        ax.set_xlabel("period (px)")

        ax = axes[row][2]
        if folded is not None:
            ax.plot(folded, lw=1.4, color="#7030a0")
            ax.axhline(1.0, color="#909090", lw=0.7)
            amp = result.get(f"{label}_pitch_amplitude_pct", 0.0)
            ax.set_title(f"{label}: folded tile profile - {amp:.1f}% peak to trough")
        else:
            ax.set_title(f"{label}: no periodicity found")
        ax.set_xlabel("position within tile (px)")

    fig.suptitle(result["file"], fontsize=11)
    fig.tight_layout()
    out = os.path.join(REPORT_DIR, result["file"].replace(".tif", "_tileartifact.png"))
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


def main():
    targets = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not targets:
        targets = sorted(glob.glob(os.path.join(TEST_DIR, "*.tif")))
    if not targets:
        print(f"No test sections found. Run 01b_export_section.groovy first.")
        return

    print(f"Measuring {len(targets)} section(s)\n")
    results = []
    for path in targets:
        result, panels = analyse(path)
        results.append(result)
        if panels:
            out = plot(path, result, panels)
            print(f"  {result['file']}  (pitch {result['expected_pitch_px']} px)")
            for label in ("x", "y"):
                if f"{label}_pitch_prominence" in result:
                    print(
                        f"      {label}: at pitch -> prominence {result[f'{label}_pitch_prominence']}x, "
                        f"amplitude {result[f'{label}_pitch_amplitude_pct']}%   "
                        f"[strongest in band: {result[f'{label}_top_period_px']} px "
                        f"at {result[f'{label}_top_prominence']}x]"
                    )
            print(f"      -> {os.path.basename(out)}")
        else:
            print(f"  {result['file']}: {result.get('note', 'no measurement')}")

    amps = [
        r[f"{a}_pitch_amplitude_pct"]
        for r in results
        for a in ("x", "y")
        if isinstance(r.get(f"{a}_pitch_amplitude_pct"), (int, float))
    ]
    proms = [
        r[f"{a}_pitch_prominence"]
        for r in results
        for a in ("x", "y")
        if isinstance(r.get(f"{a}_pitch_prominence"), (int, float))
    ]
    print()
    print("=" * 72)
    if amps:
        print(f"AT THE TILE PITCH ({PITCH_PX_NATIVE} px native, {PITCH_PX_NATIVE * BASE_PX_UM:.0f} um)")
        print(f"  amplitude : median {np.median(amps):.1f}%  max {np.max(amps):.1f}%")
        print(f"  prominence: median {np.median(proms):.1f}x  max {np.max(proms):.1f}x")
        print()
        if np.median(proms) < 2.0 and np.median(amps) < 6:
            print("PASS: no coherent power left at the tile pitch. The grid is gone.")
        elif np.median(proms) < 3.0 and np.median(amps) < 12:
            print("PARTIAL: much reduced but still detectable at the pitch. Usable for")
            print("         visual triage; rebuild the field from more sections before")
            print("         trusting density heatmaps.")
        else:
            print("FAIL: coherent power remains at the tile pitch. Correction is not")
            print("      working - rebuild from more sections, or escalate to BaSiC.")
    print("=" * 72)


if __name__ == "__main__":
    main()
