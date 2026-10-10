"""Stage 1b - illumination field measured from RAW tiles, then mapped to the
stitched domain.

`01f_tilefield.py` estimates the field by folding *stitched* sections at the
tile pitch. That works without raw tiles, but it can only ever see the composite
- anatomy has to be divided out first, and whatever the stitcher did in the
overlaps is baked in. It got the artifact from 18% down to 14.7%: real, but
short of the target.

This measures the thing directly. czifile exposes raw per-tile pixels, which
pylibCZIrw deliberately abstracts away and which Bio-Formats only offered
through the path that silently corrupted 238 sections. A per-pixel median across
thousands of raw tiles *is* the illumination profile: tissue sits at a random
position relative to the tile frame, so it averages out with no baseline model,
no detrending, and no folding assumption.

The catch is that a raw-tile field is 2040 px wide while the stitched image
repeats every 1836 px. Rather than assume which part of each tile survives
stitching, this reads the actual tile rectangles and their M indices and
reproduces the documented rule - within a scene, the subblock with the highest
M index wins - to derive the stitched-domain field exactly.

Reader: czifile (instrument characterisation only - no pixel value here reaches
a result). See LOGS.md.

Run:  python 01h_tilefield_raw.py
      python 01h_tilefield_raw.py --files 16 --tiles 60
"""

import sys
import argparse
import csv
import json
import os
import random
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import czifile

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402

SOURCE_DIR = CONFIG["source_dir"]
OUT_ROOT = CONFIG["out_root"]
FIELD_DIR = os.path.join(OUT_ROOT, "qc", "flatfield")

TILE_PX = 2040
PITCH_PX = 1836
# Same divisor the rest of the pipeline uses, so the output is drop-in
# compatible with the existing apply path. 2040/12 = 170, 1836/12 = 153.
FIELD_DIVISOR = 12
TILE_N = TILE_PX // FIELD_DIVISOR
PITCH_N = PITCH_PX // FIELD_DIVISOR

SEED = 20260812
# A tile that is almost entirely empty carries no illumination information.
MIN_TILE_MEDIAN = 50


def block_median(tile, n):
    """Reduce a 2040x2040 tile to n x n by block median.

    Median rather than mean: a bright speck or a saturated nucleus inside one
    block should not drag that block's estimate.
    """
    f = tile.shape[0] // n
    trimmed = tile[: n * f, : n * f]
    return np.median(trimmed.reshape(n, f, n, f), axis=(1, 3))


def collect_tiles(paths, tiles_per_file, rng):
    """Per-channel stacks of reduced raw tiles."""
    stacks = defaultdict(list)
    for i, (path, marker) in enumerate(paths, 1):
        try:
            with czifile.CziFile(path, memmap=True) as czi:
                base = [e for e in czi.subblock_directory if not e.is_pyramid]
                by_channel = defaultdict(list)
                for e in base:
                    ch = dict(zip(e.dims, e.start)).get("C", 0)
                    by_channel[ch].append(e)

                for ch, name in ((0, "DAPI"), (1, marker)):
                    entries = by_channel.get(ch, [])
                    if not entries:
                        continue
                    picks = rng.sample(entries, min(tiles_per_file, len(entries)))
                    for e in picks:
                        arr = e.asimage(czi).asarray()
                        if arr.ndim != 2 or arr.shape != (TILE_PX, TILE_PX):
                            continue
                        if np.median(arr) < MIN_TILE_MEDIAN:
                            continue
                        stacks[name].append(block_median(arr, TILE_N))
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {os.path.basename(path)}: {exc}")
            continue
        print(f"\r  [{i}/{len(paths)}] {os.path.basename(path):<20} "
              f"{ {k: len(v) for k, v in stacks.items()} }", end="")
    print()
    return stacks


def stitch_map(path):
    """Which position within a pitch cell comes from which tile offset.

    Reads the real tile rectangles and M indices and applies the documented
    overlap rule (highest M wins) rather than assuming that stitching keeps a
    tile's leading edge. Returns an index array of shape (PITCH_N, PITCH_N)
    giving, for each position in a pitch cell, the corresponding position in
    the tile frame.
    """
    with czifile.CziFile(path, memmap=True) as czi:
        base = [e for e in czi.subblock_directory if not e.is_pyramid]
        by_scene = defaultdict(list)
        for e in base:
            d = dict(zip(e.dims, e.start))
            if d.get("C", 0) != 0:
                continue
            by_scene[e.scene_index].append((d.get("X", 0), d.get("Y", 0), e.mosaic_index))
        if not by_scene:
            return None
        tiles = by_scene[sorted(by_scene)[0]]

    xs = sorted({t[0] for t in tiles})
    ys = sorted({t[1] for t in tiles})
    if len(xs) < 2 or len(ys) < 2:
        return None
    x0, y0 = xs[0], ys[0]

    # Work in the interior of the grid, where every position is covered by the
    # full complement of overlapping tiles.
    col, row = len(xs) // 2, len(ys) // 2
    cell_x, cell_y = xs[col], ys[row]
    m_of = {(t[0], t[1]): t[2] for t in tiles}

    tile_u = np.zeros((PITCH_N, PITCH_N), dtype=np.int64)
    tile_v = np.zeros((PITCH_N, PITCH_N), dtype=np.int64)
    for vi in range(PITCH_N):
        for ui in range(PITCH_N):
            gx = cell_x + ui * FIELD_DIVISOR
            gy = cell_y + vi * FIELD_DIVISOR
            best_m, best = None, None
            # Any tile whose frame contains this global position is a candidate.
            for tx in (cell_x - PITCH_PX, cell_x):
                for ty in (cell_y - PITCH_PX, cell_y):
                    if (tx, ty) not in m_of:
                        continue
                    du, dv = gx - tx, gy - ty
                    if 0 <= du < TILE_PX and 0 <= dv < TILE_PX:
                        m = m_of[(tx, ty)]
                        if best_m is None or m > best_m:
                            best_m, best = m, (du, dv)
            if best is None:
                best = (ui * FIELD_DIVISOR, vi * FIELD_DIVISOR)
            tile_u[vi, ui] = min(best[0] // FIELD_DIVISOR, TILE_N - 1)
            tile_v[vi, ui] = min(best[1] // FIELD_DIVISOR, TILE_N - 1)
    return tile_v, tile_u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=16)
    ap.add_argument("--tiles", type=int, default=60)
    args = ap.parse_args()
    os.makedirs(FIELD_DIR, exist_ok=True)
    rng = random.Random(SEED)

    with open(os.path.join(OUT_ROOT, "manifest", "manifest_files.csv"),
              newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["is_redundant_copy"] == "0"]

    by_marker = defaultdict(list)
    for r in rows:
        p = os.path.join(SOURCE_DIR, r["file"])
        if os.path.exists(p):
            by_marker[r["marker_channel"]].append((p, r["marker_channel"]))

    chosen = []
    for marker, pool in sorted(by_marker.items()):
        rng.shuffle(pool)
        chosen.extend(pool[: args.files // max(len(by_marker), 1)])
    print(f"sampling {len(chosen)} files x up to {args.tiles} tiles/channel\n")

    stacks = collect_tiles(chosen, args.tiles, rng)
    if not stacks:
        raise SystemExit("no tiles collected")

    print("\nderiving the stitched-domain mapping from real tile geometry ...")
    mapping = stitch_map(chosen[0][0])
    if mapping is None:
        print("  !! could not derive mapping; writing tile-domain field only")
    else:
        tv, tu = mapping
        overlap_frac = float((tu >= (PITCH_N - (TILE_PX - PITCH_PX) // FIELD_DIVISOR)).mean())
        print(f"  mapping derived; {100 * overlap_frac:.0f}% of a pitch cell comes "
              f"from a tile's trailing region")

    for name, stack in sorted(stacks.items()):
        arr = np.stack(stack)
        print(f"\n{name}: {arr.shape[0]} raw tiles")
        if arr.shape[0] < 40:
            print("  !! too few tiles for a stable median, skipping")
            continue

        tile_field = np.median(arr, axis=0)
        tile_field /= tile_field.mean()
        np.save(os.path.join(FIELD_DIR, f"tilefield_raw_{name}_tiledomain.npy"), tile_field)

        if mapping is not None:
            field = tile_field[tv, tu]
        else:
            field = tile_field[:PITCH_N, :PITCH_N]
        field = field / field.mean()

        lo, hi = np.percentile(field, [1, 99])
        print(f"  gain p1-p99 {lo:.3f}-{hi:.3f}  ({(hi / lo - 1) * 100:.0f}% across a tile)")

        # Named by CHANNEL, not by slot. The existing apply path loads
        # `tilefield_c1` as "the marker channel of this file", which silently
        # gives AF568 files and AF488 files the same correction even though
        # their measured fields differ substantially. Writing per-channel names
        # makes that impossible; the apply path selects by marker.
        #
        # Deliberately NOT written as tilefield_c0/c1: these are unvalidated
        # until 01c reports prominence < 2.0x at the pitch. Promote them only
        # after they pass.
        np.save(os.path.join(FIELD_DIR, f"tilefield_raw_{name}.npy"), field)
        try:
            import tifffile
            tifffile.imwrite(os.path.join(FIELD_DIR, f"tilefield_raw_{name}.tif"),
                             field.astype(np.float32))
        except ImportError:
            pass

        fig, ax = plt.subplots(1, 3, figsize=(15, 4.4))
        im = ax[0].imshow(tile_field, cmap="viridis")
        ax[0].set_title(f"{name}: raw-tile field ({TILE_PX} px tile)")
        fig.colorbar(im, ax=ax[0], fraction=0.046)
        im = ax[1].imshow(field, cmap="viridis")
        ax[1].set_title(f"{name}: stitched-domain field ({PITCH_PX} px pitch)")
        fig.colorbar(im, ax=ax[1], fraction=0.046)
        ax[2].plot(tile_field[TILE_N // 2, :], label=f"raw tile, horizontal")
        ax[2].plot(field[PITCH_N // 2, :], label="stitched, horizontal")
        ax[2].axhline(1.0, color="#909090", lw=0.7)
        ax[2].legend()
        ax[2].set_title(f"p1-p99 {lo:.2f}-{hi:.2f}")
        fig.tight_layout()
        fig.savefig(os.path.join(FIELD_DIR, f"tilefield_raw_{name}.png"), dpi=110)
        plt.close(fig)

    print()
    print("=" * 72)
    print("Written as tilefield_raw_<CHANNEL>.npy - NOT yet promoted to the")
    print("tilefield_c{0,1} names the apply path reads. Promote only after:")
    print("  01f_tilefield.py verify  &&  01c_measure_tile_artifact.py")
    print("PASS = prominence < 2.0x at the 1836 px pitch AND amplitude < 6%.")
    print()
    print("A gain range far outside roughly 0.6-1.4 means the median has not")
    print("converged - raise --tiles rather than trusting it. AF568 in")
    print("particular needs many more tiles: its background outshines the")
    print("tissue, so individual tiles are dominated by whatever is behind")
    print("the section rather than by the illumination profile.")
    print("=" * 72)


if __name__ == "__main__":
    main()
