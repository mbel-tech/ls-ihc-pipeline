"""Stage 4p - every scanned section, and what each stage decided about it.

One row per scene in `manifest_scenes.csv` - all **2,572** of them, both markers,
including the 1,066 that were excluded and never reach any other table. It starts
from the CZI the scene came out of and follows it downstream: what 04f proposed,
what the operator decided, what 04g masked, what 04j censored, whether 04a
reformatted it, and whether anything was ever measured in it.

**This is a JOIN, not a measurement.** Every number here already exists somewhere;
what did not exist was a single place to see them per section. `04m` does exactly
this for the 1,191 pERK sections and is the model - its `classify()` is imported
rather than reimplemented, because a second parser for the same reason strings
would be a second thing to keep in step.

Why the whole universe rather than the survivors
------------------------------------------------

Four stages decide a section's fate before the operator ever sees it in the ROI
curator, and the curator loads from `reformat_index*.csv` - the survivors. So 593
PCNA and 473 pERK exclusions, and 2,099 artifact masks, are invisible from the
tool the operator spends their time in. This table is what makes them reviewable.

Two asymmetries worth knowing, both real and neither a bug
-----------------------------------------------------------

**An excluded PCNA section still has its reformatted image; an excluded pERK
section does not.** PCNA was reformatted first and excluded afterwards, so all
1,381 have a PNG. pERK exclusions were applied before reformatting, so only the
718 survivors do. `section_img` records which, because it decides whether a
section can be shown in the analysis frame or only as the original scan.

**`exclusion_candidates.csv` and both `artifact_summary` files cover only
survivors** - they were regenerated against the curated set. For an excluded
section the measured value survives only inside the reason string it was rejected
with, which is why `classify()` parses it back out and `qc_source` says which of
the two a row's numbers came from.

Writes `reformatted/section_provenance.csv`.

Run:  python 04p_section_provenance.py
"""

import argparse
import csv
import importlib.util
import json
import os
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(_HERE), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
MASK_DIR = os.path.join(OUT_ROOT, "artifacts")
CENSOR_DIR = os.path.join(OUT_ROOT, "censor")
RESULTS = os.path.join(OUT_ROOT, "results")
MANIFEST_CSV = os.path.join(OUT_ROOT, "manifest", "manifest_scenes.csv")
FOCUS_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
TISSUE_DIR = os.path.join(OUT_ROOT, "tissue")
OUT_CSV = os.path.join(REFORMAT_DIR, "section_provenance.csv")

# 04m already turns these reason strings into a class and the number embedded in
# them. Imported by file path because the module name starts with a digit.
_spec = importlib.util.spec_from_file_location(
    "_g4m", os.path.join(_HERE, "04m_sections_dataset.py"))
G4M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G4M)

def write_tissue_masks(rows, force=False):
    """One tissue mask per section, in the OVERVIEW frame.

    **Why this has to exist at all.** Several stages compute a tissue mask and
    none of them keep it: 04g rebuilds one every run, 04i rebuilds one to align
    the two channels, 04j builds one to report
    `censored_fraction_in_tissue`, and 04a's lives only in the reformatted
    frame. So nothing downstream can ask "is this pixel tissue?" in the frame
    the overviews and the censor and artifact masks all share.

    The ROI curator's Review mode needs exactly that, to separate censoring on
    tissue from censoring on the PAP pen ring - **82% of censored pixels are
    outside the tissue**, so the overlay is mostly pen and the real clipping is
    invisible under it.

    **Thresholding DAPI in the browser was tried first and cannot work.** In the
    8-bit overview, DAPI inside tissue has a median of 4/255 against 1-2
    outside; no cut separates them, and the one that looked plausible kept 0.2%
    of the censoring that 04j says is on tissue. The mask has to come from the
    same log-space Otsu the pipeline uses, on the data it was designed for.

    `04a_reformat.tissue_mask` is that function, applied the way `04g` applies
    it - squashed to a square work grid, then stretched back - so this mask is
    the pipeline's own opinion rather than a fourth definition of tissue.
    """
    from PIL import Image
    import numpy as np
    _s = importlib.util.spec_from_file_location(
        "_rf4p", os.path.join(_HERE, "04a_reformat.py"))
    RF = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(RF)

    os.makedirs(TISSUE_DIR, exist_ok=True)
    made = skipped = failed = 0
    for i, r in enumerate(rows):
        uid = r["scene_uid"]
        out = os.path.join(TISSUE_DIR, uid + "_tissue.png")
        if os.path.exists(out) and not force:
            skipped += 1
            continue
        src = os.path.join(OVERVIEW_DIR, r["animal"], r["marker"], uid + "_DAPI.png")
        if not os.path.exists(src):
            failed += 1
            continue
        im = np.asarray(Image.open(src).convert("L")).astype(np.float32)
        small = np.asarray(Image.fromarray(im).resize(
            (RF.WORK_SIZE, RF.WORK_SIZE), Image.BILINEAR)).astype(np.float32)
        t = RF.tissue_mask(small, light_background=False)
        if t is None:
            failed += 1
            continue
        big = Image.fromarray((t.astype(np.uint8) * 255)).resize(
            (im.shape[1], im.shape[0]), Image.NEAREST)
        big.save(out)
        made += 1
        if (i + 1) % 200 == 0:
            print(f"\r  tissue masks {i + 1}/{len(rows)}", end="")
    print(f"\r  tissue masks: {made} written, {skipped} already there, "
          f"{failed} could not be built        ")


COLUMNS = [
    # where it came from
    "scene_uid", "animal", "marker", "slide", "variant", "scene_index",
    "section_order", "czi_file",
    # where it ended up
    "status",
    # 04f proposed, the operator decided
    "proposed_excluded", "decision", "exclusion_class", "decision_reason",
    # measured at export, for every section
    "tissue_area_mm2", "focus_score", "contrast", "saturated_fraction",
    # measured by 04f, survivors only
    "largest_mm2", "total_mm2", "n_pieces", "qc_source",
    # 04g
    "n_artifact_objects", "artifact_pct_of_tissue",
    # 04j, pERK only
    "in_analysis_set", "censored_fraction_in_tissue", "censor_reason",
    # 04a
    "reformatted", "angle", "manual_rotation", "manual_flip",
    # what can be shown, and what was measured
    "overview_img", "section_img", "section_rgb", "section_thumb", "mask_img",
    "tissue_img", "censor_img",
    "n_rois", "n_nuclei",
]


def load(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def rel(name):
    return load(os.path.join(REFORMAT_DIR, name))


def count_nuclei():
    """scene_uid -> nuclei measured. Streamed: the file is ~110 MB.

    csv.reader and column 0, not DictReader - this needs one field and building
    a dict per row would be ~900,000 of them for a count.
    """
    path = os.path.join(RESULTS, "roi_nuclei.csv")
    out = Counter()
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for row in rd:
            if row:
                out[row[0]] += 1
    return out


def count_rois():
    """scene_uid -> discs placed, over EVERY marker's box file.

    Both suffixed files when they exist, falling back to the unsuffixed one only
    when neither does - that is the pre-2026-09-01 layout, and it is all AF568.
    Scene uids are disjoint across markers, so this is a union, not a merge.
    """
    out = Counter()
    found = False
    for name in ("roi_boxes_AF568.csv", "roi_boxes_AF488.csv"):
        p = os.path.join(REFORMAT_DIR, name)
        if os.path.exists(p):
            found = True
            for r in load(p):
                out[r["scene_uid"]] += 1
    if not found:
        for r in load(os.path.join(REFORMAT_DIR, "roi_boxes.csv")):
            out[r["scene_uid"]] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tissue-masks", action="store_true",
                    help="build a tissue mask per section in the OVERVIEW frame "
                         "(tissue/<uid>_tissue.png). Slow - it opens every DAPI "
                         "overview - and only needed once.")
    ap.add_argument("--force", action="store_true",
                    help="rebuild tissue masks that already exist")
    args = ap.parse_args()
    man = load(MANIFEST_CSV)
    focus = {r["scene_uid"]: r for r in load(FOCUS_CSV)}

    # Per marker: the index of survivors, the exclusion list, the artifact
    # summary. AF488 keeps the unsuffixed names, as everywhere else.
    keep, excl, art = {}, {}, {}
    for mk, idx_name, exc_name, art_name in (
            ("AF488", "reformat_index.csv", "excluded_sections.csv",
             "artifact_summary.csv"),
            ("AF568", "reformat_index_AF568.csv", "excluded_sections_AF568.csv",
             "artifact_summary_AF568.csv")):
        keep.update({r["id"]: r for r in rel(idx_name) if r["kind"] == "section"})
        excl.update({r["scene_uid"]: r for r in rel(exc_name)})
        for r in load(os.path.join(MASK_DIR, art_name)):
            art[r["scene_uid"]] = r

    cand = {r["uid"]: r for r in rel("exclusion_candidates.csv")}
    aset = {r["scene_uid"]: r for r in rel("perk_analysis_set.csv")}
    link = {r["perk_scene_uid"]: r for r in rel("perk_overrides.csv")}
    n_nuc, n_roi = count_nuclei(), count_rois()

    rows, unparsed = [], []
    for m in man:
        uid, mk = m["scene_uid"], m["marker_channel"]
        f = focus.get(uid, {})
        k = keep.get(uid)
        e = excl.get(uid)
        a = aset.get(uid)

        # The pERK exclusion reason is always "PCNA partner excluded by the
        # operator" - the real one is on the PCNA side, reached through the
        # pairing. 04m established this; the same follow applies here.
        src = ""
        if e:
            src = e.get("reason", "")
            if mk == "AF568":
                lk = link.get(uid)
                partner = excl.get(lk["pcna_scene_uid"]) if lk else None
                src = (partner or {}).get("reason", "") or src
        klass, value = G4M.classify(src) if src else ("", None)
        if klass == "unparsed":
            unparsed.append(src)

        # 04f's numbers exist only for survivors; for an excluded section the
        # reason string is the only surviving record of the measurement.
        c = cand.get(uid)
        if mk == "AF568" and not c:
            lk = link.get(uid)
            c = cand.get(lk["pcna_scene_uid"]) if lk else None
        if c:
            qc_source, largest, total, pieces = ("exclusion_candidates",
                                                 c["largest_mm2"], c["total_mm2"],
                                                 c["n_pieces"])
            proposed = c["proposed"]
        else:
            qc_source = "reason_string" if value is not None else ""
            largest = value if klass == "no_tissue" else ""
            total = pieces = proposed = ""

        # What can be shown. An excluded PCNA section still has its reformatted
        # image; an excluded pERK section does not - see the module docstring.
        sec_dir = "sections" if mk == "AF488" else f"sections_{mk}"
        sec_rel = f"{sec_dir}/{uid}.png"
        ov_rel = f"../overviews/{m['animal']}/{mk}/{uid}_RGB.png"
        mask_rel = f"../artifacts/{uid}_artifact.png"

        ar = art.get(uid, {})
        n_obj = ""
        if ar:
            n_obj = int(ar.get("n_compact") or 0) + int(ar.get("n_elongated") or 0)

        # The furthest point this section reached. Ordered most-advanced first,
        # so a measured section reads as measured rather than as reformatted.
        if n_nuc.get(uid):
            status = "measured"
        elif n_roi.get(uid):
            status = "curated"
        elif e:
            status = "excluded"
        elif a and a["in_analysis_set"] == "0":
            status = "censored_out"
        elif k:
            status = "reformatted"
        else:
            status = "not_reformatted"

        rows.append({
            "scene_uid": uid, "animal": m["animal"], "marker": mk,
            "slide": m["slide"], "variant": m["variant"],
            "scene_index": m["scene_index"], "section_order": m["section_order"],
            "czi_file": m["file"],
            "status": status,
            "proposed_excluded": proposed,
            "decision": (e.get("decision") or "") if e else ("kept" if k else ""),
            "exclusion_class": klass,
            "decision_reason": src,
            "tissue_area_mm2": f.get("tissue_area_mm2", ""),
            "focus_score": f.get("focus_score", ""),
            "contrast": f.get("contrast", ""),
            "saturated_fraction": f.get("saturated_fraction", ""),
            "largest_mm2": largest, "total_mm2": total, "n_pieces": pieces,
            "qc_source": qc_source,
            "n_artifact_objects": n_obj,
            "artifact_pct_of_tissue": ar.get("artifact_pct_of_tissue", ""),
            "in_analysis_set": a["in_analysis_set"] if a else "",
            "censored_fraction_in_tissue": (a["censored_fraction_in_tissue"]
                                            if a else ""),
            "censor_reason": a["reason"] if a else "",
            "reformatted": 1 if k else 0,
            "angle": k["angle"] if k else "",
            "manual_rotation": (k.get("manual_rotation") or "") if k else "",
            "manual_flip": (k.get("manual_flip") or "") if k else "",
            "overview_img": ov_rel if os.path.exists(
                os.path.join(OVERVIEW_DIR, m["animal"], mk, uid + "_RGB.png")) else "",
            "section_img": sec_rel if os.path.exists(
                os.path.join(REFORMAT_DIR, sec_dir, uid + ".png")) else "",
            # The colour composite is a SEPARATE question from the greyscale.
            # Every one of the 2,572 has a greyscale section image now, but only
            # the 1,506 reformatted ones have a composite, so a viewer that
            # inferred one from the other would ask for 1,066 files that are not
            # there. 04o writes these; the marker decides the directory.
            "section_rgb": sec_rel.replace(sec_dir, sec_dir + "_rgb", 1)
            if os.path.exists(
                os.path.join(REFORMAT_DIR, sec_dir + "_rgb", uid + ".png")) else "",
            # The 256px colour thumbnail 04o --thumbs writes. Asked separately
            # from the composite for the same reason the composite is asked
            # separately from the greyscale: whether a file is there is a fact
            # about the disk, and a set built without thumbnails must degrade to
            # the composite rather than request one that was never made.
            "section_thumb": sec_rel.replace(sec_dir, sec_dir + "_rgb_thumb", 1)
            if os.path.exists(
                os.path.join(REFORMAT_DIR, sec_dir + "_rgb_thumb", uid + ".png")) else "",
            "mask_img": mask_rel if os.path.exists(
                os.path.join(MASK_DIR, uid + "_artifact.png")) else "",
            "tissue_img": f"../tissue/{uid}_tissue.png" if os.path.exists(
                os.path.join(TISSUE_DIR, uid + "_tissue.png")) else "",
            # WHETHER a censor mask exists, not which marker this is. 04j was
            # AF568-only when it read the 8-bit _MARK.png, because AF488's
            # display high sits below the 16-bit ceiling so a 255 there does not
            # mean clipped. Reading the raw data removed that limit and both
            # channels now have masks, so anything keyed on the marker is
            # already wrong.
            "censor_img": f"../censor/{uid}_censor.png" if os.path.exists(
                os.path.join(CENSOR_DIR, uid + "_censor.png")) else "",
            "n_rois": n_roi.get(uid, 0), "n_nuclei": n_nuc.get(uid, 0),
        })

    rows.sort(key=lambda r: (r["animal"], r["marker"],
                             int(r["section_order"] or 0)))

    # After the table is built, so the mask pass has the marker per section, and
    # before it is written, so tissue_img reflects what was just made.
    if args.tissue_masks:
        write_tissue_masks(rows, force=args.force)
        for r in rows:
            if os.path.exists(os.path.join(TISSUE_DIR,
                                           r["scene_uid"] + "_tissue.png")):
                r["tissue_img"] = f"../tissue/{r['scene_uid']}_tissue.png"

    os.makedirs(REFORMAT_DIR, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    st = Counter(r["status"] for r in rows)
    print("=" * 72)
    print(f"{len(rows)} scanned sections -> {OUT_CSV}")
    print(f"  by marker  : {dict(Counter(r['marker'] for r in rows))}")
    print(f"  status     : {dict(st)}")
    print(f"  exclusion  : {dict(Counter(r['exclusion_class'] for r in rows if r['exclusion_class']))}")
    print(f"  reformatted: {sum(r['reformatted'] for r in rows)}")
    print(f"  showable   : {sum(1 for r in rows if r['section_img'])} in the "
          f"analysis frame, {sum(1 for r in rows if not r['section_img'])} as the "
          f"original scan only")
    print(f"  masks      : {sum(1 for r in rows if r['mask_img'])} artifact, "
          f"{sum(1 for r in rows if r['censor_img'])} censor, "
          f"{sum(1 for r in rows if r['tissue_img'])} tissue")
    if unparsed:
        print(f"  UNPARSED reasons: {len(unparsed)} e.g. {unparsed[:2]}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
