"""Stage 4i - carry the curation from the PCNA scans onto the paired pERK scans.

Every curation decision so far was made on the DAPI channel of the **AF488 (PCNA)**
scan. The **AF568 (pERK)** scan of the same physical section is a separate
acquisition with its own hand-drawn scan box, so it has different framing and
`04a` gives it a different automatic angle. The decisions therefore do not
transfer by copying.

The three kinds of decision transfer differently, and lumping them would be wrong:

**Exclusions transfer directly.** A section excluded because its tissue is torn is
torn in both scans - it is one physical section imaged twice. Straight lookup
through `pairs.csv`.

**Rotations must be re-derived, not copied.** `extra_rotation` is a correction on
top of `04a`'s automatic angle, and that automatic angle differs between the two
scans because the scan boxes differ. What is shared is the *final orientation* the
operator chose. So: reformat the pERK section, then find the rotation that brings
its tissue mask into alignment with the already-curated PCNA mask of the same
section. The target is a real, near-identical shape - the same nuclei in the same
tissue - so unlike the atlas matching in `04c` there is a strong signal here, and
the alignment IoU is reported per section so weak ones can be caught.

The search covers the full 360 degrees, because the two automatic angles are
independent and `04a`'s 180 degree resolution can land differently on each.

**Artifacts are not propagated at all.** Bubbles, aggregates and fibres are
properties of the imaged field, and the two scans image different fields. Running
`04g` directly on the pERK overviews is both simpler and more correct than
mapping a mask across frames.

A flip hypothesis is scored alongside rotation as a check, not as a correction:
the two scans are the same slide the same way up, so flips should essentially
never win. If they do, the pairing is suspect.

Run:  python 04i_propagate_to_perk.py --limit 40      # try a subset first
      python 04i_propagate_to_perk.py
"""

import argparse
import csv
import json
import os

import numpy as np
from PIL import Image
from scipy import ndimage

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
SEC_DIR = os.path.join(REFORMAT_DIR, "sections")
PAIRS_CSV = os.path.join(OUT_ROOT, "pairs.csv")
OUT_CSV = os.path.join(REFORMAT_DIR, "perk_overrides.csv")
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "perk")

PHYS_DS = 4           # downsample both overviews by this -> 20.8 um/px, shared
CANVAS = 320          # px on the shared physical grid; ~6.7 mm across
COARSE = 3.0          # degrees, first pass over the full circle
FINE = 1.0
# Below this alignment IoU the two masks genuinely disagree and the transfer
# should be checked by eye. Set from the measured distribution over all 661
# sections - median 0.789, p25 0.651, p10 0.520 - so this flags the bottom ~13%
# rather than half of them, which a 0.70 gate would have done.
IOU_MIN = 0.55

import importlib.util
_SPEC = importlib.util.spec_from_file_location(
    "reformat_mod", os.path.join(os.path.dirname(os.path.abspath(__file__)), "04a_reformat.py"))
_RF = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RF)


def physical_mask(png_path, canvas):
    """Tissue mask on a shared PHYSICAL grid, centred on its own centroid.

    **Not the reformatted mask, and that distinction is the whole point.** The
    reformat crops each scan to its own tissue bounding box and resizes to
    256x256, so the tissue occupies a different fraction of the frame depending
    on how much debris the scan box happened to include. The two scans of one
    section then differ in *scale*, and no rotation can bring them together - a
    first attempt did exactly that and reached a median IoU of 0.548 with flips
    winning a third of the time, which is what a failed match looks like.

    Both overviews are at a verified 5.20 um/px, so downsampling both by the same
    factor puts them on a common physical grid where only rotation and
    translation are free.
    """
    try:
        img = Image.open(png_path).convert("L")
    except OSError:
        return None
    a = np.asarray(img).astype(np.float32)[::PHYS_DS, ::PHYS_DS]
    m = _RF.tissue_mask(a, light_background=False)
    if m is None:
        return None
    ys, xs = np.nonzero(m)
    out = np.zeros((canvas, canvas), bool)
    cy, cx = int(ys.mean()), int(xs.mean())
    y0, x0 = canvas // 2 - cy, canvas // 2 - cx
    sy = slice(max(0, y0), min(canvas, y0 + m.shape[0]))
    sx = slice(max(0, x0), min(canvas, x0 + m.shape[1]))
    ty = slice(max(0, -y0), max(0, -y0) + (sy.stop - sy.start))
    tx = slice(max(0, -x0), max(0, -x0) + (sx.stop - sx.start))
    out[sy, sx] = m[ty, tx]
    return out


def best_iou_over_shifts(a, b):
    """Max IoU between `a` and `b` over ALL translations, from one FFT.

    Intersection under a circular shift is a cross-correlation, and |a| and |b|
    do not change with the shift, so IoU(shift) = I / (|a| + |b| - I) for every
    shift at once. Same identity as the symmetry search in 04h.
    """
    A = a.astype(np.float32)
    B = b.astype(np.float32)
    na, nb = float(A.sum()), float(B.sum())
    if na < 50 or nb < 50:
        return 0.0
    corr = np.fft.irfft2(np.fft.rfft2(A) * np.conj(np.fft.rfft2(B)), s=A.shape)
    return float((corr / np.maximum(na + nb - corr, 1e-6)).max())


def align(src_mask, target_mask):
    """Rotation bringing src onto target, translation free.

    Returns (degrees, iou, flip_margin).

    **Flipping is measured but never applied.** Two scans of one section on one
    slide cannot be mirror images of each other - the scanner does not mirror -
    so a flip here can only be an error. And it would be a damaging one: it would
    swap left and right hemispheres in the pERK data relative to PCNA, which is
    exactly what a lateralisation result would be read off.

    The flip hypothesis was scored during development, won on 18.5% of sections,
    and turned out to win by a median of **0.0056 IoU** - a coin toss on a
    near-symmetric shape, with 96% of wins under 0.05. It is retained as a
    reported margin so the evidence stays visible, and discarded as a correction.
    """
    for flip in (False,):
        m = src_mask
        coarse = np.arange(0, 360, COARSE)
        scores = [best_iou_over_shifts(
            ndimage.rotate(m.astype(np.uint8), float(t), order=0, reshape=False) > 0,
            target_mask) for t in coarse]
        t0 = float(coarse[int(np.argmax(scores))])
        fine = np.arange(t0 - COARSE, t0 + COARSE + 1e-9, FINE)
        fs = [best_iou_over_shifts(
            ndimage.rotate(m.astype(np.uint8), float(t), order=0, reshape=False) > 0,
            target_mask) for t in fine]
        k = int(np.argmax(fs))
        deg, score = float(fine[k]) % 360, float(fs[k])

    # Diagnostic only: how much better the mirrored section would have scored.
    mf = src_mask[:, ::-1]
    coarse = np.arange(0, 360, COARSE)
    flip_best = max(best_iou_over_shifts(
        ndimage.rotate(mf.astype(np.uint8), float(t), order=0, reshape=False) > 0,
        target_mask) for t in coarse)
    return deg, score, float(flip_best - score)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    os.makedirs(REPORT_DIR, exist_ok=True)

    with open(PAIRS_CSV, newline="", encoding="utf-8") as fh:
        pairs = [r for r in csv.DictReader(fh)
                 if r.get("af488_scene_uid") and r.get("af568_scene_uid")]
    to568 = {r["af488_scene_uid"]: r["af568_scene_uid"] for r in pairs}

    # Curated PCNA state: what survived, and what was excluded.
    kept = {r["id"]: r for r in csv.DictReader(open(
        os.path.join(REFORMAT_DIR, "reformat_index.csv"), encoding="utf-8"))
        if r["kind"] == "section"}
    excluded = {r["scene_uid"] for r in csv.DictReader(open(
        os.path.join(REFORMAT_DIR, "excluded_sections.csv"), encoding="utf-8"))}

    chan = {}
    with open(os.path.join(OUT_ROOT, "qc", "focus.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            chan[r["scene_uid"]] = (r["animal"], r["marker_channel"])

    rows, n_excl, n_nopair, failed = [], 0, 0, 0
    todo = list(kept.items())
    if args.limit:
        todo = todo[: args.limit]

    # 1. Exclusions, straight through the pairing.
    for uid in excluded:
        u568 = to568.get(uid)
        if u568:
            rows.append({"perk_scene_uid": u568, "pcna_scene_uid": uid,
                         "animal": uid.split("_")[0], "extra_rotation": 0, "flip": 0,
                         "excluded": 1, "align_iou": "", "flip_margin": "",
                         "confidence": "",
                         "reason": "PCNA partner excluded by the operator"})
            n_excl += 1

    # 2. Rotations, re-derived by aligning to the curated PCNA mask.
    for i, (uid, meta) in enumerate(todo, 1):
        u568 = to568.get(uid)
        if not u568:
            n_nopair += 1
            continue
        animal488, _ = chan.get(uid, (uid.split("_")[0], "AF488"))
        animal, _ = chan.get(u568, (u568.split("_")[0], "AF568"))
        p488 = os.path.join(OVERVIEW_DIR, animal488, "AF488", uid + "_DAPI.png")
        p568 = os.path.join(OVERVIEW_DIR, animal, "AF568", u568 + "_DAPI.png")
        if not (os.path.exists(p488) and os.path.exists(p568)):
            failed += 1
            continue
        m488 = physical_mask(p488, CANVAS)
        m568 = physical_mask(p568, CANVAS)
        if m488 is None or m568 is None:
            failed += 1
            continue

        # `angle` in reformat_index is the TOTAL rotation 04a applied to the PCNA
        # scan - automatic plus the operator's correction. Rotating the raw PCNA
        # mask by it reproduces the curated orientation, in physical units.
        total488 = float(meta["angle"])
        target = ndimage.rotate(m488.astype(np.uint8), total488, order=0,
                                reshape=False) > 0

        deg, score, flip_margin = align(m568, target)

        # 04a will apply its own automatic angle to the pERK scan, so the
        # correction it needs is the difference between the total rotation
        # measured here and that automatic angle.
        auto = _RF.reformat(p568, light_background=False)
        if auto is None:
            failed += 1
            continue
        a568 = float(auto[2])
        extra = (deg - a568) % 360

        rows.append({"perk_scene_uid": u568, "pcna_scene_uid": uid, "animal": animal,
                     "extra_rotation": int(round(extra)), "flip": 0,
                     "excluded": 0, "align_iou": round(score, 4),
                     "flip_margin": round(flip_margin, 4),
                     "confidence": "low" if score < IOU_MIN else "high",
                     "reason": ""})
        if (i % 50) == 0:
            print(f"\r  aligned {i}/{len(todo)}", end="")
    print(f"\r  aligned {len(todo)} sections            ")

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    live = [r for r in rows if not r["excluded"] and r["align_iou"] != ""]
    s = np.array([r["align_iou"] for r in live], dtype=float)
    hi = sum(1 for r in live if r["confidence"] == "high")
    fm = np.array([r["flip_margin"] for r in live], dtype=float)
    print()
    print("=" * 74)
    print(f"{len(rows)} rows -> {OUT_CSV}")
    print(f"  exclusions transferred : {n_excl}")
    print(f"  rotations derived      : {len(live)}")
    print(f"  curated sections with no pERK partner : {n_nopair}")
    print(f"  failed to reformat     : {failed}")
    if len(s):
        print()
        print(f"  alignment IoU : median {np.median(s):.3f}  p10 {np.percentile(s, 10):.3f}  "
              f"p90 {np.percentile(s, 90):.3f}  min {s.min():.3f}")
        print(f"  high confidence (>= {IOU_MIN}) : {hi} ({100 * hi / len(live):.0f}%)")
        print(f"  mirrored-would-score-better on {int((fm > 0).sum())} section(s), "
              f"by a median of {np.median(fm[fm > 0]) if (fm > 0).any() else 0:.4f} IoU")
        print("  Flipping is measured but never applied: two scans of one slide cannot")
        print("  be mirrored, and a spurious flip would swap the hemispheres.")
        print()
        print("  This is a shape alignment between two images of the SAME physical")
        print("  section, so a low IoU means the pairing is wrong, not that the tissue")
        print("  is ambiguous. Inspect the low-confidence rows before trusting them.")
    print("=" * 74)


if __name__ == "__main__":
    main()
