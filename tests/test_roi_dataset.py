"""Stage 6a's three decisions, and the 06a/06c agreement that used to be absent.

06a turns ~895,000 nuclei into ~2,069 numbers, and every one of its decisions
fails quietly if it is wrong - a cut in the wrong place, an h from the wrong
grouping and a dropped artifact all still produce a plausible density. The
properties pinned here are the ones whose violation looks like a result:

  * the cut is a SPREAD, median + 3 * 1.4826 * MAD, not a percentile. A
    percentile would fix the false-positive rate by construction and destroy the
    only independent check the background discs exist to provide.
  * a section with fewer than 5 background nuclei gets NO cut, and its
    positivity columns go BLANK - not 0, which reads as "looked and found none".
  * h is measured per (marker, region), which is what config declares. Per
    animal, per slide or per section all still give a factor, and all put a
    group-varying correction into every density.
  * artifact nuclei leave entirely; censored nuclei count as POSITIVE and are
    excluded from the intensity median. Reversing either is 04j's stated error.
  * 06c reports the same n_nuclei and the same area as 06a. The two used to
    aggregate independently and had drifted; nothing compared them.
  * the two MARKERS stay apart. 06c and 06d keyed on (animal, region) with no
    marker, which was invisible while only pERK existed and would have summed
    AF568 + AF488 into one row the moment PCNA was measured.
  * a 06a that is one section BEHIND roi_nuclei.csv is a warning, not a
    failure - that is the ordinary state while 05c is still appending, and
    06e turns a failed refresh into ending the loop.
  * the nucleus-to-disc join is POSITIONAL, and 06a checks it. A nucleus
    names its disc by row position in roi_boxes_<marker>.csv, which 05a
    rewrites from the newest export; a disc inserted since detection shifts
    every later index on that section onto the wrong disc with plausible
    numbers. Every nucleus's box must agree on roi_kind and region.

Synthetic input throughout, so this runs on a machine with no imaging data.

Run:  python tests/test_roi_dataset.py
"""

import csv
import importlib.util
import os
import shutil
import statistics as st
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G6A = load("g6a", "06a_roi_dataset.py")
G5 = G6A.G5
# 05c imports StarDist lazily inside load_model(), so the module loads here
# and its file helpers can be tested as they are rather than as copies.
G5C = load("g5c", "05c_detect_rois.py")

fails = 0


def chk(label, got, want):
    global fails
    ok = str(got) == str(want)
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + str(got)
          + ("" if ok else "   want " + str(want)))


def close(label, got, want, tol=1e-6):
    global fails
    ok = abs(float(got) - float(want)) <= tol
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + f"{got:.4f}"
          + ("" if ok else f"   want {want:.4f}"))


# ---------------------------------------------------------------- the fixture
#
# S1 has 5 background nuclei - exactly the minimum - so it gets a cut, and the
# values are chosen so the MAD is not zero and the 1.4826 is actually tested.
# S2 has 4, one short, so it must get none.
BG_S1 = [80.0, 90.0, 100.0, 110.0, 120.0]        # median 100, MAD 10
CUT_S1 = 100.0 + 3.0 * 1.4826 * 10.0             # 144.478
DIAM = 10.0                                       # every ROI nucleus, so h = 10
AXIS = 1000.0                                     # semi-axes, both, in um

NUC_COLS = ["scene_uid", "animal", "marker", "roi_kind", "region", "seed_n",
            "roi_index", "nucleus_id", "czi_x", "czi_y", "sec_x", "sec_y",
            "area_um2", "equiv_diam_um", "dapi_mean", "marker_mean",
            "marker_median", "marker_p90", "censored", "artifact"]
BOX_COLS = ["scene_uid", "animal", "marker", "roi_kind", "region", "seed_n",
            "sec_x", "sec_y", "sec_r", "czi_file", "scene_index", "czi_cx",
            "czi_cy", "czi_x0", "czi_y0", "czi_w", "czi_h",
            "axis_a_um", "axis_b_um"]


def nucleus(uid, kind, region, idx, nid, value, diam=DIAM, cen=0, art=0,
            animal="LS01"):
    return {"scene_uid": uid, "animal": animal, "marker": "AF568",
            "roi_kind": kind, "region": region, "seed_n": "1",
            "roi_index": idx, "nucleus_id": nid, "czi_x": 0, "czi_y": 0,
            "sec_x": 128, "sec_y": 128, "area_um2": 50, "equiv_diam_um": diam,
            "dapi_mean": 1000, "marker_mean": value, "marker_median": value,
            "marker_p90": value, "censored": cen, "artifact": art}


def box(uid, kind, region, animal="LS01"):
    return {"scene_uid": uid, "animal": animal, "marker": "AF568",
            "roi_kind": kind, "region": region, "seed_n": "1",
            "sec_x": 128, "sec_y": 128, "sec_r": 20, "czi_file": "x.czi",
            "scene_index": 0, "czi_cx": 0, "czi_cy": 0, "czi_x0": 0,
            "czi_y0": 0, "czi_w": 100, "czi_h": 100,
            "axis_a_um": AXIS, "axis_b_um": AXIS}


def build(tmp):
    nuc, boxes = [], []

    # ---- S1: one ROI disc (index 1), one background disc (index 2)
    boxes.append(box("S1", "roi", "Dm"))
    boxes.append(box("S1", "background", "__background__"))
    nid = 0
    # Four uncensored ROI nuclei: 200 and 150 clear the cut, 100 and 140 do not.
    for v in (100.0, 200.0, 150.0, 140.0):
        nid += 1
        nuc.append(nucleus("S1", "roi", "Dm", 1, nid, v))
    # One censored, well BELOW the cut - it must still count as positive, and
    # must not drag the ROI's intensity median down.
    nid += 1
    nuc.append(nucleus("S1", "roi", "Dm", 1, nid, 5.0, cen=1))
    # One artifact, well above the cut - it must vanish entirely, from the
    # count, the positives and h alike.
    nid += 1
    nuc.append(nucleus("S1", "roi", "Dm", 1, nid, 9999.0, diam=99.0, art=1))
    for v in BG_S1:
        nid += 1
        nuc.append(nucleus("S1", "background", "__background__", 2, nid, v))

    # ---- S2: 4 background nuclei, one short of a cut
    boxes.append(box("S2", "roi", "Dm"))
    boxes.append(box("S2", "background", "__background__"))
    for v in (100.0, 200.0):
        nid += 1
        nuc.append(nucleus("S2", "roi", "Dm", 1, nid, v))
    for v in (80.0, 90.0, 110.0, 120.0):
        nid += 1
        nuc.append(nucleus("S2", "background", "__background__", 2, nid, v))

    npath = os.path.join(tmp, "roi_nuclei.csv")
    bpath = os.path.join(tmp, "roi_boxes.csv")
    for path, cols, rows in ((npath, NUC_COLS, nuc), (bpath, BOX_COLS, boxes)):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    return npath, bpath


def run_06a(tmp):
    """Point 06a at the fixture and run it, restoring the real paths after.

    `all_boxes` is patched rather than `BOX_CSV`, because 06a takes the UNION of
    every marker's box file - roi_nuclei.csv holds both once the PCNA pass has
    run. Patching the path alone silently gave 06a zero boxes and it wrote an
    empty file, which is how this seam was found.
    """
    keep = (G6A.NUCLEI_CSV, G6A.MEAS_CSV, G6A.SPEC_CSV, G5.BOX_CSV, G5.all_boxes)
    npath, bpath = build(tmp)
    G6A.NUCLEI_CSV = npath
    G6A.MEAS_CSV = os.path.join(tmp, "roi_measurements.csv")
    G6A.SPEC_CSV = os.path.join(tmp, "detector_specificity.csv")
    G5.BOX_CSV = bpath
    G5.all_boxes = lambda: G5.load_csv(bpath)
    # A REAL finally. Every check in this file runs in one process against one
    # shared G6A/G5 pair, so a leaked patch turns every later check into noise -
    # and the tempdir these paths point into is deleted on the way out, so the
    # leak would be into paths that no longer exist. The previous version had
    # `finally: pass` with the restore after it, which looks like this and is
    # not.
    try:
        rc = G6A.main()
        meas = G5.load_csv(G6A.MEAS_CSV)
        spec = (G5.load_csv(G6A.SPEC_CSV)
                if os.path.exists(G6A.SPEC_CSV) else [])
        paths = (npath, bpath, G6A.MEAS_CSV)
    finally:
        (G6A.NUCLEI_CSV, G6A.MEAS_CSV, G6A.SPEC_CSV, G5.BOX_CSV,
         G5.all_boxes) = keep
    return rc, meas, spec, paths


def two_marker_fixture(tmp):
    """One animal, one region, BOTH markers - which must not become one row.

    Its own fixture rather than three more sections in the main one, so the
    numbers the other assertions are built on stay where they are.
    """
    nuc, boxes = [], []
    nid = 0
    for uid, mk in (("M1", "AF568"), ("M2", "AF488")):
        boxes.append(dict(box(uid, "roi", "Dm"), marker=mk))
        boxes.append(dict(box(uid, "background", "__background__"), marker=mk))
        # AF488 nuclei are deliberately a different size, so a pooled h would
        # land between the two and match neither.
        diam = 10.0 if mk == "AF568" else 6.0
        for v in (100.0, 200.0, 150.0):
            nid += 1
            nuc.append(dict(nucleus(uid, "roi", "Dm", 1, nid, v, diam=diam),
                            marker=mk))
        for v in BG_S1:
            nid += 1
            nuc.append(dict(nucleus(uid, "background", "__background__", 2, nid, v),
                            marker=mk))

    # DISTINCT filenames. Sharing "roi_nuclei.csv" with build() silently
    # replaced the main fixture's nuclei file, and the next check then read S1
    # measurements against M1/M2 nuclei and reported them as orphaned - a
    # failure in the check that was really a failure in the fixture.
    npath = os.path.join(tmp, "m_nuclei.csv")
    bpath = os.path.join(tmp, "m_boxes.csv")
    for path, cols, rows in ((npath, NUC_COLS, nuc), (bpath, BOX_COLS, boxes)):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    return npath, bpath


def two_marker_check(tmp):
    """06a and 06c must keep AF568 and AF488 apart.

    This is a REGRESSION TEST, not a hypothetical. 06c and 06d keyed their
    aggregation on (animal, region) with no marker. That was invisible while
    only pERK had been measured and 06a read a single marker's box file, and it
    became certain once 06a started reading both: one row would have carried
    AF568 + AF488 summed into a single n_nuclei, under whichever marker's
    Abercrombie factor happened to be written last.
    """
    keep = (G6A.NUCLEI_CSV, G6A.MEAS_CSV, G6A.SPEC_CSV, G5.all_boxes)
    npath, bpath = two_marker_fixture(tmp)
    G6A.NUCLEI_CSV = npath
    G6A.MEAS_CSV = os.path.join(tmp, "m_measurements.csv")
    G6A.SPEC_CSV = os.path.join(tmp, "m_specificity.csv")
    G5.all_boxes = lambda: G5.load_csv(bpath)
    try:
        rc = G6A.main()
        meas = G5.load_csv(G6A.MEAS_CSV)
        mpath = G6A.MEAS_CSV
    finally:
        G6A.NUCLEI_CSV, G6A.MEAS_CSV, G6A.SPEC_CSV, G5.all_boxes = keep

    chk("two-marker: 06a exits 0", rc, 0)
    h = {r["marker"]: r["mean_nucleus_diam_um"]
         for r in meas if r["roi_kind"] == "roi"}
    chk("two-marker: 06a measures h PER MARKER", h.get("AF568") != h.get("AF488"), True)
    close("two-marker: AF568 h", float(h["AF568"]), 10.0, 0.005)
    close("two-marker: AF488 h", float(h["AF488"]), 6.0, 0.005)

    try:
        G6C = load("g6c2", "06c_excel_dataset.py")
        from openpyxl import load_workbook
    except Exception as exc:                                   # noqa: BLE001
        print(f"skip  two-marker 06c ({exc})")
        return
    G6C.NUCLEI_CSV, G6C.MEAS_CSV = npath, mpath
    G6C.G5.all_boxes = lambda: G6C.G5.load_csv(bpath)
    G6C.animal_environment = lambda: {}
    out = os.path.join(tmp, "m_dataset.xlsx")
    chk("two-marker: 06c exits 0", G6C.main(["--out", out]), 0)

    rows = list(load_workbook(out)["by_roi"].values)
    cols = list(rows[0])
    recs = [dict(zip(cols, r)) for r in rows[1:]]
    chk("two-marker: by_roi has a marker column", "marker" in cols, True)
    chk("two-marker: ONE ROW PER MARKER, not one pooled row", len(recs), 2)
    by_mk = {r["marker"]: r for r in recs}
    chk("two-marker: both markers present", sorted(by_mk), "['AF488', 'AF568']")
    for mk in ("AF568", "AF488"):
        # 3 ROI nuclei each; a pooled row would say 6.
        chk(f"two-marker: {mk} n_nuclei is its own", by_mk[mk]["n_nuclei"], 3)
    chk("two-marker: the two factors differ, so neither was overwritten",
        by_mk["AF568"]["abercrombie_factor"] != by_mk["AF488"]["abercrombie_factor"],
        True)


def behind_check(tmp, paths):
    """06c must tolerate a 06a that is one section behind, and refuse the reverse.

    06c is meant to be runnable while 05c is still appending, and 06e runs 06a
    at the head of each cycle - so any section finishing between 06a's read and
    06c's read leaves 06a legitimately behind. An equality check turned that
    ordinary race into a hard failure, and 06e escalates a failed refresh into
    ENDING the loop, so it would have killed the scenario it exists for.

    The other direction is a real error: 06a referencing sections the nuclei
    file does not have means the two are not from the same run at all.
    """
    npath, bpath, mpath = paths
    try:
        G6C = load("g6c3", "06c_excel_dataset.py")
    except Exception as exc:                                   # noqa: BLE001
        print(f"skip  behind-check ({exc})")
        return
    G6C.G5.all_boxes = lambda: G6C.G5.load_csv(bpath)
    G6C.animal_environment = lambda: {}
    out = os.path.join(tmp, "behind.xlsx")

    # 06a covers S1 only; the nuclei file still has S1 and S2. That is "behind".
    rows = [r for r in G6C.G5.load_csv(mpath) if r["scene_uid"] == "S1"]
    short = os.path.join(tmp, "behind_measurements.csv")
    with open(short, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    G6C.NUCLEI_CSV, G6C.MEAS_CSV = npath, short
    chk("06a behind roi_nuclei is a WARNING, not a failure",
        G6C.main(["--out", out]), 0)

    # The reverse: 06a naming a section the nuclei file has never heard of.
    rows2 = G6C.G5.load_csv(mpath)
    for r in rows2:
        r["scene_uid"] = "GHOST"
    orphan = os.path.join(tmp, "orphan_measurements.csv")
    with open(orphan, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows2[0].keys()))
        w.writeheader()
        w.writerows(rows2)
    G6C.MEAS_CSV = orphan
    chk("06a naming sections roi_nuclei lacks IS a failure",
        G6C.main(["--out", out]), 1)


def force_check(tmp):
    """05c --force must drop only its own marker's rows, and only its todo.

    THE ONLY PATH IN THE PIPELINE THAT DELETES MEASURED DATA. Both markers
    append to one roi_nuclei.csv, so opening it "w" to redo one would discard
    the other entirely - and that is hours of detection, not a number that can
    be recomputed. This used to be a copy of 05c's rewrite block, because 05c
    was thought unimportable without StarDist; the import is lazy, so the real
    `drop_rows` is exercised now. tests/test_detect_resume.py covers the
    `--limit` case and the header check in more detail.
    """
    cols = G5C.COLUMNS
    path = os.path.join(tmp, "force_nuclei.csv")

    def rec(uid, marker):
        r = dict.fromkeys(cols, "0")
        r.update(scene_uid=uid, marker=marker, roi_kind="roi", region="Dm")
        return [r[c] for c in cols]

    def seed(rows=None):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows(rows if rows is not None else
                        [rec("A1", "AF568"), rec("A2", "AF568"),
                         rec("A3", "AF568"), rec("B1", "AF488")])

    def uids():
        with open(path, newline="", encoding="utf-8") as fh:
            return [r["scene_uid"] for r in csv.DictReader(fh)]

    seed()
    G5C.drop_rows(path, "AF488", ["B1"])
    chk("--force AF488 keeps the pERK rows", uids(), "['A1', 'A2', 'A3']")
    chk("...and leaves no .tmp behind", os.path.exists(path + ".tmp"), False)

    seed()
    G5C.drop_rows(path, "AF568", ["A1", "A2", "A3"])
    chk("--force AF568 keeps the PCNA rows", uids(), "['B1']")

    # --force --limit 1: only the one section about to be redone goes.
    seed()
    G5C.drop_rows(path, "AF568", ["A2"])
    chk("--force --limit drops only the todo uid", uids(), "['A1', 'A3', 'B1']")

    # One marker only, everything dropped: the file must keep its header so
    # the caller can append to it.
    seed([rec("A1", "AF568")])
    dropped, kept = G5C.drop_rows(path, "AF568", ["A1"])
    chk("a single-marker file empties to its header", (dropped, kept), (1, 0))
    chk("...which is still there", uids(), [])


def join_check(tmp):
    """06a must refuse a nuclei/boxes pair whose positional join has shifted.

    A nucleus carries `roi_index`, the ROW POSITION of its disc in the box file
    for its section, and 06a joins on that. 05a rewrites roi_boxes_<marker>.csv
    from the newest curator export, so a disc inserted or removed after 05c ran
    moves every later index on that section: the nuclei of the background disc
    would be summed under an ROI, with a count and a density that look fine.
    Nuclei also carry roi_kind and region, so the box at each index can be
    checked against them.
    """
    bad = dict(box("S1", "roi", "Dl"))      # the disc someone added later
    cases = {
        "consistent": [box("S1", "roi", "Dm"), box("S1", "background", "__background__"),
                       box("S2", "roi", "Dm"), box("S2", "background", "__background__")],
        # inserted at position 2 on S1: the background nuclei (index 2) now
        # land on a Dl ROI disc
        "inserted": [box("S1", "roi", "Dm"), bad, box("S1", "background", "__background__"),
                     box("S2", "roi", "Dm"), box("S2", "background", "__background__")],
        # removed on S2: index 2 points past the end of the list
        "removed": [box("S1", "roi", "Dm"), box("S1", "background", "__background__"),
                    box("S2", "roi", "Dm")],
    }
    nuc = []
    for uid in ("S1", "S2"):
        nuc.append(nucleus(uid, "roi", "Dm", 1, 1, 100.0))
        nuc.append(nucleus(uid, "background", "__background__", 2, 2, 100.0))

    def by_uid(boxes):
        d = {}
        for b in boxes:
            d.setdefault(b["scene_uid"], []).append(b)
        return d

    orphans = G6A.check_join(nuc, by_uid(cases["consistent"]))
    chk("consistent nuclei/boxes pass the join check", sorted(orphans), [])

    for name, want in (("inserted", "S1"), ("removed", "S2")):
        other = "S2" if want == "S1" else "S1"
        try:
            G6A.check_join(nuc, by_uid(cases[name]))
            got = "no exit"
        except SystemExit as exc:
            got = str(exc)
        chk(f"a disc {name} after detection -> SystemExit", got != "no exit", True)
        chk(f"...naming {want}", want in got, True)
        chk(f"...and not the untouched {other}", other not in got, True)
        chk("...with the two ways out", "--force" in got and "roi_boxes" in got, True)

    # A section in the nuclei file with no boxes at all is REPORTED, not fatal:
    # that is a box file regenerated without it, or a stale row, and 06a
    # already skips it - it just used to do so silently.
    nuc.append(nucleus("S9", "roi", "Dm", 1, 1, 100.0))
    orphans = G6A.check_join(nuc, by_uid(cases["consistent"]))
    chk("a section absent from every box file is reported, not fatal",
        sorted(orphans), "['S9']")

    # And main() runs it: the fixture on disk with the inserted disc must
    # stop 06a before it writes anything.
    npath, bpath = build(tmp)
    boxes = G5.load_csv(bpath)
    boxes.insert(1, bad)
    with open(bpath, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=BOX_COLS)
        w.writeheader()
        w.writerows(boxes)
    keep = (G6A.NUCLEI_CSV, G6A.MEAS_CSV, G6A.SPEC_CSV, G5.all_boxes)
    G6A.NUCLEI_CSV = npath
    G6A.MEAS_CSV = os.path.join(tmp, "join_measurements.csv")
    G6A.SPEC_CSV = os.path.join(tmp, "join_specificity.csv")
    G5.all_boxes = lambda: G5.load_csv(bpath)
    try:
        try:
            G6A.main()
            got = "no exit"
        except SystemExit as exc:
            got = str(exc)
        chk("06a main() refuses the shifted join", got != "no exit", True)
        chk("...and wrote no measurements", os.path.exists(G6A.MEAS_CSV), False)
    finally:
        G6A.NUCLEI_CSV, G6A.MEAS_CSV, G6A.SPEC_CSV, G5.all_boxes = keep


def main():
    tmp = tempfile.mkdtemp(prefix="lsroi_")
    try:
        rc, meas, spec, paths = run_06a(tmp)
        chk("06a exits 0", rc, 0)
        by = {(r["scene_uid"], r["roi_kind"]): r for r in meas}
        chk("one row per disc", len(meas), 4)

        s1 = by[("S1", "roi")]

        # ---- the cut is a spread, and it is this section's own
        close("S1 cut is median + 3*1.4826*MAD",
              float(s1["section_positivity_cut"]), round(CUT_S1, 1), 0.05)
        chk("S1 background nuclei counted", s1["section_bg_nuclei"], 5)

        # ---- artifact out entirely, censored in the count
        chk("artifact nucleus dropped from the count", s1["n_nuclei"], 5)
        # 200 and 150 clear the cut, the censored one counts regardless.
        chk("censored counts positive, artifact does not", s1["n_positive"], 3)
        close("frac_positive", float(s1["frac_positive"]), 3 / 5)
        # median of the four UNCENSORED values 100, 140, 150, 200
        close("censored excluded from the intensity median",
              float(s1["marker_median_of_roi"]), st.median([100.0, 140.0, 150.0, 200.0]))

        # ---- h is the measured diameter, and the artifact's 99 um is not in it
        close("h is the measured diameter, artifact excluded",
              float(s1["mean_nucleus_diam_um"]), DIAM, 0.005)
        close("Abercrombie factor is T/(T+h)",
              float(s1["abercrombie_factor"]), 14.0 / (14.0 + DIAM), 5e-5)

        # ---- area is the ellipse, from the semi-axes
        import math
        close("area is pi*a*b, not pi*r^2 in curator pixels",
              float(s1["roi_area_um2"]), math.pi * AXIS * AXIS, 0.5)

        # ---- a drawn region reports the area 05a measured, not an ellipse
        #
        # A polygon has no semi-axes, so the two columns 06a used to read are
        # blank on its rows. Reading them would be a crash at best; falling back
        # to them silently would be a wrong number. `area_um2` is what 05a writes
        # for either shape, and it wins wherever it is present.
        chk("roi_area_um2 prefers area_um2 when 05a wrote one",
            G6A.roi_area_um2({"area_um2": "1234.5",
                              "axis_a_um": "1", "axis_b_um": "1"}), 1234.5)
        close("...and falls back to pi*a*b for a pre-polygon boxes file",
              G6A.roi_area_um2({"axis_a_um": "10", "axis_b_um": "4"}),
              math.pi * 40, 1e-9)
        chk("a polygon row, whose semi-axes are blank, still gives an area",
            G6A.roi_area_um2({"area_um2": "900.0",
                              "axis_a_um": "", "axis_b_um": ""}), 900.0)

        # ---- membership in a drawn region is a ring test on the 256 grid
        #
        # The same rule the disc always used - map the centroid back, decide
        # there - with "inside this circle" swapped for "inside this ring". A
        # concave shape is the case worth pinning: an operator tracing a lobe
        # produces one, and a convex-only test would quietly count the notch.
        sq = [(10, 10), (20, 10), (20, 20), (10, 20)]
        chk("a point in the middle is in", G5C.point_in_poly(15, 15, sq), True)
        chk("a point outside is out", G5C.point_in_poly(25, 15, sq), False)
        chk("...and one beyond a corner too", G5C.point_in_poly(21, 21, sq), False)
        # An L, notch on the top right. (18, 18) sits inside the bounding box and
        # outside the shape - exactly what an even-odd cast is for.
        ell = [(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)]
        chk("a concave shape excludes its notch",
            G5C.point_in_poly(18, 18, ell), False)
        chk("...and still includes the arms",
            (G5C.point_in_poly(15, 5, ell), G5C.point_in_poly(5, 15, ell)),
            (True, True))

        # ---- a section one background nucleus short gets NO cut, and blanks
        s2 = by[("S2", "roi")]
        chk("S2 gets no cut", s2["section_positivity_cut"], "")
        chk("S2 n_positive is BLANK, not 0", repr(s2["n_positive"]), repr(""))
        chk("S2 frac_positive is BLANK, not 0", repr(s2["frac_positive"]), repr(""))
        chk("S2 positive density is BLANK", repr(s2["positive_density_per_mm2"]),
            repr(""))
        chk("S2 still reports its count", s2["n_nuclei"], 2)
        chk("S2 still reports a density",
            s2["cell_density_per_mm2"] != "", True)

        # ---- the specificity file reports a MEASURED false-positive rate
        chk("one specificity row, for the section with a cut", len(spec), 1)
        if spec:
            # background values 80..120: only 120 is not above 144.478, so none
            # of them are - a spread-based cut on its own discs should find few.
            chk("false positives among the background", spec[0]["bg_false_positives"], 0)
            close("false-positive rate", float(spec[0]["false_positive_rate"]), 0.0)

        # ---- 06c must agree with 06a rather than re-deriving
        cross_check(tmp, paths, meas)

        # ---- and must keep the two markers apart
        two_marker_check(tmp)

        # ---- a 06a that is behind is normal mid-run, not a failure
        behind_check(tmp, paths)

        # ---- and --force must not take the other marker down with it
        force_check(tmp)

        # ---- and the positional nucleus-to-disc join must be checked
        join_check(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
    return 1 if fails else 0


def cross_check(tmp, paths, meas):
    """06c's by_roi must reproduce 06a's totals per (animal, region).

    This is the regression that was missing: the two carried independent
    implementations of the same aggregation and had drifted on h, and no test
    would have noticed.
    """
    npath, bpath, mpath = paths
    try:
        G6C = load("g6c", "06c_excel_dataset.py")
    except Exception as exc:                                   # noqa: BLE001
        print(f"skip  06c cross-check ({exc})")
        return
    if not hasattr(G6C, "MEAS_CSV"):
        print("skip  06c cross-check (06c has no MEAS_CSV - not refactored?)")
        return
    G6C.NUCLEI_CSV, G6C.MEAS_CSV = npath, mpath
    G6C.G5.BOX_CSV = bpath
    G6C.G5.all_boxes = lambda: G6C.G5.load_csv(bpath)
    # No workbook on a test machine, and none is needed: the join is not what
    # is being checked here.
    G6C.animal_environment = lambda: {}
    out = os.path.join(tmp, "roi_dataset.xlsx")
    try:
        rc = G6C.main(["--out", out])
    except ModuleNotFoundError as exc:                         # openpyxl
        print(f"skip  06c cross-check ({exc})")
        return
    chk("06c exits 0", rc, 0)
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError:
        print("skip  06c totals (no openpyxl)")
        return
    rows = list(load_workbook(out)["by_roi"].values)
    cols = list(rows[0])
    got = {}
    for r in rows[1:]:
        rec = dict(zip(cols, r))
        got[(rec["sample"], rec["ROI"])] = rec

    want_n, want_a, want_p = {}, {}, {}
    for r in meas:
        if r["roi_kind"] != "roi":
            continue
        k = (r["animal"], r["region"])
        want_n[k] = want_n.get(k, 0) + int(r["n_nuclei"])
        want_a[k] = want_a.get(k, 0.0) + float(r["roi_area_mm2"])
        if r["n_positive"] != "":
            want_p[k] = want_p.get(k, 0) + int(r["n_positive"])

    chk("06c has a row per (animal, region)", len(got), len(want_n))
    for k in want_n:
        chk(f"06c n_nuclei matches 06a {k}", got[k]["n_nuclei"], want_n[k])
        close(f"06c area matches 06a {k}", got[k]["total_tissue_area_mm2"],
              round(want_a[k], 6), 1e-6)
    # S2 had no cut, so the (LS01, Dm) cell mixes a disc with positives and one
    # without - which must go BLANK rather than report a partial sum.
    #
    # `in ("", None)` because openpyxl reads an empty cell back as None, not as
    # the empty string that was written. The property is "no number", and both
    # spellings satisfy it; asserting one of them would be testing openpyxl.
    chk("a cell with any uncut disc reports BLANK positivity",
        got[("LS01", "Dm")]["n_positive"] in ("", None), True)


if __name__ == "__main__":
    raise SystemExit(main())
