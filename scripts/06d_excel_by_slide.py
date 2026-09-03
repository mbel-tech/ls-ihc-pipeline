"""Stage 6d - the same dataset one level finer: per SLIDE, per ROI.

`06c_excel_dataset.py` gives one row per ROI per sample. This gives one row per
ROI per slide, so an animal contributes several rows for the same region and the
within-animal spread is visible instead of averaged away. Same columns
otherwise.

**What a slide is here.** `LS22_s01a_sc06` is animal LS22, slide 01, variant a,
scene 06 - so the slide is `LS22_s01a`, and it holds between 1 and 9 of these
sections. Checked against `manifest_scenes.csv`'s own slide and variant columns
on all sections, no disagreements. One slide is also exactly one CZI file.

"Slide" and "section" are easy to mean interchangeably and they are not the same
level here: the 130 curated pERK sections sit on 33 slides. Both are written - `by_slide` is the
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

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "_g6c", os.path.join(_HERE, "06c_excel_dataset.py"))
G6C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G6C)

G5 = G6C.G5
CONFIG = G6C.CONFIG
RESULTS = G6C.RESULTS
XLSX = os.path.join(RESULTS, "roi_dataset_by_slide.xlsx")

# LS22_s01a_sc06 -> animal LS22, slide LS22_s01a, scene 06
UID = re.compile(r"^(?P<animal>LS\d+)_s(?P<slide>\d+)(?P<variant>[a-z])_sc(?P<scene>\d+)$")


def slide_of(uid):
    m = UID.match(uid)
    if not m:
        return uid.rsplit("_", 1)[0]
    return f"{m['animal']}_s{m['slide']}{m['variant']}"


def group_rows(meas, keyfn, keyname, groups, envs):
    """One row per (key, region), where key is a slide or a section.

    `keyfn` maps a scene_uid to whatever the row is keyed by, so the slide and
    section tables are the same code at two granularities - the alternative was
    two nearly-identical loops that could drift.

    Takes 06a's per-ROI rows, not the raw nuclei. h and the Abercrombie factor
    are 06a's per-(marker, region) values and are NOT recomputed per slide: a
    slide carries a handful of discs, so a per-slide h would be a mean over a
    few hundred nuclei and would make the correction vary with sampling noise
    from row to row. See config.detection.abercrombie._h_source.
    """
    n_by, a_by, d_by = (collections.Counter(), collections.Counter(),
                        collections.Counter())
    p_by, pos_known = collections.Counter(), collections.Counter()
    sec_by = collections.defaultdict(set)
    h_by, ab_by, animal_of = {}, {}, {}
    # The marker is part of the key for the same reason it is in 06c: without it
    # a row would be AF568 + AF488 summed under one n_nuclei, and the single
    # (h, factor) pair stored per key would be whichever marker happened to come
    # last. Harmless while only pERK is measured; wrong the moment PCNA is.
    for r in meas:
        if r["roi_kind"] != "roi":
            continue
        k = (keyfn(r["scene_uid"]), r["marker"], r["region"])
        n_by[k] += int(r["n_nuclei"])
        a_by[k] += float(r["roi_area_mm2"])
        d_by[k] += 1
        sec_by[k].add(r["scene_uid"])
        if r["n_positive"] not in ("", None):
            p_by[k] += int(r["n_positive"])
            pos_known[k] += 1
        h_by[k] = float(r["mean_nucleus_diam_um"]) if r["mean_nucleus_diam_um"] else None
        ab_by[k] = float(r["abercrombie_factor"]) if r["abercrombie_factor"] else 1.0
        animal_of[keyfn(r["scene_uid"])] = r["animal"]

    out = []
    for key in sorted(a_by):
        k, mk, rg = key
        n = n_by.get(key, 0)
        area = a_by[key]
        h = h_by.get(key)
        ab = ab_by.get(key) or 1.0
        an = animal_of.get(k, "")
        # Blank, not 0, where any disc behind the row sat on a section with no
        # positivity cut - 0 would read as "looked and found none".
        full = pos_known[key] == d_by[key]
        npos = p_by[key] if full else ""
        out.append({
            "n_nuclei": n,
            "ROI": rg,
            keyname: k,
            "sample": an,
            "marker": mk,
            "treatment": groups.get(an, ""),
            "environment": envs.get(an, ""),
            "total_tissue_area_mm2": round(area, 6),
            "n_positive": npos,
            "frac_positive": round(npos / n, 4) if (full and n) else "",
            "positive_cells_per_mm2": (round(npos * ab / area, 1)
                                       if (full and area) else ""),
            "n_discs": d_by[key],
            "n_sections": len(sec_by.get(key, ())),
            "profiles_per_mm2": round(n / area, 1) if area else "",
            "mean_nucleus_diam_um": round(h, 2) if h else "",
            "abercrombie_factor": round(ab, 4),
            "cells_per_mm2": round(n * ab / area, 1) if area else "",
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=XLSX)
    # argv is passed explicitly by 06e_refresh_loop, whose own flags would
    # otherwise reach this parser and abort the cycle.
    args = ap.parse_args(argv)

    if not os.path.exists(G6C.MEAS_CSV):
        print(f"no {G6C.MEAS_CSV} - run 06a_roi_dataset.py first")
        return 1

    meas = G5.load_csv(G6C.MEAS_CSV)
    boxes = G5.all_boxes()          # both markers; see 05a.all_boxes
    groups = G6C.resolve_groups((CONFIG.get("groups") or {}).get("by_animal") or {})
    envs = G6C.animal_environment()

    # 06a emits rows only for measured sections, and only for discs on them, so
    # the "partial count divided by a complete area" rule 06c states is already
    # enforced upstream - there is no `live` filter to apply here any more.
    measured = {r["scene_uid"] for r in meas}
    planned = {b["scene_uid"] for b in boxes}
    n_total = sum(int(r["n_nuclei"]) for r in meas)
    print(f"{len(measured)} of {len(planned)} sections measured "
          f"({100*len(measured)/len(planned):.0f}%), {n_total} nuclei")

    by_slide = group_rows(meas, slide_of, "slide", groups, envs)
    by_section = group_rows(meas, lambda u: u, "scene_uid", groups, envs)

    # Per (slide, MARKER), for the same reason as 06c's.
    coverage = []
    for sl, mk in sorted({(slide_of(b["scene_uid"]), b["marker"]) for b in boxes}):
        pl = {b["scene_uid"] for b in boxes
              if slide_of(b["scene_uid"]) == sl and b["marker"] == mk}
        an = next(b["animal"] for b in boxes
                  if slide_of(b["scene_uid"]) == sl and b["marker"] == mk)
        coverage.append({
            "slide": sl, "marker": mk, "sample": an,
            "treatment": groups.get(an, ""),
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
