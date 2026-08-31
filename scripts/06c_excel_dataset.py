"""Stage 6c - the analysis table as a spreadsheet, buildable mid-run.

Written to be run at ANY point while `05c_detect_rois.py` is still working. It
reads whatever nuclei are on disk, reports how much of the job that is, and
writes a workbook from it. Combined with 05c's balanced ordering - which
alternates treatment and control section by section - a partial run is a real
comparison rather than a head start for one arm.

The requested sheet is `by_roi`: one row per ROI per sample.

    n_nuclei                 nuclei counted in that region for that animal
    ROI                      the atlas region, e.g. Dm, Dl, Vv
    sample                   animal ID
    treatment                control / exercise
    total_tissue_area_mm2    summed area of the discs those nuclei came from

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

import argparse
import collections
import csv
import importlib.util
import json
import os
import statistics as st

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_g5", os.path.join(_HERE, "05a_roi_geometry.py"))
G5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G5)

_spec6b = importlib.util.spec_from_file_location(
    "_g6b", os.path.join(_HERE, "06b_join_sampling.py"))
G6B = importlib.util.module_from_spec(_spec6b)
_spec6b.loader.exec_module(G6B)

CONFIG = G5.CONFIG
OUT_ROOT = G5.OUT_ROOT
RESULTS = os.path.join(OUT_ROOT, "results")
NUCLEI_CSV = os.path.join(RESULTS, "roi_nuclei.csv")
XLSX = os.path.join(RESULTS, "roi_dataset.xlsx")

T_UM = CONFIG["section_thickness_um"]
AB_ON = bool(CONFIG["detection"].get("abercrombie", {}).get("enabled"))


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
        sheet = G6B.read_sheet(G6B.DEFAULT_XLSX)[1:]
    except Exception as exc:                                   # noqa: BLE001
        print(f"  (no environment: {exc})")
        return {}
    out = {}
    for r in sheet:
        fid = (r.get(G6B.COL["fish"], "") or "").strip()
        if fid.isdigit():
            out["LS" + fid] = (r.get(G6B.COL["environment"], "") or "").strip()
    return out


def disc_area_mm2(b):
    """The ellipse the disc became on the slide, in mm^2.

    Rounded HERE, once, and both sheets sum the rounded value - so pivoting
    `by_disc` reproduces `by_roi` exactly. Summing full precision and rounding
    the total instead differs in the seventh decimal after seventy-odd discs,
    which is meaningless as an area and very annoying as a discrepancy.
    """
    import math
    return round(math.pi * float(b["axis_a_um"]) * float(b["axis_b_um"]) / 1e6, 6)


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
    wb.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=XLSX)
    args = ap.parse_args()

    if not os.path.exists(NUCLEI_CSV):
        print(f"no {NUCLEI_CSV} yet - 05c_detect_rois.py has not written anything")
        return 1

    nuc = G5.load_csv(NUCLEI_CSV)
    boxes = G5.load_csv(G5.BOX_CSV)
    groups = (CONFIG.get("groups") or {}).get("by_animal") or {}
    envs = animal_environment()

    measured = {r["scene_uid"] for r in nuc}
    planned = {b["scene_uid"] for b in boxes}
    print(f"{len(measured)} of {len(planned)} sections measured "
          f"({100*len(measured)/len(planned):.0f}%), {len(nuc)} nuclei")

    # Artifact pixels are not tissue; those nuclei leave the analysis. Censored
    # ones stay - a pixel at the 16-bit ceiling is lost signal, not absent
    # tissue - and are excluded only from intensity statistics, which this
    # sheet does not report.
    nuc = [r for r in nuc if r["artifact"] != "1"]

    # Only discs on sections that have actually been measured contribute an
    # area. Counting the area of a disc whose nuclei have not been found yet
    # would divide a partial count by a complete area and understate every
    # density in the file.
    live = [b for b in boxes if b["scene_uid"] in measured]

    # ONE PASS over the nuclei, building every index at once.
    #
    # This used to re-scan the whole file for each output row: n_sections
    # filtered all of it per (animal, region), h did the same again, and
    # by_section did it once per section. At 883,078 nuclei that is tens of
    # millions of comparisons and the rebuild ran long enough to be killed
    # part-written - which is how a 7 KB xlsx that openpyxl could not reopen got
    # there. It only gets worse: PCNA is roughly six times this.
    n_by = collections.Counter()
    sec_by = collections.defaultdict(set)      # (animal, region) -> scene_uids
    diam_by = collections.defaultdict(list)    # (animal, region) -> diameters
    per_disc_n = collections.Counter()         # (scene_uid, roi_index) -> nuclei
    per_sec = collections.defaultdict(lambda: [0, 0, set()])  # uid -> roi, bg, regions
    for r in nuc:
        uid = r["scene_uid"]
        per_disc_n[(uid, int(r["roi_index"]))] += 1
        slot = per_sec[uid]
        if r["roi_kind"] == "roi":
            key = (r["animal"], r["region"])
            n_by[key] += 1
            sec_by[key].add(uid)
            diam_by[key].append(float(r["equiv_diam_um"]))
            slot[0] += 1
            slot[2].add(r["region"])
        else:
            slot[1] += 1

    a_by, d_by = collections.Counter(), collections.Counter()
    disc_by_sec = collections.defaultdict(list)
    for b in live:
        disc_by_sec[b["scene_uid"]].append(b)
        if b["roi_kind"] != "roi":
            continue
        a_by[(b["animal"], b["region"])] += disc_area_mm2(b)
        d_by[(b["animal"], b["region"])] += 1

    # h for Abercrombie, measured per region from the segmentation rather than
    # assumed. See config.detection.abercrombie.
    h_by = {k: st.mean(v) for k, v in diam_by.items() if v}

    by_roi = []
    for key in sorted(a_by, key=lambda k: (k[0], k[1])):
        an, rg = key
        n = n_by.get(key, 0)
        area = a_by[key]
        h = h_by.get(key)
        ab = (T_UM / (T_UM + h)) if (AB_ON and h) else 1.0
        by_roi.append({
            "n_nuclei": n,
            "ROI": rg,
            "sample": an,
            "treatment": groups.get(an, ""),
            "environment": envs.get(an, ""),
            "total_tissue_area_mm2": round(area, 6),   # already a sum of rounded discs
            # Everything past this point is derived from the five columns above
            # and is here so the sheet can be checked without recomputing it.
            "n_discs": d_by[key],
            "n_sections": len(sec_by.get(key, ())),
            "profiles_per_mm2": round(n / area, 1) if area else "",
            "mean_nucleus_diam_um": round(h, 2) if h else "",
            "abercrombie_factor": round(ab, 4),
            "cells_per_mm2": round(n * ab / area, 1) if area else "",
        })

    by_disc = []
    seen = collections.Counter()
    for b in live:
        seen[b["scene_uid"]] += 1
        i = seen[b["scene_uid"]]
        by_disc.append({
            "sample": b["animal"], "treatment": groups.get(b["animal"], ""),
            "environment": envs.get(b["animal"], ""),
            "scene_uid": b["scene_uid"], "roi_index": i,
            "roi_kind": b["roi_kind"], "ROI": b["region"], "seed_n": b["seed_n"],
            "n_nuclei": per_disc_n.get((b["scene_uid"], i), 0),
            "tissue_area_mm2": round(disc_area_mm2(b), 6),
            "axis_a_um": b["axis_a_um"], "axis_b_um": b["axis_b_um"],
        })

    by_section = []
    for uid in sorted(measured):
        n_roi, n_bg, regions = per_sec[uid]
        discs = disc_by_sec.get(uid, ())
        an = next((b["animal"] for b in discs), uid.split("_")[0])
        by_section.append({
            "sample": an, "treatment": groups.get(an, ""),
            "environment": envs.get(an, ""), "scene_uid": uid,
            "n_roi_nuclei": n_roi, "n_background_nuclei": n_bg,
            "n_roi_discs": sum(1 for b in discs if b["roi_kind"] == "roi"),
            "n_background_discs": sum(1 for b in discs if b["roi_kind"] == "background"),
            "regions": ", ".join(sorted(regions)),
        })

    coverage = []
    for an in sorted({b["animal"] for b in boxes},
                     key=lambda a: int(a[2:]) if a[2:].isdigit() else 0):
        pl = {b["scene_uid"] for b in boxes if b["animal"] == an}
        coverage.append({
            "sample": an, "treatment": groups.get(an, ""),
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
    print(f"  {'sample':8} {'treatment':10} {'sections':>9} {'ROIs':>6} {'nuclei':>8}")
    for c in coverage:
        n = sum(r["n_nuclei"] for r in by_roi if r["sample"] == c["sample"])
        d = sum(r["n_discs"] for r in by_roi if r["sample"] == c["sample"])
        print(f"  {c['sample']:8} {c['treatment'] or '?':10} "
              f"{c['sections_measured']:>4}/{c['sections_planned']:<4} {d:>6} {n:>8}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
