"""05c segments each marker the way the study declares it.

SYNTHETIC, AND SAY SO. No study declares `segment: own` and none is
`multiplex`, so nothing here has met a real section. What these checks
guarantee is the DISPATCH and the recorded provenance - which plane is
segmented, which backend runs, and what lands in the three new columns - not
that a threshold backend segments a real fibre stain usefully. The first study
that declares `segment: own` will find things these cannot.

The half that DOES matter today is the paired half. The live LS study is
`paired`, declares no channel table at all, and both its markers take the
route that already existed: segment the nuclear plane with StarDist, measure
the marker inside the nuclear mask. That is driven here end to end against a
fake reader and a fake model, and the numbers in the written row are checked -
because "the live study must not move" is not a thing to assume.

Run:  python tests/test_detect_backends.py
"""

import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from _fixture import temp_study, load_stage                  # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


MULTIPLEX = {"layout": "multiplex", "channels": [
    {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
    {"name": "pERK", "role": "marker", "czi_name": "AF568", "index": 1,
     "segment": "nuclear"},
    {"name": "GFAP", "role": "marker", "czi_name": "AF647", "index": 2,
     "segment": "own", "backend": "threshold", "nucleus_shaped": False}]}

#: The live study's shape: two markers, no channel table, no declared nuclear
#: channel. `_BY_NAME` is EMPTY for it, so every helper here has to answer from
#: its fallback rather than from a channel.
PAIRED = {"layout": "paired", "markers": ["AF568", "AF488"], "channels": []}


# --------------------------------------------------------------------------
# Driving 05c's real detection loop without a CZI, StarDist, or the operator's
# data. Same approach as tests/test_detect_resume.py, which pins what reaches
# doc.read(); this adds a model that returns known objects, so what reaches the
# OUTPUT ROW can be checked too.

class FakeCzi:
    """Returns a fixed plane per channel index, and records every read."""

    def __init__(self, planes):
        self.planes = planes
        self.calls = []

    def read(self, **kwargs):
        self.calls.append(kwargs)
        return self.planes[int(kwargs["plane"]["C"])]


class FakeOpenCzi:
    """Stands in for pylibCZIrw.czi.open_czi."""

    def __init__(self, doc):
        self.doc = doc

    def __call__(self, path, *a, **kw):
        return self

    def __enter__(self):
        return self.doc

    def __exit__(self, *exc):
        return False


class FakeModel:
    """A StarDist stand-in that returns one known object and records its input.

    Recording the call is the point: a run that never touches this has not
    taken the stardist route, whatever its output columns say.
    """

    def __init__(self, labels):
        self.labels = labels
        self.calls = []

    def predict_instances(self, img, **kw):
        self.calls.append(np.asarray(img))
        return self.labels, {}


BOX = (100, 100, 24, 20)                   # x0, y0, w, h in CZI px
SEC = (112, 110, 50)                       # sec_x, sec_y, sec_r on the 256 grid


def drive(D5, marker, uid, planes, model_labels):
    """Run 05c.main() over one section and one ROI. Returns (fake, model, rows).

    The affine is the identity, so a CZI coordinate IS a grid coordinate and
    the box at (100, 100) sits inside the disc at (112, 110) r=50.
    """
    import pylibCZIrw.czi as pyczi

    x0, y0, bw, bh = BOX
    sx, sy, sr = SEC
    D5.G5.use_marker(marker)
    os.makedirs(D5.REFORMAT_DIR, exist_ok=True)

    geom_row = {"scene_uid": uid, "animal": "AB12", "marker": marker,
                "czi_file": "AB12_1a.czi", "scene_index": "6",
                "m00": "1", "m01": "0", "m02": "0",
                "m10": "0", "m11": "1", "m12": "0"}
    with open(D5.G5.GEOM_CSV, "w", newline="\n", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(geom_row))
        w.writeheader()
        w.writerow(geom_row)

    box_row = {"scene_uid": uid, "animal": "AB12", "marker": marker,
               "roi_kind": "roi", "region": "Dm", "seed_n": "1",
               "czi_x0": str(x0), "czi_y0": str(y0),
               "czi_w": str(bw), "czi_h": str(bh),
               "sec_x": str(sx), "sec_y": str(sy), "sec_r": str(sr),
               "sec_poly": ""}
    with open(D5.G5.BOX_CSV, "w", newline="\n", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(box_row))
        w.writeheader()
        w.writerow(box_row)

    mask_dir = os.path.join(D5.REFORMAT_DIR, "sections")
    os.makedirs(mask_dir, exist_ok=True)
    np.save(os.path.join(mask_dir, f"{uid}_mask.npy"),
            np.ones((256, 256), dtype=bool))

    fake = FakeCzi(planes)
    model = FakeModel(model_labels)
    saved = (pyczi.open_czi, D5.load_model, sys.argv)
    pyczi.open_czi = FakeOpenCzi(fake)
    D5.load_model = lambda: model
    sys.argv = ["05c_detect_rois.py", "--marker", marker, "--order", "uid"]
    try:
        rc = D5.main()
    finally:
        pyczi.open_czi, D5.load_model, sys.argv = saved
    if rc != 0:
        raise SystemExit(f"05c.main() returned {rc} for {marker}")

    with open(D5.NUCLEI_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return fake, model, rows


def read_rows(path):
    """A CSV as a list of dicts, or [] when it was never written."""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def widths(path):
    """The field count of the header and of every data row."""
    with open(path, newline="", encoding="utf-8") as fh:
        return [len(r) for r in csv.reader(fh)]


def block(shape, value, patch=None):
    """A constant plane, optionally with one bright rectangle painted on it."""
    a = np.full(shape, float(value), dtype=np.float64)
    if patch:
        y0, x0, h, w, v = patch
        a[y0:y0 + h, x0:x0 + w] = v
    return a


HAVE_CZI = True
try:
    import pylibCZIrw.czi                                    # noqa: F401
except ImportError:                                          # noqa: BLE001
    HAVE_CZI = False


# --------------------------------------------------------------------------
print("=== a multiplex study that declares both routes ===")
print()

with temp_study(acquisition=MULTIPLEX) as study:
    D5 = load_stage("05c_detect_rois.py")

    print("--- which channel each marker is segmented on ---")
    chk("a nuclear-segmented marker uses the nuclear plane",
        D5.segment_plane_for("pERK"), "DAPI")
    chk("an own-segmented marker uses its own plane",
        D5.segment_plane_for("GFAP"), "GFAP")

    print()
    print("--- which backend each marker gets ---")
    chk("a nuclear-segmented marker inherits stardist",
        D5.backend_for("pERK"), "stardist")
    chk("an own-segmented marker takes its declared backend",
        D5.backend_for("GFAP"), "threshold")

    print()
    print("--- and whether its objects are nuclei ---")
    chk("nuclear-segmented objects ARE nuclei", D5.nucleus_shaped_for("pERK"),
        True)
    chk("...whatever the antibody is", D5.nucleus_shaped_for("GFAP"), False)

    print()
    print("--- which plane of the file each marker's pixels are on ---")
    # The legacy `channels.marker_index` is ONE index for the whole study, so
    # under multiplex it would read every marker off the same plane. The
    # channel table's own index is what makes `segment: own` mean anything.
    chk("the nuclear plane is the declared nuclear channel's",
        D5.NUCLEAR_C, 0)
    chk("the first marker's plane is its own", D5.plane_index_for("pERK"), 1)
    chk("...and so is the second's", D5.plane_index_for("GFAP"), 2)

    print()
    print("--- provenance is recorded on every row ---")
    for col in ("segmented_on", "backend", "nucleus_shaped"):
        chk(f"{col} is an output column", col in D5.COLUMNS, True)
    chk("the three are the LAST three, in that order",
        D5.COLUMNS[-3:], ["segmented_on", "backend", "nucleus_shaped"])

    print()
    print("--- the threshold backend's two settings are read here now ---")
    chk("mad_k comes from config", D5.MAD_K, 3.0)
    chk("min_area_um2 comes from config", D5.MIN_AREA_UM2, 5.0)

    print()
    print("--- 05c does not assume a nuclear channel exists ---")
    chk("...but names it when the study declares one", D5.NUCLEAR_NAME, "DAPI")

    if not HAVE_CZI:
        print()
        print("   (pylibCZIrw is not installed - the detection loop cannot be "
              "driven, even against a fake reader, since 05c imports the "
              "package itself)")
    else:
        print()
        print("--- an own-segmented marker, driven through the real loop ---")

        bh, bw = BOX[3], BOX[2]
        planes = {0: block((bh, bw), 100),          # DAPI, flat
                  1: block((bh, bw), 150),          # pERK, flat
                  2: block((bh, bw), 200,           # GFAP, one bright square
                           patch=(4, 4, 6, 6, 9000))}
        # A model that would report a nucleus if it were ever asked. It must
        # not be: GFAP is `segment: own` with the threshold backend.
        star = np.zeros((bh, bw), dtype=np.int32)
        star[2:8, 2:8] = 1
        fake, model, rows = drive(D5, "GFAP", "AB12_1a-s0", planes, star)

        chk("the threshold backend never loads the model", model.calls, [])
        chk("two planes were read (nuclear + the marker's own)",
            len(fake.calls), 2)
        chk("...the nuclear one and GFAP's own, not the legacy marker_index",
            sorted(c["plane"]["C"] for c in fake.calls), [0, 2])
        chk("...both naming the geometry row's scene",
            {c["scene"] for c in fake.calls}, {6})
        chk("the bright square is one object", len(rows), 1)
        chk("...measured on GFAP's own plane",
            float(rows[0]["marker_mean"]), 9000.0)
        chk("...with the nuclear plane still reported beside it",
            float(rows[0]["dapi_mean"]), 100.0)
        chk("segmented_on names its own channel", rows[0]["segmented_on"],
            "GFAP")
        chk("backend names what found it", rows[0]["backend"], "threshold")
        chk("nucleus_shaped says these are not nuclei",
            rows[0]["nucleus_shaped"], "0")

        print()
        print("--- a nuclear-segmented marker in the same study ---")

        planes = {0: block((bh, bw), 100), 1: block((bh, bw), 150),
                  2: block((bh, bw), 200)}
        fake, model, rows = drive(D5, "pERK", "AB12_1b-s0", planes, star)
        perk = [r for r in rows if r["marker"] == "pERK"]
        chk("the model was asked exactly once", len(model.calls), 1)
        chk("one nucleus was written", len(perk), 1)
        chk("...measured on the pERK plane, not on GFAP's",
            float(perk[0]["marker_mean"]), 150.0)
        chk("segmented_on names the nuclear channel",
            perk[0]["segmented_on"], "DAPI")
        chk("backend is stardist", perk[0]["backend"], "stardist")
        chk("nucleus_shaped is true", perk[0]["nucleus_shaped"], "1")

        print()
        print("--- the row is a POSITIONAL list; it must match COLUMNS ---")
        chk("every line has exactly len(COLUMNS) fields",
            set(widths(D5.NUCLEI_CSV)), {len(D5.COLUMNS)})

        print()
        print("--- co-localisation, computed in the same pass ---")

        # GFAP's run owns no pair - pERK is declared first, so pERK's run
        # relates the two - and a run that owns none must not create the file.
        # The GFAP drive above ran first, and the pERK drive after it did own
        # the pair, so by now the file exists; what is checked is which run
        # wrote rows into it.
        rel = read_rows(D5.COLOC_CSV)
        chk("the file exists once a run that owns a pair has run",
            os.path.exists(D5.COLOC_CSV), True)
        chk("...and the flat partner plane related nothing", rel, [])

        # Now a section where BOTH markers have an object, overlapping.
        # pERK's nucleus is the model's block at rows/cols 2-7; GFAP's is the
        # bright square at 4-9. Each centroid lands inside the other.
        planes = {0: block((bh, bw), 100), 1: block((bh, bw), 150),
                  2: block((bh, bw), 200, patch=(4, 4, 6, 6, 9000))}
        fake, model, rows = drive(D5, "pERK", "AB12_1c-s0", planes, star)
        rel = read_rows(D5.COLOC_CSV)
        chk("three planes were read - the partner's too", len(fake.calls), 3)
        chk("...including GFAP's own", sorted(c["plane"]["C"] for c in
                                              fake.calls), [0, 1, 2])
        chk("one relation was written", len(rel), 1)
        chk("...naming both markers and both object ids",
            [rel[0]["marker_a"], rel[0]["object_a"],
             rel[0]["marker_b"], rel[0]["object_b"]],
            ["pERK", "1", "GFAP", "1"])
        chk("...with both directions recorded",
            [rel[0]["a_centroid_in_b"], rel[0]["b_centroid_in_a"]], ["1", "1"])
        chk("the join table's lines match COLOC_COLUMNS",
            set(widths(D5.COLOC_CSV)), {len(D5.COLOC_COLUMNS)})

        # The object ids are the join to roi_nuclei.csv, not fresh numbering.
        nuc = [r for r in read_rows(D5.NUCLEI_CSV)
               if r["scene_uid"] == "AB12_1c-s0"]
        chk("object_a is a nucleus_id of the same (uid, roi_index)",
            [(r["nucleus_id"], r["roi_index"]) for r in nuc],
            [(rel[0]["object_a"], rel[0]["roi_index"])])

        print()
        print("--- --force drops the relations of the sections it redoes ---")
        # The join table has no `marker` column - its rows belong to the run
        # of `marker_a` - so the drop that keeps the two files in step has to
        # be told which column names the owner. Checked last, because it
        # deletes the row the assertions above read.
        dropped, kept = D5.drop_rows(D5.COLOC_CSV, "pERK", ["AB12_1c-s0"],
                                     marker_col="marker_a")
        chk("the pair of the redone section goes", dropped, 1)
        chk("...and nothing else does", kept, 0)
        chk("...the header survives",
            widths(D5.COLOC_CSV), [len(D5.COLOC_COLUMNS)])
        chk("a section that is NOT being redone is untouched",
            D5.drop_rows(D5.COLOC_CSV, "pERK", ["AB12_1z-s0"],
                         marker_col="marker_a"), (0, 0))


# --------------------------------------------------------------------------
print()
print("=== the live study's shape: paired, and no channel table at all ===")
print()

with temp_study(acquisition=PAIRED) as study:
    D5 = load_stage("05c_detect_rois.py")

    print("--- every helper answers from its fallback ---")
    chk("there is no declared nuclear channel", D5.NUCLEAR_NAME, None)
    chk("a marker that is in no channel table segments on the counterstain",
        D5.segment_plane_for("AF568"), "nuclear")
    chk("...with stardist", D5.backend_for("AF568"), "stardist")
    chk("...and its objects are nuclei", D5.nucleus_shaped_for("AF568"), True)
    chk("the planes are the legacy channels block's",
        (D5.NUCLEAR_C, D5.plane_index_for("AF568")), (D5.DAPI_C, D5.MARK_C))

    if not HAVE_CZI:
        print()
        print("   (pylibCZIrw is not installed - the detection loop cannot be "
              "driven)")
    else:
        print()
        print("--- and the loop takes the route it took before this change ---")

        bh, bw = BOX[3], BOX[2]
        planes = {0: block((bh, bw), 100), 1: block((bh, bw), 250)}
        star = np.zeros((bh, bw), dtype=np.int32)
        star[2:8, 2:8] = 1
        fake, model, rows = drive(D5, "AF568", "AB12_1a-s0", planes, star)

        chk("StarDist was asked, exactly once", len(model.calls), 1)
        chk("...for a plane the size of the box",
            model.calls[0].shape if model.calls else None, (bh, bw))
        chk("two reads, dapi + marker", len(fake.calls), 2)
        chk("...the legacy dapi/marker indices",
            sorted(c["plane"]["C"] for c in fake.calls),
            sorted([D5.DAPI_C, D5.MARK_C]))
        chk("one nucleus", len(rows), 1)
        # THE CHECK THAT MATTERS: segmented on the nuclear plane, measured on
        # the marker plane. If those two were ever swapped, this is the row
        # that says so.
        chk("dapi_mean is the nuclear plane's", float(rows[0]["dapi_mean"]),
            100.0)
        chk("marker_mean is the marker plane's",
            float(rows[0]["marker_mean"]), 250.0)
        chk("segmented_on records the counterstain",
            rows[0]["segmented_on"], "nuclear")
        chk("backend records stardist", rows[0]["backend"], "stardist")
        chk("nucleus_shaped is true", rows[0]["nucleus_shaped"], "1")
        chk("every line has exactly len(COLUMNS) fields",
            set(widths(D5.NUCLEI_CSV)), {len(D5.COLUMNS)})

        # THE REFUSAL WITH A REASON. Not an empty file - a paired study's
        # markers are separate scans of different sections, and an empty
        # roi_colocalisation.csv beside them would read as "nothing overlaps".
        chk("and NO co-localisation file was written for it",
            os.path.exists(D5.COLOC_CSV), False)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
