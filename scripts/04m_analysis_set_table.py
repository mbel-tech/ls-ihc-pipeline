"""Stage 4m - one table for the pERK analysis set, both channels side by side.

The 454 sections that survived clipped-pixel censoring, each joined to its PCNA
partner, so the two channels can be read together instead of from four files.

**The two `manual_rotation` columns do not mean the same thing, despite the
name.** Every curation decision was made on the **PCNA** scan: the operator
entered those angles by hand in `04d_rotation_curator.py`. The pERK scan is a
separate acquisition with its own hand-drawn scan box, so `04i` states plainly
that "rotations must be re-derived, not copied" - the pERK figure is the
difference between the rotation its silhouette alignment measured and the
automatic angle `04a` gives that scan. It is a machine estimate.

Both are written here under names that say which is which:
`pcna_manual_rotation_deg` is the operator's; `perk_derived_rotation_deg` is not.
They disagree on 420 of the 424 paired sections, so reading one as the other
would be a real error rather than a cosmetic one.

**30 of the 454 have no PCNA partner at all** - absent from `perk_overrides.csv`
entirely, never paired rather than paired-and-dropped. They keep their pERK
columns and carry `paired=0`, so a filter is a choice the reader makes rather
than one already made for them.

Run:  python 04m_analysis_set_table.py
"""

import csv
import json
import os
from collections import Counter

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

REFORMAT_DIR = os.path.join(CONFIG["out_root"], "reformatted")
OUT_CSV = os.path.join(REFORMAT_DIR, "analysis_set_dataset.csv")

COLUMNS = ["scene_uid", "animal", "section_order", "pcna_scene_uid", "paired",
           "pcna_manual_rotation_deg", "pcna_manual_flip", "pcna_final_angle_deg",
           "perk_derived_rotation_deg", "perk_manual_flip", "perk_final_angle_deg",
           "censored_fraction", "censored_fraction_in_tissue",
           "recorded_saturated_fraction",
           "pair_align_iou", "pair_flip_margin", "pair_confidence"]


def load(name):
    with open(os.path.join(REFORMAT_DIR, name), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def sections(name):
    return {r["id"]: r for r in load(name) if r["kind"] == "section"}


def main():
    aset = {r["scene_uid"]: r for r in load("perk_analysis_set.csv")
            if r["in_analysis_set"] == "1"}
    perk = sections("reformat_index_AF568.csv")
    pcna = sections("reformat_index.csv")
    pmap = {r["perk_scene_uid"]: r for r in load("perk_overrides.csv")}

    missing = sorted(u for u in aset if u not in perk)
    if missing:
        raise SystemExit(f"analysis-set uid absent from reformat_index_AF568: {missing[:5]}")

    rows = []
    for uid, a in aset.items():
        p, link = perk[uid], pmap.get(uid)
        partner = pcna.get(link["pcna_scene_uid"]) if link else None
        rows.append({
            "scene_uid": uid,
            "animal": p["animal"],
            "section_order": p["section_order"],
            "pcna_scene_uid": link["pcna_scene_uid"] if link else "",
            "paired": 1 if partner else 0,
            "pcna_manual_rotation_deg": partner["manual_rotation"] if partner else "",
            "pcna_manual_flip": partner["manual_flip"] if partner else "",
            "pcna_final_angle_deg": partner["angle"] if partner else "",
            "perk_derived_rotation_deg": p["manual_rotation"] or "0",
            "perk_manual_flip": p["manual_flip"] or "0",
            "perk_final_angle_deg": p["angle"],
            "censored_fraction": a["censored_fraction"],
            "censored_fraction_in_tissue": a["censored_fraction_in_tissue"],
            "recorded_saturated_fraction": a["recorded_saturated_fraction"],
            "pair_align_iou": link["align_iou"] if link else "",
            "pair_flip_margin": link["flip_margin"] if link else "",
            "pair_confidence": link["confidence"] if link else "",
        })
    rows.sort(key=lambda r: (r["animal"], int(r["section_order"] or 0)))

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    paired = [r for r in rows if r["paired"]]
    conf = Counter(r["pair_confidence"] for r in paired)
    print("=" * 70)
    print(f"{len(rows)} sections -> {OUT_CSV}")
    print(f"  paired with PCNA        : {len(paired)}   unpaired: {len(rows)-len(paired)}")
    print(f"  pairing confidence      : {dict(conf)}")
    print(f"  animals                 : {len(set(r['animal'] for r in rows))}")
    nz = sum(1 for r in paired if float(r['pcna_manual_rotation_deg'] or 0))
    print(f"  nonzero OPERATOR tilt   : {nz} of {len(paired)} paired sections")
    print("=" * 70)


if __name__ == "__main__":
    main()
