"""Stage 4m - every pERK section, with what happened to it and why.

One row per pERK section in the whole universe - 1191 of them - each joined to
its PCNA partner. `status` says which of three fates it met:

    analysis_set   454   measurable
    censored_out   264   reformatted, then failed the 1% clipped-pixel tolerance
    excluded       473   never reformatted; the operator or a measurement rejected it

Keeping the rejected sections in the table rather than in a separate file is the
point. The exclusion rate varies a great deal by animal, that variation is itself
a result, and it **must be checked against experimental group at unblinding** -
which is easy to forget entirely if the rejects live somewhere else.

**The two rotation columns do not mean the same thing.** Only the PCNA angles
were entered by hand (`04d_rotation_curator.py`). `04i` re-derives the pERK
figure from silhouette alignment rather than copying it - "rotations must be
re-derived, not copied" - because the pERK scan is a separate acquisition with
its own hand-drawn scan box. They are named `pcna_manual_rotation_deg` and
`perk_derived_rotation_deg`, and disagree on 420 of 424 paired analysis-set rows.

**Where the quality numbers come from differs by fate, deliberately.**
`exclusion_candidates.csv` was regenerated against the curated set, so it only
describes sections that survived. For an excluded section the measured value is
recovered from the reason string it was rejected with, which is the only place it
still exists. `qc_source` records which of the two applies per row, so nobody has
to guess which they are looking at.

Identity comes from `manifest_scenes.csv`, the only source that covers rejected
sections too; its `section_order` agrees with `reformat_index_AF568.csv` on all
718 kept rows.

Run:  python 04m_sections_dataset.py
"""

import csv
import json
import os
import re
from collections import Counter

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
MANIFEST_CSV = os.path.join(OUT_ROOT, "manifest", "manifest_scenes.csv")
OUT_CSV = os.path.join(REFORMAT_DIR, "perk_sections_dataset.csv")

COLUMNS = ["scene_uid", "animal", "slide", "variant", "scene_index", "section_order",
           "status", "exclusion_class", "disposition_reason",
           "pcna_scene_uid", "paired", "pcna_kept", "pair_align_iou", "pair_flip_margin",
           "pair_confidence",
           "pcna_manual_rotation_deg", "pcna_manual_flip", "pcna_final_angle_deg",
           "perk_derived_rotation_deg", "perk_manual_flip", "perk_final_angle_deg",
           "censored_fraction", "censored_fraction_in_tissue",
           "recorded_saturated_fraction",
           "qc_source", "pcna_focus_score", "pcna_largest_piece_mm2",
           "pcna_total_tissue_mm2", "pcna_n_pieces"]


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def rel(name):
    return load(os.path.join(REFORMAT_DIR, name))


def classify(reason):
    """Exclusion reason -> (class, measured value). All 593 recorded reasons match.

    The measurement is embedded in the string - "focus 0.061", "larger than
    0.30 mm2" - and for a rejected section that string is the only surviving
    record of it, so it is parsed back out rather than dropped.
    """
    if reason.startswith("manually excluded"):
        return "tissue_damaged", None
    m = re.match(r"no resolvable nuclear detail \(focus ([\d.]+)", reason)
    if m:
        return "out_of_focus", float(m.group(1))
    m = re.match(r"no tissue piece larger than ([\d.]+) mm2", reason)
    if m:
        return "no_tissue", float(m.group(1))
    return "unparsed", None


def main():
    man = {r["scene_uid"]: r for r in load(MANIFEST_CSV)}
    perk = {r["id"]: r for r in rel("reformat_index_AF568.csv") if r["kind"] == "section"}
    pcna = {r["id"]: r for r in rel("reformat_index.csv") if r["kind"] == "section"}
    pexc = {r["scene_uid"]: r for r in rel("excluded_sections_AF568.csv")}
    cexc = {r["scene_uid"]: r for r in rel("excluded_sections.csv")}
    link = {r["perk_scene_uid"]: r for r in rel("perk_overrides.csv")}
    aset = {r["scene_uid"]: r for r in rel("perk_analysis_set.csv")}
    cand = {r["uid"]: r for r in rel("exclusion_candidates.csv")}

    universe = sorted(set(perk) | set(pexc))
    overlap = set(perk) & set(pexc)
    if overlap:
        raise SystemExit(f"section both kept and excluded: {sorted(overlap)[:5]}")
    missing = [u for u in universe if u not in man]
    if missing:
        raise SystemExit(f"not in manifest_scenes: {missing[:5]}")

    rows, unparsed = [], []
    for uid in universe:
        m, p, lk = man[uid], perk.get(uid), link.get(uid)
        partner = pcna.get(lk["pcna_scene_uid"]) if lk else None
        a = aset.get(uid)

        if uid in pexc:
            status = "excluded"
            # The pERK reason is always "PCNA partner excluded by the operator";
            # the real one is on the PCNA side, so follow the pairing to it.
            src = cexc.get(lk["pcna_scene_uid"], {}).get("reason", "") if lk else ""
            reason = src or pexc[uid]["reason"]
            klass, value = classify(src) if src else ("", None)
            if klass == "unparsed":
                unparsed.append(src)
        elif a and a["in_analysis_set"] == "1":
            status, klass, value, reason = "analysis_set", "", None, ""
        else:
            status, klass, value = "censored_out", "", None
            reason = a["reason"] if a else ""

        c = cand.get(lk["pcna_scene_uid"]) if lk else None
        if c:
            qc_source = "exclusion_candidates"
            focus, largest = c["focus_score"], c["largest_mm2"]
            total, pieces = c["total_mm2"], c["n_pieces"]
        else:
            qc_source = "reason_string" if value is not None else ""
            focus = value if klass == "out_of_focus" else ""
            largest = value if klass == "no_tissue" else ""
            total = pieces = ""

        rows.append({
            "scene_uid": uid, "animal": m["animal"], "slide": m["slide"],
            "variant": m["variant"], "scene_index": m["scene_index"],
            "section_order": m["section_order"],
            "status": status, "exclusion_class": klass, "disposition_reason": reason,
            "pcna_scene_uid": lk["pcna_scene_uid"] if lk else "",
            # Two different facts. `paired` is whether a PCNA partner was ever
            # recorded; `pcna_kept` is whether that partner survived curation.
            # An excluded section is normally paired AND not kept - collapsing
            # them would read every exclusion as a pairing failure.
            "paired": 1 if lk else 0,
            "pcna_kept": 1 if partner else 0,
            "pair_align_iou": lk["align_iou"] if lk else "",
            "pair_flip_margin": lk["flip_margin"] if lk else "",
            "pair_confidence": lk["confidence"] if lk else "",
            "pcna_manual_rotation_deg": partner["manual_rotation"] if partner else "",
            "pcna_manual_flip": partner["manual_flip"] if partner else "",
            "pcna_final_angle_deg": partner["angle"] if partner else "",
            "perk_derived_rotation_deg": (p["manual_rotation"] or "0") if p else "",
            "perk_manual_flip": (p["manual_flip"] or "0") if p else "",
            "perk_final_angle_deg": p["angle"] if p else "",
            "censored_fraction": a["censored_fraction"] if a else "",
            "censored_fraction_in_tissue": a["censored_fraction_in_tissue"] if a else "",
            "recorded_saturated_fraction": a["recorded_saturated_fraction"] if a else "",
            "qc_source": qc_source, "pcna_focus_score": focus,
            "pcna_largest_piece_mm2": largest, "pcna_total_tissue_mm2": total,
            "pcna_n_pieces": pieces,
        })
    rows.sort(key=lambda r: (r["animal"], int(r["section_order"] or 0)))

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    st = Counter(r["status"] for r in rows)
    excl = Counter(r["exclusion_class"] for r in rows if r["status"] == "excluded")
    print("=" * 72)
    print(f"{len(rows)} pERK sections -> {OUT_CSV}")
    print(f"  status     : {dict(st)}")
    print(f"  exclusion  : {dict(excl)}")
    print(f"  qc_source  : {dict(Counter(r['qc_source'] for r in rows))}")
    print(f"  paired     : {sum(r['paired'] for r in rows)} of {len(rows)}"
          f"   (PCNA partner also kept: {sum(r['pcna_kept'] for r in rows)})")
    print(f"  animals    : {len(set(r['animal'] for r in rows))}")
    if unparsed:
        print(f"  UNPARSED reasons: {len(unparsed)} e.g. {unparsed[:2]}")
    print()
    print(f"  {'animal':8s} {'total':>6} {'analysis':>9} {'censored':>9} {'excluded':>9}   excl%")
    for an in sorted(set(r["animal"] for r in rows)):
        g = [r for r in rows if r["animal"] == an]
        c = Counter(r["status"] for r in g)
        print(f"  {an:8s} {len(g):>6} {c['analysis_set']:>9} {c['censored_out']:>9} "
              f"{c['excluded']:>9}   {100 * c['excluded'] / len(g):5.1f}%")
    print("=" * 72)


if __name__ == "__main__":
    main()
