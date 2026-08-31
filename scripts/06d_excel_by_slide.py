"""Stage 6d - the same dataset one level finer: per SLIDE, per ROI.

`06c_excel_dataset.py` gives one row per ROI per sample. This gives one row per
ROI per slide, so an animal contributes several rows for the same region and the
within-animal spread is visible instead of averaged away. Same columns
otherwise.

**What a slide is here.** `LS22_s01a_sc06` is animal LS22, slide 01, variant a,
scene 06 - so the slide is `LS22_s01a`, and it holds between 1 and 9 of these
sections. Checked against `manifest_scenes.csv`'s own slide and variant columns
on all 128 sections, no disagreements. One slide is also exactly one CZI file.

"Slide" and "section" are easy to mean interchangeably and they are not the same
level here: 128 sections sit on 33 slides. Both are written - `by_slide` is the
requested sheet, `by_section` is the same table one level down - so whichever
was meant is present rather than guessed at.

Only ROIs actually placed on a given slide appear in its rows: the table is
built from the discs, so a region nobody marked there simply has no row, rather
than a zero that would read as "looked and found none".

Run:  python 06d_excel_by_slide.py
"""

import argparse
import collections
import importlib.util
import os
import re
import statistics as st

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "_g6c", os.path.join(_HERE, "06c_excel_dataset.py"))
G6C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G6C)

G5 = G6C.G5
CONFIG = G6C.CONFIG
RESULTS = G6C.RESULTS
T_UM = G6C.T_UM
AB_ON = G6C.AB_ON
XLSX = os.path.join(RESULTS, "roi_dataset_by_slide.xlsx")

# LS22_s01a_sc06 -> animal LS22, slide LS22_s01a, scene 06
UID = re.compile(r"^(?P<animal>LS\d+)_s(?P<slide>\d+)(?P<variant>[a-z])_sc(?P<scene>\d+)$")


def slide_of(uid):
    m = UID.match(uid)
    if not m:
        return uid.rsplit("_", 1)[0]
    return f"{m['animal']}_s{m['slide']}{m['variant']}"


def group_rows(nuc, live, keyfn, keyname, groups, envs):
    """One row per (key, region), where key is a slide or a section.

    `keyfn` maps a scene_uid to whatever the row is keyed by, so the slide and
    section tables are the same code at two granularities - the alternative was
    two nearly-identical loops that could drift.
    """
    n_by, a_by, d_by, sec_by = (collections.Counter(), collections.Counter(),
                                collections.Counter(), collections.defaultdict(set))
    for r in nuc:
        if r["roi_kind"] != "roi":
            continue
        n_by[(keyfn(r["scene_uid"]), r["region"])] += 1
        sec_by[(keyfn(r["scene_uid"]), r["region"])].add(r["scene_uid"])
    for b in live:
        if b["roi_kind"] != "roi":
            continue
        k = (keyfn(b["scene_uid"]), b["region"])
        a_by[k] += G6C.disc_area_mm2(b)
        d_by[k] += 1

    diam = collections.defaultdict(list)
    for r in nuc:
        if r["roi_kind"] == "roi":
            diam[(keyfn(r["scene_uid"]), r["region"])].append(float(r["equiv_diam_um"]))

    animal_of = {}
    for b in live:
        animal_of[keyfn(b["scene_uid"])] = b["animal"]

    out = []
    for key in sorted(a_by):
        k, rg = key
        n = n_by.get(key, 0)
        area = a_by[key]
        h = st.mean(diam[key]) if diam.get(key) else None
        ab = (T_UM / (T_UM + h)) if (AB_ON and h) else 1.0
        an = animal_of.get(k, "")
        out.append({
            "n_nuclei": n,
            "ROI": rg,
            keyname: k,
            "sample": an,
            "treatment": groups.get(an, ""),
            "environment": envs.get(an, ""),
            "total_tissue_area_mm2": round(area, 6),
            "n_discs": d_by[key],
            "n_sections": len(sec_by.get(key, ())),
            "profiles_per_mm2": round(n / area, 1) if area else "",
            "mean_nucleus_diam_um": round(h, 2) if h else "",
            "abercrombie_factor": round(ab, 4),
            "cells_per_mm2": round(n * ab / area, 1) if area else "",
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=XLSX)
    args = ap.parse_args()

    if not os.path.exists(G6C.NUCLEI_CSV):
        print(f"no {G6C.NUCLEI_CSV} yet - run 05c_detect_rois.py first")
        return 1

    nuc = G5.load_csv(G6C.NUCLEI_CSV)
    boxes = G5.load_csv(G5.BOX_CSV)
    groups = (CONFIG.get("groups") or {}).get("by_animal") or {}
    envs = G6C.animal_environment()

    measured = {r["scene_uid"] for r in nuc}
    planned = {b["scene_uid"] for b in boxes}
    print(f"{len(measured)} of {len(planned)} sections measured "
          f"({100*len(measured)/len(planned):.0f}%), {len(nuc)} nuclei")

    nuc = [r for r in nuc if r["artifact"] != "1"]
    # Only discs on measured sections contribute area, or a partial count would
    # be divided by a complete area. Same rule as 06c.
    live = [b for b in boxes if b["scene_uid"] in measured]

    by_slide = group_rows(nuc, live, slide_of, "slide", groups, envs)
    by_section = group_rows(nuc, live, lambda u: u, "scene_uid", groups, envs)

    coverage = []
    for sl in sorted({slide_of(b["scene_uid"]) for b in boxes}):
        pl = {b["scene_uid"] for b in boxes if slide_of(b["scene_uid"]) == sl}
        an = next(b["animal"] for b in boxes if slide_of(b["scene_uid"]) == sl)
        coverage.append({
            "slide": sl, "sample": an, "treatment": groups.get(an, ""),
            "environment": envs.get(an, ""),
            "sections_measured": len(pl & measured), "sections_planned": len(pl),
            "percent": round(100 * len(pl & measured) / len(pl), 1) if pl else "",
        })

    G6C.write_workbook(args.out, (("by_slide", by_slide),
                                  ("by_section", by_section),
                                  ("coverage", coverage)))

    print("=" * 72)
    print(f"{len(by_slide)} rows (one per ROI per slide) -> {args.out}")
    print(f"  sheets: by_slide, by_section ({len(by_section)}), coverage")
    print(f"  slides with data: {len({r['slide'] for r in by_slide})} "
          f"of {len(coverage)}")
    tr = collections.Counter(r["treatment"] or "?" for r in by_slide)
    print(f"  rows by arm: {dict(tr)}")
    rg = collections.Counter(r["ROI"] for r in by_slide)
    print(f"  rows per ROI: {dict(sorted(rg.items(), key=lambda t: -t[1]))}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
