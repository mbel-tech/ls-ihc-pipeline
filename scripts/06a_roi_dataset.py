"""Stage 6a - per-nucleus measurements to a per-ROI dataset. Still blind.

Reads `results/roi_nuclei.csv` and decides three things.

**Where the positivity cut comes from.** Each section's own background discs -
tissue the operator judged to carry no real signal - give a robust upper bound:

    cut = median(background) + 3 * 1.4826 * MAD(background)

Per section, because this is a high-baseline marker and the background level
moves from section to section. **The earlier reason given here was wrong and is
corrected:** it claimed the background level "splits the animals into two groups
8,732 units apart" and called that a staining batch effect. LOGS.md later
overturned that reading - restricted to clip-free sections the two groups are
the same (background 10,844 vs 12,300; tissue 5,542 vs 5,494), and the 1.86x gap
is *produced by* clipped pixels pinned at 65,535 dragging the mean up. That is
information loss, not a gain difference. The per-section cut is still the right
choice; the reason is section-to-section variation, not two batches.

Robust rather than a percentile, and this is the point: a percentile would fix
the false-positive rate by construction and destroy the only independent check
available. With a spread based cut, how many background nuclei land above it is
a MEASUREMENT.

**What the background discs then report.** The same detector over tissue called
empty is a false-positive rate, per section and per animal. It is not a negative
control - the primary antibody is on that tissue - so it measures non-specific
binding plus autofluorescence, not zero.

**Abercrombie.** Sections are 14 um and imaged in one plane, so what is counted
is nuclear PROFILES: a nucleus straddling the cut face still appears in the
section it is cut into, and neighbouring sections are consecutive, so pooling
raw counts across them counts that cell twice. N = n * T/(T + h), with h MEASURED
here per region and marker from the segmentation rather than taken from the
7.0 um in config - the factor moves from 0.74 to 0.58 across a plausible range,
and an assumed h would bury that in every density.

Writes, all still keyed by animal only:
    results/roi_measurements.csv       one row per placed ROI
    results/detector_specificity.csv   what the background discs found

Run:  python 06a_roi_dataset.py
"""

import collections
import csv
import importlib.util
import os
import statistics as st

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_g5", os.path.join(_HERE, "05a_roi_geometry.py"))
G5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G5)

CONFIG = G5.CONFIG
OUT_ROOT = G5.OUT_ROOT
RESULTS = os.path.join(OUT_ROOT, "results")
NUCLEI_CSV = os.path.join(RESULTS, "roi_nuclei.csv")
MEAS_CSV = os.path.join(RESULTS, "roi_measurements.csv")
SPEC_CSV = os.path.join(RESULTS, "detector_specificity.csv")

T_UM = CONFIG["section_thickness_um"]
AB = CONFIG["detection"].get("abercrombie", {})
AB_ON = bool(AB.get("enabled"))
BASE_PX_UM = CONFIG["pixel_size_um"]

# The intensity a nucleus is judged on. The median over its own pixels, so one
# bright speck inside a nucleus cannot carry it over the line.
STAT = "marker_median"


def mad(xs):
    m = st.median(xs)
    return st.median([abs(x - m) for x in xs])


def roi_area_um2(b):
    """The ellipse the disc became on the slide, from the two semi-axes 05a
    measured. Not pi*r^2 in canonical pixels: the map is not a similarity."""
    return np.pi * float(b["axis_a_um"]) * float(b["axis_b_um"])


def main():
    if not os.path.exists(NUCLEI_CSV):
        print(f"no {NUCLEI_CSV} - run 05c_detect_rois.py first")
        return 1
    nuc = G5.load_csv(NUCLEI_CSV)
    box_by = {}
    # EVERY marker's boxes. roi_nuclei.csv holds both once the PCNA pass has
    # run, and the cut is per section and h is per (marker, region), so one
    # run covers both without pooling anything across them.
    for b in G5.all_boxes():
        box_by.setdefault(b["scene_uid"], []).append(b)
    print(f"{len(nuc)} nuclei over "
          f"{len({r['scene_uid'] for r in nuc})} sections")

    for r in nuc:
        r["_v"] = float(r[STAT])
        r["_cen"] = r["censored"] == "1"
        r["_art"] = r["artifact"] == "1"
        r["_d"] = float(r["equiv_diam_um"])

    # Artifact pixels are not tissue and leave the analysis entirely. Censored
    # ones are RIGHT-censored - value lost, but at least the ceiling - so they
    # stay in the count and are excluded only from the intensity statistics.
    # Reversing those two would bias positive rates down in exactly the
    # brightest-staining animals (LOGS.md 2026-08-12).
    nuc = [r for r in nuc if not r["_art"]]

    # ONE PASS over the nuclei, building every index at once.
    #
    # This used to re-scan the whole table for each of three things: the cut
    # filtered all of it per section, h did the same per (marker, region), and
    # by_idx did it once more per section. At 883,078 nuclei that is hundreds of
    # millions of comparisons. 06c_excel_dataset.py already hit exactly this and
    # records what it cost - a rebuild that ran long enough to be killed
    # part-written, leaving an xlsx openpyxl could not reopen. PCNA is roughly
    # six times this file, so the shape matters more than the current runtime.
    bg_by = collections.defaultdict(list)      # uid -> background values
    by_idx = collections.defaultdict(list)     # (uid, roi_index) -> nuclei
    diam_by = collections.defaultdict(list)    # (marker, region) -> diameters
    uids, d_all = set(), []
    for r in nuc:
        uid = r["scene_uid"]
        uids.add(uid)
        d_all.append(r["_d"])
        # roi_index is what ties a nucleus to the disc it was found in - 05c
        # numbers the discs in the order roi_boxes.csv lists them for a section,
        # and the emit loop below enumerates the same list in the same order.
        by_idx[(uid, int(r["roi_index"]))].append(r)
        if r["roi_kind"] == "background":
            if not r["_cen"]:
                bg_by[uid].append(r["_v"])
        else:
            diam_by[(r["marker"], r["region"])].append(r["_d"])

    # ---- the per-section cut, from that section's own background discs
    cuts, bgstat = {}, {}
    for uid, bg in bg_by.items():
        if len(bg) < 5:
            continue
        m, s = st.median(bg), mad(bg) * 1.4826
        cuts[uid] = m + 3.0 * s
        bgstat[uid] = (m, s, len(bg))

    # ---- h for Abercrombie, measured per region and marker
    hs = {k: st.mean(v) for k, v in diam_by.items() if v}
    h_all = st.mean(d_all) if d_all else 0.0

    rows, spec = [], []
    for uid in sorted(uids):
        cut = cuts.get(uid)
        for i, b in enumerate(box_by.get(uid, []), 1):
            here = by_idx.get((uid, i), [])
            area = roi_area_um2(b)
            n_nuc = len(here)
            usable = [r for r in here if not r["_cen"]]
            # A censored nucleus counts as POSITIVE and is still dropped from
            # `usable`. That is not an inconsistency: 04j_censor_clipped.py
            # defines a censored pixel as right-censored at the 16-bit ceiling,
            # so it is unambiguously above any cut, while including a ceiling
            # value in a median would bias the intensity statistic. 04j states
            # both halves outright - censoring "MUST NOT be excluded from
            # detection or from positivity" and MUST be excluded from any
            # intensity statistic. Do not "fix" this to drop them.
            n_pos = (sum(1 for r in here if r["_cen"] or r["_v"] > cut)
                     if cut is not None else "")
            h = hs.get((b["marker"], b["region"]), h_all)
            ab = T_UM / (T_UM + h) if (AB_ON and h) else 1.0
            row = {
                "scene_uid": uid, "animal": b["animal"], "marker": b["marker"],
                "roi_kind": b["roi_kind"], "region": b["region"],
                "seed_n": b["seed_n"], "roi_index": i,
                "plate_id": "", "sec_x": b["sec_x"], "sec_y": b["sec_y"],
                "roi_area_um2": round(area, 1),
                "roi_area_mm2": round(area / 1e6, 6),
                "n_nuclei": n_nuc,
                "n_positive": n_pos,
                "frac_positive": (round(n_pos / n_nuc, 4) if (cut is not None and n_nuc)
                                  else ""),
                "profile_density_per_mm2": round(n_nuc / (area / 1e6), 1) if area else "",
                "abercrombie_factor": round(ab, 4),
                "mean_nucleus_diam_um": round(h, 2) if h else "",
                "cell_density_per_mm2": (round(n_nuc * ab / (area / 1e6), 1)
                                         if area else ""),
                "positive_density_per_mm2": (round(n_pos * ab / (area / 1e6), 1)
                                             if (cut is not None and area) else ""),
                "marker_median_of_roi": (round(st.median([r["_v"] for r in usable]), 1)
                                         if usable else ""),
                "section_bg_level": round(bgstat[uid][0], 1) if uid in bgstat else "",
                "section_bg_spread": round(bgstat[uid][1], 1) if uid in bgstat else "",
                "section_bg_nuclei": bgstat[uid][2] if uid in bgstat else 0,
                "section_positivity_cut": round(cut, 1) if cut is not None else "",
                "n_censored": sum(1 for r in here if r["_cen"]),
            }
            rows.append(row)

        # what the background discs report about the detector, per section
        bgrows = [r for r in rows if r["scene_uid"] == uid
                  and r["roi_kind"] == "background"]
        if bgrows and cut is not None:
            tot_n = sum(r["n_nuclei"] for r in bgrows)
            tot_p = sum(r["n_positive"] for r in bgrows)
            tot_a = sum(r["roi_area_mm2"] for r in bgrows)
            dens = [r["profile_density_per_mm2"] for r in bgrows
                    if r["profile_density_per_mm2"] != ""]
            spec.append({
                "scene_uid": uid, "animal": bgrows[0]["animal"],
                "marker": bgrows[0]["marker"],
                "n_discs": len(bgrows), "bg_nuclei": tot_n,
                "bg_area_mm2": round(tot_a, 6),
                "bg_nuclei_per_mm2": round(tot_n / tot_a, 1) if tot_a else "",
                "bg_false_positives": tot_p,
                "false_positive_rate": round(tot_p / tot_n, 4) if tot_n else "",
                "bg_level": round(bgstat[uid][0], 1),
                "bg_spread": round(bgstat[uid][1], 1),
                "positivity_cut": round(cut, 1),
                # Disagreement between discs on one section is heterogeneous
                # autofluorescence, and is worth seeing before it is averaged.
                "disc_density_spread": (round(max(dens) - min(dens), 1)
                                        if len(dens) > 1 else 0),
            })

    real = [r for r in rows if r["roi_kind"] == "roi"]
    for path, data in ((MEAS_CSV, rows), (SPEC_CSV, spec)):
        if not data:
            continue
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)

    print("=" * 72)
    print(f"{len(real)} ROIs and {len(rows) - len(real)} background discs -> {MEAS_CSV}")
    print(f"{len(spec)} sections -> {SPEC_CSV}")
    print(f"  sections with a cut : {len(cuts)} of {len({r['scene_uid'] for r in nuc})}"
          f"   (needs >=5 background nuclei)")
    if AB_ON:
        print(f"  Abercrombie         : T={T_UM} um, measured h "
              f"{min(hs.values()):.1f}-{max(hs.values()):.1f} um -> factor "
              f"{T_UM/(T_UM+max(hs.values())):.3f}-{T_UM/(T_UM+min(hs.values())):.3f}")
    if spec:
        fp = [s["false_positive_rate"] for s in spec if s["false_positive_rate"] != ""]
        print(f"  false-positive rate : median {st.median(fp)*100:.1f}%, "
              f"range {min(fp)*100:.1f}-{max(fp)*100:.1f}%   "
              f"(measured on {sum(s['bg_nuclei'] for s in spec)} background nuclei)")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
