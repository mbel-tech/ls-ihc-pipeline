"""Stage 4f - propose sections that hold no measurable tissue.

The curator lets you exclude sections by hand. Doing that by eye across 1,381
sections is slow and, worse, inconsistent: the twelfth animal gets judged by a
tireder standard than the first. This proposes the unambiguous cases so the
manual pass becomes *adjudication* rather than *search*.

**The proposal is deliberately conservative, and the asymmetry is the reason.**
A wrongly *included* section adds a little noise to a group mean and stays
visible in the data. A wrongly *excluded* section vanishes silently and takes
its evidence with it. So this flags only sections with no tissue worth the name,
carries the numbers that produced each call, and every one is reversible with a
right-click. Torn-but-substantial sections are *not* proposed - that is a
judgement about how much damage is too much, and it belongs to the eye.

The measure, and two that were tried and rejected
------------------------------------------------

**Kept: largest connected tissue component, in mm2.** Measured on the source
overview at a known 5.20 um/px, so it is a physical size rather than a fraction
of a hand-drawn scan box. A section reduced to debris has no piece of any real
size, whatever threshold you pick, because the specks are physically small. On
the eight sections used to set this up the separation was an order of magnitude:
0.1-0.2 mm2 for debris-only frames against 1.8-7.2 mm2 for real tissue.

**Rejected: solidity** (mask area / convex hull area). It looked principled and
it is actively wrong here. A transverse brain section at telencephalic level is
two bilaterally separated lobes, so its hull spans the midline gap and solidity
collapses. Thresholding on it proposed excluding 334 sections - 24% of the
dataset - and the montage showed them to be *good telencephalon*, which is the
region of interest. It punished precisely the anatomy the study is about.

**Rejected: in-mask median intensity.** It is a constant by construction. The
reformat stretches every section on its own median +/- MAD, so the in-mask
median always lands near 51/255. Measured across the dataset: p1 47, median 51,
p95 55. It carried no information at all.

**Not used: `tissue_area_mm2` from focus.csv.** That column is computed per
image with its own auto-threshold, and the thresholds range from 27 to 2274
across sections of a single slide. It reported 59.4 mm2 of "tissue" for a frame
containing nothing but specks (threshold collapsed to 37, calling 82% of the
frame tissue) and 2.6 mm2 for a frame with two intact lobes. It is not a
quantity that can be compared between sections, and nothing downstream should
treat it as one.

Run:  python 04f_exclusion_candidates.py
      python 04f_exclusion_candidates.py --survey      # measure and plot only
"""

import argparse
import csv
import json
import os

import importlib.util

import numpy as np
from PIL import Image
from scipy import ndimage

# Import 04a's mask directly - a module name cannot start with a digit, so it is
# loaded by path. Sharing the function rather than copying it means the two
# stages cannot drift apart.
_SPEC = importlib.util.spec_from_file_location(
    "reformat_mod", os.path.join(os.path.dirname(os.path.abspath(__file__)), "04a_reformat.py"))
_RF = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RF)
tissue_mask, WORK = _RF.tissue_mask, _RF.WORK_SIZE

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "exclusion")

UM_PX = 5.20e-3        # mm per pixel in the overviews - verified constant, all 222 files
PIECE_MIN_MM2 = 0.5    # a "piece" of tissue rather than a speck

# The single proposal rule, placed inside the gap that separated hand-labelled
# good sections (4.0-11.6 mm2) from debris-only frames (0.8-1.9 mm2), not at a
# round number chosen in advance.
LARGEST_MIN_MM2 = 2.5


def measure(path):
    """Physical geometry of the tissue in one overview.

    Uses `04a_reformat.tissue_mask` rather than a threshold of its own. Two
    reasons, one of them learned the hard way.

    Consistency: that mask is what defines "the section" everywhere else in the
    pipeline, so a section proposed for exclusion here is judged by the same rule
    that will crop and measure it later.

    Correctness: a first attempt thresholded the source directly and badly
    under-counted real tissue. Sections are bright at the rim and dim inside, so
    a raw threshold returns a thin ring whose area is small - it reported 0.83
    mm2 for a frame holding two intact, obviously textured lobes. `tissue_mask`
    closes and fills, which recovers the interior. Same sections, remeasured:
    good tissue 4.0-11.6 mm2, debris-only frames 0.8-1.9 mm2.
    """
    try:
        img = Image.open(path).convert("L")
    except OSError:
        return None
    w, h = img.size
    work = np.asarray(img.resize((WORK, WORK), Image.BILINEAR)).astype(np.float32)

    # One work pixel covers (w/WORK) x (h/WORK) source pixels, and the source
    # pixel size is a verified constant across all 222 files. So this is a
    # physical area, not a fraction of a hand-drawn scan box.
    px_mm2 = (w * h / float(WORK * WORK)) * UM_PX ** 2
    frame_mm2 = round(w * h * UM_PX ** 2, 1)

    mask = tissue_mask(work, light_background=False)
    if mask is None:
        return {"largest_mm2": 0.0, "total_mm2": 0.0, "n_pieces": 0,
                "frame_mm2": frame_mm2}

    labels, n = ndimage.label(mask)
    if n == 0:
        return {"largest_mm2": 0.0, "total_mm2": 0.0, "n_pieces": 0,
                "frame_mm2": frame_mm2}
    sizes = np.array(ndimage.sum(mask, labels, range(1, n + 1))) * px_mm2
    return {
        "largest_mm2": round(float(sizes.max()), 2),
        "total_mm2": round(float(sizes.sum()), 2),
        # Pieces, not components: a count that ignores specks is the one that
        # means "this section arrived in N parts".
        "n_pieces": int((sizes >= PIECE_MIN_MM2).sum()),
        "frame_mm2": frame_mm2,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--survey", action="store_true", help="measure and plot, propose nothing")
    ap.add_argument("--montage", type=int, default=32)
    args = ap.parse_args()
    os.makedirs(REPORT_DIR, exist_ok=True)

    chan = {}
    with open(QC_CSV, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            chan[r["scene_uid"]] = r["marker_channel"]

    with open(os.path.join(REFORMAT_DIR, "reformat_index.csv"), newline="", encoding="utf-8") as fh:
        index = [r for r in csv.DictReader(fh) if r["kind"] == "section"]

    rows = []
    for i, r in enumerate(index):
        src = os.path.join(OVERVIEW_DIR, r["animal"], chan.get(r["id"], "AF488"),
                           r["id"] + "_DAPI.png")
        m = measure(src)
        if m is None:
            continue
        m.update(uid=r["id"], animal=r["animal"], section_order=int(r["section_order"]))
        rows.append(m)
        if (i + 1) % 100 == 0:
            print(f"\r  measured {i + 1}/{len(index)}", end="")
    print(f"\r  measured {len(rows)}/{len(index)} sections        ")
    if not rows:
        raise SystemExit("nothing measured - run 04a_reformat.py first")

    largest = np.array([r["largest_mm2"] for r in rows])
    for r in rows:
        r["proposed"] = int(r["largest_mm2"] < LARGEST_MIN_MM2) if not args.survey else 0
        r["reason"] = (f"no tissue piece larger than {r['largest_mm2']:.2f} mm2 "
                       f"(threshold {LARGEST_MIN_MM2:.1f})") if r["proposed"] else ""

    n_prop = sum(r["proposed"] for r in rows)

    print()
    print("=" * 74)
    print(f"{len(rows)} sections measured via 04a tissue_mask at {WORK}x{WORK}")
    qs = [0.5, 1, 2, 5, 10, 25, 50, 95]
    print("  largest tissue piece, mm2")
    print("   " + "".join(f"p{q:<7g}" for q in qs))
    print("   " + "".join(f"{np.percentile(largest, q):<8.2f}" for q in qs))
    print(f"  sections with no piece >= {PIECE_MIN_MM2} mm2 at all: "
          f"{sum(1 for r in rows if r['n_pieces'] == 0)}")
    print()
    if not args.survey:
        print(f"proposed for exclusion: {n_prop} ({100 * n_prop / len(rows):.1f}%)")
        per = {}
        for r in rows:
            if r["proposed"]:
                per[r["animal"]] = per.get(r["animal"], 0) + 1
        for a, c in sorted(per.items(), key=lambda kv: -kv[1]):
            tot = sum(1 for r in rows if r["animal"] == a)
            print(f"    {a:<8} {c:>3} / {tot}")
        print()
        print("These are PROPOSALS, pre-marked in the curator and reversible with a")
        print("right-click. The export records auto vs manual, so how often the")
        print("proposal was wrong stays measurable rather than assumed.")
    print("=" * 74)

    out = os.path.join(REFORMAT_DIR, "exclusion_candidates.csv")
    keys = ["uid", "animal", "section_order", "proposed", "reason",
            "largest_mm2", "total_mm2", "n_pieces", "frame_mm2"]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (-r["proposed"], r["animal"], r["section_order"])))
    print(f"wrote {out}")

    montage(rows, args.montage)


def montage(rows, n):
    """Render the proposals, and the sections just *above* threshold.

    The second panel is the one that matters. It shows what the cut nearly
    caught, which is the only way to see whether it falls in the right place
    rather than merely somewhere.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sec_dir = os.path.join(REFORMAT_DIR, "sections")
    prop = sorted((r for r in rows if r["proposed"]), key=lambda r: -r["largest_mm2"])[:n]
    keep = sorted((r for r in rows if not r["proposed"]), key=lambda r: r["largest_mm2"])[:n]

    for name, sel, title in (
            ("proposed", prop, "PROPOSED for exclusion - largest first (closest to the cut)"),
            ("kept_borderline", keep, "KEPT - smallest first (just above the cut)")):
        if not sel:
            continue
        cols = 8
        nrow = int(np.ceil(len(sel) / cols))
        fig, ax = plt.subplots(nrow, cols, figsize=(2.0 * cols, 2.35 * nrow))
        ax = np.atleast_2d(ax)
        for a in ax.ravel():
            a.axis("off")
        for k, r in enumerate(sel):
            a = ax[k // cols, k % cols]
            p = os.path.join(sec_dir, r["uid"] + ".png")
            if os.path.exists(p):
                a.imshow(np.asarray(Image.open(p)), cmap="gray", vmin=0, vmax=255)
            a.set_title(f"{r['uid']}\nlargest {r['largest_mm2']:.2f} mm2  "
                        f"{r['n_pieces']} pieces", fontsize=6)
        fig.suptitle(f"{title}  (n={len(sel)})", fontsize=11)
        fig.tight_layout()
        path = os.path.join(REPORT_DIR, f"{name}.png")
        fig.savefig(path, dpi=110)
        plt.close(fig)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
