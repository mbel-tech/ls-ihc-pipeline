"""Stage 1d - find scenes that may hold more than one brain section, and build
a sheet for the user to adjudicate.

Confirmed with the user: one CZI file = one slide = many scan regions, each
normally holding ONE brain section. LS136_s05b_sc10 is an exception - two
complete sections stacked inside a single scan region. Stage 4 assumes one
section per scene for registration, ordering and atlas matching, so exceptions
have to be found and split before it runs.

The hard part is that blob count alone cannot decide this. **A single rostral
telencephalic section is naturally two separate lobes.** Two blobs side by side
is one section; two blobs stacked, each with full brain morphology, is two.
Guessing at that from geometry would be guessing at salmonid neuroanatomy.

So this script does not decide. It finds candidates, measures the features that
plausibly separate the two cases, renders them for review, and writes a CSV with
an empty `n_sections` column. Ticking that column calibrates the rule on real
judgement; `--fit` then reports which feature actually separates the classes.

Run:  python 01i_multisection_review.py            # find and render candidates
      python 01i_multisection_review.py --fit      # after marking the CSV
"""

import argparse
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from scipy import ndimage

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "multisection")
REVIEW_CSV = os.path.join(REPORT_DIR, "multisection_review.csv")

# A blob smaller than this fraction of the largest is debris, not a section.
MIN_BLOB_FRACTION = 0.15
PER_PAGE = 12


def tissue_blobs(dapi):
    positive = dapi[dapi > 0]
    if positive.size < 500:
        return None, None
    thr = np.percentile(positive, 60)
    mask = ndimage.gaussian_filter(dapi.astype(np.float32), 3) > thr
    mask = ndimage.binary_opening(mask, np.ones((5, 5)))
    mask = ndimage.binary_fill_holes(mask)
    labels, n = ndimage.label(mask)
    if n == 0:
        return None, None
    sizes = np.array(ndimage.sum(mask, labels, range(1, n + 1)))
    keep = np.where(sizes >= MIN_BLOB_FRACTION * sizes.max())[0] + 1
    return np.isin(labels, keep), labels * np.isin(labels, keep)


def features(labels):
    """Measurements that plausibly separate hemispheres from stacked sections."""
    ids = [i for i in np.unique(labels) if i]
    if len(ids) < 2:
        return None
    cents = np.array(ndimage.center_of_mass(labels > 0, labels, ids))
    sizes = np.array(ndimage.sum(labels > 0, labels, ids))

    spread_y = float(cents[:, 0].max() - cents[:, 0].min())
    spread_x = float(cents[:, 1].max() - cents[:, 1].min())
    order = np.argsort(-sizes)
    a, b = sizes[order[0]], sizes[order[1]]

    # Bounding boxes in image pixel space, for the curation GUI to draw over
    # the overview. Kept as [x, y, w, h] so the page can scale them to whatever
    # size the browser letterboxes the image to.
    boxes = []
    for sl, bid in zip(ndimage.find_objects(labels), range(1, labels.max() + 1)):
        if sl is None or bid not in ids:
            continue
        ys, xs = sl
        boxes.append([int(xs.start), int(ys.start),
                      int(xs.stop - xs.start), int(ys.stop - ys.start)])

    return {
        "n_blobs": len(ids),
        "blob_boxes": json.dumps(boxes),
        # Hemispheres separate across the short axis; stacked sections along the
        # long axis. This ratio is the most likely discriminator.
        "separation_ratio": round(spread_y / max(spread_x, 1e-6), 3),
        # Hemispheres of one section are near-equal; a section plus a fragment is not.
        "size_ratio": round(float(b / max(a, 1e-9)), 3),
        "blob_area_frac": round(float(sizes.sum() / labels.size), 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--max-render", type=int, default=48)
    args = ap.parse_args()
    os.makedirs(REPORT_DIR, exist_ok=True)

    if args.fit:
        return fit()

    with open(QC_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(f"scanning {len(rows)} sections for multi-blob scenes ...")

    candidates = []
    for i, r in enumerate(rows):
        p = os.path.join(OVERVIEW_DIR, r["animal"], r["marker_channel"], r["scene_uid"] + "_DAPI.png")
        if not os.path.exists(p):
            continue
        dapi = np.asarray(Image.open(p).convert("L"))
        mask, labels = tissue_blobs(dapi)
        if labels is None:
            continue
        f = features(labels)
        if f:
            f.update({"scene_uid": r["scene_uid"], "animal": r["animal"],
                      "slide": r["slide"], "marker_channel": r["marker_channel"],
                      "tissue_area_mm2": r["tissue_area_mm2"], "n_sections": ""})
            candidates.append(f)
        if (i + 1) % 400 == 0:
            print(f"\r  {i + 1}/{len(rows)}  candidates {len(candidates)}", end="")
    print()

    keys = ["scene_uid", "animal", "slide", "marker_channel", "n_blobs", "blob_boxes",
            "separation_ratio", "size_ratio", "blob_area_frac", "tissue_area_mm2",
            "n_sections"]
    with open(REVIEW_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(candidates)

    # Render the most ambiguous first: those where the blobs are similar in size
    # and well separated are the ones a rule is most likely to get wrong.
    candidates.sort(key=lambda c: -(c["size_ratio"] * min(c["separation_ratio"], 2.0)))
    render(candidates[: args.max_render])

    print()
    print("=" * 72)
    print(f"{len(candidates)} scenes have 2 or more large tissue blobs "
          f"({100 * len(candidates) / max(len(rows), 1):.0f}% of {len(rows)})")
    print(f"rendered the {min(args.max_render, len(candidates))} most ambiguous")
    print()
    print(f"  1. open {REPORT_DIR}\\review_p*.png")
    print(f"  2. in {os.path.basename(REVIEW_CSV)}, set n_sections to 1 or 2 for those scenes")
    print(f"  3. run: python 01i_multisection_review.py --fit")
    print()
    print("Only the rendered scenes need marking - enough to calibrate the rule,")
    print("which then classifies the rest.")
    print("=" * 72)


def render(cands):
    for page, start in enumerate(range(0, len(cands), PER_PAGE), 1):
        chunk = cands[start:start + PER_PAGE]
        cols = 4
        rows_n = -(-len(chunk) // cols)
        fig, axes = plt.subplots(rows_n, cols, figsize=(4 * cols, 4.6 * rows_n), squeeze=False)
        for ax in axes.ravel():
            ax.axis("off")
        for i, c in enumerate(chunk):
            ax = axes[i // cols][i % cols]
            p = os.path.join(OVERVIEW_DIR, c["animal"], c["marker_channel"],
                             c["scene_uid"] + "_DAPI.png")
            dapi = np.asarray(Image.open(p).convert("L"))
            mask, labels = tissue_blobs(dapi)
            ax.imshow(dapi, cmap="gray")
            if labels is not None:
                for j, bid in enumerate([b for b in np.unique(labels) if b], 1):
                    ax.contour(labels == bid, levels=[0.5], colors=["#ff3020"], linewidths=0.8)
                    cy, cx = ndimage.center_of_mass(labels == bid)
                    ax.text(cx, cy, str(j), color="#ffd000", fontsize=15,
                            ha="center", va="center", weight="bold")
            ax.set_title(f"{c['scene_uid']}\n{c['n_blobs']} blobs  "
                         f"sep {c['separation_ratio']}  size {c['size_ratio']}", fontsize=8)
            ax.axis("off")
        fig.suptitle("How many BRAIN SECTIONS in each? (lobes of one section = 1)", fontsize=13)
        fig.tight_layout()
        out = os.path.join(REPORT_DIR, f"review_p{page:02d}.png")
        fig.savefig(out, dpi=95)
        plt.close(fig)
        print(f"  wrote {os.path.basename(out)}")


def fit():
    with open(REVIEW_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    marked = [r for r in rows if r["n_sections"].strip() in ("1", "2", "3", "4")]
    if len(marked) < 8:
        raise SystemExit(f"only {len(marked)} scenes marked - mark more before fitting")

    print(f"{len(marked)} scenes marked\n")
    for feat in ("separation_ratio", "size_ratio", "blob_area_frac"):
        one = [float(r[feat]) for r in marked if r["n_sections"] == "1"]
        many = [float(r[feat]) for r in marked if r["n_sections"] != "1"]
        if not one or not many:
            continue
        # A threshold midway between the classes, and how cleanly it separates.
        thr = (np.median(one) + np.median(many)) / 2
        correct = sum(1 for r in marked
                      if (float(r[feat]) >= thr) == (r["n_sections"] != "1"))
        print(f"{feat:<18} one-section median {np.median(one):.3f}  "
              f"multi median {np.median(many):.3f}  "
              f"threshold {thr:.3f} -> {100 * correct / len(marked):.0f}% correct")
    print()
    print("Use the feature that separates most cleanly. If none exceeds ~90%,")
    print("the split is not recoverable from these features and the affected")
    print("scenes should be listed for manual handling instead.")


if __name__ == "__main__":
    main()
