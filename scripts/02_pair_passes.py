"""Stage 2 - pair the AF568 and AF488 passes onto the same physical sections.

Both passes imaged the same slides, but the scan regions were redrawn each time,
so scene indices do not correspond (LS45_8a has 10 scenes, LS45_8b has 12).
Matching therefore has to go through stage coordinates, not indices.

The slide sits in a kinematic holder, so a reload displaces it by a small rigid
translation. That offset is recovered by voting: every possible pairing casts a
vote for the translation it implies, and the translation with the most inliers
wins. With sections ~7-10 mm apart and reload offsets far smaller, the vote is
unambiguous. Assignment under the winning offset is then solved optimally rather
than greedily, so one bad section cannot cascade.

Produces the canonical `section_uid` that every later stage keys on, and lists
unmatched sections explicitly rather than dropping them.

Run:  python 02_pair_passes.py
"""

import csv
import json
import os
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
MANIFEST_DIR = os.path.join(OUT_ROOT, "manifest")

# Tolerances are expressed as fractions of the nearest-neighbour spacing within
# a constellation, never as absolute distances. Scan regions are hand-drawn, so
# a box centre can sit 1-2.5 mm from the section centre even when the two passes
# imaged the identical slide (LS45 slide 5 residuals run 220-2500 um). What
# distinguishes the same slide from a different one is whether the residual is
# small *relative to how far apart the sections are*, which an absolute
# threshold cannot express.
INLIER_TOL_FRAC = 0.45
MAX_MATCH_FRAC = 0.50
SAME_SLIDE_TOL_FRAC = 0.50
# Median residual below this fraction of section spacing = same physical slide.
SAME_SLIDE_MEDIAN_FRAC = 0.35
# Fraction of the smaller constellation that must agree.
SAME_SLIDE_MIN_FRACTION = 0.6
# A kinematic slide holder cannot displace a reloaded slide further than this.
# Without the constraint the vote happily locks onto a one-section shift, which
# scores nearly as well on a regular grid and produced spurious 12 mm offsets.
MAX_RELOAD_UM = 3000.0


def nn_spacing(pts):
    """Median nearest-neighbour distance - the natural length scale of a slide."""
    if len(pts) < 2:
        return np.inf
    d = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=2)
    np.fill_diagonal(d, np.inf)
    return float(np.median(d.min(axis=1)))


def load_scenes():
    path = os.path.join(MANIFEST_DIR, "manifest_scenes.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["slide"] = int(r["slide"])
        r["scene_index"] = int(r["scene_index"])
        r["slide_serial"] = int(r["slide_serial"])
        r["section_order"] = int(r["section_order"])
        r["center_x_um"] = float(r["center_x_um"])
        r["center_y_um"] = float(r["center_y_um"])
    return rows


def choose_variants(rows):
    """One variant per (animal, slide, marker).

    Where a slide was re-scanned (LS45_8b/8c, LS61_2b/2c, LS85_7a/7b-) prefer
    the variant with more scenes, then the earlier letter. Stage 1's focus
    scores can override this later via manifest/chosen_variants.csv.
    """
    override_path = os.path.join(MANIFEST_DIR, "chosen_variants.csv")
    overrides = {}
    if os.path.exists(override_path):
        with open(override_path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                overrides[(r["animal"], int(r["slide"]), r["marker_channel"])] = r["variant"]
        print(f"Loaded {len(overrides)} variant override(s)")

    by_key = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_key[(r["animal"], r["slide"], r["marker_channel"])][r["variant"]].append(r)

    chosen, notes = {}, []
    for key, variants in by_key.items():
        if key in overrides and overrides[key] in variants:
            pick = overrides[key]
        else:
            pick = sorted(variants, key=lambda v: (-len(variants[v]), v))[0]
        chosen[key] = variants[pick]
        if len(variants) > 1:
            notes.append(
                {
                    "animal": key[0], "slide": key[1], "marker_channel": key[2],
                    "chosen_variant": pick,
                    "candidates": "|".join(f"{v}({len(variants[v])})" for v in sorted(variants)),
                    "source": "override" if key in overrides else "most_scenes",
                }
            )
    return chosen, notes


def best_offset(a_pts, b_pts, inlier_tol):
    """Translation taking A onto B, chosen by inlier vote."""
    if not len(a_pts) or not len(b_pts):
        return np.array([0.0, 0.0]), 0
    INLIER_TOL_UM = inlier_tol

    best, best_score = np.array([0.0, 0.0]), (-1, np.inf)
    candidates = [np.array([0.0, 0.0])]
    candidates += [b - a for a in a_pts for b in b_pts]

    for offset in candidates:
        if np.linalg.norm(offset) > MAX_RELOAD_UM:
            continue
        shifted = a_pts + offset
        d = np.linalg.norm(shifted[:, None, :] - b_pts[None, :, :], axis=2)
        nearest = d.min(axis=1)
        inliers = int((nearest <= INLIER_TOL_UM).sum())
        # Tie-break on residual: a one-section shift can match the inlier count
        # of the true offset but never its residual.
        residual = float(nearest[nearest <= INLIER_TOL_UM].sum()) if inliers else np.inf
        if (inliers, -residual) > (best_score[0], -best_score[1]):
            best, best_score = offset, (inliers, residual)
    best_inliers = best_score[0]

    # Refine on the inlier set so the estimate is not tied to one arbitrary pair.
    shifted = a_pts + best
    d = np.linalg.norm(shifted[:, None, :] - b_pts[None, :, :], axis=2)
    nearest = d.argmin(axis=1)
    keep = d.min(axis=1) <= INLIER_TOL_UM
    if keep.any():
        refined = np.mean(b_pts[nearest[keep]] - a_pts[keep], axis=0)
        # Refinement is unconstrained, so re-apply the physical limit rather
        # than let a skewed inlier set drag the estimate past it.
        if np.linalg.norm(refined) <= MAX_RELOAD_UM:
            best = refined
    return best, best_inliers


def match_slide(a_rows, b_rows):
    """Optimal 1:1 assignment under the recovered offset, plus a same-slide call.

    The two passes are only the same physical slide if the constellations agree
    tightly after a small translation. Where they do not - LS136 slide 1 has a
    2-row AF568 layout against a 3-row AF488 grid with a 4 mm origin shift -
    forcing matches would invent correspondences that do not exist.
    """
    a_pts = np.array([[r["center_x_um"], r["center_y_um"]] for r in a_rows])
    b_pts = np.array([[r["center_x_um"], r["center_y_um"]] for r in b_rows])

    scale = min(nn_spacing(a_pts), nn_spacing(b_pts))
    if not np.isfinite(scale):
        scale = 8000.0
    offset, votes = best_offset(a_pts, b_pts, INLIER_TOL_FRAC * scale)

    cost = np.linalg.norm((a_pts + offset)[:, None, :] - b_pts[None, :, :], axis=2)
    rows_i, cols_i = linear_sum_assignment(cost)
    assigned = [(i, j, float(cost[i, j])) for i, j in zip(rows_i, cols_i)]

    tight = [d for _, _, d in assigned if d <= SAME_SLIDE_TOL_FRAC * scale]
    fraction = len(tight) / max(min(len(a_rows), len(b_rows)), 1)
    median_residual = float(np.median([d for _, _, d in assigned])) if assigned else float("nan")
    same_slide = (
        fraction >= SAME_SLIDE_MIN_FRACTION
        and median_residual <= SAME_SLIDE_MEDIAN_FRAC * scale
    )

    pairs, used_a, used_b = [], set(), set()
    if same_slide:
        for i, j, d in assigned:
            if d <= MAX_MATCH_FRAC * scale:
                pairs.append((a_rows[i], b_rows[j], d))
                used_a.add(i)
                used_b.add(j)

    unmatched_a = [a_rows[i] for i in range(len(a_rows)) if i not in used_a]
    unmatched_b = [b_rows[j] for j in range(len(b_rows)) if j not in used_b]
    diagnostics = {
        "same_slide": same_slide,
        "tight_fraction": round(fraction, 3),
        "median_residual_um": round(median_residual, 1),
        "votes": votes,
    }
    return pairs, unmatched_a, unmatched_b, offset, diagnostics


def main():
    rows = load_scenes()
    chosen, variant_notes = choose_variants(rows)

    markers = sorted({r["marker_channel"] for r in rows})
    if len(markers) != 2:
        print(f"  !! expected two marker channels, found {markers}")
    marker_a, marker_b = "AF568", "AF488"

    animals = sorted({r["animal"] for r in rows}, key=lambda a: int(a[2:]))
    pair_rows, offset_rows = [], []

    for animal in animals:
        slides = sorted({k[1] for k in chosen if k[0] == animal})
        entries = []

        for slide in slides:
            a_rows = chosen.get((animal, slide, marker_a), [])
            b_rows = chosen.get((animal, slide, marker_b), [])

            if not a_rows or not b_rows:
                only = marker_a if a_rows else marker_b
                for r in (a_rows or b_rows):
                    entries.append({"slide": slide, "serial": r["slide_serial"], "marker": only,
                                    "a": r if a_rows else None, "b": None if a_rows else r,
                                    "dist": "", "status": f"only_{only}"})
                offset_rows.append({"animal": animal, "slide": slide, "n_af568": len(a_rows),
                                    "n_af488": len(b_rows), "same_slide": "",
                                    "tight_fraction": "", "median_residual_um": "",
                                    "dx_um": "", "dy_um": "",
                                    "inlier_votes": "", "n_matched": 0,
                                    "note": f"only {only} present"})
                continue

            pairs, un_a, un_b, offset, diag = match_slide(a_rows, b_rows)
            same = diag["same_slide"]

            for a, b, dist in pairs:
                entries.append({"slide": slide, "serial": a["slide_serial"], "marker": marker_a,
                                "a": a, "b": b, "dist": round(dist, 1), "status": "matched"})
            for r in un_a:
                entries.append({"slide": slide, "serial": r["slide_serial"], "marker": marker_a,
                                "a": r, "b": None, "dist": "",
                                "status": "unmatched_AF568" if same else "separate_slide_AF568"})
            for r in un_b:
                entries.append({"slide": slide, "serial": r["slide_serial"], "marker": marker_b,
                                "a": None, "b": r, "dist": "",
                                "status": "unmatched_AF488" if same else "separate_slide_AF488"})

            offset_rows.append({
                "animal": animal, "slide": slide,
                "n_af568": len(a_rows), "n_af488": len(b_rows),
                "same_slide": int(same),
                "tight_fraction": diag["tight_fraction"],
                "median_residual_um": diag["median_residual_um"],
                "dx_um": round(float(offset[0]), 1), "dy_um": round(float(offset[1]), 1),
                "inlier_votes": diag["votes"], "n_matched": len(pairs),
                "note": "" if same else "constellations disagree - treat as separate slides",
            })

        # Canonical rostro-caudal numbering across the whole animal.
        entries.sort(key=lambda e: (e["slide"], e["serial"], e["marker"]))
        for position, e in enumerate(entries, start=1):
            a, b = e["a"], e["b"]
            pair_rows.append({
                "section_uid": f"{animal}_sec{position:03d}",
                "animal": animal,
                "slide": e["slide"],
                "slide_serial": e["serial"],
                "status": e["status"],
                "af568_file": a["file"] if a else "",
                "af568_scene": a["scene_index"] if a else "",
                "af568_scene_uid": a["scene_uid"] if a else "",
                "af488_file": b["file"] if b else "",
                "af488_scene": b["scene_index"] if b else "",
                "af488_scene_uid": b["scene_uid"] if b else "",
                "match_distance_um": e["dist"],
                "center_x_um": round((a or b)["center_x_um"], 1),
                "center_y_um": round((a or b)["center_y_um"], 1),
            })

    _write(os.path.join(OUT_ROOT, "pairs.csv"), pair_rows)
    _write(os.path.join(OUT_ROOT, "qc", "pairing_offsets.csv"), offset_rows)
    if variant_notes:
        _write(os.path.join(MANIFEST_DIR, "variant_choices.csv"), variant_notes)

    _report(pair_rows, offset_rows, variant_notes)


def _write(path, rows):
    if not rows:
        print(f"  (nothing to write for {os.path.basename(path)})")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {os.path.basename(path)}  ({len(rows)} rows)")


def _report(pair_rows, offset_rows, variant_notes):
    counts = defaultdict(int)
    for r in pair_rows:
        counts[r["status"]] += 1
    total = len(pair_rows)
    matched = counts.get("matched", 0)

    print()
    print("=" * 72)
    print(f"physical sections identified : {total}")
    for status, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status:<18}: {n}  ({100.0 * n / max(total, 1):.1f}%)")

    dists = [r["match_distance_um"] for r in pair_rows if r["status"] == "matched"]
    if dists:
        print(f"match distance um            : median {np.median(dists):.0f}  p95 {np.percentile(dists, 95):.0f}  max {np.max(dists):.0f}")

    offsets = [(r["dx_um"], r["dy_um"]) for r in offset_rows if r["dx_um"] != ""]
    if offsets:
        dx = [o[0] for o in offsets]
        dy = [o[1] for o in offsets]
        print(f"slide reload offset um       : dx median {np.median(dx):+.0f} (range {min(dx):+.0f}..{max(dx):+.0f})")
        print(f"                               dy median {np.median(dy):+.0f} (range {min(dy):+.0f}..{max(dy):+.0f})")

    by_animal = defaultdict(lambda: defaultdict(int))
    for r in pair_rows:
        by_animal[r["animal"]][r["status"]] += 1
    print("\nper animal (matched / total):")
    for animal in sorted(by_animal, key=lambda a: int(a[2:])):
        d = by_animal[animal]
        tot = sum(d.values())
        print(f"  {animal:<7} {d.get('matched', 0):>4} / {tot:<4}"
              + ("   " + ", ".join(f"{k}={v}" for k, v in sorted(d.items()) if k != "matched") if len(d) > 1 else ""))

    if variant_notes:
        print(f"\nre-scanned slides resolved: {len(variant_notes)}")
        for n in variant_notes:
            print(f"  {n['animal']} slide {n['slide']} {n['marker_channel']}: chose {n['chosen_variant']} from {n['candidates']} ({n['source']})")

    print("=" * 72)
    print("section_uid in pairs.csv is now the canonical id for every later stage.")


if __name__ == "__main__":
    main()
