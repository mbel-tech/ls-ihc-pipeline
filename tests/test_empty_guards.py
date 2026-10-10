"""First-run and partial-run inputs that used to crash.

Run:  python tests/test_empty_guards.py
"""

import csv
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

# This suite imports stage modules, which read config at import. Without a
# config of its own it would fall through to the operator's live study and
# then pass or fail on their data. See tests/_fixture.py.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _fixture import use_temp_study  # noqa: E402

STUDY = use_temp_study()
PY = sys.executable


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


tmp = tempfile.mkdtemp(prefix="guards_")
try:
    # 00b: no archives -> no rows, and the writer must still produce a header.
    V = load("v", "00b_verify_extraction.py")
    chk("00b check() with an empty inventory", V.check({}, False), [])
    chk("00b names its columns", V.STATUS_KEYS[:2], ["file", "zip"])

    # 01k: summarise() on nothing measured returns instead of raw.max()
    K = load("k", "01k_saturation_raw.py")
    K.summarise([], measured=0, failed=0)
    chk("01k summarise([]) returns", True, True)

    # 04a preview with n=1: subplots(2, 1) must still index as [row, col]
    RF = load("rf", "04a_reformat.py")
    sec, pla = os.path.join(tmp, "sec"), os.path.join(tmp, "pla")
    os.makedirs(sec); os.makedirs(pla)
    Image.fromarray(np.zeros((8, 8), np.uint8)).save(os.path.join(sec, "s1.png"))
    Image.fromarray(np.zeros((8, 8), np.uint8)).save(os.path.join(pla, "p1.png"))
    RF.REFORMAT_DIR = tmp
    RF.preview([{"kind": "plate", "id": "p1", "angle": 0.0},
                {"kind": "section", "id": "s1", "angle": 0.0}], sec, pla, 1)
    chk("04a preview(n=1) writes", os.path.exists(os.path.join(tmp, "reformat_preview.png")), True)

    # 02: a blank centre cell reads as nan, not a crash
    P = load("p", "02_pair_passes.py")
    P.MANIFEST_DIR = tmp
    with open(os.path.join(tmp, "manifest_scenes.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["slide", "scene_index", "slide_serial", "section_order",
                                           "center_x_um", "center_y_um"])
        w.writeheader()
        w.writerow({"slide": 1, "scene_index": 0, "slide_serial": 1, "section_order": 1,
                    "center_x_um": "", "center_y_um": "12.5"})
    rows = P.load_scenes()
    chk("02 blank centre -> nan", np.isnan(rows[0]["center_x_um"]), True)
    chk("02 filled centre still parses", rows[0]["center_y_um"], 12.5)

    # 01_overviews: a marker missing from display_ranges.json is a clear stop
    O = load("o", "01_overviews.py")
    chk("01 channel_range returns the pair", O.channel_range({"DAPI": {"lo": 1, "hi": 9}}, "DAPI"), (1, 9))
    msg = ""
    try:
        O.channel_range({"DAPI": {"lo": 1, "hi": 9}}, "AF488")
    except SystemExit as exc:
        msg = str(exc)
    chk("01 missing marker names the file to delete", "display_ranges.json" in msg and "AF488" in msg, True)

    # 01g: no module-level fallback list; analyse() reports through its argument
    G = load("g", "01g_saturation_map.py")
    chk("01g has no module-level _fallbacks", hasattr(G, "_fallbacks"), False)
    fb = []
    got = G.analyse({"animal": "LSX", "marker_channel": "AF568", "scene_uid": "nope",
                     "slide": "1", "section_order": "1"}, 5.2, fb)
    chk("01g analyse() on a missing section returns None", got, None)
    chk("...and records no fallback", fb, [])

    # 04l: --worklist that does not exist stops with a message, not a traceback
    r = subprocess.run([PY, os.path.join(SCRIPTS, "04l_roi_curator.py"),
                        "--worklist", os.path.join(tmp, "nope.csv"),
                        "--out", os.path.join(tmp, "x.html")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    chk("04l missing worklist exits 1", r.returncode, 1)
    chk("...without a traceback", "Traceback" in r.stderr, False)
    chk("...and names 04n", "04n_roi_worklist" in (r.stdout + r.stderr), True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
