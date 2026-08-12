"""Stage 1 - export a browsable overview of every section, plus per-section QC.

Port of 01_overviews.groovy from Bio-Formats/Fiji to pylibCZIrw. Motivation:

  speed        0.25 s to open a file and 0.26 s per section, against ~56 s and
               ~9 s through Bio-Formats. The full dataset drops from ~5 hours
               to roughly 12 minutes.

  correctness  Bio-Formats' Memoizer caches reader state keyed on file path
               alone, so a reader saved in tile mode by another script came
               back in tile mode here and 238 sections silently exported as
               single 2040x2040 tiles instead of whole sections. pylibCZIrw has
               no such cache and no autostitch flag to get restored wrongly.

  exactness    `zoom` is continuous, so sections come out at exactly 5.20 um/px
               instead of "nearest stored pyramid level", which is why
               tissue_area_mm2 previously ranged 0.18-28.83 mm2 within one brain.

Display ranges are computed once from TISSUE pixels and then frozen dataset-wide.
Sampling the whole frame let the AF568 background - brighter than the brain on
many sections - pin the top of the range at 65535, leaving real tissue rendering
around 20/255.

Requires the Python 3.13 venv: D:/LS-analysis/work/czienv (no cp314 wheel yet).

Run:  D:/LS-analysis/work/czienv/Scripts/python.exe 01_overviews.py
      ... --limit 20 --force
"""

import argparse
import csv
import json
import os
import sys
import time

import numpy as np
from PIL import Image
from pylibCZIrw import czi as pyczi

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

SOURCE_DIR = CONFIG["source_dir"]
OUT_ROOT = CONFIG["out_root"]
BASE_PX_UM = CONFIG["pixel_size_um"]
TARGET_UM = CONFIG["overview_target_um_per_px"]

OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
QC_DIR = os.path.join(OUT_ROOT, "qc")
RANGES_PATH = os.path.join(QC_DIR, "display_ranges.json")
QC_CSV = os.path.join(QC_DIR, "focus.csv")

SAMPLE_SECTIONS = 120
SEED = 20260811
# Pulled in from 0.1/99.9: a few clipped pixels inside the mask would otherwise
# drag the top of the range back to 65535.
LO_PCT, HI_PCT = 1.0, 99.5

# Exact geometry, confirmed independently by pylibCZIrw's subblock enumeration
# and by parsing the CZI directory: 2040 px tiles on an 1836 px pitch.
PITCH_PX = 1836
FIELD_DIVISOR = 12

QC_KEYS = ["scene_uid", "file", "animal", "slide", "variant", "marker_channel",
           "scene_index", "section_order", "width", "height", "um_px",
           "tissue_threshold", "tissue_fraction", "tissue_area_mm2", "tissue_mean",
           "background_mean", "contrast", "focus_score", "saturated_fraction",
           "tilefield_applied", "reader"]


# ---------------------------------------------------------------- image helpers

def otsu(values):
    hist, edges = np.histogram(values, bins=512)
    hist = hist.astype(np.float64)
    centres = (edges[:-1] + edges[1:]) / 2.0
    w1, w2 = np.cumsum(hist), np.cumsum(hist[::-1])[::-1]
    valid = (w1 > 0) & (w2 > 0)
    m1 = np.cumsum(hist * centres) / np.maximum(w1, 1e-9)
    m2 = (np.cumsum((hist * centres)[::-1]) / np.maximum(w2[::-1], 1e-9))[::-1]
    var = w1 * w2 * (m1 - m2) ** 2
    var[~valid] = -1
    return float(centres[int(np.argmax(var))])


def tissue_threshold(image):
    """Log-space Otsu.

    DAPI runs a median near 500 against a 99.9th percentile near 30000. Plain
    Otsu maximises between-class variance by chasing that tail and returns a
    threshold above nearly every pixel; logs make the two populations
    comparably wide so the split lands between them.
    """
    sample = image[::3, ::3].ravel()
    positive = sample[sample > 0].astype(np.float64)
    if positive.size < 500:
        return float(image.max())
    return float(np.expm1(otsu(np.log1p(positive))))


def fold_index(length, downsample, field_n):
    """Field-grid index per pixel along one axis.

    Tile starts sit on exact multiples of the pitch from the scene origin, so
    the fold phase is zero and no alignment search is needed.
    """
    native = np.arange(length, dtype=np.float64) * downsample
    return (np.round((native % PITCH_PX) / FIELD_DIVISOR).astype(np.int64)) % field_n


def apply_tile_field(image, field, downsample):
    if field is None:
        return image
    n = field.shape[0]
    gain = field[np.ix_(fold_index(image.shape[0], downsample, n),
                        fold_index(image.shape[1], downsample, n))]
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(gain > 0.05, image.astype(np.float32) / gain, image)
    return np.clip(out, 0, 65535).astype(np.uint16)


def focus_score(image, mask):
    """Sobel-style edge energy inside tissue, normalised by brightness.

    Normalising stops a dim section being mistaken for a blurred one.
    """
    if not mask.any():
        return 0.0
    a = image.astype(np.float32)
    gy = np.abs(np.diff(a, axis=0, prepend=a[:1]))
    gx = np.abs(np.diff(a, axis=1, prepend=a[:, :1]))
    mean = float(a[mask].mean())
    if mean <= 0:
        return 0.0
    return float((gx + gy)[mask].mean() / mean)


def to_8bit(image, lo, hi):
    if hi <= lo:
        hi = lo + 1
    scaled = (image.astype(np.float32) - lo) * (255.0 / (hi - lo))
    return np.clip(scaled, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- czi access

def read_scene(czidoc, rect, channel, zoom):
    """One scene, one channel, at the requested zoom, as 2-D uint16."""
    arr = czidoc.read(roi=(rect.x, rect.y, rect.w, rect.h),
                      plane={"C": channel}, zoom=zoom)
    return np.squeeze(arr)


def load_manifest():
    with open(os.path.join(OUT_ROOT, "manifest", "manifest_scenes.csv"),
              newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_tile_fields():
    fields = {}
    for c in (0, 1):
        p = os.path.join(QC_DIR, "flatfield", f"tilefield_c{c}.npy")
        if os.path.exists(p):
            fields[c] = np.load(p)
    if fields:
        print(f"tile fields loaded for channels {sorted(fields)}")
    else:
        print("no tile fields found - exporting UNCORRECTED")
    return fields


def write_qc(rows):
    """Atomic write, so an interrupted write cannot truncate the checkpoint."""
    if not rows:
        return
    tmp = QC_CSV + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=QC_KEYS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, QC_CSV)


# ---------------------------------------------------------------- passes

def sample_display_ranges(scenes, fields, zoom, force):
    if os.path.exists(RANGES_PATH) and not force:
        with open(RANGES_PATH, encoding="utf-8") as fh:
            ranges = json.load(fh)
        print(f"display ranges loaded: {ranges}")
        return ranges

    rng = np.random.default_rng(SEED)
    pool = list(scenes)
    rng.shuffle(pool)
    sample = pool[:SAMPLE_SECTIONS]
    by_file = {}
    for r in sample:
        by_file.setdefault(r["file"], []).append(r)

    print(f"sampling {len(sample)} sections for the display range (tissue pixels only) ...")
    values = {}
    done = 0
    for fname, rows in by_file.items():
        path = os.path.join(SOURCE_DIR, fname)
        if not os.path.exists(path):
            continue
        with pyczi.open_czi(path) as czidoc:
            rects = czidoc.scenes_bounding_rectangle
            for r in rows:
                s = int(r["scene_index"])
                if s not in rects:
                    continue
                dapi = apply_tile_field(read_scene(czidoc, rects[s], 0, zoom), fields.get(0), 1 / zoom)
                mark = apply_tile_field(read_scene(czidoc, rects[s], 1, zoom), fields.get(1), 1 / zoom)
                mask = dapi > tissue_threshold(dapi)
                if mask.sum() < 500:
                    continue
                values.setdefault("DAPI", []).append(dapi[mask][::7])
                values.setdefault(r["marker_channel"], []).append(mark[mask][::7])
                done += 1
        print(f"\r  sampled {done}/{len(sample)}", end="")
    print()

    ranges = {}
    for name, chunks in values.items():
        v = np.concatenate(chunks)
        ranges[name] = {"lo": int(np.percentile(v, LO_PCT)), "hi": int(np.percentile(v, HI_PCT))}
        print(f"  {name}: {ranges[name]['lo']} .. {ranges[name]['hi']}  (n={v.size})")
    os.makedirs(QC_DIR, exist_ok=True)
    with open(RANGES_PATH, "w", encoding="utf-8") as fh:
        json.dump(ranges, fh, indent=2)
    return ranges


def export(scenes, fields, ranges, zoom, limit, force):
    done_uids = set()
    qc_rows = []
    if os.path.exists(QC_CSV) and not force:
        with open(QC_CSV, newline="", encoding="utf-8") as fh:
            qc_rows = list(csv.DictReader(fh))
        done_uids = {r["scene_uid"] for r in qc_rows}
        print(f"resuming: {len(done_uids)} sections already exported")

    by_file = {}
    for r in scenes:
        if r["scene_uid"] not in done_uids:
            by_file.setdefault(r["file"], []).append(r)

    total = sum(len(v) for v in by_file.values())
    print(f"{total} sections to export across {len(by_file)} files")

    exported = failed = 0
    t0 = time.time()
    for fname, rows in by_file.items():
        if limit and exported >= limit:
            break
        path = os.path.join(SOURCE_DIR, fname)
        if not os.path.exists(path):
            failed += len(rows)
            continue

        marker = rows[0]["marker_channel"]
        out_dir = os.path.join(OVERVIEW_DIR, rows[0]["animal"], marker)
        os.makedirs(out_dir, exist_ok=True)
        d_lo, d_hi = ranges["DAPI"]["lo"], ranges["DAPI"]["hi"]
        m_lo, m_hi = ranges[marker]["lo"], ranges[marker]["hi"]

        try:
            with pyczi.open_czi(path) as czidoc:
                rects = czidoc.scenes_bounding_rectangle
                for r in rows:
                    if limit and exported >= limit:
                        break
                    s = int(r["scene_index"])
                    if s not in rects:
                        failed += 1
                        continue

                    dapi = apply_tile_field(read_scene(czidoc, rects[s], 0, zoom), fields.get(0), 1 / zoom)
                    mark = apply_tile_field(read_scene(czidoc, rects[s], 1, zoom), fields.get(1), 1 / zoom)
                    h, w = dapi.shape
                    um_px = BASE_PX_UM / zoom

                    thr = tissue_threshold(dapi)
                    mask = dapi > thr
                    # No-data corners are exactly zero in both channels and are
                    # not background - they were never scanned.
                    scanned = (dapi > 0) | (mark > 0)
                    background = (~mask) & scanned

                    n_tissue = int(mask.sum())
                    tissue_mean = float(mark[mask].mean()) if n_tissue else 0.0
                    bg_mean = float(mark[background].mean()) if background.sum() > 500 else float("nan")

                    uid = r["scene_uid"]
                    d8, m8 = to_8bit(dapi, d_lo, d_hi), to_8bit(mark, m_lo, m_hi)
                    # Blue nuclei, yellow marker: the most separable pairing and
                    # it survives the common forms of colour blindness.
                    rgb = np.dstack([m8, m8, d8])
                    Image.fromarray(d8).save(os.path.join(out_dir, f"{uid}_DAPI.png"))
                    Image.fromarray(m8).save(os.path.join(out_dir, f"{uid}_MARK.png"))
                    Image.fromarray(rgb).save(os.path.join(out_dir, f"{uid}_RGB.png"))

                    qc_rows.append({
                        "scene_uid": uid, "file": fname, "animal": r["animal"],
                        "slide": r["slide"], "variant": r["variant"],
                        "marker_channel": marker, "scene_index": s,
                        "section_order": r["section_order"],
                        "width": w, "height": h, "um_px": f"{um_px:.2f}",
                        "tissue_threshold": f"{thr:.0f}",
                        "tissue_fraction": f"{n_tissue / dapi.size:.4f}",
                        "tissue_area_mm2": f"{n_tissue * um_px * um_px / 1e6:.3f}",
                        "tissue_mean": f"{tissue_mean:.1f}",
                        "background_mean": "" if np.isnan(bg_mean) else f"{bg_mean:.1f}",
                        "contrast": "" if (np.isnan(bg_mean) or bg_mean <= 0)
                                    else f"{tissue_mean / bg_mean:.3f}",
                        "focus_score": f"{focus_score(dapi, mask):.4f}",
                        "saturated_fraction": f"{float((mark >= 65535).mean()):.6f}",
                        "tilefield_applied": int(bool(fields)),
                        "reader": "pylibCZIrw",
                    })
                    exported += 1
        except Exception as exc:  # noqa: BLE001 - one bad file must not kill the run
            print(f"\n  !! {fname}: {exc}")
            failed += len(rows)

        # Checkpoint per file: this runs unattended against an external drive
        # that has already dropped writes once.
        write_qc(qc_rows)
        rate = exported / max(time.time() - t0, 1e-9)
        print(f"\r  exported {exported}/{total}  failed {failed}  "
              f"({rate:.1f}/s, {(time.time() - t0) / 60:.1f} min)", end="")

    print()
    write_qc(qc_rows)
    return exported, failed, len(qc_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    zoom = BASE_PX_UM / TARGET_UM
    print(f"target {TARGET_UM} um/px -> zoom {zoom:.4f} (exact, not a pyramid level)")

    scenes = load_manifest()
    print(f"manifest: {len(scenes)} sections")
    fields = load_tile_fields()

    ranges = sample_display_ranges(scenes, fields, zoom, args.force)
    exported, failed, total_rows = export(scenes, fields, ranges, zoom, args.limit, args.force)

    print()
    print("=" * 72)
    print(f"exported {exported}, failed {failed}, focus.csv now holds {total_rows} sections")
    print("=" * 72)


if __name__ == "__main__":
    main()
