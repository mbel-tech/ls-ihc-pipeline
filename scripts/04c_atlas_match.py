"""Stage 4c - match sections to atlas plates, on reformatted data.

Replaces the silhouette matcher in `04b_atlas_match.py`, which compared raw
hand-drawn scan regions against arbitrarily cropped plates and topped out at a
mean IoU of 0.51. Three methods adopted from prior work (see REFERENCES.md):

**Reformatted inputs** (BrainJ). Sections and plates arrive from `04a_reformat.py`
already centred, rotated horizontal and stripped of debris, so position, scale and
rotation are no longer free parameters to search over.

**Per-section flip** (BrainJ). Free-floating sections land face up or face down.
BrainJ makes flipping a separate manual step because a bilaterally near-symmetric
section carries little shape evidence either way. Here both hypotheses are scored
per section and the better is proposed - and, because the evidence is often thin,
the margin between them is reported so the curator can see when the call is a
coin toss.

**Synthetic augmentation** (DeepSlice). DeepSlice trained on ~920k virtual
sections rendered from the template with stochastic angles, noise and warping.
The same idea without a network: expand each plate into a small bank of warped,
rotated and scaled variants, and score a section against its best variant. A real
section is a deformed, obliquely-cut version of the plate, so matching against
only the pristine plate systematically under-scores the correct one.

Ordering remains a monotonic dynamic program: serial sections cannot run
backwards along the brain.

DOES NOT WORK - measured, and the reason is in the data
=======================================================

Run on the curated 841 sections this produces a median score of 0.688, and the
assignments are **not informative about rostro-caudal level**. Three measurements
say so:

1. **Correlation between a section's serial order and its best-matching plate:
   -0.05, 0.00, 0.17, -0.04** across four animals. Effectively zero. Each section
   picks a plate confidently - only 2-3 plates tie within 0.02 of the best, and
   the best is 0.185 above a typical plate - and those picks spread over 71-87 of
   the 101 plates. Confident, well spread, and unrelated to where the section
   actually came from.

2. **Silhouettes barely change along the brain.** In LS45 the median IoU between
   *adjacent* sections is 0.595; between sections *30 apart* it is 0.551. A gap
   of 0.044 over thirty sections is not something a matcher can exploit.

3. The monotonic DP therefore collapses - many sections onto few plates - and a
   step-cost prior does not rescue it, because there is no signal to order.

**What the shape normalisation costs.** `04a` square-pads and resizes every
section to 256x256, which deletes absolute size. Size *does* carry position:
correlation between section order and tissue area is 0.45 median across animals
(LS138 0.84, LS37 0.72). That is a real cue thrown away - though at 0.45 it is
too weak on its own to place a section to +/-1 plate.

This is consistent with AnNoBrainer's stated limitation, already in
REFERENCES.md: *DAPI is unlikely to register well against an H&E/Nissl atlas due
to data sparsity and poor morphological correspondence.* The earlier IoU ceiling
near 0.51 was the same problem, not a tuning failure.

**The route that fits the data** is not better image matching. The sections are
already in known serial order at uniform thickness, which is a far stronger
constraint than their outlines: anchor a small number of levels per animal by eye
and interpolate the rest by section number - the QUINT/VisuAlign shape of
workflow. That is a curation task of a few minutes per brain rather than an
unsolved vision problem.

Run:  python 04c_atlas_match.py
      python 04c_atlas_match.py --animal LS45 --variants 12
"""

import argparse
import csv
import glob
import json
import os

import numpy as np
from scipy import ndimage

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
PLATE_DIR = os.path.join(OUT_ROOT, "atlas", "plates")
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "atlasmatch")

TOP_K = 4
SEED = 20260812

# Cost per plate of deviating from an even progression through the atlas.
# Scores are IoU in [0, 1] and the median gap between the monotonic assignment
# and the unconstrained best is ~0.03, so this is deliberately of that order:
# big enough to stop the path standing still, small enough that a genuinely
# better-matching plate still wins. Swept before choosing - see LOGS.md.
STEP_WEIGHT = 0.02

# Augmentation ranges. Deliberately modest: these model plausible differences
# between a real section and its plate - a slightly oblique cut, a little
# shrinkage, some tearing - not arbitrary distortion. Too much and every plate
# starts matching everything.
ROTATIONS = (-8, -4, 0, 4, 8)          # degrees, residual obliquity after reformatting
SCALES = (0.92, 1.0, 1.08)             # section thickness and shrinkage differences
WARP_SIGMA = 12.0                      # smoothness of the elastic displacement
WARP_AMPLITUDE = (0.0, 3.0)            # pixels; 0 keeps the undeformed variant


def iou(a, b):
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter / union) if union else 0.0


def elastic(mask, amplitude, rng):
    """Smooth random deformation, as used to synthesise training data."""
    if amplitude <= 0:
        return mask
    h, w = mask.shape
    dy = ndimage.gaussian_filter(rng.standard_normal((h, w)), WARP_SIGMA) * amplitude * WARP_SIGMA
    dx = ndimage.gaussian_filter(rng.standard_normal((h, w)), WARP_SIGMA) * amplitude * WARP_SIGMA
    yy, xx = np.mgrid[0:h, 0:w]
    out = ndimage.map_coordinates(mask.astype(np.float32),
                                  [yy + dy, xx + dx], order=1, mode="constant")
    return out > 0.5


def rescale(mask, factor):
    if abs(factor - 1.0) < 1e-6:
        return mask
    h, w = mask.shape
    zoomed = ndimage.zoom(mask.astype(np.float32), factor, order=1) > 0.5
    out = np.zeros_like(mask)
    zh, zw = zoomed.shape
    if factor > 1:
        oy, ox = (zh - h) // 2, (zw - w) // 2
        out = zoomed[oy:oy + h, ox:ox + w]
    else:
        oy, ox = (h - zh) // 2, (w - zw) // 2
        out[oy:oy + zh, ox:ox + zw] = zoomed
    return out


def build_bank(mask, n_variants, rng):
    """A plate plus plausible deformations of it."""
    bank = [mask]
    combos = [(r, s) for r in ROTATIONS for s in SCALES if not (r == 0 and s == 1.0)]
    rng.shuffle(combos)
    for r, s in combos[: max(0, n_variants - 1)]:
        v = mask
        if r:
            v = ndimage.rotate(v.astype(np.uint8), r, order=0, reshape=False) > 0
        v = rescale(v, s)
        amp = rng.uniform(*WARP_AMPLITUDE)
        v = elastic(v, amp, rng)
        if v.sum() > 100:
            bank.append(v)
    return bank


def score(section, bank):
    """Best IoU against any variant of the plate."""
    return max(iou(section, v) for v in bank)


def best_path(sim, step_weight=STEP_WEIGHT):
    """Monotonic assignment maximising total similarity, with a cost on the step.

    **This does not fix the collapse, and the docstring says so because the
    measurement says so.** Without a step cost the path parks many sections on
    one plate: LS120 put 74 sections on 8 plates with 43 on one, LS37 put 53 of
    83 on a single plate. Adding the cost was the obvious remedy and it barely
    moved anything - swept over 0 to 0.08, LS120 went from 8 plates to 12 and
    LS37 got slightly *worse* (18 plates to 16).

    The reason is upstream, and it is not a tuning problem. See the module
    docstring: silhouette shape carries essentially no rostro-caudal signal in
    this data, so the DP is imposing an order on noise. The step cost is kept
    because it is the right prior and costs nothing, not because it works.
    """
    n, m = sim.shape
    if n < 2:
        return np.array([int(np.argmax(sim[0]))], dtype=np.int32)

    # Expected step: how fast this brain ought to move through the atlas,
    # estimated from where its sections match best when unconstrained.
    local = np.argmax(sim, axis=1)
    span = float(np.percentile(local, 90) - np.percentile(local, 10))
    s0 = max(span / max(n - 1, 1), 0.0)

    steps = np.arange(m)[None, :] - np.arange(m)[:, None]      # step[k, j] = j - k
    cost = np.where(steps < 0, -np.inf, -step_weight * np.abs(steps - s0))

    dp = np.full((n, m), -np.inf)
    back = np.zeros((n, m), dtype=np.int32)
    dp[0] = sim[0]
    for i in range(1, n):
        cand = dp[i - 1][:, None] + cost                       # (from k) x (to j)
        back[i] = np.argmax(cand, axis=0)
        dp[i] = sim[i] + cand[back[i], np.arange(m)]
    path = np.zeros(n, dtype=np.int32)
    path[-1] = int(np.argmax(dp[-1]))
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--animal", default=None)
    ap.add_argument("--variants", type=int, default=10)
    args = ap.parse_args()
    os.makedirs(REPORT_DIR, exist_ok=True)
    rng = np.random.default_rng(SEED)

    plate_files = sorted(glob.glob(os.path.join(REFORMAT_DIR, "plates", "*_mask.npy")))
    if not plate_files:
        raise SystemExit("no reformatted plates - run 04a_reformat.py first")
    plate_ids = [os.path.basename(f).replace("_mask.npy", "") for f in plate_files]
    plate_masks = [np.load(f) for f in plate_files]

    regions = {}
    with open(os.path.join(PLATE_DIR, "plates.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            regions[r["plate_id"]] = r["regions"]

    print(f"{len(plate_masks)} plates; building banks of {args.variants} variants ...")
    banks = [build_bank(m, args.variants, rng) for m in plate_masks]
    print(f"  {sum(len(b) for b in banks)} plate variants total")

    with open(os.path.join(REFORMAT_DIR, "reformat_index.csv"), newline="", encoding="utf-8") as fh:
        index = [r for r in csv.DictReader(fh) if r["kind"] == "section"]
    if args.animal:
        index = [r for r in index if r["animal"] == args.animal]

    by_animal = {}
    for r in index:
        by_animal.setdefault(r["animal"], []).append(r)

    proposals = []
    for animal, group in sorted(by_animal.items(), key=lambda kv: int(kv[0][2:])):
        group.sort(key=lambda r: int(r["section_order"]))
        masks, keep = [], []
        for r in group:
            p = os.path.join(REFORMAT_DIR, "sections", r["id"] + "_mask.npy")
            if os.path.exists(p):
                masks.append(np.load(p))
                keep.append(r)
        if not masks:
            continue

        # Score each section under both flip hypotheses.
        sim_plain = np.array([[score(m, b) for b in banks] for m in masks])
        sim_flip = np.array([[score(m[:, ::-1], b) for b in banks] for m in masks])
        flipped = sim_flip.max(axis=1) > sim_plain.max(axis=1)
        margin = np.abs(sim_flip.max(axis=1) - sim_plain.max(axis=1))
        sim = np.where(flipped[:, None], sim_flip, sim_plain)

        path = best_path(sim)
        for i, r in enumerate(keep):
            order = np.argsort(-sim[i])[:TOP_K]
            proposals.append({
                "scene_uid": r["id"], "animal": animal,
                "section_order": r["section_order"],
                "proposed_plate": plate_ids[int(path[i])],
                "proposed_score": round(float(sim[i, int(path[i])]), 3),
                "local_best": plate_ids[int(np.argmax(sim[i]))],
                "local_best_score": round(float(sim[i].max()), 3),
                "flipped": int(flipped[i]),
                # A small margin means the flip call is close to a coin toss.
                "flip_margin": round(float(margin[i]), 4),
                "regions": regions.get(plate_ids[int(path[i])], ""),
                "candidates": "|".join(plate_ids[j] for j in order),
                "confirmed_plate": "", "confirmed_flip": "",
            })
        chosen = sim[np.arange(len(keep)), path]
        print(f"  {animal:<7} {len(keep):>4} sections  "
              f"{plate_ids[int(path.min())]} -> {plate_ids[int(path.max())]}  "
              f"mean {chosen.mean():.3f}  flipped {int(flipped.sum())}/{len(keep)}")

    out = os.path.join(REPORT_DIR, "atlas_proposals_v2.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(proposals[0].keys()))
        w.writeheader()
        w.writerows(proposals)

    scores = [p["proposed_score"] for p in proposals]
    locals_ = [p["local_best_score"] for p in proposals]
    close = sum(1 for p in proposals if p["flip_margin"] < 0.02)
    print()
    print("=" * 72)
    print(f"{len(proposals)} sections -> {out}")
    print(f"  assigned score : median {np.median(scores):.3f}  (local best {np.median(locals_):.3f})")
    print(f"  flip too close to call (<0.02): {close} ({100 * close / len(proposals):.0f}%)")
    print()
    print("Benchmark: AnNoBrainer's layer classifier reaches 59% exact, 94% within")
    print("two layers. Exact match is not the standard, and expert-vs-expert")
    print("agreement on annotation is Kappa 0.17 - the curator decides, not this.")
    print("=" * 72)


if __name__ == "__main__":
    main()
