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
