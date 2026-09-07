"""The map from the curator's 256 grid to CZI pixels.

Everything downstream reads pixels at the coordinates this produces, so an error
here does not fail loudly - it quantifies the wrong piece of tissue and reports
a number. The properties worth pinning are the ones whose violation still looks
like a plausible answer:

  * a transposed axis or a dropped flip still gives a matrix;
  * treating the map as a similarity still gives a circle, just the wrong one;
  * an inverse that disagrees with the forward map still round-trips against
    itself.

The pure-geometry checks run anywhere. The ones that need the dataset skip
themselves with a note rather than failing, so this suite is still worth running
on a machine that has the repo and not the images.

Run:  python tests/test_roi_geometry.py
"""

import importlib.util
import os
import sys

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

_spec = importlib.util.spec_from_file_location(
    "g5", os.path.join(SCRIPTS, "05a_roi_geometry.py"))
G5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G5)

fails = 0


def chk(label, got, want):
    global fails
    ok = str(got) == str(want)
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(56) + " " + str(got)
          + ("" if ok else "   want " + str(want)))


def close(label, got, want, tol):
    global fails
    ok = abs(float(got) - float(want)) <= tol
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(56)
          + f" {float(got):.6g}" + ("" if ok else f"   want {want} +-{tol}"))


def note(t):
    print(t)


# --------------------------------------------------------------- pure geometry
note("\nreading an affine off a function:\n")

TRUE = np.array([[2.0, -0.5, 30.0],
                 [0.25, 3.0, -7.0]])


def fn(u, v):
    return (TRUE[0, 0] * u + TRUE[0, 1] * v + TRUE[0, 2],
            TRUE[1, 0] * u + TRUE[1, 1] * v + TRUE[1, 2])


M = G5.affine_from(fn)
close("recovers every coefficient", np.abs(M - TRUE).max(), 0.0, 1e-12)

# The recovery is only valid because the map is affine. If a nonlinearity ever
# creeps into grid_to_overview, three points would silently linearise it - so
# check that a curved map is NOT reproduced, which is what makes the test above
# meaningful rather than tautological.
bent = G5.affine_from(lambda u, v: (u * u + v, u - v))
pu, pv = G5.apply_affine(bent, 10.0, 0.0)
chk("a nonlinear map is not silently linearised", abs(pu - 100.0) > 50, True)

inv = G5.invert_affine(M)
u, v = 37.5, -12.25
x, y = G5.apply_affine(M, u, v)
bu, bv = G5.apply_affine(inv, x, y)
close("the inverse takes a point back (u)", bu, u, 1e-9)
close("the inverse takes a point back (v)", bv, v, 1e-9)

# --------------------------------------------------- the anisotropy that bites
note("\na circle on the 256 grid is an ellipse on the slide:\n")

SQUARE = {"src_w": 1000, "src_h": 1000, "work_size": 400, "angle": 0.0,
          "flip": False, "rot_w": 400, "rot_h": 400, "x0": 0, "y0": 0,
          "crop_w": 400, "crop_h": 400, "side": 400, "ox": 0, "oy": 0,
          "grid": 256}
TALL = dict(SQUARE, src_w=944, src_h=1632)

def axis_ratio(M):
    """How far from a similarity the map is: the two column norms, compared."""
    return np.linalg.norm(M[:, 1]) / np.linalg.norm(M[:, 0])


ms = G5.affine_from(G5.grid_to_overview(SQUARE))
mt = G5.affine_from(G5.grid_to_overview(TALL))
close("a square scan box keeps circles circular", axis_ratio(ms), 1.0, 1e-9)
ratio = axis_ratio(mt)
close("a 944x1632 box stretches y by exactly h/w", ratio, 1632 / 944, 1e-9)
chk("...which is a 73% distortion, not a rounding detail", round(ratio, 2), 1.73)

# The failure this guards against: carrying sec_r forward as a radius.
t = np.linspace(0, 2 * np.pi, 720, endpoint=False)
X, Y = G5.apply_affine(mt, 128 + 10 * np.cos(t), 128 + 10 * np.sin(t))
w_um, h_um = X.max() - X.min(), Y.max() - Y.min()
chk("the mapped outline is wider one way than the other",
    round(h_um / w_um, 2), 1.73)

# Column norms are the semi-axes only while the columns are orthogonal, which
# is true at angle 0, 90, 180, 270 and nowhere else. Rotate the same tall box
# by 45 degrees and the two columns have EQUAL norms - a reading of 1.00, a
# circle - while the section is exactly as stretched as it was before. The
# semi-axes of the image of a circle are the singular values of the linear
# part, whatever the angle.
note("\n...and the ellipse does not change shape when the section rotates:\n")

ROT45 = dict(TALL, angle=45.0)
mr = G5.affine_from(G5.grid_to_overview(ROT45))
sr = 10.0
sv = np.linalg.svd(mr[:, :2], compute_uv=False) * sr
a_ax, b_ax = G5.ellipse_axes(mr, sr)
close("ellipse_axes: the larger semi-axis is the top singular value", a_ax, sv[0], 1e-9)
close("ellipse_axes: the smaller is the other one", b_ax, sv[1], 1e-9)
chk("axis_a is the larger", a_ax >= b_ax, True)
col_a = np.linalg.norm(mr[:, 0]) * sr
col_b = np.linalg.norm(mr[:, 1]) * sr
chk("at 45 deg the column norms read as a circle", round(float(col_b / col_a), 6), 1.0)
chk("...and are NOT the semi-axes", abs(col_a - a_ax) > 1.0 and abs(col_b - b_ax) > 1.0, True)
close("at 45 deg the ellipse area still comes from |det A|", a_ax * b_ax,
      abs(np.linalg.det(mr[:, :2])) * sr * sr, 1e-9)
close("the area the column norms implied was 15% too large",
      (col_a * col_b) / (a_ax * b_ax), 1.1536, 1e-3)

# At angle 0 the columns are orthogonal and the old reading was right, so the
# new helper must agree with it there.
a0, b0 = G5.ellipse_axes(mt, sr)
close("at angle 0 ellipse_axes agrees with the column norms (a)", a0,
      max(np.linalg.norm(mt[:, 0]), np.linalg.norm(mt[:, 1])) * sr, 1e-9)
close("...and (b)", b0,
      min(np.linalg.norm(mt[:, 0]), np.linalg.norm(mt[:, 1])) * sr, 1e-9)

close("anisotropy is s_max/s_min at 45 deg", G5.anisotropy(mr), 1632 / 944, 1e-9)
close("...and the same number at angle 0", G5.anisotropy(mt), 1632 / 944, 1e-9)
close("...and 1.0 for a square box", G5.anisotropy(ms), 1.0, 1e-9)

# ----------------------------------------------- rotation, flip, crop and pad
note("\nthe steps that are easy to get backwards:\n")

# 180 degrees about the centre must send a corner to the opposite corner.
HALF = dict(SQUARE, angle=180.0)
m180 = G5.affine_from(G5.grid_to_overview(HALF))
x0, y0 = G5.apply_affine(m180, 0.0, 0.0)
x1, y1 = G5.apply_affine(m180, 255.0, 255.0)
chk("180 deg sends (0,0) past the far corner", (x0 > x1) and (y0 > y1), True)

# A flip must mirror x and leave y alone.
NOFLIP = dict(SQUARE, angle=0.0, flip=False)
FLIP = dict(SQUARE, angle=0.0, flip=True)
a = G5.affine_from(G5.grid_to_overview(NOFLIP))
b = G5.affine_from(G5.grid_to_overview(FLIP))
ax, ay = G5.apply_affine(a, 10.0, 20.0)
bx, by = G5.apply_affine(b, 10.0, 20.0)
close("flip leaves y untouched", by, ay, 1e-9)
chk("flip mirrors x", round(float(ax + bx), 3),
    round(float(G5.apply_affine(a, 0.0, 20.0)[0]
                + G5.apply_affine(a, 255.0, 20.0)[0]), 3))

# Crop and pad are translations, and must move things the opposite way.
CROP = dict(SQUARE, x0=30, y0=40)
c = G5.affine_from(G5.grid_to_overview(CROP))
cx, cy = G5.apply_affine(c, 10.0, 20.0)
sx = SQUARE["src_w"] / SQUARE["work_size"]
sy = SQUARE["src_h"] / SQUARE["work_size"]
close("a crop origin shifts the map by +x0 (in source px)", cx - ax, 30 * sx, 1e-6)
close("...and by +y0", cy - ay, 40 * sy, 1e-6)

PAD = dict(SQUARE, ox=5, oy=7)
d = G5.affine_from(G5.grid_to_overview(PAD))
dx, dy = G5.apply_affine(d, 10.0, 20.0)
close("a pad offset shifts it the other way", dx - ax, -5 * sx, 1e-6)
close("...on both axes", dy - ay, -7 * sy, 1e-6)

# ------------------------------------------------------- drawn region polygons
note("\na drawn region is an outline already, so the map does no new work:\n")

chk("a blank cell is no polygon", G5.parse_poly(""), None)
chk("...and so is a missing one", G5.parse_poly(None), None)
# Two points enclose nothing. Read as a polygon they would give 05c a ring with
# no interior and 06a an area of zero, which reaches the dataset as a density of
# something per nothing.
chk("two points are not a polygon", G5.parse_poly("1 2;3 4"), None)
sq = G5.parse_poly("10 10;20 10;20 20;10 20")
chk("four points are", sq.shape, (4, 2))
chk("...read in order", sq.tolist(), [[10.0, 10.0], [20.0, 10.0],
                                      [20.0, 20.0], [10.0, 20.0]])
chk("a cell that is not numbers is refused", G5.parse_poly("10 10;a b;20 20"), None)

close("the shoelace of a 10x10 square", G5.outline_area(sq[:, 0], sq[:, 1]), 100.0, 1e-9)
# Wound the other way it is the same square. abs() is not cosmetic: the curator
# does not constrain which way round an operator clicks the corners, so half of
# all polygons would otherwise come out with a negative area.
close("...and the same wound backwards",
      G5.outline_area(sq[::-1, 0], sq[::-1, 1]), 100.0, 1e-9)

# THE CLAIM THIS MAKES: the area of a mapped polygon is |det A| times its area
# on the grid, at EVERY angle. This is the polygon's version of the bug fixed in
# `ellipse_axes` - reading the axes off the column norms was right at 0, 90, 180
# and 270 and wrong everywhere else, which is where every real section sits.
for _ang in (0.0, 30.0, 45.0, 137.0):
    _a = np.radians(_ang)
    # Deliberately anisotropic, 3x in one axis and 1.7 in the other: an isotropic
    # matrix would pass a wrong area formula as easily as a right one.
    _M = np.array([[3.0 * np.cos(_a), -1.7 * np.sin(_a), 11.0],
                   [3.0 * np.sin(_a), 1.7 * np.cos(_a), -4.0]])
    _X, _Y = G5.apply_affine(_M, sq[:, 0], sq[:, 1])
    close(f"area scales by |det A| at {_ang:g} deg",
          G5.outline_area(_X, _Y), 100.0 * abs(np.linalg.det(_M[:, :2])), 1e-6)

# The bounding box is taken from the MAPPED vertices, so it has to contain them
# all however the section was rotated - which is the whole reason 05a maps an
# outline instead of a radius.
_a = np.radians(45.0)
_M = np.array([[3.0 * np.cos(_a), -1.7 * np.sin(_a), 11.0],
               [3.0 * np.sin(_a), 1.7 * np.cos(_a), -4.0]])
_X, _Y = G5.apply_affine(_M, sq[:, 0], sq[:, 1])
_x0, _x1 = np.floor(_X.min()), np.ceil(_X.max())
_y0, _y1 = np.floor(_Y.min()), np.ceil(_Y.max())
chk("the box contains every mapped vertex",
    bool(np.all((_X >= _x0) & (_X <= _x1) & (_Y >= _y0) & (_Y <= _y1))), True)
# A rotated square is not axis-aligned, so its box must be strictly larger than
# it. A box that matched the area would mean the rotation had been dropped.
chk("...and is larger than the shape, because the shape is rotated",
    (_x1 - _x0) * (_y1 - _y0) > G5.outline_area(_X, _Y), True)

# ------------------------------------------------------- against the real data
note("\nagainst the dataset, if it is present:\n")

try:
    out_root = G5.OUT_ROOT
except Exception:                                                # noqa: BLE001
    out_root = None

if not (out_root and os.path.exists(G5.FOCUS_CSV)):
    note("   (no dataset on this machine - the checks above are the whole suite)")
else:
    worst, checked = G5.verify(n_sections=3)
    chk("sections checked against the real transform", checked > 0, True)
    # The floor is PIL's resize filter, measured at 0.12 px on a plain ramp.
    # A composition error moves things by whole pixels, so this is a wide gate
    # on purpose - it is testing for wrong, not for imprecise.
    chk("the composed map matches reformat to well under a pixel",
        worst < 0.3, True)

    if os.path.exists(G5.GEOM_CSV):
        drop, n = G5.verify_czi(limit=2)
        if n:
            chk("the scene rectangle aligns with the exported overview",
                drop > 0.3, True)
    else:
        note("   (no roi_geometry.csv - run the stage to check the CZI half)")

print("\n" + (f"{fails} FAILED" if fails else "ALL PASS"))
sys.exit(1 if fails else 0)
