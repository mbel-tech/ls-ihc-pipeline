"""The one place the pipeline reads pixels out of a CZI.

Two things it exists to stop.

`scene=` was passed nowhere. 219 of 222 files have overlapping scene
rectangles, so a read of one scene's rectangle composites the tissue of
whichever neighbours overlap it - 2241 of 2572 scenes, and clipped fractions
overstated by up to 2.6x. See docs/czi-reading-audit.md finding 1.

And `np.squeeze` was assuming the result is grayscale. A channel with an RGB
pixel type squeezes to 3-D and every downstream shape check would compare the
wrong thing.

A fake reader is used rather than a real file: the point is which arguments
reach `read()`, and a fixture that needs a 3 GB image cannot run on a machine
without the dataset.

Run:  python tests/test_czi_read.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import czi_read as CR                                       # noqa: E402

failures = []


def chk(name, got, want):
    ok = got == want
    shown = got if len(repr(got)) < 90 else f"<{type(got).__name__}>"
    print(f"{'ok  ' if ok else 'FAIL'} {name:60} {shown!r}")
    if not ok:
        print(f"     want {want!r}")
        failures.append(name)


class Rect:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


class FakeDoc:
    """Records the arguments it was called with, and returns what it is told."""

    def __init__(self, out=None):
        self.calls = []
        self.out = np.zeros((4, 6), dtype=np.uint16) if out is None else out

    def read(self, **kwargs):
        self.calls.append(kwargs)
        return self.out


RECT = Rect(10, 20, 6, 4)

print("--- the scene reaches the reader ---")
doc = FakeDoc()
CR.read_plane(doc, RECT, 1, scene=3, zoom=0.125)
call = doc.calls[0]
chk("the scene is passed", call["scene"], 3)
chk("the plane is passed", call["plane"], {"C": 1})
chk("the rectangle is passed", call["roi"], (10, 20, 6, 4))
chk("the zoom is passed", call["zoom"], 0.125)

doc = FakeDoc()
CR.read_plane(doc, RECT, 0, scene=0)
chk("scene 0 is a scene, not a missing one", doc.calls[0]["scene"], 0)
chk("...and the default zoom is 1.0", doc.calls[0]["zoom"], 1.0)

# A scene must be given. Defaulting it to None would silently restore exactly
# the behaviour this helper exists to end.
try:
    CR.read_plane(FakeDoc(), RECT, 0)
    chk("omitting the scene is a programming error", False, True)
except TypeError:
    chk("omitting the scene is a programming error", True, True)

print()
print("--- the result is a plane, and is checked to be one ---")
doc = FakeDoc(np.zeros((1, 4, 6, 1), dtype=np.uint16))
chk("singleton axes are squeezed away", CR.read_plane(doc, RECT, 0, scene=1).shape,
    (4, 6))

doc = FakeDoc(np.zeros((4, 6, 3), dtype=np.uint8))
try:
    CR.read_plane(doc, RECT, 0, scene=1)
    chk("a non-grayscale plane raises rather than being squeezed", False, True)
except CR.ReadError as exc:
    chk("a non-grayscale plane raises rather than being squeezed", True, True)
    chk("...and says which scene and channel", "scene 1" in str(exc), True)

print()
print("--- reading several channels of one scene ---")
doc = FakeDoc()
planes = CR.read_planes(doc, RECT, {"DAPI": 0, "pERK": 2}, scene=5, zoom=0.5)
chk("one array per requested channel", sorted(planes), ["DAPI", "pERK"])
chk("each read named its own plane",
    sorted(c["plane"]["C"] for c in doc.calls), [0, 2])
chk("...at the same scene", {c["scene"] for c in doc.calls}, {5})
chk("...and the same zoom", {c["zoom"] for c in doc.calls}, {0.5})

doc = FakeDoc()
try:
    CR.read_planes(doc, RECT, {}, scene=1)
    chk("asking for no channels raises", False, True)
except CR.ReadError:
    chk("asking for no channels raises", True, True)

# --------------------------------------------------------------------------
print()
print("--- 01_overviews reads through it ---")

import importlib.util                                       # noqa: E402

sys.path.insert(0, HERE)
from _fixture import use_temp_study                         # noqa: E402

use_temp_study()
spec = importlib.util.spec_from_file_location(
    "probe_ov", os.path.join(REPO, "scripts", "01_overviews.py"))
OV = importlib.util.module_from_spec(spec)
sys.modules["probe_ov"] = OV
spec.loader.exec_module(OV)

doc = FakeDoc()
OV.read_scene(doc, RECT, 1, 0.125, scene=7)
chk("01_overviews passes the scene down", doc.calls[0]["scene"], 7)
chk("...and still the plane it asked for", doc.calls[0]["plane"], {"C": 1})

try:
    OV.read_scene(FakeDoc(), RECT, 1, 0.125)
    chk("a caller that forgot the scene fails at the call", False, True)
except TypeError:
    chk("a caller that forgot the scene fails at the call", True, True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
