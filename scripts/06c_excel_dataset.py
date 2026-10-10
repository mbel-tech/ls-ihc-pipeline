"""Stage 6c - the analysis table as a spreadsheet, buildable mid-run.

Reads `results/roi_measurements.csv` from **06a**, which owns every per-ROI
number - the positivity cut, the Abercrombie factor, the disc area. This stage
groups and formats; it does not re-derive. It used to, and the two
implementations had silently drifted: 06a computes Abercrombie's h per
(marker, region) as config declares, the copy here computed it per
(animal, region), and nothing compared them.

Still buildable at ANY point while `05c_detect_rois.py` is working - run 06a
first, which is seconds, and this reports how much of the job that is.
`06e_refresh_loop.py` does exactly that on each cycle. Combined with 05c's
balanced ordering - which alternates treatment and control section by section -
a partial run is a real comparison rather than a head start for one arm.

The requested sheet is `by_roi`: one row per ROI per sample.

    n_nuclei                 nuclei counted in that region for that animal
    ROI                      the atlas region, e.g. Dm, Dl, Vv
    sample                   animal ID
    treatment                control / exercise
    total_tissue_area_mm2    summed area of the discs those nuclei came from

**`cells_per_mm2` is corrected, unless the last column says it is not.**
`abercrombie_withheld_reason` is blank wherever the Abercrombie correction was
applied, and carries 06a's reason wherever it was not - objects that are not
nucleus-shaped, for which N = n * T/(T+h) does not hold, or a study that
switched the correction off. The factor is 1.0 in those rows, so
`cells_per_mm2` equals `profiles_per_mm2` there and the two columns can be read
side by side. The reason is CARRIED from 06a, not re-derived: a factor of 1.0
on its own cannot be told apart from a correction that came out at 1.0.

**Positivity sits alongside the count, not instead of it.** `n_positive`,
`frac_positive` and `positive_cells_per_mm2` come from 06a's per-section cut.
They are blank where a section carried fewer than 5 background nuclei and no cut
could be formed - blank rather than 0, which would read as "looked and found
none". With no no-primary control and no tERK normaliser an absolute positivity
rate is not defensible; the comparison between arms at matched levels is, and
`detector_specificity.csv` carries the false-positive rate to quote with it.

**What "total tissue area" means here.** It is the area of the ROI discs
themselves, mapped onto the slide and summed - not the whole section, and not a
mask-derived tissue fraction. The operator places discs inside tissue, so the
two are the same thing up to the odd disc clipping an edge; saying which one is
meant matters more than the difference. Density is n_nuclei / that area, and the
column is there so it can be recomputed rather than trusted.

A disc is a CIRCLE on the curator's 256 px frame and an ELLIPSE on the slide -
the reformat resizes a hand-drawn scan box to a square grid - so the area comes
from the two semi-axes 05a measured, never from pi*r^2 in curator pixels. The
axis ratio runs 0.66 to 1.42 across these sections.

Three more sheets, because the first one cannot be checked from inside itself:
`by_disc` keeps every individual ROI placement, `by_section` shows how much of
each animal is measured so far, and `coverage` says what is still missing.

Run:  python 06c_excel_dataset.py
      python 06c_excel_dataset.py --out somewhere.xlsx
"""

import sys
import argparse
import collections
import csv
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_g5", os.path.join(_HERE, "05a_roi_geometry.py"))
G5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G5)

_spec6b = importlib.util.spec_from_file_location(
    "_g6b", os.path.join(_HERE, "06b_join_sampling.py"))
G6B = importlib.util.module_from_spec(_spec6b)
_spec6b.loader.exec_module(G6B)

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
import ls_naming as NM  # noqa: E402
OUT_ROOT = G5.OUT_ROOT
RESULTS = os.path.join(OUT_ROOT, "results")
NUCLEI_CSV = os.path.join(RESULTS, "roi_nuclei.csv")
MEAS_CSV = os.path.join(RESULTS, "roi_measurements.csv")
XLSX = os.path.join(RESULTS, "roi_dataset.xlsx")

def animal_environment():
    """animal -> sea / brackish, read straight from the sampling workbook.

    Reuses `read_sheet()` from 06b rather than requiring 06a and 06b to have run
    first: this stage is meant to be runnable while detection is still going,
    and making it depend on the end of the chain would take that away.

    NOTE that environment is perfectly confounded with timepoint in this design
    - brackish IS timepoint 1 and sea IS timepoint 2 - so anything reported by
    environment is equally a statement about time.
    """
    try:
        col, sheet = G6B.read_table(G6B.DEFAULT_XLSX)
    except Exception as exc:                                   # noqa: BLE001
        print(f"  (no environment: {exc})")
        return {}
    out = {}
    for r in sheet:
        fid = (r.get(col["fish"], "") or "").strip()
        if fid.isdigit():
            out["LS" + fid] = (r.get(col["environment"], "") or "").strip()
    return out


def write_workbook(path, sheets):
    """Write (name, rows) pairs as a workbook, one sheet each.

    Shared with 06d so the two datasets are formatted by the same code - bold
    header, frozen first row, columns sized to their contents. A second copy of
    this would be a second thing to keep in step for no benefit.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    for i, (name, data) in enumerate(sheets):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = name
        if not data:
            continue
        cols = list(data[0].keys())
        ws.append(cols)
        for c in range(1, len(cols) + 1):
            ws.cell(row=1, column=c).font = Font(bold=True)
        for row in data:
            ws.append([row[c] for c in cols])
        ws.freeze_panes = "A2"
        for c, col in enumerate(cols, 1):
            width = max(len(str(col)), *(len(str(r[col])) for r in data)) + 2
            ws.column_dimensions[get_column_letter(c)].width = min(width, 30)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with IO.atomic_save(path) as tmp:
        wb.save(tmp)


def resolve_groups(config_groups, meta_csv=None):
    """Treatment per animal. 06b is the unblinding step and validates the
    workbook; config.groups.by_animal is hand-typed. Where both exist they
    must agree, and the metadata fills in animals the config does not list."""
    meta_csv = meta_csv or G6B.META_CSV
    if not os.path.exists(meta_csv):
        return dict(config_groups)
    meta = {r["animal"]: r["treatment"] for r in G5.load_csv(meta_csv) if r.get("treatment")}
    clash = {a: (config_groups[a], meta[a]) for a in config_groups
             if a in meta and config_groups[a] != meta[a]}
    if clash:
        raise SystemExit(
            "config.groups.by_animal disagrees with results/animal_metadata.csv: "
            + ", ".join(f"{a}: config={c} workbook={m}" for a, (c, m) in sorted(clash.items()))
            + "\n  06b_join_sampling.py is the unblinding - fix config.json or rerun 06b.")
    return {**meta, **config_groups}

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=XLSX)
    # argv is passed explicitly by 06e_refresh_loop, whose own flags would
    # otherwise reach this parser and abort the cycle.
    args = ap.parse_args(argv)

    if not os.path.exists(NUCLEI_CSV):
        print(f"no {NUCLEI_CSV} yet - 05c_detect_rois.py has not written anything")
        return 1
    if not os.path.exists(MEAS_CSV):
        print(f"no {MEAS_CSV} - run 06a_roi_dataset.py first.\n"
              f"  This stage no longer re-derives the per-ROI numbers; 06a owns "
              f"them, so a stale or absent 06a is a missing input, not a "
              f"fallback to recomputing.")
        return 1

    meas = G5.load_csv(MEAS_CSV)
    boxes = G5.all_boxes()          # both markers; see 05a.all_boxes
    groups = resolve_groups((CONFIG.get("groups") or {}).get("by_animal") or {})
    envs = animal_environment()

    # 06a emits a row only for sections that are in roi_nuclei.csv, so the set
    # of measured sections comes from it directly. Checked against the nuclei
    # file rather than assumed: a 06a that predates the current detection run
    # would otherwise silently under-report coverage, which is the one thing
    # this sheet exists to state.
    measured = {r["scene_uid"] for r in meas}
    nuc_secs = set()
    with open(NUCLEI_CSV, encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for row in rd:
            if row:
                nuc_secs.add(row[0])
    # A SUBSET IS NORMAL MID-RUN, AND MUST NOT FAIL.
    #
    # This stage is meant to be runnable while 05c is still appending. 06a runs
    # first in each 06e cycle and takes seconds to minutes, and 05c keeps
    # writing throughout - so any section that finishes in between leaves 06a
    # legitimately one or more sections behind. Requiring exact equality turned
    # that ordinary race into a hard failure, and 06e escalates a failed refresh
    # into ending the loop, so the check would have killed the very scenario it
    # was written to protect. It says so and carries on instead.
    #
    # The genuine error is the other direction: 06a referencing sections the
    # nuclei file does not contain means the two files are not from the same
    # data at all, and every count would be joined against the wrong geometry.
    orphaned = measured - nuc_secs
    if orphaned:
        print(f"  INCONSISTENT: roi_measurements.csv has {len(orphaned)} "
              f"sections that are not in roi_nuclei.csv "
              f"(e.g. {sorted(orphaned)[0]}). The two files are not from the "
              f"same run. Re-run 06a_roi_dataset.py.")
        return 1
    behind = nuc_secs - measured
    if behind:
        print(f"  06a is {len(behind)} section(s) behind roi_nuclei.csv - "
              f"reporting the {len(measured)} it covers. Normal while "
              f"05c_detect_rois.py is still running; re-run 06a for the rest.")

    planned = {b["scene_uid"] for b in boxes}
    n_nuclei_total = sum(int(r["n_nuclei"]) for r in meas)
    print(f"{len(measured)} of {len(planned)} sections measured "
          f"({100*len(measured)/len(planned):.0f}%), {n_nuclei_total} nuclei")

    # Per-ROI numbers come from 06a, which owns them. This stage groups and
    # formats; it does not re-derive.
    #
    # The duplicate implementation that used to live here computed Abercrombie's
    # h per (animal, region), while 06a computes it per (marker, region) as
    # config.detection.abercrombie._h_source declares. The two therefore
    # disagreed by up to 9.7% on a per-ROI density, and nothing compared them.
    # Worse, measured nuclear diameter is not the same in both arms - Vl differs
    # by 1.50 um - so a per-animal h put a group-varying correction into every
    # density, which is exactly what config._effect_on_the_comparison warns
    # against. See LOGS.md.
    #
    # 06a has already dropped artifact nuclei and applied the censoring rule
    # (04j: a censored nucleus is positive by construction and excluded from
    # intensity statistics), so neither is repeated here.
    roi_rows = [r for r in meas if r["roi_kind"] == "roi"]

    def num(v, cast=float):
        return cast(v) if v not in ("", None) else None

    n_by = collections.Counter()               # (animal, region) -> nuclei
    p_by = collections.Counter()               # (animal, region) -> positives
    a_by = collections.Counter()               # (animal, region) -> area mm2
    d_by = collections.Counter()               # key -> discs
    sec_by = collections.defaultdict(set)      # key -> scene_uids
    h_by, ab_by, why_by = {}, {}, {}
    pos_known = collections.Counter()          # discs whose section had a cut

    # THE MARKER IS PART OF THE KEY. Without it a row is AF568 + AF488 summed:
    # different antibodies, different acquisitions, one n_nuclei. It was
    # invisible while only pERK had been measured and 06a read a single marker's
    # boxes, and it became certain the moment 06a started reading both. It also
    # made the h note below false, because two markers under one key carry two
    # different (h, factor) pairs and "the last one" would win arbitrarily.
    for r in roi_rows:
        key = (r["animal"], r["marker"], r["region"])
        n_by[key] += int(r["n_nuclei"])
        a_by[key] += float(r["roi_area_mm2"])
        d_by[key] += 1
        sec_by[key].add(r["scene_uid"])
        npos = num(r["n_positive"], int)
        if npos is not None:
            p_by[key] += npos
            pos_known[key] += 1
        # h and the factor are properties of (marker, region) in 06a, and the
        # marker is in the key here, so every row under a key really does carry
        # the same pair - taking the last is taking the only one.
        h_by[key] = num(r["mean_nucleus_diam_um"])
        ab_by[key] = num(r["abercrombie_factor"]) or 1.0
        # CARRIED, NOT RE-DERIVED. Whether the correction applies is 06a's
        # decision - it is the stage that can see `nucleus_shaped` on the
        # nuclei - and a factor of 1.0 alone cannot be told apart from a
        # correction that happened to come out at 1.0. Same key, same "the last
        # one is the only one" argument as h and the factor above.
        #
        # .get, because a roi_measurements.csv written before 2026-09-08 has no
        # such column. Blank then means what it means everywhere else here: the
        # correction was applied.
        why_by[key] = r.get("abercrombie_withheld_reason", "")

    by_roi = []
    for key in sorted(a_by):
        an, mk, rg = key
        n, area = n_by[key], a_by[key]
        ab = ab_by.get(key) or 1.0
        h = h_by.get(key)
        # A disc whose section had no positivity cut contributes no positives.
        # Reporting 0 for it would read as "looked and found none", so the cell
        # goes blank unless every disc behind it had a cut.
        full = pos_known[key] == d_by[key]
        npos = p_by[key] if full else ""
        by_roi.append({
            "n_nuclei": n,
            "ROI": rg,
            "sample": an,
            "marker": mk,
            "treatment": groups.get(an, ""),
            "environment": envs.get(an, ""),
            "total_tissue_area_mm2": round(area, 6),
            # Positivity sits ALONGSIDE the count, never replacing it. With no
            # no-primary control and no tERK normaliser, an absolute positivity
            # rate is not a claim these data support; the comparison between
            # arms at matched levels is. detector_specificity.csv carries the
            # false-positive rate that has to be quoted with it.
            "n_positive": npos,
            "frac_positive": round(npos / n, 4) if (full and n) else "",
            "positive_cells_per_mm2": (round(npos * ab / area, 1)
                                       if (full and area) else ""),
            # Everything past this point is derived from the columns above and
            # is here so the sheet can be checked without recomputing it.
            "n_discs": d_by[key],
            "n_sections": len(sec_by.get(key, ())),
            "profiles_per_mm2": round(n / area, 1) if area else "",
            "mean_nucleus_diam_um": round(h, 2) if h else "",
            "abercrombie_factor": round(ab, 4),
            "cells_per_mm2": round(n * ab / area, 1) if area else "",
            # Beside the corrected density, because that is the number it is
            # about. Blank means the correction was applied; anything else is
            # 06a saying cells_per_mm2 is the profile count uncorrected, and
            # why. A withheld correction that only ever appeared in a CSV
            # nobody opens is not reported.
            "abercrombie_withheld_reason": why_by.get(key, ""),
        })

    # by_disc keeps every individual placement so by_roi can be checked by
    # pivoting it. The two axis columns are the only thing 06a does not carry,
    # so they are joined back from roi_boxes.csv on (scene_uid, roi_index) -
    # rebuilding the index exactly the way 06a numbered the discs.
    #
    # PER MARKER, exactly as 06a numbers them: 05c's roi_index counts within
    # one marker's own box file, and under `multiplex` all_boxes() returns
    # both markers' boxes for the same uid. Counting them together would put
    # the second marker's semi-axes on the first marker's discs. Under
    # `paired` a uid belongs to one marker, so this is the old counter.
    axes, seen = {}, collections.Counter()
    for b in boxes:
        key = (b["scene_uid"], b["marker"])
        seen[key] += 1
        axes[(b["scene_uid"], b["marker"], seen[key])] = b

    by_disc = []
    for r in meas:
        b = axes.get((r["scene_uid"], r["marker"], int(r["roi_index"])), {})
        by_disc.append({
            "sample": r["animal"], "treatment": groups.get(r["animal"], ""),
            "environment": envs.get(r["animal"], ""),
            "scene_uid": r["scene_uid"], "roi_index": int(r["roi_index"]),
            "roi_kind": r["roi_kind"], "ROI": r["region"], "seed_n": r["seed_n"],
            "marker": r["marker"],
            "n_nuclei": int(r["n_nuclei"]),
            # int, not the raw CSV string. This sheet exists so by_roi can be
            # checked by pivoting it, and a text column will not pivot - the
            # two columns either side of this one are cast for the same reason.
            # Blank stays blank: no cut means no number, not zero.
            "n_positive": num(r["n_positive"], int) if r["n_positive"] != "" else "",
            "tissue_area_mm2": float(r["roi_area_mm2"]),
            "axis_a_um": b.get("axis_a_um", ""),
            "axis_b_um": b.get("axis_b_um", ""),
        })

    per_sec = collections.defaultdict(lambda: [0, 0, set(), 0, 0])
    cut_by, animal_by, marker_by = {}, {}, {}
    for r in meas:
        s = per_sec[r["scene_uid"]]
        cut_by[r["scene_uid"]] = r["section_positivity_cut"]
        animal_by[r["scene_uid"]] = r["animal"]
        marker_by[r["scene_uid"]] = r["marker"]
        if r["roi_kind"] == "roi":
            s[0] += int(r["n_nuclei"])
            s[2].add(r["region"])
            s[3] += 1
        else:
            s[1] += int(r["n_nuclei"])
            s[4] += 1

    by_section = []
    for uid in sorted(measured):
        n_roi, n_bg, regions, d_roi, d_bg = per_sec[uid]
        an = animal_by.get(uid, NM.subject_of(uid))
        by_section.append({
            "sample": an, "treatment": groups.get(an, ""),
            "environment": envs.get(an, ""), "scene_uid": uid,
            "marker": marker_by.get(uid, ""),
            "n_roi_nuclei": n_roi, "n_background_nuclei": n_bg,
            "n_roi_discs": d_roi,
            "n_background_discs": d_bg,
            # Blank means the section had fewer than 5 background nuclei, so no
            # cut could be formed and its positivity columns are empty upstream.
            "positivity_cut": cut_by.get(uid, ""),
            "regions": ", ".join(sorted(regions)),
        })

    # Coverage is per (animal, MARKER): pooling the two would report one
    # percentage for a pERK pass that is finished and a PCNA one that has not
    # started, which is the one question this sheet exists to answer.
    coverage = []
    for an, mk in sorted({(b["animal"], b["marker"]) for b in boxes},
                         key=lambda t: (NM.natural_key(t[0]), t[1])):
        pl = {b["scene_uid"] for b in boxes
              if b["animal"] == an and b["marker"] == mk}
        coverage.append({
            "sample": an, "marker": mk, "treatment": groups.get(an, ""),
            "environment": envs.get(an, ""),
            "sections_measured": len(pl & measured),
            "sections_planned": len(pl),
            "percent": round(100 * len(pl & measured) / len(pl), 1) if pl else "",
        })

    write_workbook(args.out, (("by_roi", by_roi), ("by_disc", by_disc),
                              ("by_section", by_section), ("coverage", coverage)))

    print("=" * 72)
    print(f"{len(by_roi)} rows (one per ROI per sample) -> {args.out}")
    print(f"  sheets: by_roi, by_disc ({len(by_disc)}), "
          f"by_section ({len(by_section)}), coverage")
    tr = collections.Counter(r["treatment"] or "(none)" for r in by_section)
    print(f"  sections measured by arm: {dict(tr)}")
    print()
    # Matched to the coverage sheet, which is per (sample, MARKER). Summing
    # by sample alone printed each animal's pooled totals twice, once against
    # each marker's section count - two rows that disagreed with themselves.
    print(f"  {'sample':8} {'marker':7} {'treatment':10} {'sections':>9} "
          f"{'ROIs':>6} {'nuclei':>8}")
    for c in coverage:
        same = [r for r in by_roi
                if r["sample"] == c["sample"] and r["marker"] == c["marker"]]
        n = sum(r["n_nuclei"] for r in same)
        d = sum(r["n_discs"] for r in same)
        print(f"  {c['sample']:8} {c['marker']:7} {c['treatment'] or '?':10} "
              f"{c['sections_measured']:>4}/{c['sections_planned']:<4} {d:>6} {n:>8}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
