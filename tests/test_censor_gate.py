"""What 04j calls "tissue" when it decides whether a section is measurable.

The section-level gate in `04j_censor_clipped.py` sets a section aside when 1%
of its pixels sit at the 16-bit ceiling. The pixels that matter are the ones on
tissue: clipping on the PAP pen ring outside the section is real, but it does
not touch any nucleus that will ever be measured. So the gate has to be decided
on the in-tissue fraction, and "tissue" has to mean the pipeline's own tissue
mask rather than "DAPI overview > 0" - the 8-bit overview is stretched from the
frame's 1st percentile, so `> 0` is most of the frame.

The scene here is built so the two definitions disagree loudly: a tissue disc on
a low but nonzero background, and a clipping ring entirely outside the disc plus
a few clipped pixels inside it. Frame fraction fails the gate; tissue fraction
passes it. The checks pin that the in-tissue fraction comes from a real tissue
mask, that the verdict follows it, that the frame fraction is still recorded,
and that the mask on disk (tissue/<uid>_tissue.png) is preferred over a rebuild.

Nothing here touches the dataset. Run:  python tests/test_censor_gate.py
"""

import importlib.util
import math
import os
import shutil
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

_spec = importlib.util.spec_from_file_location(
    "g4j", os.path.join(SCRIPTS, "04j_censor_clipped.py"))
G4J = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G4J)

fails = 0


def chk(label, got, want):
    global fails
    ok = str(got) == str(want)
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(60) + " " + str(got)
          + ("" if ok else "   want " + str(want)))


def close(label, got, want, tol):
    global fails
    ok = abs(float(got) - float(want)) <= tol
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(60)
          + f" {float(got):.6g}" + ("" if ok else f"   want {want} +-{tol}"))


def note(t):
    print(t)


# ------------------------------------------------------------- synthetic scene
N = 240
yy, xx = np.mgrid[:N, :N]
rr = np.hypot(yy - N / 2, xx - N / 2)

# 8-bit DAPI overview as 01_overviews would write it: the 1st percentile of the
# frame maps to 0, so the background is a low NONZERO value nearly everywhere.
dapi = np.full((N, N), 3, dtype=np.uint8)
dapi[rr < 60] = 120
tissue_true = rr < 60

# Clipping: a ring well outside the disc (the PAP pen), plus a few pixels inside.
cen = (rr > 85) & (rr < 100)
cen[N // 2 - 2:N // 2 + 2, N // 2 - 3:N // 2 + 2] = True      # 4 x 5 = 20 pixels
n_inside = int((cen & tissue_true).sum())

frac_frame = float(cen.mean())
want_tissue = n_inside / float(tissue_true.sum())
TOL = 0.01

note("\nthe two definitions of tissue disagree on this scene:\n")
chk("DAPI > 0 covers the whole frame", float((dapi > 0).mean()) == 1.0, True)
close("true tissue is a fifth of the frame", tissue_true.mean(), math.pi * 60 ** 2 / N ** 2, 0.01)
chk("frame fraction is above the 1% tolerance", frac_frame >= TOL, True)
chk("in-tissue fraction is below it", want_tissue < TOL, True)

# ------------------------------------------------------------ tissue_fraction
note("\ntissue_fraction():\n")
close("fraction of tissue pixels that are clipped", G4J.tissue_fraction(cen, tissue_true), want_tissue, 1e-9)
chk("no tissue mask -> nan", math.isnan(G4J.tissue_fraction(cen, None)), True)
chk("empty tissue mask -> nan", math.isnan(G4J.tissue_fraction(cen, np.zeros_like(cen))), True)
close("DAPI > 0 would have reported the frame fraction",
      G4J.tissue_fraction(cen, dapi > 0), frac_frame, 1e-9)

# ------------------------------------------------------------ section_verdict
note("\nsection_verdict():\n")
v = G4J.section_verdict(frac_frame, want_tissue, TOL)
chk("decided on the in-tissue fraction: in the set", v["in_analysis_set"], 1)
chk("gate says tissue", v["gate"], "tissue")
close("frame fraction is still recorded", v["censored_fraction"], frac_frame, 1e-6)
close("in-tissue fraction is recorded", v["censored_fraction_in_tissue"], want_tissue, 1e-6)
chk("no reason when kept", v["reason"], "")

v = G4J.section_verdict(frac_frame, 0.05, TOL)
chk("5% clipped on tissue -> set aside", v["in_analysis_set"], 0)
chk("reason names the tissue fraction", "5.0%" in v["reason"] and "tissue" in v["reason"], True)

v = G4J.section_verdict(frac_frame, float("nan"), TOL)
chk("no tissue mask: falls back to the frame fraction", v["in_analysis_set"], 0)
chk("and says so", v["gate"], "frame")
chk("nan in-tissue fraction survives as nan", math.isnan(v["censored_fraction_in_tissue"]), True)

v = G4J.section_verdict(0.0, float("nan"), TOL)
chk("frame fallback with nothing clipped keeps the section", v["in_analysis_set"], 1)

# ---------------------------------------------------- tissue mask, disk or rebuilt
note("\nload_tissue_mask():\n")
tmp = tempfile.mkdtemp(prefix="censor_gate_")
try:
    dapi_path = os.path.join(tmp, "X_DAPI.png")
    Image.fromarray(dapi).save(dapi_path)
    tissue_dir = os.path.join(tmp, "tissue")
    os.makedirs(tissue_dir)

    t = G4J.load_tissue_mask("uid", dapi_path, tissue_dir)
    chk("rebuilt from DAPI when nothing is on disk", t is not None, True)
    chk("rebuilt mask is boolean in the overview frame",
        t is not None and t.dtype == bool and t.shape == dapi.shape, True)
    iou = float((t & tissue_true).sum() / (t | tissue_true).sum())
    chk("rebuilt mask is the disc (IoU > 0.9)", iou > 0.9, True)
    chk("and not the frame (covers < 30%)", float(t.mean()) < 0.3, True)
    close("in-tissue fraction from the rebuilt mask", G4J.tissue_fraction(cen, t), want_tissue, 0.002)

    # A deliberately different mask on disk must win over the rebuild.
    on_disk = np.zeros((N, N), dtype=bool)
    on_disk[:N // 2, :] = True
    Image.fromarray(on_disk.astype(np.uint8) * 255).save(os.path.join(tissue_dir, "uid_tissue.png"))
    t2 = G4J.load_tissue_mask("uid", dapi_path, tissue_dir)
    chk("tissue/<uid>_tissue.png is preferred when present", bool(np.array_equal(t2, on_disk)), True)

    chk("no mask and no DAPI -> None", G4J.load_tissue_mask("other", os.path.join(tmp, "nope.png"), tissue_dir) is None, True)

    flat = np.full((N, N), 3, dtype=np.uint8)
    flat_path = os.path.join(tmp, "flat_DAPI.png")
    Image.fromarray(flat).save(flat_path)
    chk("featureless DAPI -> None rather than a made-up mask",
        G4J.load_tissue_mask("flat", flat_path, tissue_dir) is None, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + (f"{fails} FAILED" if fails else "ALL PASS"))
sys.exit(1 if fails else 0)
