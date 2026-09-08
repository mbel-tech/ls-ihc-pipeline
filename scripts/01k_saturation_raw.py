"""Stage 1k - measure clipping on the RAW plane, before the tile field.

`01_overviews.py` applied `apply_tile_field()` and *then* measured
`saturated_fraction`. Dividing by a gain above 1 lifts a pixel off the 16-bit
ceiling, so it stops counting as clipped - but the value is gone either way,
because no correction puts back what the sensor never recorded. `tilefield_c1`
runs 0.812-1.097 and exceeds 1.0 over **54%** of its area, so the recorded
column is approximately `clipping x 0.46`.

Measured, before and after, on the same scenes:

    LS45_1a.czi sc14   raw 0.28314   corrected 0.13611   (focus.csv: 0.13611)
    LS53_2b.czi sc11   raw 0.42662   corrected 0.20842
    median |raw - corrected| = 0.104 over 10 clipping-heavy sections

This backfills the two `_raw` columns onto the 2,572 rows `focus.csv` already
holds, **without re-exporting a single PNG**, and writes the raw clipping mask
that `04j_censor_clipped.py` should have been using. `04j` derived its censor
mask by thresholding the exported 8-bit `_MARK.png` at 255 - a post-correction
image - so the mask inherited the same undercount and carried it into the
per-nucleus `censored` column through `05c_detect_rois.py`.

**Its validation was circular.** `04j`'s docstring reports a median absolute
difference of 0.00000 against `focus.csv`'s `saturated_fraction`. That is true
and it proves nothing: both sides were measured after the same correction.

Resolution is a second, smaller understatement, and it is **scale-dependent** -
which is why `--native-sample` measures it rather than assuming a constant.
Downsampling only loses a clipped pixel whose neighbours were not clipped, so
sparse clipping dilutes hard and dense clipping barely at all. Measured over 30
sections:

    all sampled sections          median 1.73x   (max 22.99x)
    clipping above 0.1% of frame  median 1.09x
    clipping above 1%   of frame  median 1.09x   (1.08-1.23)

The large ratios are sections with a handful of isolated clipped pixels, where
the denominator is a few pixels and the ratio means little. **On the sections
that matter the factor is about 1.09**, so the combined understatement there is
roughly 2.2x, not the 3.4x that multiplying the two medians would suggest.

Run:  work/appenv/Scripts/python.exe scripts/01k_saturation_raw.py
      ... --limit 50 --force --native-sample 30
"""

import argparse
import csv
import importlib.util
import os
import time
import sys

import numpy as np
from PIL import Image

# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_channels as CH  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_ov", os.path.join(_HERE, "01_overviews.py"))
OV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(OV)

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

SOURCE_DIR = OV.SOURCE_DIR
OUT_ROOT = OV.OUT_ROOT
QC_DIR = OV.QC_DIR
FOCUS_CSV = OV.QC_CSV
OUT_CSV = os.path.join(QC_DIR, "saturation_raw.csv")
MASK_DIR = os.path.join(QC_DIR, "censor_raw")
NATIVE_CSV = os.path.join(QC_DIR, "saturation_raw_native.csv")

# Fallback only. The real value is per-file, from the manifest's clip_ceiling
# column, via OV.ceiling_for() - see load_ceilings()'s docstring in
# 01_overviews.py for why 65535 cannot just be assumed.
CEILING = 65535
# Masks are written for BOTH markers.
#
# **AF488 is not clip-free, and the belief that it was came from this same bug.**
# LOGS.md said "AF488 cannot clip, so there is nothing to censor". Measured on
# the raw plane it clips on most sections - median 0.000007 of frame - and
# reaches **1.3%** on the worst. It went unnoticed because the only test anyone
# had was the 8-bit proxy, and AF488's display high is 37,263: a PNG value of
# 255 there means "at or above the display high", not "at the sensor ceiling",
# so the question could not even be asked. Raw 16-bit measurement can ask it.
MASK_MARKERS = tuple(CH.marker_names(CONFIG))

KEYS = ["scene_uid", "file", "animal", "slide", "variant", "marker_channel",
        "scene_index", "section_order", "width", "height", "um_px", "zoom",
        # The scene origin in CZI stage pixels. Recorded here so 06f can map a
        # nucleus from czi_x/czi_y into this mask without reopening 222 CZIs.
        "rect_x", "rect_y", "rect_w", "rect_h",
        "saturated_fraction_raw", "saturated_fraction_dapi_raw",
        "saturated_fraction_corrected", "raw_over_corrected",
        "mask_path", "tilefield_applied", "reader"]


def measure(czidoc, rect, fields, zoom, want_mask, ceiling=CEILING, *, scene):
    """Raw clipping for both channels, and the corrected figure for comparison.

    `scene` is required: measuring clipping on a rectangle that composites a
    neighbour's tissue is how the clipped fraction came to be overstated by up
    to 2.6x in the first place.
    """
    dapi_raw = OV.read_scene(czidoc, rect, 0, zoom, scene=scene)
    mark_raw = OV.read_scene(czidoc, rect, 1, zoom, scene=scene)
    clipped = mark_raw >= ceiling
    corrected = OV.apply_tile_field(mark_raw, fields.get(1), 1 / zoom)
    return {
        "raw": float(clipped.mean()),
        "dapi_raw": float((dapi_raw >= ceiling).mean()),
        "corrected": float((corrected >= ceiling).mean()),
        "shape": mark_raw.shape,
        "mask": clipped if want_mask else None,
    }


def native_sample(scenes, n, ceilings, seed=20260901):
    """Measure the resolution-dilution factor instead of assuming it.

    A clipped pixel survives downsampling only if its whole neighbourhood was
    clipped, so 5.20 um/px understates what the sensor lost. Sampled from
    sections that clip at all - where nothing clips there is nothing to dilute
    and the ratio is undefined.
    """
    from pylibCZIrw import czi as pyczi

    rng = np.random.default_rng(seed)
    # AF568 only: it is the marker that clips at a measurable scale, so it is
    # the only one where a dilution ratio has a denominator worth dividing by.
    pool = [r for r in scenes if r["marker_channel"] == "AF568"]
    rng.shuffle(pool)
    by_file = {}
    for r in pool:
        by_file.setdefault(r["file"], []).append(r)

    rows = []
    for fname, rs in by_file.items():
        if len(rows) >= n:
            break
        path = os.path.join(SOURCE_DIR, fname)
        if not os.path.exists(path):
            continue
        ceiling = OV.ceiling_for(ceilings, fname)
        with pyczi.open_czi(path) as czidoc:
            rects = czidoc.scenes_bounding_rectangle
            for r in rs:
                if len(rows) >= n:
                    break
                s = int(r["scene_index"])
                if s not in rects:
                    continue
                # This function's whole purpose is measuring how much the
                # dilution ratio understates clipping at low zoom, so a
                # rectangle that composites a neighbouring section's tissue
                # corrupts the measurement itself, not merely a pixel count.
                low = OV.read_scene(czidoc, rects[s], 1, 0.125, scene=s)
                f_low = float((low >= ceiling).mean())
                if f_low <= 0:
                    continue
                hi = OV.read_scene(czidoc, rects[s], 1, 1.0, scene=s)
                f_hi = float((hi >= ceiling).mean())
                rows.append({
                    "scene_uid": r["scene_uid"], "file": fname,
                    "frac_at_5_20um": round(f_low, 6),
                    "frac_at_0_65um": round(f_hi, 6),
                    "native_over_overview": round(f_hi / f_low, 4),
                })
                print("\r  native sample %d/%d" % (len(rows), n), end="")
    print()
    atomic_write(NATIVE_CSV, rows, ["scene_uid", "file", "frac_at_5_20um",
                                    "frac_at_0_65um", "native_over_overview"])
    if rows:
        v = np.array([r["native_over_overview"] for r in rows], dtype=float)
        print("  native / overview clipped fraction: median %.3f  min %.3f  max %.3f  (n=%d)"
              % (np.median(v), v.min(), v.max(), len(v)))
    return rows


def merge_into_focus(rows):
    """Add the two _raw columns to focus.csv, matching 01_overviews' QC_KEYS."""
    if not os.path.exists(FOCUS_CSV):
        print("  focus.csv not found - nothing to merge")
        return 0
    with open(FOCUS_CSV, newline="", encoding="utf-8") as fh:
        rdr = csv.DictReader(fh)
        foc = list(rdr)
        keys = list(rdr.fieldnames)
    by_uid = {r["scene_uid"]: r for r in rows}
    for k in ("saturated_fraction_dapi_raw", "saturated_fraction_raw"):
        if k not in keys:
            keys.insert(keys.index("saturated_fraction") + 1, k)
    hit = 0
    for r in foc:
        m = by_uid.get(r["scene_uid"])
        if not m:
            r.setdefault("saturated_fraction_raw", "")
            r.setdefault("saturated_fraction_dapi_raw", "")
            continue
        r["saturated_fraction_raw"] = m["saturated_fraction_raw"]
        r["saturated_fraction_dapi_raw"] = m["saturated_fraction_dapi_raw"]
        hit += 1
    atomic_write(FOCUS_CSV, foc, keys)
    print("  merged %d/%d rows into %s" % (hit, len(foc), FOCUS_CSV))
    return hit


def summarise(rows, measured, failed):
    """The console summary. Returns early on nothing measured: np.max on an
    empty array raises, and a run whose only file failed still has to exit
    with a sentence rather than a traceback."""
    print()
    print("=" * 74)
    print("measured %d, failed %d, %s now holds %d sections"
          % (measured, failed, OUT_CSV, len(rows)))
    if not rows:
        print("nothing measured - is the source drive mounted?")
        print("=" * 74)
        return
    raw = np.array([float(r["saturated_fraction_raw"]) for r in rows])
    dap = np.array([float(r["saturated_fraction_dapi_raw"]) for r in rows])
    ratio = np.array([float(r["raw_over_corrected"]) for r in rows if r["raw_over_corrected"]])
    print("  marker clipping (raw) : median %.6f  p95 %.6f  max %.6f"
          % (np.median(raw), np.percentile(raw, 95), raw.max()))
    print("  DAPI clipping (raw)   : median %.6f  max %.6f   <- expected near zero"
          % (np.median(dap), dap.max()))
    if len(ratio):
        print("  raw / corrected       : median %.3f  p05 %.3f  p95 %.3f  (n=%d)"
              % (np.median(ratio), np.percentile(ratio, 5), np.percentile(ratio, 95), len(ratio)))
    print("=" * 74)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--native-sample", type=int, default=30,
                    help="sections to also read at zoom=1.0; 0 to skip")
    ap.add_argument("--no-merge", action="store_true")
    args = ap.parse_args()

    from pylibCZIrw import czi as pyczi

    zoom = OV.BASE_PX_UM / OV.TARGET_UM
    scenes = OV.load_manifest()
    fields = OV.load_tile_fields()
    ceilings = OV.load_ceilings()
    os.makedirs(MASK_DIR, exist_ok=True)
    print("manifest: %d sections at zoom %.4f (%s um/px)" % (len(scenes), zoom, OV.TARGET_UM))

    rows, done = [], set()
    if os.path.exists(OUT_CSV) and not args.force:
        with open(OUT_CSV, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        # A row counts as done only if the mask its marker now calls for is
        # actually on disk. Without this, widening MASK_MARKERS would resume
        # straight past every section it was widened to cover.
        keep = []
        for r in rows:
            if r["marker_channel"] in MASK_MARKERS and not os.path.exists(
                    os.path.join(MASK_DIR, r["scene_uid"] + "_clipped.png")):
                continue
            keep.append(r)
        remeasure = len(rows) - len(keep)
        rows = keep
        done = {r["scene_uid"] for r in rows}
        print("resuming: %d sections already measured" % len(done))
        if remeasure:
            print("  %d measured rows have no mask yet and will be redone" % remeasure)

    by_file = {}
    for r in scenes:
        if r["scene_uid"] not in done:
            by_file.setdefault(r["file"], []).append(r)
    total = sum(len(v) for v in by_file.values())
    print("%d sections to measure across %d files" % (total, len(by_file)))

    measured = failed = 0
    t0 = time.time()
    for fname, rs in by_file.items():
        if args.limit and measured >= args.limit:
            break
        path = os.path.join(SOURCE_DIR, fname)
        if not os.path.exists(path):
            failed += len(rs)
            continue
        try:
            with pyczi.open_czi(path) as czidoc:
                rects = czidoc.scenes_bounding_rectangle
                for r in rs:
                    if args.limit and measured >= args.limit:
                        break
                    s = int(r["scene_index"])
                    if s not in rects:
                        failed += 1
                        continue
                    uid = r["scene_uid"]
                    want = r["marker_channel"] in MASK_MARKERS
                    ceiling = OV.ceiling_for(ceilings, fname)
                    m = measure(czidoc, rects[s], fields, zoom, want, ceiling, scene=s)

                    mask_path = ""
                    if want:
                        mask_path = os.path.join(MASK_DIR, uid + "_clipped.png")
                        with IO.atomic_save(mask_path) as tmp:
                            Image.fromarray((m["mask"] * 255).astype(np.uint8)).save(tmp, format="PNG")

                    h, w = m["shape"]
                    ratio = m["raw"] / m["corrected"] if m["corrected"] > 0 else None
                    rows.append({
                        "scene_uid": uid, "file": fname, "animal": r["animal"],
                        "slide": r["slide"], "variant": r["variant"],
                        "marker_channel": r["marker_channel"], "scene_index": s,
                        "section_order": r["section_order"],
                        "width": w, "height": h,
                        "rect_x": rects[s].x, "rect_y": rects[s].y,
                        "rect_w": rects[s].w, "rect_h": rects[s].h,
                        "um_px": "%.2f" % (OV.BASE_PX_UM / zoom), "zoom": "%.4f" % zoom,
                        "saturated_fraction_raw": "%.6f" % m["raw"],
                        "saturated_fraction_dapi_raw": "%.6f" % m["dapi_raw"],
                        "saturated_fraction_corrected": "%.6f" % m["corrected"],
                        "raw_over_corrected": "" if ratio is None else "%.3f" % ratio,
                        "mask_path": os.path.relpath(mask_path, OUT_ROOT) if mask_path else "",
                        # 0, and that is the whole point of this script.
                        "tilefield_applied": 0,
                        "reader": "pylibCZIrw",
                    })
                    measured += 1
        except Exception as exc:  # noqa: BLE001 - one bad file must not kill the run
            print("\n  !! %s: %s" % (fname, exc))
            failed += len(rs)

        # Checkpoint per file, like 01_overviews.py, for the same reason.
        IO.atomic_write_csv(OUT_CSV, rows, KEYS)
        rate = measured / max(time.time() - t0, 1e-9)
        print("\r  measured %d/%d  failed %d  (%.1f/s, %.1f min)"
              % (measured, total, failed, rate, (time.time() - t0) / 60), end="")
    print()
    IO.atomic_write_csv(OUT_CSV, rows, KEYS)

    summarise(rows, measured, failed)
    print("measured %d, failed %d, %s now holds %d sections"
          % (measured, failed, OUT_CSV, len(rows)))
    print("  marker clipping (raw) : median %.6f  p95 %.6f  max %.6f"
          % (np.median(raw), np.percentile(raw, 95), raw.max()))
    print("  DAPI clipping (raw)   : median %.6f  max %.6f   <- expected near zero"
          % (np.median(dap), dap.max()))
    if len(ratio):
        print("  raw / corrected       : median %.3f  p05 %.3f  p95 %.3f  (n=%d)"
              % (np.median(ratio), np.percentile(ratio, 5), np.percentile(ratio, 95), len(ratio)))
    print("=" * 74)

    if not rows:
        return
    if not args.no_merge:
        merge_into_focus(rows)
    if args.native_sample:
        print()
        print("measuring the resolution-dilution factor on %d sections ..." % args.native_sample)
        native_sample(scenes, args.native_sample, ceilings)


if __name__ == "__main__":
    main()
