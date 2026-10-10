"""Abercrombie is applied where the objects are nuclei, and withheld elsewhere.

N = n * T/(T + h) assumes spherical, randomly positioned objects. A threshold
region on a fibre-stained channel is neither. Raw and corrected stay side by
side either way, and when the correction is withheld the reason is a value in
the output rather than something a reader has to infer from the config.

SYNTHETIC, AND THE WITHHELD SIDE HAS NEVER SEEN DATA. No study declares
`nucleus_shaped: false` - the live one is `paired` with two nuclear-segmented
markers - so what is guaranteed below is that the RULE is what the spec says,
not that it has been exercised on microscopy. The applied side is the route the
pipeline has always taken and is checked against the live study separately.

Run:  python tests/test_abercrombie_gate.py
"""

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from _fixture import use_temp_study, load_stage             # noqa: E402

STUDY = use_temp_study()
A6 = load_stage("06a_roi_dataset.py")
G5 = A6.G5

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


print("--- the gate itself ---")

chk("nuclear-segmented objects get the correction",
    A6.abercrombie_reason(segmented_on="DAPI", nucleus_shaped=True), "")
chk("own-segmented but nucleus-shaped objects get it too",
    A6.abercrombie_reason(segmented_on="pERK", nucleus_shaped=True), "")

why = A6.abercrombie_reason(segmented_on="GFAP", nucleus_shaped=False)
chk("objects that are not nucleus-shaped do not", bool(why), True)
chk("...and the reason names the assumption",
    "spherical" in why or "nucleus" in why.lower(), True)
chk("...and names the channel they came from", "GFAP" in why, True)

# The study's own switch is a withholding too, and it is in the reason for one
# reason: so that a BLANK cell means one thing only - the correction was
# applied. Otherwise `enabled: false` would emit factor 1.0 beside an empty
# reason, which reads as "corrected, and the factor happened to be 1.0".
off = A6.abercrombie_reason(segmented_on="DAPI", nucleus_shaped=True,
                            enabled=False)
chk("a study that disables the correction says so too", bool(off), True)
chk("...naming the config key", "abercrombie.enabled" in off, True)

print()
print("--- what the factor becomes when it is withheld ---")

chk("a withheld correction is 1.0, not blank",
    A6.abercrombie_factor(h=8.0, apply=False), 1.0)
chk("...so the corrected column equals the raw one",
    A6.abercrombie_factor(h=8.0, apply=True) < 1.0, True)
chk("...and an unmeasured h is 1.0 as well, as it always was",
    A6.abercrombie_factor(h=0.0, apply=True), 1.0)
chk("the applied factor is still T/(T+h)",
    round(A6.abercrombie_factor(h=8.0), 6),
    round(A6.T_UM / (A6.T_UM + 8.0), 6))

print()
print("--- absence means nuclear, which is what every old file is ---")

# THE LS COMPATIBILITY RULE. roi_nuclei.csv gained `nucleus_shaped` on
# 2026-09-08; every object in a file written before that came from the nuclear
# channel via StarDist, because that was the only route 05c had. Reading its
# silence as False would withhold the correction from 961,233 nuclei.
chk("a missing column reads as nucleus-shaped",
    A6.reads_nucleus_shaped(None), True)
chk("...and so does an empty cell", A6.reads_nucleus_shaped(""), True)
chk("'1' is nucleus-shaped", A6.reads_nucleus_shaped("1"), True)
chk("'0' is not", A6.reads_nucleus_shaped("0"), False)
chk("...nor is 'false'", A6.reads_nucleus_shaped("false"), False)


# ---------------------------------------------------------------------------
# The column has to be checked THROUGH THE EMIT PATH. 06a has no COLUMNS
# constant: at the write it does `list(data[0].keys())`, so the header is the
# first emitted row's keys and a key that only some rows carry would either
# vanish from the header or raise in the writer. Asserting on a constant would
# assert on nothing; this drives main() over a fixture and reads the header off
# the file.

NUC_COLS = ["scene_uid", "animal", "marker", "roi_kind", "region", "seed_n",
            "roi_index", "nucleus_id", "czi_x", "czi_y", "sec_x", "sec_y",
            "area_um2", "equiv_diam_um", "dapi_mean", "marker_mean",
            "marker_median", "marker_p90", "censored", "artifact",
            "off_tissue", "segmented_on", "backend", "nucleus_shaped"]
BOX_COLS = ["scene_uid", "animal", "marker", "roi_kind", "region", "seed_n",
            "sec_x", "sec_y", "sec_r", "czi_file", "scene_index", "czi_cx",
            "czi_cy", "czi_x0", "czi_y0", "czi_w", "czi_h",
            "axis_a_um", "axis_b_um"]
BG = [80.0, 90.0, 100.0, 110.0, 120.0]           # 5, the minimum for a cut


def box(uid, marker, kind, region):
    return {"scene_uid": uid, "animal": "LS01", "marker": marker,
            "roi_kind": kind, "region": region, "seed_n": "1",
            "sec_x": 128, "sec_y": 128, "sec_r": 20, "czi_file": "x.czi",
            "scene_index": 0, "czi_cx": 0, "czi_cy": 0, "czi_x0": 0,
            "czi_y0": 0, "czi_w": 100, "czi_h": 100,
            "axis_a_um": 1000.0, "axis_b_um": 1000.0}


def nucleus(uid, marker, kind, region, idx, nid, value, seg_on, shaped):
    return {"scene_uid": uid, "animal": "LS01", "marker": marker,
            "roi_kind": kind, "region": region, "seed_n": "1",
            "roi_index": idx, "nucleus_id": nid, "czi_x": 0, "czi_y": 0,
            "sec_x": 128, "sec_y": 128, "area_um2": 50, "equiv_diam_um": 10.0,
            "dapi_mean": 1000, "marker_mean": value, "marker_median": value,
            "marker_p90": value, "censored": 0, "artifact": 0, "off_tissue": 0,
            "segmented_on": seg_on, "backend": "stardist" if shaped else
            "threshold", "nucleus_shaped": "1" if shaped else "0"}


def fixture(tmp, drop_provenance=False):
    """Two markers on two sections: one nuclear, one not nucleus-shaped."""
    nuc, boxes = [], []
    nid = 0
    for uid, marker, seg_on, shaped in (("S1", "pERK", "DAPI", True),
                                        ("S2", "GFAP", "GFAP", False)):
        boxes.append(box(uid, marker, "roi", "Dm"))
        boxes.append(box(uid, marker, "background", "__background__"))
        for v in (100.0, 200.0, 150.0):
            nid += 1
            nuc.append(nucleus(uid, marker, "roi", "Dm", 1, nid, v,
                               seg_on, shaped))
        for v in BG:
            nid += 1
            nuc.append(nucleus(uid, marker, "background", "__background__",
                               2, nid, v, seg_on, shaped))

    cols = NUC_COLS
    if drop_provenance:
        # A roi_nuclei.csv written before 2026-09-08: the three columns are
        # not there at all, which is the LS file's shape.
        cols = [c for c in NUC_COLS
                if c not in ("segmented_on", "backend", "nucleus_shaped")]
    npath = os.path.join(tmp, "n.csv")
    bpath = os.path.join(tmp, "b.csv")
    for path, cs, rows in ((npath, cols, nuc), (bpath, BOX_COLS, boxes)):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cs, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    return npath, bpath


def run_06a(tmp, stem, **kw):
    """Point 06a at the fixture and run it, restoring the real paths after."""
    keep = (A6.NUCLEI_CSV, A6.MEAS_CSV, A6.SPEC_CSV, G5.all_boxes)
    npath, bpath = fixture(tmp, **kw)
    A6.NUCLEI_CSV = npath
    A6.MEAS_CSV = os.path.join(tmp, stem + "_measurements.csv")
    A6.SPEC_CSV = os.path.join(tmp, stem + "_specificity.csv")
    G5.all_boxes = lambda: G5.load_csv(bpath)
    try:
        rc = A6.main()
        with open(A6.MEAS_CSV, newline="", encoding="utf-8") as fh:
            header = next(csv.reader(fh))
        meas = G5.load_csv(A6.MEAS_CSV)
        paths = (npath, bpath, A6.MEAS_CSV)
    finally:
        A6.NUCLEI_CSV, A6.MEAS_CSV, A6.SPEC_CSV, G5.all_boxes = keep
    return rc, header, meas, paths


def emit_check(tmp):
    print()
    print("--- through the emit path, which is where the header comes from ---")

    rc, header, meas, _ = run_06a(tmp, "gate")
    chk("06a exits 0", rc, 0)
    chk("abercrombie_withheld_reason is a column of the written file",
        "abercrombie_withheld_reason" in header, True)
    chk("...and EVERY row carries it, blank included",
        all("abercrombie_withheld_reason" in r for r in meas), True)

    by_marker = {}
    for r in meas:
        by_marker.setdefault(r["marker"], []).append(r)

    perk = by_marker["pERK"]
    chk("the nuclear marker's reason is blank",
        {r["abercrombie_withheld_reason"] for r in perk}, {""})
    chk("...and its factor is below 1",
        all(float(r["abercrombie_factor"]) < 1.0 for r in perk), True)

    gfap = by_marker["GFAP"]
    chk("the fibre marker's factor is exactly 1.0",
        {r["abercrombie_factor"] for r in gfap}, {"1.0"})
    chk("...and every one of its rows says why",
        all("nucleus-shaped" in r["abercrombie_withheld_reason"]
            for r in gfap), True)
    chk("...naming the channel it was segmented on",
        all("GFAP" in r["abercrombie_withheld_reason"] for r in gfap), True)
    chk("...so its corrected density equals its raw one",
        {r["cell_density_per_mm2"] == r["profile_density_per_mm2"]
         for r in gfap}, {True})
    chk("...while the nuclear marker's does not",
        {r["cell_density_per_mm2"] == r["profile_density_per_mm2"]
         for r in perk}, {False})
    chk("h is still MEASURED and reported for the withheld marker",
        all(float(r["mean_nucleus_diam_um"]) > 0 for r in gfap), True)


def legacy_check(tmp):
    print()
    print("--- a file with no provenance columns is corrected, as it was ---")

    rc, header, meas, _ = run_06a(tmp, "legacy", drop_provenance=True)
    chk("06a exits 0 on a pre-provenance file", rc, 0)
    chk("...the column is still emitted",
        "abercrombie_withheld_reason" in header, True)
    chk("...blank on every row - nothing was withheld",
        {r["abercrombie_withheld_reason"] for r in meas}, {""})
    chk("...and every factor is the corrected one",
        all(float(r["abercrombie_factor"]) < 1.0 for r in meas), True)


def workbook_check(tmp):
    """And it has to REACH the workbook: a reason only in a CSV is not reported.

    06c owns no number - 06a computes each one once - so what is checked here
    is that the reason is CARRIED, and that the sheet's corrected density and
    its raw one agree wherever it is set.
    """
    print()
    print("--- the reason reaches the workbook ---")

    rc, header, meas, paths = run_06a(tmp, "wb")
    npath, bpath, mpath = paths
    C6 = load_stage("06c_excel_dataset.py")
    C6.NUCLEI_CSV, C6.MEAS_CSV = npath, mpath
    C6.G5.BOX_CSV = bpath
    C6.G5.all_boxes = lambda: C6.G5.load_csv(bpath)
    # No sampling workbook on a test machine, and the join is not what is
    # under test here.
    C6.animal_environment = lambda: {}
    out = os.path.join(tmp, "wb.xlsx")
    try:
        rc = C6.main(["--out", out])
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:                          # openpyxl
        print(f"skip  06c ({exc})")
        return
    chk("06c exits 0", rc, 0)

    rows = list(load_workbook(out)["by_roi"].values)
    cols = list(rows[0])
    recs = [dict(zip(cols, r)) for r in rows[1:]]
    chk("abercrombie_withheld_reason is a by_roi column",
        "abercrombie_withheld_reason" in cols, True)
    by_mk = {r["marker"]: r for r in recs}
    # openpyxl reads an empty cell back as None, not as the "" that was
    # written. The property is "no reason"; both spellings satisfy it.
    chk("the nuclear marker's cell is blank",
        by_mk["pERK"]["abercrombie_withheld_reason"] in ("", None), True)
    chk("the fibre marker's cell carries 06a's reason",
        "nucleus-shaped" in (by_mk["GFAP"]["abercrombie_withheld_reason"] or ""),
        True)
    chk("...beside a factor of 1.0",
        by_mk["GFAP"]["abercrombie_factor"], 1.0)
    chk("...so cells_per_mm2 is the uncorrected profile density",
        by_mk["GFAP"]["cells_per_mm2"], by_mk["GFAP"]["profiles_per_mm2"])
    chk("...while the nuclear marker's is corrected",
        by_mk["pERK"]["cells_per_mm2"] < by_mk["pERK"]["profiles_per_mm2"], True)


def main():
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="lsab_")
    try:
        emit_check(tmp)
        legacy_check(tmp)
        workbook_check(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("ALL PASS" if not failures else f"{len(failures)} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
