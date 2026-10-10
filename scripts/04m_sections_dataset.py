"""Stage 4m - every section of the measured pass, with what happened to it.

**Paired only** (`ls_layouts.RESTRICTED`). The universe here is a two-pass join
and `partner_kept` has no meaning without a partner; a multiplex study gets the
same table, per scene, from `04p_section_provenance.py`.

One row per section of the measured marker in the whole universe - 1191 of them
on the LS study - each joined to its partner in the geometry-source pass.
`status` says which of four fates it met:

    analysis_set   454   measurable
    censored_out   264   reformatted, then failed the 1% clipped-pixel tolerance
    excluded       473   never reformatted; the operator or a measurement rejected it
    unmeasured           no 04j row yet, or no raw clipping mask - not a statement
                         about clipping

Keeping the rejected sections in the table rather than in a separate file is the
point. The exclusion rate varies a great deal by animal, that variation is itself
a result, and it **must be checked against experimental group at unblinding** -
which is easy to forget entirely if the rejects live somewhere else.

**The two rotation columns do not mean the same thing, and the column names are
the only place that is written down.** Only the PARTNER's angles were entered by
hand (`04d_rotation_curator.py`). `04i` re-derives this pass's figure from
silhouette alignment rather than copying it - "rotations must be re-derived, not
copied" - because it is a separate acquisition with its own hand-drawn scan box.
So `manual` stays on the partner and `derived` stays on the row:
`partner_manual_rotation_deg` against `derived_rotation_deg`. They disagree on
420 of 424 paired analysis-set rows on the LS study; spelling them the same way
for symmetry would be claiming they are one number.

**Where the quality numbers come from differs by fate, deliberately.**
`exclusion_candidates.csv` was regenerated against the curated set, so it only
describes sections that survived. For an excluded section the measured value is
recovered from the reason string it was rejected with, which is the only place it
still exists. `qc_source` records which of the two applies per row, so nobody has
to guess which they are looking at.

Identity comes from `manifest_scenes.csv`, the only source that covers rejected
sections too; its `section_order` agrees with the measured marker's reformat
index on all 718 kept rows.

Run:  python 04m_sections_dataset.py
"""

import sys
import csv
import importlib.util
import json
import os
import re
from collections import Counter

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
import ls_channels as CH  # noqa: E402
import ls_paths as LP  # noqa: E402

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
MANIFEST_CSV = os.path.join(OUT_ROOT, "manifest", "manifest_scenes.csv")

# ---- which pass is the row and which is the partner ------------------------
#
# The rows are the pass that is NOT the geometry source, and the partner is the
# one that is. On the LS study that reads AF568 joined to AF488, which is what
# the literals said; stated as a rule it also reads Mk1 joined to Mk2.
#
# **The geometry source is the SECOND declared marker** - `04a.DEFAULT_MARKER`
# is `MARKERS[1]`, the pass that was curated first and therefore owns the
# unsuffixed filenames. Deriving the row marker as `MARKERS[0]` would be that
# rule restated, and restating it is how the other seven copies got inverted;
# `ls_paths.geometry_source` is asked instead.
MARKERS = list(CH.marker_names(CONFIG))
LAYOUT = (CONFIG.get("acquisition") or {}).get("layout", CH.LAYOUT_MULTIPLEX)
NAMES = LP.for_config(CONFIG)
PARTNER = LP.geometry_source(MARKERS, LAYOUT)
MARKER = next((m for m in MARKERS if m != PARTNER), PARTNER)

# A WRITE path, so `path()` and never `read()`: resolving this to the
# operator's `perk_sections_dataset.csv` would keep writing an antibody name
# forever and the derived branch would never run. The reads below are the
# other half - they DO resolve, and only to a file that is on the drive.
OUT_CSV = NAMES.path("sections_dataset", MARKER)

# ls_paths rather than `04a.marker_paths` for every one of these, though
# `tests/test_ls_paths.py` pins the two to the same answers. 04a imports numpy,
# PIL and scipy, and `04p_section_provenance.py` imports THIS module at module
# level to borrow `classify()` - so importing 04a here would pull the whole
# image stack into a stage whose job is to write a CSV. Same reason
# `04j.analysis_set_path` is not imported for the analysis set: 04j imports 04a.
# `Names.read` gives the same answer for the analysis set in every case where
# the file exists, which is the only case either of them can be right about.


def index_csv(marker):
    """The reformat index of one pass. Resolves a legacy name if that is what
    is on the drive."""
    return NAMES.read("index", marker)


def excluded_csv(marker):
    return NAMES.read("excluded", marker)


def overrides_csv():
    """The measured pass's rotation-override file - the pairing, in effect.

    This is the operator's 82,893-byte `perk_overrides.csv` on the LS study,
    covering 130 curated sections, and `read()` is what still finds it.
    """
    return NAMES.read("overrides", MARKER)


def analysis_set_csv():
    return NAMES.read("analysis_set", MARKER)


COLUMNS = ["scene_uid", "animal", "slide", "variant", "scene_index", "section_order",
           "status", "exclusion_class", "disposition_reason",
           "partner_scene_uid", "paired", "partner_kept", "pair_align_iou",
           "pair_flip_margin", "pair_confidence",
           # manual on the PARTNER, derived on the ROW - see the docstring.
           "partner_manual_rotation_deg", "partner_manual_flip",
           "partner_final_angle_deg",
           "derived_rotation_deg", "manual_flip", "final_angle_deg",
           "censored_fraction", "censored_fraction_in_tissue",
           "recorded_saturated_fraction",
           "qc_source", "partner_focus_score", "partner_largest_piece_mm2",
           "partner_total_tissue_mm2", "partner_n_pieces"]


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_header(path):
    """(fieldnames, rows). The header is needed even when there are no rows.

    An overrides file with a header and nothing under it is a real state - 04i
    writes one before anything is curated - and the column names still have to
    be resolved from it, not from `rows[0]`.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        rows = list(rd)
        return list(rd.fieldnames or []), rows


def override_columns(fieldnames):
    """(key, partner) - the two uid columns of a rotation-override file.

    Two spellings each, and asked ONCE against the header rather than per row.
    `04i` still writes `perk_scene_uid`/`pcna_scene_uid`; the generic pair is
    accepted so this reader does not have to change again when it stops. Not
    `.get()`: a renamed column would then read as an empty cell, every row
    would come back unpaired, and `paired` would say 0 for all 1,191 sections
    with nothing raised anywhere.
    """
    what = os.path.basename(overrides_csv())
    return (IO.pick_column(fieldnames, "scene_uid", "perk_scene_uid", what=what),
            IO.pick_column(fieldnames, "source_scene_uid", "pcna_scene_uid",
                           what=what))


def rel(name):
    return load(os.path.join(REFORMAT_DIR, name))


def classify(reason):
    """Exclusion reason -> (class, measured value). All 593 recorded reasons match.

    The measurement is embedded in the string - "focus 0.061", "larger than
    0.30 mm2" - and for a rejected section that string is the only surviving
    record of it, so it is parsed back out rather than dropped.
    """
    # Three spellings of one decision: the curator export's prefix, 04a's
    # default when the export carried no reason (04a:469), and the Review
    # mode's default (04a:446).
    if (reason.startswith("manually excluded") or reason == "too damaged to measure"
            or reason == "excluded on review"):
        return "tissue_damaged", None
    m = re.match(r"no resolvable nuclear detail \(focus ([\d.]+)", reason)
    if m:
        return "out_of_focus", float(m.group(1))
    m = re.match(r"no tissue piece larger than ([\d.]+) mm2", reason)
    if m:
        return "no_tissue", float(m.group(1))
    return "unparsed", None


def fate(a):
    """(status, reason) for a section that is NOT excluded, from its analysis-set
    row. No row, or a blank in_analysis_set, is UNMEASURED - 04j has not seen a
    raw mask for it - and must not be reported as censored."""
    if a is None:
        return "unmeasured", "no analysis-set row - 04j has not measured this section"
    if a["in_analysis_set"] == "":
        return "unmeasured", a["reason"]
    if a["in_analysis_set"] == "1":
        return "analysis_set", ""
    return "censored_out", a["reason"]

def main():
    # Refused rather than run empty. Without a partner the join has nothing on
    # its right-hand side, every row would come back paired=0, partner_kept=0,
    # and that table is indistinguishable from a paired study where nothing
    # paired. `ls_layouts.RESTRICTED` keeps run_all.sh and the app from getting
    # here; this is for the operator who runs the script by hand.
    if PARTNER is None or MARKER == PARTNER:
        raise SystemExit(
            f"04m joins two passes of one section, and this study is {LAYOUT} "
            f"with markers {MARKERS} - there is no partner pass to join to. "
            "04p_section_provenance.py builds the per-scene table instead.")

    man = {r["scene_uid"]: r for r in load(MANIFEST_CSV)}
    kept = {r["id"]: r for r in load(index_csv(MARKER)) if r["kind"] == "section"}
    partner_kept = {r["id"]: r for r in load(index_csv(PARTNER))
                    if r["kind"] == "section"}
    pexc = {r["scene_uid"]: r for r in load(excluded_csv(MARKER))}
    cexc = {r["scene_uid"]: r for r in load(excluded_csv(PARTNER))}
    link_header, link_rows = load_header(overrides_csv())
    uid_col, src_col = override_columns(link_header)
    link = {r[uid_col]: r for r in link_rows}
    aset = {r["scene_uid"]: r for r in load(analysis_set_csv())}
    cand = {r["uid"]: r for r in rel("exclusion_candidates.csv")}

    universe = sorted(set(kept) | set(pexc))
    overlap = set(kept) & set(pexc)
    if overlap:
        raise SystemExit(f"section both kept and excluded: {sorted(overlap)[:5]}")
    missing = [u for u in universe if u not in man]
    if missing:
        raise SystemExit(f"not in manifest_scenes: {missing[:5]}")

    rows, unparsed = [], []
    for uid in universe:
        m, p, lk = man[uid], kept.get(uid), link.get(uid)
        partner = partner_kept.get(lk[src_col]) if lk else None
        a = aset.get(uid)

        if uid in pexc:
            status = "excluded"
            # This pass's reason is always "partner excluded by the operator";
            # the real one is on the partner's side, so follow the pairing.
            src = cexc.get(lk[src_col], {}).get("reason", "") if lk else ""
            reason = src or pexc[uid]["reason"]
            klass, value = classify(src) if src else ("", None)
            if klass == "unparsed":
                unparsed.append(src)
        else:
            status, reason = fate(a)
            klass, value = "", None

        c = cand.get(lk[src_col]) if lk else None
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
            "partner_scene_uid": lk[src_col] if lk else "",
            # Two different facts. `paired` is whether a partner was ever
            # recorded; `partner_kept` is whether that partner survived
            # curation. An excluded section is normally paired AND not kept -
            # collapsing them would read every exclusion as a pairing failure.
            "paired": 1 if lk else 0,
            "partner_kept": 1 if partner else 0,
            "pair_align_iou": lk["align_iou"] if lk else "",
            "pair_flip_margin": lk["flip_margin"] if lk else "",
            "pair_confidence": lk["confidence"] if lk else "",
            "partner_manual_rotation_deg": partner["manual_rotation"] if partner else "",
            "partner_manual_flip": partner["manual_flip"] if partner else "",
            "partner_final_angle_deg": partner["angle"] if partner else "",
            # `manual_rotation` is what 04a's index calls the column; on this
            # pass 04i DERIVED the number in it, which is the whole reason the
            # two rotations get different names here.
            "derived_rotation_deg": (p["manual_rotation"] or "0") if p else "",
            "manual_flip": (p["manual_flip"] or "0") if p else "",
            "final_angle_deg": p["angle"] if p else "",
            "censored_fraction": a["censored_fraction"] if a else "",
            "censored_fraction_in_tissue": a["censored_fraction_in_tissue"] if a else "",
            "recorded_saturated_fraction": a["recorded_saturated_fraction"] if a else "",
            "qc_source": qc_source, "partner_focus_score": focus,
            "partner_largest_piece_mm2": largest,
            "partner_total_tissue_mm2": total,
            "partner_n_pieces": pieces,
        })
    rows.sort(key=lambda r: (r["animal"], int(r["section_order"] or 0)))

    IO.atomic_write_csv(OUT_CSV, rows, COLUMNS)

    st = Counter(r["status"] for r in rows)
    excl = Counter(r["exclusion_class"] for r in rows if r["status"] == "excluded")
    print("=" * 72)
    print(f"{len(rows)} {MARKER} sections -> {OUT_CSV}")
    print(f"  status     : {dict(st)}")
    print(f"  exclusion  : {dict(excl)}")
    print(f"  qc_source  : {dict(Counter(r['qc_source'] for r in rows))}")
    print(f"  paired     : {sum(r['paired'] for r in rows)} of {len(rows)}"
          f"   ({PARTNER} partner also kept: "
          f"{sum(r['partner_kept'] for r in rows)})")
    print(f"  animals    : {len(set(r['animal'] for r in rows))}")
    if unparsed:
        print(f"  UNPARSED reasons: {len(unparsed)} e.g. {unparsed[:2]}")
    print()
    print(f"  {'animal':8s} {'total':>6} {'analysis':>9} {'censored':>9} {'excluded':>9}"
          f" {'unmeasured':>11}   excl%")
    for an in sorted(set(r["animal"] for r in rows)):
        g = [r for r in rows if r["animal"] == an]
        c = Counter(r["status"] for r in g)
        print(f"  {an:8s} {len(g):>6} {c['analysis_set']:>9} {c['censored_out']:>9} "
              f"{c['excluded']:>9} {c['unmeasured']:>11}   "
              f"{100 * c['excluded'] / len(g):5.1f}%")
    print("=" * 72)


if __name__ == "__main__":
    main()
