"""Two plate sets, before and after a swap. Not a test - shared setup.

Shaped on the swap that actually happened here on 2026-09-06: same ids, some
plates re-rendered, some genuinely different, some gone. Four plates instead of
sixty-four, one per outcome of `ls_atlas.plate_status` that a plate set ON DISK
can actually produce:

    plate_001   byte-identical            -> OK
    plate_002   the same image at 1.5x    -> RESIZED
    plate_003   re-cropped, new aspect    -> CHANGED
    plate_004   absent from `after`       -> GONE

That is four of `plate_status`'s six outcomes. UNCHECKED and BY_INDEX describe
a STORED record that predates fingerprints, not a state a plate set on disk
can be in - no fixture plate produces them; they are pinned directly in
`tests/test_ls_atlas.py:141-146` instead.

`plate_005` is present in `after` and absent from `before`, so a test can
check that a new id is not mistaken for one of the other four.

A real limitation of `plate_status`, not of this fixture: it cannot tell a
genuine re-render from an unrelated image dropped in at the same size - both
come back RESIZED, because nothing but the id ties two images together. See
the "a replacement at the same size" assertion in `tests/test_ls_atlas.py`.

The images are deterministic - a seeded pattern, not random - so a fingerprint
is stable across runs and a failure is reproducible.
"""

import csv
import os

import numpy as np
from PIL import Image

PLATE_W, PLATE_H = 120, 80
COLUMNS = ("plate_id", "page", "image_file", "px_w", "px_h")

# Fixture plumbing only - NOT a real-schema column. `plates_final/plates.csv`
# has no `regions` column at all; a real set's regions live in `seeds.csv`,
# one row per seed. This dict exists solely to give `_seeds_csv` something to
# write, keyed by plate id since a real plate's regions do not change with
# the plate set it happens to be rendered into.
_REGIONS = {
    "plate_001": "Dl;Dm",
    "plate_002": "Dl;Dm",
    "plate_003": "Dl",
    "plate_004": "Dl;Dm",
    "plate_005": "Vd",
}


def _pattern(w, h, seed):
    """A deterministic greyscale plate. Different seed, different bytes."""
    ys, xs = np.mgrid[0:h, 0:w]
    value = (xs * (seed + 3) + ys * (seed + 7)) % 251
    return np.uint8(value)


def _write(path, array):
    Image.fromarray(array, mode="L").save(path)


def build(root):
    """Lay out `<root>/before/` and `<root>/after/`. Returns (before, after)."""
    before = os.path.join(root, "before")
    after = os.path.join(root, "after")
    for d in (before, after):
        os.makedirs(d, exist_ok=True)

    base = {n: _pattern(PLATE_W, PLATE_H, n) for n in (1, 2, 3, 4)}

    # image_file deliberately does NOT collapse onto plate_id - the real set
    # pairs plate_id=plate_001 with image_file=plate_001_p01.png, and that
    # divergence is the whole reason `ls_atlas._image_stem` exists. The name
    # for a given plate must also stay IDENTICAL between `before` and
    # `after` (page == plate number here in both), because the cache test
    # below replaces `swapped/<name>` in place and needs the same path to
    # land on the same plate in both sets.
    def image_name(n):
        return "plate_%03d_p%02d.png" % (n, n)

    rows_before = []
    for n in (1, 2, 3, 4):
        name = image_name(n)
        _write(os.path.join(before, name), base[n])
        rows_before.append({"plate_id": "plate_%03d" % n, "page": n,
                            "image_file": name, "px_w": PLATE_W,
                            "px_h": PLATE_H})

    rows_after = []
    # plate_001: the same bytes.
    _write(os.path.join(after, image_name(1)), base[1])
    rows_after.append({"plate_id": "plate_001", "page": 1,
                       "image_file": image_name(1), "px_w": PLATE_W,
                       "px_h": PLATE_H})
    # plate_002: the same picture, re-rendered 1.5x. Same aspect, new bytes.
    big = np.asarray(Image.fromarray(base[2], mode="L").resize(
        (int(PLATE_W * 1.5), int(PLATE_H * 1.5)), Image.NEAREST))
    _write(os.path.join(after, image_name(2)), big)
    rows_after.append({"plate_id": "plate_002", "page": 2,
                       "image_file": image_name(2),
                       "px_w": int(PLATE_W * 1.5), "px_h": int(PLATE_H * 1.5)})
    # plate_003: re-cropped. The aspect moves, so this is not a resize.
    crop = base[3][:, : PLATE_W // 2]
    _write(os.path.join(after, image_name(3)), crop)
    rows_after.append({"plate_id": "plate_003", "page": 3,
                       "image_file": image_name(3), "px_w": PLATE_W // 2,
                       "px_h": PLATE_H})
    # plate_004 is absent. plate_005 is new.
    _write(os.path.join(after, image_name(5)), _pattern(PLATE_W, PLATE_H, 5))
    rows_after.append({"plate_id": "plate_005", "page": 5,
                       "image_file": image_name(5), "px_w": PLATE_W,
                       "px_h": PLATE_H})

    _plates_csv(before, rows_before)
    _plates_csv(after, rows_after)
    _seeds_csv(before, rows_before)
    _seeds_csv(after, rows_after)
    return before, after


def _plates_csv(directory, rows):
    with open(os.path.join(directory, "plates.csv"), "w",
              newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _seeds_csv(directory, rows):
    """Two seeds per plate, in the schema every real set shares.

    Coordinates are schema filler, not a rescale to assert against - a test
    that needs seeds at rescaled coordinates should compute its own expected
    values rather than trust a fixture's precomputed ones.
    """
    keys = ("plate_id", "page", "plate_seq", "region", "region_raw",
            "is_unknown", "colour_hex", "from_raster", "x_px", "y_px",
            "x_frac", "y_frac")
    out = []
    for r in rows:
        regions = _REGIONS.get(r["plate_id"], "Dl").split(";")[:2]
        for i, region in enumerate(regions, 1):
            out.append({"plate_id": r["plate_id"], "page": r["page"],
                        "plate_seq": i, "region": region, "region_raw": region,
                        "is_unknown": 0, "colour_hex": "#ff0000",
                        "from_raster": 1, "x_px": 10 * i, "y_px": 20 * i,
                        "x_frac": round(10 * i / float(r["px_w"]), 4),
                        "y_frac": round(20 * i / float(r["px_h"]), 4)})
    with open(os.path.join(directory, "seeds.csv"), "w",
              newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(keys))
        writer.writeheader()
        writer.writerows(out)
