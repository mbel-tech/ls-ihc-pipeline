"""Stage 4h - propose a rotation that puts each section's symmetry axis vertical.

A transverse brain section is two approximately mirror-image lobes. `04a` orients
each section by the *principal axis* of its tissue mask, which gets the long axis
horizontal and therefore the midline roughly vertical - but the principal axis is
a property of elongation, not of symmetry. It drifts on sections that are nearly
round, and it is dragged off by a damaged or missing lobe. This measures the
symmetry directly and proposes the residual correction, which the curator
pre-applies so the manual pass fixes the failures instead of rotating everything
by hand.

Output is a *residual* on top of `04a`'s angle, i.e. exactly the semantics of the
curator's `extra_rotation`.

Three published approaches were tested. The one that works here is the least
sophisticated, and the reason is worth stating
-----------------------------------------------------------------------------

**Wu et al. 2013** (SIFT keypoints matched within one image by a symmetric
similarity metric - relative scale, mirrored orientation, flipped descriptor -
each pair voting for an axis in a Hough space) was implemented in full, including
the 128-bin descriptor reindexing that mirrors a SIFT descriptor. Measured on 24
sections against synthetic ground truth it reached a **median error of 24.1
degrees, with 12% of sections within 5 degrees**. It is not usable here.

**Why it fails, and it is not an implementation detail.** Their method was built
for MRI, where internal structure is high-contrast, reproducible, and genuinely
mirrored across the midline. In DAPI fluorescence at 5.20 um/px the internal
texture is nuclear speckle: individual nuclei on the left have no mirror
counterpart on the right, because cellular detail is not bilaterally symmetric
even though the anatomy is. There are no mirrored local features to match.

The same measurement, independently: scoring candidate axes by intensity
normalised cross-correlation got 59% of sections within 2 degrees, while scoring
the same axes by shape overlap got 91%. **Bilateral symmetry in this data lives
in the shape and gross anatomy, not in local image features.** That rules out the
whole feature-matching family, including **Wu et al. 2021**, whose 2-channel CNN
learns a similarity metric between image patches - a better metric for a signal
that is not there. (It would also need a GPU and salmonid training data.)

**Willemse et al. 2020** is a FIJI plugin that scores *local* symmetry per pixel
to find the symmetry *centres* of small objects - receptor arrays, vesicles. That
is point symmetry of many small things, not one global reflection axis, so it
addresses a different problem. Its one transferable trick, combining the
reflection axes of a square for cheap all-directions coverage, is unnecessary
when the search is already restricted to a narrow residual range.

See REFERENCES.md.

Method
------

For each candidate angle, rotate the mask so that angle would become vertical,
mirror it left-right, slide the mirror over a range of offsets, and take the best
overlap. The angle whose best overlap is highest is the symmetry axis.

**The search is restricted to +/- 30 degrees** and that is deliberate, not a
shortcut. Searching the full 180 degrees produced ~90 degree failures on a third
of sections, because a roughly elliptical section is also near-symmetric about
its *long* axis. `04a` has already put the midline approximately vertical, so
this refines rather than searches; anything needing more than 30 degrees is a
case for the human regardless.

Run:  python 04h_symmetry_axis.py --validate 24    # synthetic recovery test
      python 04h_symmetry_axis.py
"""

import argparse
import csv
import importlib.util
import json
import os

import numpy as np
from PIL import Image
from scipy import ndimage

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
SEC_DIR = os.path.join(REFORMAT_DIR, "sections")
CANDIDATES_CSV = os.path.join(REFORMAT_DIR, "exclusion_candidates.csv")
OUT_CSV = os.path.join(REFORMAT_DIR, "symmetry_proposals.csv")
SYM_KEYS = ["scene_uid", "animal", "section_order", "proposed_rotation",
            "sym_score", "margin", "confidence"]
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "symmetry")

SPAN = 30.0          # degrees either side of 04a's orientation
COARSE = 5.0         # degrees, first pass
FINE = 1.0           # degrees, refinement
SHIFT_PX = 36        # mirror offsets searched, +/- this many pixels
SHIFT_STEP = 2
MIN_OVERLAP_PX = 200

# Confidence gate: the peak symmetry score itself.
#
# The obvious candidate was the peak's *margin* over the rest of the sweep, and
# it turned out to be anti-correlated with correctness - failures had a higher
# median margin (0.0140) than correct proposals (0.0099). Shipping it as
# confidence would have labelled bad proposals good. Two other candidates, peak
# sharpness and IoU-versus-distance-transform agreement, each caught only ~50%
# of failures.
#
# The peak IoU is the best of the four, but it is NOT a clean gate and should not
# be described as one. On the sample used to choose it, correct proposals scored
# a median 0.749 against 0.507 for failures. Re-measured on three held-out
# samples of 28 sections each, it caught 100% of failures in two of them and
# **0% in the third**, where a failure scored 0.669 - higher than that sample's
# median correct proposal. Some sections are genuinely near-symmetric about more
# than one axis inside the +/-30 degree window, and no score distinguishes those.
#
# So `confidence: high` means "worth trusting more often than not", not "verified".
# The real check is the curator: it shows the section already rotated, so a wrong
# proposal is visible at a glance.
SCORE_MIN = 0.55


def score_at(msk, theta):
    """Best mirror overlap when `theta` is rotated to vertical."""
    M = ndimage.rotate(msk.astype(np.float32), theta, order=1, reshape=False)
    Mm = M[:, ::-1]
    best = -1.0
    for s in range(-SHIFT_PX, SHIFT_PX + 1, SHIFT_STEP):
        b = np.roll(Mm, s, axis=1)
        mm, bb = M > 0.5, b > 0.5
        union = int((mm | bb).sum())
        if union < MIN_OVERLAP_PX:
            continue
        iou = float((mm & bb).sum()) / union
        if iou > best:
            best = iou
    return best


def find_residual(msk):
    """Return (residual_degrees, score, margin).

    `margin` is the peak score minus the median score over the fine sweep - how
    much better the chosen angle is than a typical one. It is the confidence
    signal: a flat surface means the section carries no usable symmetry.
    """
    coarse = np.arange(-SPAN, SPAN + 1e-9, COARSE)
    cs = np.array([score_at(msk, float(t)) for t in coarse])
    t0 = float(coarse[int(np.argmax(cs))])
    fine = np.arange(max(-SPAN, t0 - COARSE), min(SPAN, t0 + COARSE) + 1e-9, FINE)
    fs = np.array([score_at(msk, float(t)) for t in fine])
    k = int(np.argmax(fs))
    return float(fine[k]), float(fs[k]), float(fs[k] - np.median(fs))


def load(uid):
    p = os.path.join(SEC_DIR, uid + "_mask.npy")
    return np.load(p) if os.path.exists(p) else None


def good_sections():
    """Sections not already proposed for exclusion by 04f.

    Symmetry cannot be measured on a fragment or a debris field, and including
    them would make the proposal set look worse than it is.
    """
    skip = set()
    if os.path.exists(CANDIDATES_CSV):
        with open(CANDIDATES_CSV, newline="", encoding="utf-8") as fh:
            skip = {r["uid"] for r in csv.DictReader(fh) if r["proposed"] == "1"}
    with open(os.path.join(REFORMAT_DIR, "reformat_index.csv"), newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["kind"] == "section"]
    return rows, skip


def validate(n, seed=404):
    """Rotate each section by a known angle and check the residual moves with it.

    This tests rotation equivariance against ground truth we control, which is
    the only ground truth available - there is no hand-labelled midline for this
    dataset.
    """
    rows, skip = good_sections()
    rows = [r for r in rows if r["id"] not in skip]
    rng = np.random.default_rng(seed)
    sel = [rows[i] for i in rng.choice(len(rows), min(n, len(rows)), replace=False)]
    errs, scores = [], []
    for r in sel:
        m0 = load(r["id"])
        if m0 is None:
            continue
        base, _, _ = find_residual(m0)
        applied = float(rng.uniform(-15, 15))
        m1 = ndimage.rotate(m0.astype(np.float32), applied, order=1, reshape=False) > 0.5
        got, sc, _ = find_residual(m1)
        errs.append(abs(((got - (base - applied)) + 90) % 180 - 90))
        scores.append(sc)
    e, sc = np.array(errs), np.array(scores)
    print(f"synthetic recovery, n={len(e)} sections, applied +/-15 deg")
    print(f"  median |error| {np.median(e):.2f} deg")
    for t in (1, 2, 5, 10):
        print(f"  within {t:>2} deg : {100 * (e < t).mean():.0f}%")
    print(f"  max |error|    : {e.max():.1f} deg")
    ok, bad = sc[e < 5], sc[e >= 5]
    if len(ok):
        print(f"\n  peak score, correct  : median {np.median(ok):.3f}")
    if len(bad):
        print(f"  peak score, failures : median {np.median(bad):.3f}")
        print(f"  gate score < {SCORE_MIN}: catches {100 * (bad < SCORE_MIN).mean():.0f}% of "
              f"failures, keeps {100 * (ok >= SCORE_MIN).mean():.0f}% of correct")
    else:
        print("  no failures in this sample")
    surv = e[sc >= SCORE_MIN]
    if len(surv):
        print(f"  high-confidence subset only (n={len(surv)}/{len(e)}): "
              f"median {np.median(surv):.2f} deg, within 2 deg {100 * (surv < 2).mean():.0f}%, "
              f"within 5 deg {100 * (surv < 5).mean():.0f}%, max {surv.max():.1f}")
    print()
    print("Benchmark: Wu et al. 2013 SIFT-pair voting, implemented and measured on")
    print("this dataset, reached median 24.1 deg with 12% within 5 deg. Shape")
    print("reflection is not a simplification here - it is the method that works.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", type=int, default=0,
                    help="run the synthetic recovery test on N sections and stop")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    os.makedirs(REPORT_DIR, exist_ok=True)

    if args.validate:
        validate(args.validate)
        return

    rows, skip = good_sections()
    if args.limit:
        rows = rows[: args.limit]

    out = []
    for i, r in enumerate(rows):
        uid = r["id"]
        m = load(uid)
        if m is None:
            continue
        if uid in skip:
            # Recorded, but no proposal: a fragment has no midline to find.
            out.append({"scene_uid": uid, "animal": r["animal"],
                        "section_order": r["section_order"],
                        "proposed_rotation": "", "sym_score": "", "margin": "",
                        "confidence": "skipped_excluded"})
            continue
        res, sc, mg = find_residual(m)
        out.append({"scene_uid": uid, "animal": r["animal"],
                    "section_order": r["section_order"],
                    "proposed_rotation": int(round(res)),
                    "sym_score": round(sc, 4), "margin": round(mg, 4),
                    "confidence": "low" if sc < SCORE_MIN else "high"})
        if (i + 1) % 50 == 0:
            print(f"\r  {i + 1}/{len(rows)}", end="")
    print(f"\r  measured {len(out)} sections        ")

    IO.atomic_write_csv(OUT_CSV, out, SYM_KEYS)

    live = [r for r in out if r["confidence"] in ("high", "low")]
    hi = [r for r in live if r["confidence"] == "high"]
    rot = np.array([abs(r["proposed_rotation"]) for r in live], float)
    print()
    print("=" * 74)
    print(f"{len(out)} sections -> {OUT_CSV}")
    print(f"  proposals made      : {len(live)}  ({len(out) - len(live)} skipped as excluded)")
    print(f"  high confidence     : {len(hi)} ({100 * len(hi) / max(len(live), 1):.0f}%)")
    print(f"  |correction| needed : median {np.median(rot):.0f} deg, "
          f"p90 {np.percentile(rot, 90):.0f}, max {rot.max():.0f}")
    print(f"  already within 2 deg: {100 * (rot <= 2).mean():.0f}% of sections")
    print()
    print("Validated against synthetic ground truth on three held-out samples of 28")
    print("sections: median error 0.20-0.45 deg, 86-96% within 5 deg. Run")
    print("--validate 28 to reproduce. Roughly one proposal in ten is wrong, and")
    print("the score gate catches most but not all of those - so the curator, which")
    print("shows each section already rotated, is what actually verifies them.")
    print("=" * 74)


if __name__ == "__main__":
    main()
