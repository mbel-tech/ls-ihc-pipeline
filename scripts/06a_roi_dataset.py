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

import sys
import collections
import importlib.util
import os
import statistics as st

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_g5", os.path.join(_HERE, "05a_roi_geometry.py"))
G5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G5)

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
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
    """The area of the ROI on the slide, in um^2, as 05a measured it.

    `area_um2` is the answer for either shape - pi*a*b for a disc, the shoelace
    over the mapped vertices for a drawn region - and is preferred wherever it
    is present. Falling back to the two semi-axes keeps a roi_boxes file written
    before 05a computed the area readable; a POLYGON has no semi-axes and leaves
    those columns blank, so the fallback is for old disc files only.

    Never pi*r^2 in canonical pixels either way: the map is not a similarity."""
    a = b.get("area_um2", "")
    if a not in ("", None):
        return float(a)
    return np.pi * float(b["axis_a_um"]) * float(b["axis_b_um"])


def split_by_marker(boxes):
    """One section's boxes, split per marker, each group keeping its own order.

    THE JOIN KEY IS (scene_uid, marker, roi_index), NOT (scene_uid, roi_index).
    05c_detect_rois numbers `roi_index` within THAT MARKER'S OWN box file,
    from 1, and 05a.all_boxes() concatenates every marker's file. Under
    `paired` the uids are disjoint - all_boxes() proves it - so a section has
    exactly one group here and this returns the same list in the same order:
    the join is byte-for-byte what it was.

    Under `multiplex` the markers ARE one scan of one section, so all_boxes()
    hands over both markers' boxes for the SAME uid and they interleave. A
    section with 2 discs per marker gets positions 1..4, while `roi_index` only
    ever runs 1..2 - so without this split the second marker's discs would be
    unreachable and its nuclei would be pooled onto the first marker's. That
    is the silent, plausible, wrong number the `paired` uid guard exists to
    prevent, and relaxing that guard for `multiplex` moved the problem here.
    """
    out = {}
    for b in boxes:
        out.setdefault(b.get("marker", ""), []).append(b)
    return out


def check_join(nuc, box_by):
    """The nucleus-to-disc join is POSITIONAL. Check it before trusting it.

    A nucleus names its disc by `roi_index`, the row position of that disc in
    roi_boxes_<marker>.csv for its section, and the emit loop in main()
    enumerates the same list in the same order. 05a rewrites that file from
    the newest curator export, so a disc inserted or removed on a section after
    05c ran shifts every later index on it: the background disc's nuclei would
    be summed under an ROI, with a count and a density that look fine. The
    nuclei rows also carry roi_kind and region, so for every (section, marker,
    index) the box at that position must agree on both - a mismatch means the
    boxes changed under the measurements.

    The MARKER is part of that key, and has to be: see split_by_marker. A
    nucleus whose marker has no boxes on its section is fatal for the same
    reason a shifted index is - the emit loop would otherwise report zero
    nuclei for that marker while its nuclei were counted under another's disc.

    Sections present in the nuclei but absent from every box file are the
    other case: a stale row, or a box file regenerated without them. Those are
    skipped by the emit loop already; they are returned and reported, not
    fatal.
    """
    seen, bad, orphan = set(), {}, set()
    split = {u: split_by_marker(bs) for u, bs in box_by.items()}
    for r in nuc:
        uid = r["scene_uid"]
        mk = r.get("marker", "")
        key = (uid, mk, r["roi_index"])
        if key in seen:
            continue
        seen.add(key)
        groups = split.get(uid)
        if not groups:
            orphan.add(uid)
            continue
        boxes = groups.get(mk)
        if not boxes:
            bad.setdefault(uid, f"nuclei for marker {mk!r} but this section's "
                                f"boxes are {sorted(groups)}")
            continue
        i = int(r["roi_index"])
        if not 1 <= i <= len(boxes):
            bad.setdefault(uid, f"roi_index {i} but only {len(boxes)} boxes"
                                f" for {mk}")
            continue
        b = boxes[i - 1]
        if b["roi_kind"] != r["roi_kind"] or b["region"] != r["region"]:
            bad.setdefault(uid, f"roi_index {i}: nuclei say {r['roi_kind']}/"
                                f"{r['region']}, box is {b['roi_kind']}/{b['region']}")
    if orphan:
        print(f"  !! {len(orphan)} sections in roi_nuclei.csv have no boxes in any "
              f"roi_boxes_<marker>.csv and are skipped: {sorted(orphan)[:8]}")
    if bad:
        lines = "\n".join(f"    {u}  {why}" for u, why in sorted(bad.items()))
        raise SystemExit(
            f"!! roi_boxes disagree with roi_nuclei.csv on {len(bad)} sections:\n"
            f"{lines}\n"
            f"  The boxes were regenerated after detection, so the positional "
            f"join is shifted. Either restore the roi_boxes file the nuclei "
            f"were measured against, or re-run 05c_detect_rois.py --force for "
            f"those sections.")
    return orphan


def main(argv=None):
    # argv is accepted and ignored: this stage has no flags, and taking it
    # lets 06e call every stage the same way instead of branching on a label.
    del argv
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
    check_join(nuc, box_by)

    for r in nuc:
        r["_v"] = float(r[STAT])
        r["_cen"] = r["censored"] == "1"
        r["_art"] = r["artifact"] == "1"
        # .get, because a roi_nuclei.csv written before 2026-09-02 has no such
        # column. Absent reads as False, which reproduces the old behaviour
        # exactly rather than silently reinterpreting an old file - run
        # 06g_flag_off_tissue.py to backfill it.
        r["_off"] = r.get("off_tissue") == "1"
        r["_d"] = float(r["equiv_diam_um"])

    # Artifact pixels are not tissue and leave the analysis entirely. Censored
    # ones are RIGHT-censored - value lost, but at least the ceiling - so they
    # stay in the count and are excluded only from the intensity statistics.
    # Reversing those two would bias positive rates down in exactly the
    # brightest-staining animals (LOGS.md 2026-08-12).
    #
    # `off_tissue` joins the artifact side, for the same reason and more
    # bluntly: the nucleus is not on the section at all. 05c accepted a nucleus
    # on disc membership alone, so a disc overhanging the silhouette - or, in
    # one case, sitting 2.6 mm off the scanned scene entirely - contributed
    # objects found on glass. Those are worst in a BACKGROUND disc, where they
    # enter median + 3*1.4826*MAD and drag the positivity cut down, making a
    # section look more positive than it is.
    n_art = sum(1 for r in nuc if r["_art"])
    n_off = sum(1 for r in nuc if r["_off"] and not r["_art"])
    nuc = [r for r in nuc if not r["_art"] and not r["_off"]]
    print(f"  dropped {n_art} on an artifact, {n_off} off the tissue "
          f"-> {len(nuc)} nuclei quantified")

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
    # (uid, marker, roi_index) -> nuclei
    by_idx = collections.defaultdict(list)
    diam_by = collections.defaultdict(list)    # (marker, region) -> diameters
    uids, d_all = set(), []
    for r in nuc:
        uid = r["scene_uid"]
        uids.add(uid)
        d_all.append(r["_d"])
        # roi_index is what ties a nucleus to the disc it was found in - 05c
        # numbers the discs in the order roi_boxes_<marker>.csv lists them for
        # a section, WITHIN THAT MARKER, and the emit loop below enumerates the
        # same per-marker list in the same order. The marker is in the key
        # because it is in 05c's numbering; see split_by_marker.
        by_idx[(uid, r["marker"], int(r["roi_index"]))].append(r)
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

    # THE FALLBACK IS PER MARKER TOO, and it is not an edge case: background
    # discs carry region "__background__", which is never a key in diam_by, so
    # EVERY background row takes it - 586 of 2,069 today. A single pooled mean
    # would let PCNA, at roughly six times the pERK volume, set the Abercrombie
    # factor on pERK's background rows. The number would change, driven entirely
    # by the other antibody, and nothing would error.
    h_by_marker = {}
    for mk in {r["marker"] for r in nuc}:
        d = [r["_d"] for r in nuc if r["marker"] == mk]
        if d:
            h_by_marker[mk] = st.mean(d)
    h_all = st.mean(d_all) if d_all else 0.0

    rows, spec = [], []
    for uid in sorted(uids):
        cut = cuts.get(uid)
        # PER MARKER, so `i` restarts at 1 for each one - which is how 05c
        # numbered them. Under `paired` there is exactly one group per section
        # and this is the old single loop unchanged.
        for mk, mboxes in split_by_marker(box_by.get(uid, [])).items():
            for i, b in enumerate(mboxes, 1):
                here = by_idx.get((uid, mk, i), [])
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
                h = hs.get((b["marker"], b["region"]),
                           h_by_marker.get(b["marker"], h_all))
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
            # An EMPTY result must not leave the previous run's file standing.
            # detector_specificity.csv is read by plot_roi_figures.R to caption
            # every positivity figure with a false-positive rate; a stale one
            # would put a number from an earlier dataset on a new figure and
            # look entirely current. Skipping the write was the quiet option.
            if os.path.exists(path):
                os.remove(path)
                print(f"  nothing to write - removed the previous {os.path.basename(path)}")
            continue
        IO.atomic_write_csv(path, data, list(data[0].keys()))

    print("=" * 72)
    print(f"{len(real)} ROIs and {len(rows) - len(real)} background discs -> {MEAS_CSV}")
    print(f"{len(spec)} sections -> {SPEC_CSV}")
    # ONE BLOCK PER MARKER. This stage runs once for both, and all three of
    # these numbers are per marker. An h RANGE spanning two markers is not a
    # range of anything - pERK 9.4 and PCNA 6.0 would print as "6.0-9.4" and
    # destroy the check that a large deviation means the h grouping changed -
    # and the false-positive rate is the number the operator is told to stop and
    # read before building any figure on the cut. It is filtered on the figure;
    # pooling it in the console would put the two in disagreement.
    markers = sorted({r["marker"] for r in rows}) or [""]
    for mk in markers:
        m_uids = {r["scene_uid"] for r in nuc if r["marker"] == mk}
        m_cuts = [u for u in cuts if u in m_uids]
        m_hs = {k: v for k, v in hs.items() if k[0] == mk}
        m_spec = [s for s in spec if s["marker"] == mk]
        head = f"  [{mk}] " if len(markers) > 1 else "  "
        print(f"{head}sections with a cut : {len(m_cuts)} of {len(m_uids)}"
              f"   (needs >=5 background nuclei)")
        if AB_ON and m_hs:
            lo, hi = min(m_hs.values()), max(m_hs.values())
            print(f"{head}Abercrombie         : T={T_UM} um, measured h "
                  f"{lo:.1f}-{hi:.1f} um -> factor "
                  f"{T_UM/(T_UM+hi):.3f}-{T_UM/(T_UM+lo):.3f}")
        fp = [s["false_positive_rate"] for s in m_spec
              if s["false_positive_rate"] != ""]
        if fp:
            print(f"{head}false-positive rate : median {st.median(fp)*100:.1f}%, "
                  f"range {min(fp)*100:.1f}-{max(fp)*100:.1f}%   "
                  f"(measured on {sum(s['bg_nuclei'] for s in m_spec)} "
                  f"background nuclei)")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
