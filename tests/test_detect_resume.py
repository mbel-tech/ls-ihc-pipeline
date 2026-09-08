"""Stage 5c's two file-handling helpers: the header check and the forced drop.

roi_nuclei.csv is the artefact this pipeline exists to produce - hours of
StarDist over 130 scenes, shared by both markers, appended to across runs. Two
ways of quietly corrupting it are pinned here:

  * RESUMING ONTO AN OLD HEADER. COLUMNS gained `off_tissue` on 2026-09-02. A
    resume against a file written before that appends 21-field rows under a
    20-field header; csv.DictReader maps the extra field to key None, so every
    new nucleus reads off_tissue = None in 06a and 06g cannot backfill a file
    that is half old and half new. The resume must refuse and name 06g.
  * `--force --limit N`. The force path used to drop EVERY row of the marker
    and then re-measure only N sections, silently discarding the rest. It
    must drop exactly the sections it is about to redo, and nothing of the
    other marker.

05c imports StarDist lazily inside load_model(), so the module itself loads on
a machine without it. Synthetic files throughout.

Run:  python tests/test_detect_resume.py
"""

import sys
import csv
import importlib.util
import os
import shutil
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

# This suite imports stage modules, which read config at import. Without a
# config of its own it would fall through to the operator's live study and
# then pass or fail on their data. See tests/_fixture.py.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _fixture import use_temp_study  # noqa: E402

STUDY = use_temp_study()


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G5C = load("g5c", "05c_detect_rois.py")

fails = 0


def chk(label, got, want):
    global fails
    ok = str(got) == str(want)
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + str(got)
          + ("" if ok else "   want " + str(want)))


OLD_COLUMNS = [c for c in G5C.COLUMNS if c != "off_tissue"]


def write(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def row(uid, marker, n):
    """One nucleus row in the CURRENT column order, filler everywhere else."""
    r = dict.fromkeys(G5C.COLUMNS, "0")
    r.update(scene_uid=uid, marker=marker, nucleus_id=str(n),
             roi_kind="roi", region="Dm")
    return [r[c] for c in G5C.COLUMNS]


def header_check(tmp):
    """A resume onto a pre-off_tissue file must stop and say what to run."""
    old = os.path.join(tmp, "old_nuclei.csv")
    write(old, OLD_COLUMNS, [row("A1", "AF568", 1)[:-1]])
    try:
        G5C.check_header(old, G5C.COLUMNS)
        got = "no exit"
    except SystemExit as exc:
        got = str(exc)
    chk("old 20-column header -> SystemExit", got != "no exit", True)
    chk("...and the message names 06g_flag_off_tissue.py",
        "06g_flag_off_tissue.py" in got, True)
    chk("...and names the missing column", "off_tissue" in got, True)

    cur = os.path.join(tmp, "cur_nuclei.csv")
    write(cur, G5C.COLUMNS, [row("A1", "AF568", 1)])
    try:
        G5C.check_header(cur, G5C.COLUMNS)
        got = "fine"
    except SystemExit as exc:
        got = str(exc)
    chk("current header passes", got, "fine")

    # The same columns in a different order is still a mismatch: 05c writes
    # positionally, and a permuted file would take every new row scrambled.
    perm = os.path.join(tmp, "perm_nuclei.csv")
    write(perm, list(reversed(G5C.COLUMNS)), [])
    try:
        G5C.check_header(perm, G5C.COLUMNS)
        got = "no exit"
    except SystemExit:
        got = "exit"
    chk("same columns, different order -> SystemExit", got, "exit")


def drop_check(tmp):
    """`drop_rows` removes the marker's rows for the given uids and no others."""
    path = os.path.join(tmp, "nuclei.csv")

    def seed():
        write(path, G5C.COLUMNS, [
            row("A1", "AF568", 1), row("A1", "AF568", 2),
            row("A2", "AF568", 3), row("A3", "AF568", 4),
            row("B1", "AF488", 5),
        ])

    # --force --limit 1: todo is one uid. The other two AF568 sections and
    # the AF488 one must all still be there afterwards.
    seed()
    dropped, kept = G5C.drop_rows(path, "AF568", ["A1"])
    rows = read(path)
    chk("--force --limit: dropped only the todo uid's rows", dropped, 2)
    chk("...kept the rest", kept, 3)
    chk("...the other AF568 sections survive",
        sorted({r["scene_uid"] for r in rows if r["marker"] == "AF568"}),
        "['A2', 'A3']")
    chk("...and so does the other marker",
        [r["scene_uid"] for r in rows if r["marker"] == "AF488"], "['B1']")
    chk("...the header is intact", list(rows[0].keys()) == G5C.COLUMNS, True)
    chk("...and no .tmp is left behind", os.path.exists(path + ".tmp"), False)

    # A uid of the OTHER marker in todo is not this marker's to drop. Sections
    # are disjoint across markers, so this never happens in practice, but the
    # helper is the one place that deletes data and should be exact.
    seed()
    dropped, kept = G5C.drop_rows(path, "AF568", ["B1"])
    chk("a uid of the other marker is never dropped", dropped, 0)
    chk("...file untouched", len(read(path)), 5)

    # Plain --force: todo is every section of the marker.
    seed()
    dropped, kept = G5C.drop_rows(path, "AF568", ["A1", "A2", "A3"])
    rows = read(path)
    chk("--force with no limit drops all of the marker", dropped, 4)
    chk("...and keeps the other marker", [r["scene_uid"] for r in rows], "['B1']")

    # Dropping everything must still leave a headed, appendable file.
    seed()
    G5C.drop_rows(path, "AF568", ["A1", "A2", "A3"])
    G5C.drop_rows(path, "AF488", ["B1"])
    with open(path, newline="", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    chk("an emptied file keeps its header", lines, [",".join(G5C.COLUMNS)])


# --------------------------------------------------------------------------
print()
print("--- 05c measures the scene, not its neighbours ---")

# The substring checks this replaced - 'scene=int(g["scene_index"])' in
# inspect.getsource(G5C), and 'doc.read(roi=roi, plane=' NOT in it - assert
# that a line of text exists (or does not) somewhere in the file. They would
# pass an implementation that read the wrong row's scene, one where the
# rectangle beside it did not match the box, or one missing a space in
# plane={"C": 0} (a `not in` check on that literal text passes just as
# happily against `plane={"C":0}`, with the space gone). 05c is where every
# nucleus in the dataset gets measured, so what actually matters is what
# reaches doc.read() - drive the real detection loop for one section and one
# ROI box through a fake reader and a fake StarDist model, and check the
# kwargs the reads recorded.
#
# What this exercises: main()'s CZI-reading path end to end - argument
# parsing, section/box resume bookkeeping, the tissue-mask gate, and the two
# CR.read_planes calls for the one box. What it does NOT exercise: real
# segmentation or measurement. The fake model reports "no nuclei found",
# which is enough to prove what reached read() without needing StarDist to
# actually run, or csbdeep normalisation / regionprops to behave any
# particular way on synthetic data.


class _FakeCzi:
    """Records the kwargs .read() was called with, and returns a fixed plane."""

    def __init__(self, shape):
        self.calls = []
        self._shape = shape

    def read(self, **kwargs):
        self.calls.append(kwargs)
        return np.random.default_rng(len(self.calls)).random(self._shape)


class _FakeOpenCzi:
    """Stands in for pylibCZIrw.czi.open_czi: a context manager around one doc."""

    def __init__(self, doc):
        self.doc = doc

    def __call__(self, path, *a, **kw):
        return self

    def __enter__(self):
        return self.doc

    def __exit__(self, *exc):
        return False


class _FakeModel:
    """Stands in for the StarDist model: reports no nuclei, every time.

    Segmentation is out of scope for this check (see the note above) - this
    is enough to prove the read reached the model with its result unused
    downstream, without loading a real pretrained model.
    """

    def predict_instances(self, img, **kw):
        return np.zeros(img.shape, dtype=np.int32), {}


def detect_read_check():
    try:
        import pylibCZIrw.czi as _real_pyczi
    except ImportError:                                          # noqa: BLE001
        print("   (pylibCZIrw is not installed on this machine - the "
              "detection read cannot be exercised, even against a fake "
              "reader, since 05c imports the package itself)")
        return

    # The marker is the STUDY's, not a literal. This suite runs under
    # use_temp_study(), whose one marker is whatever config.example.json
    # declares, and 05a's use_marker() refuses a marker the study never
    # declared. The literal used to work only because 05a's MARKERS was the
    # LS pair written into the file.
    uid, czi_file = "AB12_1a-s0", "AB12_1a.czi"
    marker = G5C.G5.MARKER
    scene_index = 6
    x0, y0, bw, bh = 300, 400, 24, 20

    os.makedirs(G5C.REFORMAT_DIR, exist_ok=True)
    G5C.G5.use_marker(marker)

    geom_row = {
        "scene_uid": uid, "animal": "AB12", "marker": marker,
        "czi_file": czi_file, "scene_index": str(scene_index),
        "m00": "1", "m01": "0", "m02": "0",
        "m10": "0", "m11": "1", "m12": "0",
    }
    with open(G5C.G5.GEOM_CSV, "w", newline="\n", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(geom_row))
        w.writeheader()
        w.writerow(geom_row)

    box_row = {
        "scene_uid": uid, "animal": "AB12", "marker": marker,
        "roi_kind": "roi", "region": "Dm", "seed_n": "1",
        "czi_x0": str(x0), "czi_y0": str(y0),
        "czi_w": str(bw), "czi_h": str(bh),
        "sec_x": "128", "sec_y": "128", "sec_r": "50", "sec_poly": "",
    }
    with open(G5C.G5.BOX_CSV, "w", newline="\n", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(box_row))
        w.writeheader()
        w.writerow(box_row)

    # Where 05c's own mask_at() will look. It tries `sections_AF568` first and
    # falls back to `sections`, so the fallback is the one directory that is
    # right for any study - the literal in mask_at is a separate genericisation
    # job, and writing to `sections_<this study's marker>` here would only pass
    # while that marker happened to be AF568.
    mask_dir = os.path.join(G5C.REFORMAT_DIR, "sections")
    os.makedirs(mask_dir, exist_ok=True)
    np.save(os.path.join(mask_dir, f"{uid}_mask.npy"),
            np.ones((256, 256), dtype=bool))

    fake_doc = _FakeCzi((bh, bw))
    saved_open_czi = _real_pyczi.open_czi
    saved_load_model = G5C.load_model
    saved_argv = sys.argv
    _real_pyczi.open_czi = _FakeOpenCzi(fake_doc)
    G5C.load_model = lambda: _FakeModel()
    sys.argv = ["05c_detect_rois.py", "--marker", marker, "--order", "uid"]
    try:
        rc = G5C.main()
    finally:
        _real_pyczi.open_czi = saved_open_czi
        G5C.load_model = saved_load_model
        sys.argv = saved_argv

    chk("the run completed", rc, 0)
    chk("two reads were made (dapi + marker) for the one box",
        len(fake_doc.calls), 2)
    chk("both reads named the same scene",
        {c["scene"] for c in fake_doc.calls}, {scene_index})
    chk("...which is the geometry row's scene_index",
        fake_doc.calls[0]["scene"] if fake_doc.calls else None, scene_index)
    chk("both reads used the box's own rectangle (czi_x0/y0/w/h)",
        {c["roi"] for c in fake_doc.calls}, {(x0, y0, bw, bh)})
    chk("...and the dapi/marker channel indices",
        sorted(c["plane"]["C"] for c in fake_doc.calls),
        sorted([G5C.DAPI_C, G5C.MARK_C]))


detect_read_check()


def main():
    tmp = tempfile.mkdtemp(prefix="ls5c_")
    try:
        header_check(tmp)
        drop_check(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
