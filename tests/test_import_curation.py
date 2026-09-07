"""`04q_import_curation` - the curator's exports turned back into seed state.

This is the path that decides WHERE EVERY ROI SITS when curation comes back from
a browser, and almost everything it can get wrong is quiet:

  * a global K reproduces one set of sections exactly and displaces every ROI in
    the other by 3x - on a page that loads without complaint and puts the discs
    somewhere plausible;
  * scaling the plate coordinates too would break the transform while leaving
    the section points looking right;
  * a background disc that loses its "bg" marker becomes an ROI, and one that
    keeps it but loses its radius becomes an ROI-sized disc - both change what
    the false-positive rate is measured on;
  * a dropped `excl`/`fav` flag silently reinstates sections the operator threw
    out, or loses the subset they marked;
  * a coordinate row for a section with no plates row means the three files did
    not come from one export, which has to be said rather than crashed on.

None of those raise. All of them produce a page that opens and looks curated.

Run:  python tests/test_import_curation.py
"""

import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

# This suite imports stage modules, which read config at import. Without a
# config of its own it would fall through to the operator's live study and
# then pass or fail on their data. See tests/_fixture.py.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _fixture import use_temp_study  # noqa: E402

STUDY = use_temp_study()

_spec = importlib.util.spec_from_file_location(
    "q4", os.path.join(SCRIPTS, "04q_import_curation.py"))
Q = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(Q)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(56) + " %r" % (got,)
          + ("" if ok else "   want %r" % (want,)))


def close(label, got, want, tol=1e-9):
    global fails
    ok = abs(got - want) <= tol
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(56) + " %r" % (got,)
          + ("" if ok else "   want %r" % (want,)))


# Two sections, deliberately at DIFFERENT scales and different markers: the
# pERK one is displayed as a 768px composite (K=3), the PCNA one as the 256px
# greyscale (K=1). A global K cannot satisfy both, which is the point.
PLATES = [
    {"scene_uid": "A_s01a_sc00", "marker": "AF568", "plate_id": "plate_010",
     "plate_index": "9", "status": "registered", "favorite": "0",
     "view_rotation_deg": "12.5", "excluded": "0"},
    {"scene_uid": "B_s01b_sc00", "marker": "AF488", "plate_id": "",
     "plate_index": "", "status": "favourite_only", "favorite": "1",
     "view_rotation_deg": "0.0", "excluded": "0"},
    {"scene_uid": "C_s02a_sc00", "marker": "AF568", "plate_id": "",
     "plate_index": "", "status": "excluded", "favorite": "0",
     "view_rotation_deg": "270.0", "excluded": "1"},
    {"scene_uid": "D_s02b_sc00", "marker": "AF488", "plate_id": "plate_003",
     "plate_index": "2", "status": "no_roi", "favorite": "0",
     "view_rotation_deg": "0.0", "excluded": "0"},
]

LANDMARKS = [
    {"scene_uid": "A_s01a_sc00", "sec_x": "10.38", "sec_y": "97.28",
     "sec_r": "9.69", "plate_x": "141.85", "plate_y": "498.17", "seed_n": "1"},
    # no seed_n: a landmark not answering a numbered atlas ROI
    {"scene_uid": "A_s01a_sc00", "sec_x": "14.75", "sec_y": "118.07",
     "sec_r": "14.19", "plate_x": "146.94", "plate_y": "630.78", "seed_n": ""},
    {"scene_uid": "B_s01b_sc00", "sec_x": "20.00", "sec_y": "30.00",
     "sec_r": "8.00", "plate_x": "11.00", "plate_y": "22.00", "seed_n": "2"},
]

REGIONS = [
    {"scene_uid": "A_s01a_sc00", "roi_kind": "background", "sec_x": "13.60",
     "sec_y": "73.68", "sec_r": "8.00"},
    {"scene_uid": "B_s01b_sc00", "roi_kind": "background", "sec_x": "50.00",
     "sec_y": "60.00", "sec_r": "5.50"},
    # ROI rows are already carried by roi_landmarks.csv and must NOT be added
    # again here, or every placed ROI would be duplicated.
    {"scene_uid": "A_s01a_sc00", "roi_kind": "roi", "sec_x": "10.38",
     "sec_y": "97.28", "sec_r": "9.69"},
    # A DRAWN REGION. This is the one thing roi_regions.csv holds that
    # roi_landmarks.csv cannot supply, so it is also the one thing a round trip
    # can silently lose. On the K=3 section, to prove the vertices go through
    # the same per-section scale as sec_x/sec_y and not some other one.
    {"scene_uid": "A_s01a_sc00", "roi_kind": "roi", "roi_shape": "polygon",
     "region": "Dl", "part": "2", "sec_x": "15.00", "sec_y": "15.00",
     "sec_r": "", "roi_n": "4", "landmarks_at_draw": "2",
     "sec_poly": "10.00 10.00;20.00 10.00;20.00 20.00;10.00 20.00"},
]

# Under three corners is not a shape. Kept OUT of the fixture above so that
# `skipped` stays empty there and goes on meaning "a well-formed export loses
# nothing" - a refusal folded into that list would have made the assertion pass
# for the wrong reason ever after.
BAD_POLY = [
    {"scene_uid": "B_s01b_sc00", "roi_kind": "roi", "roi_shape": "polygon",
     "region": "Dm", "part": "1", "sec_x": "0", "sec_y": "0", "sec_r": "",
     "sec_poly": "1.00 1.00;2.00 2.00"},
]

# The scale the real page implies for these two, without touching a disk.
K = {"A_s01a_sc00": 3.0, "B_s01b_sc00": 1.0, "C_s02a_sc00": 3.0,
     "D_s02b_sc00": 1.0}


def k_of(uid, marker):
    return K.get(uid, 1.0)


def main():
    state, skipped = Q.build(PLATES, LANDMARKS, REGIONS, k_of)

    # ---- the scale is per section ------------------------------------------
    a = state["A_s01a_sc00"]["pairs"][0]
    b = state["B_s01b_sc00"]["pairs"][0]
    close("K=3 section: sec_x scaled", a[0], 31.14)
    close("...sec_y scaled", a[1], 291.84)
    close("...and the radius with it", a[5], 29.07)
    close("K=1 section in the SAME import is not scaled", b[0], 20.0)
    close("...nor its radius", b[5], 8.0)

    # The trap this stage exists for: one global K would have to be 3 or 1, and
    # either way one of these two moves.
    chk("the two sections did not share a scale",
        (a[0] / 10.38, b[0] / 20.0), (3.0, 1.0))

    # ---- the plate frame is not the section frame ---------------------------
    close("plate_x is left alone", a[2], 141.85)
    close("plate_y is left alone", a[3], 498.17)

    # ---- pair shape --------------------------------------------------------
    chk("a landmark pair has six elements", len(a), 6)
    chk("seed_n is carried", a[4], 1)
    chk("a landmark with no seed_n gets 0",
        state["A_s01a_sc00"]["pairs"][1][4], 0)

    bg = [p for p in state["A_s01a_sc00"]["pairs"] if len(p) > 6]
    chk("the background disc is marked", bg[0][6], Q.BG_MARK)
    chk("...and answers no plate point", bg[0][2:5], [0, 0, 0])
    close("...at its own scaled radius", bg[0][5], 24.0)   # 8.00 * 3

    # An ROI row in roi_regions.csv is the same pair roi_landmarks.csv already
    # carried; counting both would double every placed ROI.
    chk("ROI rows in regions are not re-added",
        len(state["A_s01a_sc00"]["pairs"]), 3)   # 2 landmarks + 1 background

    # ---- a drawn region survives the round trip ----------------------------
    pg = state["A_s01a_sc00"]["polys"]
    chk("the polygon came back", len(pg), 1)
    chk("...with its region", pg[0]["region"], "Dl")
    chk("...and its lobe", pg[0]["part"], 2)
    chk("...as a flat x,y list, the shape the page stores",
        pg[0]["v"], [30.0, 30.0, 60.0, 30.0, 60.0, 60.0, 30.0, 60.0])
    # 10.00 * 3: the vertices ride the SAME per-section K as sec_x and sec_y.
    # Scaling them by anything else would put a region somewhere the operator
    # never drew one, on a page that opens without complaint.
    chk("the vertices took this section's own scale, not a global one",
        [v / 10.0 for v in pg[0]["v"][:2]], [3.0, 3.0])
    bad, bad_skip = Q.build(PLATES, [], BAD_POLY, k_of)
    chk("a two-corner row is refused rather than imported as a shape",
        bad["B_s01b_sc00"]["polys"], [])
    chk("...and is reported rather than dropped in silence",
        [k for k, _u in bad_skip], ["polygon"])
    # A polygon is not a pair. Adding it to `pairs` would put a shape into the
    # landmark fit, whose (0, 0) plate point would drag the whole transform.
    chk("the polygon did not join the pairs",
        len(state["A_s01a_sc00"]["pairs"]), 3)
    # An export written before polygons existed has no roi_shape column at all.
    chk("a pre-polygon import still yields an empty polys list",
        state["C_s02a_sc00"]["polys"], [])

    # The ROI NUMBER has to survive. It is what the guided cursor reads to know a
    # re-imported section is already done; without it the walk would ask for
    # every region again on a section that was finished weeks ago.
    chk("the polygon's ROI number came back", pg[0]["roi"], 4)
    noroi, _s = Q.build(PLATES, [], [dict(REGIONS[-1], roi_n="")], k_of)
    chk("...and a row written before roi_n existed imports as 0",
        noroi["A_s01a_sc00"]["polys"][0]["roi"], 0)

    # The ORDER STAMP. `z` compares a region's age against the landmarks by it,
    # and the curator rebuilds polys from this file, so a stamp that does not
    # survive here does not survive at all.
    chk("the order stamp came back", pg[0]["n"], 2)
    zero, _s = Q.build(PLATES, [], [dict(REGIONS[-1], landmarks_at_draw="0")], k_of)
    chk("...and 0 is a stamp, not a missing one - a region drawn before any "
        "landmark", zero["A_s01a_sc00"]["polys"][0]["n"], 0)
    # Absent has to stay absent rather than defaulting: the curator reads an
    # unstamped region as the newer of the two, and a 0 invented here would
    # assert the opposite - that it was drawn before every landmark on the
    # section - about a file that never said so.
    older = {k: v for k, v in REGIONS[-1].items() if k != "landmarks_at_draw"}
    pre, _s = Q.build(PLATES, [], [older], k_of)
    chk("a row written before the column carries no stamp at all",
        "n" in pre["A_s01a_sc00"]["polys"][0], False)

    # ---- the decision flags ------------------------------------------------
    chk("a named plate reads as assigned", state["A_s01a_sc00"]["assigned"], True)
    chk("...and carries its index", state["A_s01a_sc00"]["plate"], 9)
    chk("no plate named, not assigned", state["B_s01b_sc00"]["assigned"], False)
    chk("...and the index falls back to 0", state["B_s01b_sc00"]["plate"], 0)
    chk("favourite is read", state["B_s01b_sc00"]["fav"], True)
    chk("exclusion is read", state["C_s02a_sc00"]["excl"], True)
    chk("...and does not also mark it favourite", state["C_s02a_sc00"]["fav"], False)
    chk("no_roi is read from status", state["D_s02b_sc00"]["noroi"], True)
    chk("...and only from that status", state["A_s01a_sc00"]["noroi"], False)
    chk("rotation survives", state["C_s02a_sc00"]["rot"], 270)
    chk("a whole rotation is written as an int, like the page does",
        isinstance(state["C_s02a_sc00"]["rot"], int), True)

    # ---- every section is present, decision or not -------------------------
    chk("every plates row becomes a section", len(state), 4)
    chk("an excluded section still carries its pairs list",
        state["C_s02a_sc00"]["pairs"], [])
    chk("no coordinate rows were dropped", skipped, [])

    # ---- a coordinate row with no plates row -------------------------------
    orphan, sk = Q.build(
        PLATES,
        LANDMARKS + [{"scene_uid": "GHOST", "sec_x": "1", "sec_y": "2",
                      "sec_r": "3", "plate_x": "4", "plate_y": "5", "seed_n": ""}],
        REGIONS + [{"scene_uid": "GHOST2", "roi_kind": "background",
                    "sec_x": "1", "sec_y": "2", "sec_r": "3"}],
        k_of)
    chk("an orphan landmark is reported, not invented",
        ("landmark", "GHOST") in sk, True)
    chk("...and an orphan background disc too",
        ("background", "GHOST2") in sk, True)
    chk("...and neither creates a section", "GHOST" in orphan, False)

    # ---- counts, which are what the operator reads back --------------------
    c = Q.counts(state)
    chk("counts: sections", c["sections"], 4)
    chk("counts: excluded", c["excluded"], 1)
    chk("counts: favourites", c["favourites"], 1)
    chk("counts: assigned", c["assigned"], 2)
    chk("counts: landmark pairs", c["landmarks"], 3)
    chk("counts: background discs", c["background"], 2)

    # ---- compare() names work that exists only on disk ---------------------
    tmp = tempfile.mkdtemp(prefix="lsimp_")
    try:
        disk = os.path.join(tmp, "seed.json")
        with open(disk, "w", encoding="utf-8") as fh:
            json.dump({"A_s01a_sc00": state["A_s01a_sc00"],
                       "ONLY_ON_DISK": {"plate": 0, "pairs": [], "assigned": False,
                                        "noroi": False, "fav": True, "rot": 0,
                                        "excl": False}}, fh)
        d = Q.compare(state, disk)
        chk("compare: work only on disk is named", d["only_on_disk"], ["ONLY_ON_DISK"])
        chk("compare: unchanged sections are not flagged", d["changed"], [])
        chk("compare: the new ones are counted", len(d["added"]), 3)
        chk("compare: a missing file is not an error", Q.compare(state, disk + "x"), None)

        # ---- the CLI does not write unless asked ---------------------------
        import csv as _csv

        def dump(name, rows, fields):
            p = os.path.join(tmp, name)
            with open(p, "w", newline="", encoding="utf-8") as fh:
                w = _csv.DictWriter(fh, fieldnames=fields)
                w.writeheader()
                w.writerows(rows)
            return p

        pl = dump("p.csv", PLATES, list(PLATES[0]))
        lm = dump("l.csv", LANDMARKS, list(LANDMARKS[0]))
        # The UNION of every row's keys, in first-seen order. Taking the first
        # row's alone was fine while every region row was a disc; a polygon row
        # carries four columns a disc does not, and DictWriter raises on them.
        rgf = list(dict.fromkeys(k for r in REGIONS for k in r))
        rg = dump("r.csv", REGIONS, rgf)
        out = os.path.join(tmp, "written.json")
        argv = ["--plates", pl, "--landmarks", lm, "--regions", rg,
                "--out", out, "--no-rgb"]
        Q.main(argv)
        chk("a report-only run writes nothing", os.path.exists(out), False)
        Q.main(argv + ["--write"])
        chk("--write writes the file", os.path.exists(out), True)
        with open(out, encoding="utf-8") as fh:
            chk("...with every section in it", len(json.load(fh)), 4)

        # A second --write must not lose the first: the backup is the only copy
        # of whatever it overwrites.
        Q.main(argv + ["--write"])
        chk("a rewrite leaves a backup", os.path.exists(out + ".backup"), True)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("ALL PASS" if not fails else "%d FAILED" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
