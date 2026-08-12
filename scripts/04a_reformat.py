"""Stage 4a - normalise sections and atlas plates into a common frame.

Adopted from BrainJ (Hammond, Cellular Imaging Platform), whose second pipeline
step centres each section, rotates it horizontal, and removes surrounding tissue
and debris *before* any analysis. See REFERENCES.md.

Why this comes first: `04b_atlas_match.py` was comparing raw hand-drawn scan
regions against arbitrarily cropped atlas plates. Position, scale, rotation and
debris were all free parameters, which is why it needed an eight-way orientation
search at all - and why the search returned nothing useful until the silhouettes
themselves were fixed. Normalising removes those parameters instead of searching
over them.

Each image is reduced to a tissue mask, then:

  1. **debris removed**    - components below a fraction of the largest are dropped,
                             so a fleck of tissue cannot drag the centroid or the axis
  2. **rotated horizontal** - by the principal axis of the mask, so the section's long
                             axis lies along x regardless of how it was mounted
  3. **centred and cropped** - to the tissue bounding box, then padded square
  4. **rescaled**           - to a fixed grid

Step 2 has a 180 degree ambiguity: the principal axis gives an orientation, not a
direction. That is resolved by making the heavier half consistently the same
side, which is stable for a shape with any dorsoventral asymmetry.

Left-right mirroring is *not* resolved here and deliberately so. Free-floating
sections land face up or face down, and a bilaterally near-symmetric section
carries almost no shape evidence of which. BrainJ makes flipping a separate
manual step for the same reason; here it is carried as an explicit per-section
hypothesis into matching (04b) and the curator.

Run:  python 04a_reformat.py
      python 04a_reformat.py --preview 12
"""

import argparse
import csv
import json
import os

import numpy as np
from PIL import Image
from scipy import ndimage

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
PLATE_DIR = os.path.join(OUT_ROOT, "atlas", "plates")
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")

GRID = 256                  # normalised output is GRID x GRID
MIN_COMPONENT_FRACTION = 0.12   # debris threshold, relative to the largest component
WORK_SIZE = 400             # analysis resolution; output is resampled from the source


def otsu(values):
    hist, edges = np.histogram(values, bins=256)
    hist = hist.astype(np.float64)
    centres = (edges[:-1] + edges[1:]) / 2.0
    w1, w2 = np.cumsum(hist), np.cumsum(hist[::-1])[::-1]
    valid = (w1 > 0) & (w2 > 0)
    m1 = np.cumsum(hist * centres) / np.maximum(w1, 1e-9)
    m2 = (np.cumsum((hist * centres)[::-1]) / np.maximum(w2[::-1], 1e-9))[::-1]
    var = w1 * w2 * (m1 - m2) ** 2
    var[~valid] = -1
    return float(centres[int(np.argmax(var))])


def tissue_mask(v, light_background):
    """Binary tissue mask.

    Two polarities, two thresholds. Atlas plates are dark tissue on light paper;
    sections are faint fluorescence on black. Using one rule for both is what
    produced rim-only plates and speckle-only sections in the first attempt.
    """
    if light_background:
        mask = v < np.percentile(v, 90) * 0.92
    else:
        positive = v[v > 0]
        if positive.size < 200:
            return None
        mask = v > float(np.expm1(otsu(np.log1p(positive))))

    mask = ndimage.binary_closing(mask, np.ones((7, 7)))
    mask = ndimage.binary_fill_holes(mask)
    mask = ndimage.binary_opening(mask, np.ones((3, 3)))

    labels, n = ndimage.label(mask)
    if n == 0:
        return None
    sizes = np.array(ndimage.sum(mask, labels, range(1, n + 1)))
    keep = np.where(sizes >= MIN_COMPONENT_FRACTION * sizes.max())[0] + 1
    mask = np.isin(labels, keep)
    return mask if mask.sum() >= 200 else None


def principal_angle(mask):
    """Angle of the mask's long axis, in degrees.

    Second central moments give the orientation of the best-fitting ellipse.
    Rotating by its negative puts the long axis along x.
    """
    ys, xs = np.nonzero(mask)
    y, x = ys - ys.mean(), xs - xs.mean()
    cov = np.cov(np.vstack([x, y]))
    evals, evecs = np.linalg.eigh(cov)
    major = evecs[:, int(np.argmax(evals))]
    return float(np.degrees(np.arctan2(major[1], major[0])))


def resolve_180(mask):
    """Decide between an orientation and its 180 degree twin.

    The principal axis is an axis, not a direction. Fixing it by putting the
    heavier half consistently on the same side is stable for any shape with
    dorsoventral asymmetry, and harmless for one without.
    """
    h = mask.shape[0]
    return mask[: h // 2].sum() < mask[h // 2:].sum()


def reformat(path, light_background):
    """Return (normalised grayscale, normalised mask, angle applied)."""
    try:
        img = Image.open(path).convert("L")
    except OSError:
        return None
    work = np.asarray(img.resize((WORK_SIZE, WORK_SIZE), Image.BILINEAR)).astype(np.float32)

    mask = tissue_mask(work, light_background)
    if mask is None:
        return None

    angle = principal_angle(mask)
    # Rotate the mask and the image by the same angle; order=0 on the mask keeps
    # it binary, order=1 on the image avoids blocking.
    rot_mask = ndimage.rotate(mask.astype(np.uint8), angle, order=0, reshape=True) > 0
    rot_img = ndimage.rotate(work, angle, order=1, reshape=True)
    if rot_mask.sum() < 100:
        return None
    if resolve_180(rot_mask):
        rot_mask, rot_img = rot_mask[::-1, ::-1], rot_img[::-1, ::-1]
        angle += 180.0

    ys, xs = np.nonzero(rot_mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop_m = rot_mask[y0:y1, x0:x1]
    crop_i = np.where(rot_mask, rot_img, 0.0)[y0:y1, x0:x1]

    # Square-pad rather than stretch, so aspect - which is real shape
    # information - survives the resize.
    h, w = crop_m.shape
    side = max(h, w)
    pm = np.zeros((side, side), bool)
    pi = np.zeros((side, side), np.float32)
    oy, ox = (side - h) // 2, (side - w) // 2
    pm[oy:oy + h, ox:ox + w] = crop_m
    pi[oy:oy + h, ox:ox + w] = crop_i

    out_m = np.asarray(Image.fromarray(pm.astype(np.uint8) * 255).resize((GRID, GRID), Image.BILINEAR)) > 127

    # Stretch on percentiles of in-tissue pixels, not min/max. A single bright
    # speck inside the mask - debris, a saturated nucleus - sets the max and
    # crushes the whole section to near black, which is what the first preview
    # showed.
    inside = pi[pm]
    if inside.size > 50:
        lo, hi = np.percentile(inside, [1, 99])
    else:
        lo, hi = float(pi.min()), float(pi.max())
    norm = np.clip((pi - lo) / max(hi - lo, 1e-6), 0, 1) * 255.0
    norm[~pm] = 0
    out_i = np.asarray(Image.fromarray(norm.astype(np.uint8)).resize((GRID, GRID), Image.BILINEAR))
    return out_i, out_m, angle % 360.0


def load_overrides():
    """Manual rotation corrections from 04d_rotation_curator.py.

    Stored as a correction *on top of* the automatic angle rather than as an
    absolute orientation, so improving the auto-rotation later does not
    invalidate the manual work.
    """
    path = os.path.join(REFORMAT_DIR, "rotation_overrides.csv")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["scene_uid"]] = (int(r["extra_rotation"] or 0), r["flip"] == "1")
    print(f"loaded {len(out)} manual rotation override(s)")
    return out


def apply_override(img, mask, rotation, flip):
    k = (rotation // 90) % 4
    if k:
        img, mask = np.rot90(img, k), np.rot90(mask, k)
    if flip:
        img, mask = img[:, ::-1], mask[:, ::-1]
    return np.ascontiguousarray(img), np.ascontiguousarray(mask)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=int, default=8)
    ap.add_argument("--marker", default="AF488")
    ap.add_argument("--apply-overrides", action="store_true",
                    help="apply manual rotations from rotation_overrides.csv")
    args = ap.parse_args()
    overrides = load_overrides() if args.apply_overrides else {}

    sec_dir = os.path.join(REFORMAT_DIR, "sections")
    plate_dir = os.path.join(REFORMAT_DIR, "plates")
    os.makedirs(sec_dir, exist_ok=True)
    os.makedirs(plate_dir, exist_ok=True)

    rows = []

    with open(os.path.join(PLATE_DIR, "plates.csv"), newline="", encoding="utf-8") as fh:
        plates = list(csv.DictReader(fh))
    ok = 0
    for p in plates:
        out = reformat(os.path.join(PLATE_DIR, p["image_file"]), light_background=True)
        if out is None:
            continue
        img, mask, angle = out
        Image.fromarray(img).save(os.path.join(plate_dir, p["plate_id"] + ".png"))
        np.save(os.path.join(plate_dir, p["plate_id"] + "_mask.npy"), mask)
        rows.append({"kind": "plate", "id": p["plate_id"], "angle": round(angle, 1),
                     "fill": round(float(mask.mean()), 4), "regions": p["regions"]})
        ok += 1
    print(f"plates reformatted: {ok}/{len(plates)}")

    with open(QC_CSV, newline="", encoding="utf-8") as fh:
        secs = [r for r in csv.DictReader(fh) if r["marker_channel"] == args.marker]
    ok = 0
    for i, r in enumerate(secs):
        src = os.path.join(OVERVIEW_DIR, r["animal"], r["marker_channel"],
                           r["scene_uid"] + "_DAPI.png")
        if not os.path.exists(src):
            continue
        out = reformat(src, light_background=False)
        if out is None:
            continue
        img, mask, angle = out
        extra, flip = overrides.get(r["scene_uid"], (0, False))
        if extra or flip:
            img, mask = apply_override(img, mask, extra, flip)
        Image.fromarray(img).save(os.path.join(sec_dir, r["scene_uid"] + ".png"))
        np.save(os.path.join(sec_dir, r["scene_uid"] + "_mask.npy"), mask)
        rows.append({"kind": "section", "id": r["scene_uid"], "angle": round(angle, 1),
                     "fill": round(float(mask.mean()), 4),
                     "animal": r["animal"], "section_order": r["section_order"],
                     "manual_rotation": extra, "manual_flip": int(flip)})
        ok += 1
        if (i + 1) % 200 == 0:
            print(f"\r  sections {i + 1}/{len(secs)}  ok {ok}", end="")
    print(f"\rsections reformatted: {ok}/{len(secs)}          ")

    out_csv = os.path.join(REFORMAT_DIR, "reformat_index.csv")
    keys = ["kind", "id", "angle", "fill", "animal", "section_order", "regions",
            "manual_rotation", "manual_flip"]
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    if args.preview:
        preview(rows, sec_dir, plate_dir, args.preview)

    fills = [r["fill"] for r in rows if r["kind"] == "section"]
    pfills = [r["fill"] for r in rows if r["kind"] == "plate"]
    print()
    print("=" * 72)
    print(f"wrote {out_csv}")
    if fills and pfills:
        print(f"tissue fill  sections median {np.median(fills):.3f} | plates median {np.median(pfills):.3f}")
        print("  these should now be comparable - they were not before reformatting")
    print("NEXT: 04b_atlas_match.py --reformatted")
    print("=" * 72)


def preview(rows, sec_dir, plate_dir, n):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plates = [r for r in rows if r["kind"] == "plate"][:n]
    secs = [r for r in rows if r["kind"] == "section"]
    secs = secs[:: max(1, len(secs) // n)][:n]
    fig, ax = plt.subplots(2, n, figsize=(2.1 * n, 4.6))
    for k, p in enumerate(plates):
        ax[0, k].imshow(np.asarray(Image.open(os.path.join(plate_dir, p["id"] + ".png"))), cmap="gray")
        ax[0, k].set_title(f"{p['id']}\n{p['angle']:.0f} deg", fontsize=7)
    for k, s in enumerate(secs):
        ax[1, k].imshow(np.asarray(Image.open(os.path.join(sec_dir, s["id"] + ".png"))), cmap="gray")
        ax[1, k].set_title(f"{s['id']}\n{s['angle']:.0f} deg", fontsize=7)
    for a in ax.ravel():
        a.axis("off")
    fig.suptitle("Reformatted: centred, rotated horizontal, debris removed  "
                 "(TOP plates, BOTTOM sections)", fontsize=11)
    fig.tight_layout()
    out = os.path.join(REFORMAT_DIR, "reformat_preview.png")
    fig.savefig(out, dpi=100)
    plt.close(fig)
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
