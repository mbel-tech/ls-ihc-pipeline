"""Stage 1b - exact tile origins, read from the CZI subblock directory.

The tile pitch has to be known precisely. Estimating it from the image's own
power spectrum gives roughly the right number (~1210 um) but nowhere near
enough precision: an error of one part in 500 accumulates to a whole tile of
drift across a 13,000 px section, so a correction built on it would slide out
of phase halfway across the image.

The CZI already records it exactly. Each subblock directory entry carries the
mosaic pixel coordinates of its tile, so the true grid can be read without
decoding any pixel data - roughly a second per file.

Segment layout:
  SubBlockDirectorySegment = SegmentHeader(32) + EntryCount(4) + reserved(124)
  DirectoryEntryDV         = SchemaType(2) PixelType(4) FilePosition(8)
                             FilePart(4) Compression(4) PyramidType(1)
                             spare(1) spare(4) DimensionCount(4)   = 32 bytes
  DimensionEntryDV         = Dimension(4) Start(4) Size(4)
                             StartCoordinate(4) StoredSize(4)      = 20 bytes

Run:  python 01e_tile_geometry.py                  # a sample of files
      python 01e_tile_geometry.py LS45_5a.czi ...  # specific files
      python 01e_tile_geometry.py --all
"""

import csv
import glob
import json
import os
import struct
import sys
from collections import defaultdict

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402

SOURCE_DIR = CONFIG["source_dir"]
OUT_ROOT = CONFIG["out_root"]
QC_DIR = os.path.join(OUT_ROOT, "qc")
PX_UM = CONFIG["pixel_size_um"]

SAMPLE_FILES = 12
HEADER_LEN = 288
SEGMENT_HEADER_LEN = 32
DIR_RESERVED = 124
ENTRY_LEN = 32
DIM_ENTRY_LEN = 20


def read_tiles(path):
    """Every full-resolution tile in the file as a dict of dimension values."""
    with open(path, "rb") as fh:
        head = fh.read(HEADER_LEN)
        if head[:10] != b"ZISRAWFILE":
            raise ValueError("not a CZI")
        dir_pos, _meta_pos = struct.unpack("<QQ", head[84:100])

        fh.seek(dir_pos)
        seg = fh.read(SEGMENT_HEADER_LEN)
        # The segment ID field is 16 bytes wide; anything past that is already
        # the allocated-size field.
        if seg[:16].rstrip(b"\x00") != b"ZISRAWDIRECTORY":
            raise ValueError(f"unexpected segment at directory position: {seg[:16]!r}")

        count, = struct.unpack("<i", fh.read(4))
        fh.read(DIR_RESERVED)

        tiles = []
        for _ in range(count):
            entry = fh.read(ENTRY_LEN)
            if len(entry) < ENTRY_LEN:
                break
            n_dims, = struct.unpack("<i", entry[28:32])

            dims = {}
            for _ in range(n_dims):
                raw = fh.read(DIM_ENTRY_LEN)
                if len(raw) < DIM_ENTRY_LEN:
                    break
                name = raw[:4].rstrip(b"\x00").decode("ascii", "replace")
                start, size, _start_coord, stored = struct.unpack("<iifi", raw[4:20])
                dims[name] = {"start": start, "size": size, "stored": stored}

            x, y = dims.get("X"), dims.get("Y")
            if not x or not y:
                continue
            # Downsampled pyramid tiles store fewer pixels than they span.
            if x["stored"] and x["size"] // x["stored"] != 1:
                continue

            tiles.append(
                {
                    "scene": dims.get("S", {}).get("start", 0),
                    "m": dims.get("M", {}).get("start", 0),
                    "channel": dims.get("C", {}).get("start", 0),
                    "x_start": x["start"], "y_start": y["start"],
                    "width": x["size"], "height": y["size"],
                }
            )
    return tiles


def grid_pitch(values):
    """Spacing of a regular 1-D grid, from the smallest positive step."""
    unique = np.unique(np.asarray(values, dtype=np.int64))
    if unique.size < 2:
        return None, unique.size
    steps = np.diff(unique)
    steps = steps[steps > 0]
    if not steps.size:
        return None, unique.size
    # Origins repeat per row/column, so the modal smallest step is the pitch.
    return float(np.median(steps[steps <= np.percentile(steps, 60)])), unique.size


def analyse(path):
    tiles = read_tiles(path)
    if not tiles:
        return None, []

    by_scene = defaultdict(list)
    for t in tiles:
        if t["channel"] == 0:
            by_scene[t["scene"]].append(t)

    rows = []
    pitches_x, pitches_y = [], []
    for scene, group in sorted(by_scene.items()):
        xs = [t["x_start"] for t in group]
        ys = [t["y_start"] for t in group]
        px, ncols = grid_pitch(xs)
        py, nrows = grid_pitch(ys)
        if px:
            pitches_x.append(px)
        if py:
            pitches_y.append(py)

        widths = {t["width"] for t in group}
        heights = {t["height"] for t in group}
        rows.append(
            {
                "file": os.path.basename(path), "scene": scene, "n_tiles": len(group),
                "tile_w": sorted(widths)[0], "tile_h": sorted(heights)[0],
                "n_cols": ncols, "n_rows": nrows,
                "pitch_x_px": round(px, 2) if px else "",
                "pitch_y_px": round(py, 2) if py else "",
                "pitch_x_um": round(px * PX_UM, 2) if px else "",
                "pitch_y_um": round(py * PX_UM, 2) if py else "",
                "overlap_x_pct": round(100.0 * (1 - px / sorted(widths)[0]), 2) if px else "",
                "overlap_y_pct": round(100.0 * (1 - py / sorted(heights)[0]), 2) if py else "",
                "origin_x": min(xs), "origin_y": min(ys),
            }
        )

    summary = {
        "file": os.path.basename(path),
        "n_scenes": len(by_scene),
        "n_tiles_total": len(tiles),
        "pitch_x_px": round(float(np.median(pitches_x)), 2) if pitches_x else "",
        "pitch_y_px": round(float(np.median(pitches_y)), 2) if pitches_y else "",
    }
    return summary, rows


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    take_all = "--all" in sys.argv

    if args:
        paths = [os.path.join(SOURCE_DIR, a) for a in args]
    else:
        paths = sorted(glob.glob(os.path.join(SOURCE_DIR, "*.czi")))
        if not take_all:
            step = max(1, len(paths) // SAMPLE_FILES)
            paths = paths[::step][:SAMPLE_FILES]

    print(f"Reading tile geometry from {len(paths)} file(s)\n")
    all_rows, summaries = [], []
    for path in paths:
        if not os.path.exists(path):
            print(f"  !! {os.path.basename(path)} not on disk")
            continue
        try:
            summary, rows = analyse(path)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {os.path.basename(path)}: {exc}")
            continue
        if not summary:
            continue
        summaries.append(summary)
        all_rows.extend(rows)
        print(f"  {summary['file']:<18} {summary['n_scenes']:>3} scenes  "
              f"{summary['n_tiles_total']:>5} tiles  pitch {summary['pitch_x_px']} x {summary['pitch_y_px']} px")

    if not all_rows:
        print("nothing measured")
        return

    os.makedirs(QC_DIR, exist_ok=True)
    out = os.path.join(QC_DIR, "tile_geometry.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    px = [r["pitch_x_px"] for r in all_rows if r["pitch_x_px"] != ""]
    py = [r["pitch_y_px"] for r in all_rows if r["pitch_y_px"] != ""]
    tw = sorted({r["tile_w"] for r in all_rows})
    th = sorted({r["tile_h"] for r in all_rows})

    print()
    print("=" * 72)
    print(f"scenes measured   : {len(all_rows)}")
    print(f"tile size (px)    : {tw} x {th}")
    if px:
        print(f"pitch X (px)      : median {np.median(px):.2f}  spread {np.min(px):.1f}-{np.max(px):.1f}")
        print(f"pitch X (um)      : {np.median(px) * PX_UM:.2f}")
        print(f"overlap X         : {100 * (1 - np.median(px) / tw[0]):.1f}%")
    if py:
        print(f"pitch Y (px)      : median {np.median(py):.2f}  spread {np.min(py):.1f}-{np.max(py):.1f}")
        print(f"pitch Y (um)      : {np.median(py) * PX_UM:.2f}")
        print(f"overlap Y         : {100 * (1 - np.median(py) / th[0]):.1f}%")
    print()
    print("Compare against the power-spectrum estimate of ~1206-1227 um: these")
    print("are the exact values, and they are what the correction must use.")
    print(f"wrote {out}")
    print("=" * 72)


if __name__ == "__main__":
    main()
