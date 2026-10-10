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

import sys
import argparse
import csv
import importlib.util
import json
import os
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
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
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
MASK_DIR = os.path.join(OUT_ROOT, "artifacts")

# The section-directory rule, borrowed rather than restated. ls_paths, not 04a:
# this stage builds a CSV and must not pull numpy, PIL and scipy in to answer a
# question about a filename. (04a IS imported, but lazily and only by
# --tissue, which really does need the image code.)
NAMES = LP.for_config(CONFIG)

# ---- which passes there are, and which one carries the pairing -------------
#
# `PARTNER` is the geometry source - the pass whose artifacts have the
# unsuffixed names, and which `04d` rotated by hand. It is the SECOND declared
# marker; see ls_paths.geometry_source, and note that `sec_dir`'s literal below
# had that exact fact inverted. `MEASURED` is the other pass, the one 04i
# propagated onto and 04j censored, and it is the side that carries the
# pairing. Under multiplex there is one scan per section, so there is no
# partner and no pairing: both are None and every follow-through below is
# skipped rather than aimed at the wrong marker.
MARKERS = list(CH.marker_names(CONFIG))
LAYOUT = (CONFIG.get("acquisition") or {}).get("layout", CH.LAYOUT_MULTIPLEX)
PARTNER = LP.geometry_source(MARKERS, LAYOUT)
MEASURED = (next((m for m in MARKERS if m != PARTNER), None)
            if PARTNER is not None else None)

# Whose analysis set describes THESE rows. Under paired that is the measured
# pass alone, and deliberately so: `pcna_analysis_set.csv` exists on the LS
# drive and describes the partner's 1,381 scenes, but 04l's Review pane has
# never seen those columns filled for them and this stage is not the place to
# start. Under multiplex every scene is its own row, so every declared marker's
# set applies.
ANALYSIS_MARKERS = [MEASURED] if MEASURED else list(MARKERS)

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

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

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


#: Files this run asked for and did not find. Reported at the end of main().
#:
#: ABSENT AND EMPTY ARE NOT THE SAME ANSWER, and collapsing them is how all
#: four of this stage's naming bugs stayed silent for as long as they did. A
#: header with no rows under it means "04a reformatted nothing yet"; a file
#: that is not there means "this stage is looking for a name nothing writes" -
#: which is what `reformat_index_AF568.csv` was for every study that is not LS.
#: Both produced [], both produced a full 2,572-row table, and the only
#: difference was that every row of it said `not_reformatted`.
#:
#: Recorded rather than raised, because most of these files legitimately do not
#: exist yet on a part-run study, and this table is exactly what an operator
#: builds to find out how far a run got. A miss is now printed by name.
MISSING = []


def load(path, required=False):
    """Rows from a CSV. A file that is not there is RECORDED, not ignored.

    `required=True` for the inputs without which the table is meaningless
    rather than incomplete - the manifest is the universe this stage is a join
    over, and an empty universe is not a fact about the study.
    """
    if not os.path.exists(path):
        if required:
            raise SystemExit(
                f"{path} is not there, and every row of section_provenance.csv "
                "is a row of it. Run the stage that writes it first; an empty "
                "table here would read as a study in which nothing was ever "
                "scanned.")
        if path not in MISSING:
            MISSING.append(path)
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def rel(name):
    return load(os.path.join(REFORMAT_DIR, name))


def section_dir(marker):
    """The directory 04a wrote this marker's sections into, as a bare name.

    A NAME, not a path: it goes into `section_provenance.csv` as part of a URL
    the curator page resolves relative to itself.

    The literal this replaces was `"sections" if mk == "AF488" else
    f"sections_{mk}"` - which is EXACTLY INVERTED for any other pair. The
    unsuffixed directory belongs to the geometry source, and the geometry
    source is the SECOND declared marker; hardcoding AF488 pinned that role to
    a fluorophore name, so for a study with markers ["Mk1", "Mk2"] the default
    marker Mk2 was sent to `sections_Mk2` (which 04a never wrote) and Mk1 to
    `sections` (which holds Mk2's). Every thumbnail in the Review pane's grid
    then came back blank, or - worse - showed the other marker's section.

    `including()` because `marker` is the manifest's `marker_channel` column,
    which can name a channel this config does not declare as a marker.
    """
    return NAMES.including(marker).basename("sections", marker)


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

    The names come from ls_paths, which holds 05a's rule rather than restating
    it: `roi_boxes_<marker>.csv`, with the pre-2026-09-01 `roi_boxes.csv`
    adopted only when it is on the drive and the suffixed one is not - and only
    together with `roi_geometry.csv`, which is `05a.resolve_paths`'s own
    condition (05a:142-155) reproduced in `ls_paths.LEGACY_GROUPS`.

    The two literals this replaces were `roi_boxes_AF568.csv` and
    `roi_boxes_AF488.csv`, which for any other study match nothing at all. The
    consequence is not a blank column: `n_rois` is 0 for every section, no
    section ever reaches `status = "curated"`, and the Review pane shows a
    fully curated study as untouched.

    ls_paths and not `05a.box_csv`, which the plan asked for: 05a imports
    numpy, PIL and czi_read at module level, and this stage says in
    `section_dir` below that it must not pull the image stack in to answer a
    question about a filename.

    Scene uids are disjoint across the markers of a paired study - they are
    separate acquisitions - so this is a union, not a merge. A file that is not
    there is recorded by `load` rather than passed over.
    """
    out = Counter()
    for m in MARKERS:
        for r in load(NAMES.read("roi_boxes", m)):
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
    man = load(MANIFEST_CSV, required=True)
    focus = {r["scene_uid"]: r for r in load(FOCUS_CSV)}

    # Per marker: the index of survivors, the exclusion list, the artifact
    # summary. The literal tuple this replaces named six files after two
    # fluorophores, so for any other study none of the three suffixed ones
    # existed, `load` returned [] for each, and every section of the measured
    # pass fell to `status = "not_reformatted"` - including the ones 04a had
    # reformatted. The unsuffixed three still matched by accident, which made
    # the failure look like a one-marker problem rather than a naming one.
    #
    # Scene uids are disjoint across the markers of a paired study, so these
    # three dicts are unions and the iteration order does not decide anything.
    keep, excl, art = {}, {}, {}
    for m in MARKERS:
        keep.update({r["id"]: r for r in load(NAMES.read("index", m))
                     if r["kind"] == "section"})
        excl.update({r["scene_uid"]: r for r in load(NAMES.read("excluded", m))})
        for r in load(NAMES.read("artifact_summary", m)):
            art[r["scene_uid"]] = r

    cand = {r["uid"]: r for r in rel("exclusion_candidates.csv")}
    aset = {}
    for m in ANALYSIS_MARKERS:
        aset.update({r["scene_uid"]: r for r in load(NAMES.read("analysis_set", m))})

    # The pairing, and the two columns it is keyed on. 04m owns both - it does
    # the same join over the same file - so they are imported rather than
    # spelled out a second time here. Under multiplex there is no partner pass
    # and no pairing file to read: `link` stays empty and `src_col` is None,
    # which is what the `mk == MEASURED` guards below test for.
    link, src_col = {}, None
    if MEASURED and PARTNER:
        overrides = G4M.overrides_csv()
        if os.path.exists(overrides):
            link_header, link_rows = G4M.load_header(overrides)
            uid_col, src_col = G4M.override_columns(link_header)
            link = {r[uid_col]: r for r in link_rows}
        elif overrides not in MISSING:
            MISSING.append(overrides)
    n_nuc, n_roi = count_nuclei(), count_rois()

    rows, unparsed = [], []
    for m in man:
        uid, mk = m["scene_uid"], m["marker_channel"]
        f = focus.get(uid, {})
        k = keep.get(uid)
        e = excl.get(uid)
        a = aset.get(uid)

        # The measured pass's exclusion reason is always "partner excluded by
        # the operator" - the real one is on the partner's side, reached
        # through the pairing. 04m established this; the same follow applies
        # here. `mk == MEASURED` and not `mk == "AF568"`: the literal pinned
        # this to a fluorophore, so for any other pair the follow never fired
        # and the reason stayed the placeholder. MEASURED is None under
        # multiplex, where no manifest row can match it and there is nothing
        # to follow.
        src = ""
        if e:
            src = e.get("reason", "")
            if mk == MEASURED:
                lk = link.get(uid)
                partner = excl.get(lk[src_col]) if lk else None
                src = (partner or {}).get("reason", "") or src
        klass, value = G4M.classify(src) if src else ("", None)
        if klass == "unparsed":
            unparsed.append(src)

        # 04f's numbers exist only for survivors; for an excluded section the
        # reason string is the only surviving record of the measurement.
        c = cand.get(uid)
        if mk == MEASURED and not c:
            lk = link.get(uid)
            c = cand.get(lk[src_col]) if lk else None
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
        sec_dir = section_dir(mk)
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
    IO.atomic_write_csv(OUT_CSV, rows, COLUMNS)

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
    if MISSING:
        # Named, because every failure in this table is otherwise silent. Some
        # of these are legitimately absent on a part-run study; a name this
        # stage derived and nothing ever writes is not, and the two are only
        # distinguishable if the list is printed.
        print(f"  not found  : {len(MISSING)} input(s) this run asked for")
        for p in MISSING:
            print(f"      {os.path.relpath(p, OUT_ROOT)}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
