"""04i mixes two angle frames unless it converts between them explicitly.

`04a` resizes every overview to a 400x400 square BEFORE measuring the principal
axis, so its angle - `angle` in reformat_index.csv, and what `reformat()` returns
for the pERK scan - lives in a per-scan anisotropic frame. `04i.align()` measures
its angle on the isotropic physical grid. Subtracting one from the other is only
right when the scan box is square, which it rarely is, and the two scans of a
section have different boxes so the errors do not cancel.

What this suite pins is the thing the number is for: reformat the pERK overview
with the derived `extra_rotation` and compare its 256-px mask with the curated
PCNA 256-px mask. The gate is NOT a fixed IoU. The two 256-px masks are
differently-squashed pictures of one shape, so their IoU has a ceiling well
below 1 that depends on the two aspect ratios - measured at 0.65-0.81 on the
shapes below - and no rotation can raise it. The gate is that the derived angle
reaches that ceiling: within a few degrees of the angle that maximises the
256-px IoU, and within a small margin of the maximum itself. The ceiling is
found by brute force over the full circle, so the test does not assume the
conversion formula it is checking.

Synthetic throughout: an off-symmetric shape at a physical size, drawn once as
the PCNA overview and once rotated by a known angle as the pERK overview, each
on a scan box of a different aspect. Nothing here reads the dataset.

Run:  python tests/test_propagate_frames.py
"""

import importlib.util
import os
import sys
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage

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
    "p4i", os.path.join(SCRIPTS, "04i_propagate_to_perk.py"))
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
RF = P._RF

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


def iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))


def ang_diff(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


# ------------------------------------------------------------- synthetic scans
def shape(n=1000):
    """Ellipse tilted 25 degrees plus two off-centre blobs: no symmetry axis."""
    yy, xx = np.mgrid[:n, :n]
    c = n / 2
    t = np.radians(25)
    u = (xx - c) * np.cos(t) + (yy - c) * np.sin(t)
    v = -(xx - c) * np.sin(t) + (yy - c) * np.cos(t)
    m = (u / 330.0) ** 2 + (v / 170.0) ** 2 <= 1
    m |= (xx - (c + 180)) ** 2 + (yy - (c - 190)) ** 2 <= 80 ** 2
    m |= (xx - (c - 250)) ** 2 + (yy - (c + 60)) ** 2 <= 60 ** 2
    return m


def overview(mask, w, h, path, seed):
    """Draw the mask centred on a w x h scan box, with a little background noise
    so 04a's Otsu threshold has something to threshold."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w), np.float32)
    mh, mw = mask.shape
    y0, x0 = (h - mh) // 2, (w - mw) // 2
    sub = mask[max(0, -y0):, max(0, -x0):]
    y0, x0 = max(0, y0), max(0, x0)
    sub = sub[:h - y0, :w - x0]
    img[y0:y0 + sub.shape[0], x0:x0 + sub.shape[1]] = sub * 180.0
    img += rng.uniform(0, 12, img.shape)
    img = ndimage.gaussian_filter(img, 1.0)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path)


def ceiling(p568, pcna_mask):
    """Best 256-px IoU any extra_rotation can reach, and the angle that reaches
    it. Coarse over the circle, then fine around the best."""
    def at(e):
        r = RF.reformat(p568, False, extra_angle=float(e))
        return iou(r[1], pcna_mask)
    coarse = list(range(0, 360, 2))
    sc = [at(e) for e in coarse]
    e0 = coarse[int(np.argmax(sc))]
    fine = [e0 + k for k in range(-3, 4)]
    fs = [at(e) for e in fine]
    k = int(np.argmax(fs))
    return float(fs[k]), float(fine[k] % 360)


CASES = [
    # (physical rotation between the scans, PCNA box, pERK box, PCNA manual tilt)
    (37.0, (944, 1632), (1174, 1404), 20.0),
    (37.0, (1174, 1404), (944, 1632), 0.0),
    (37.0, (1000, 1400), (1000, 1400), 20.0),   # same aspect, still not square
]

tmp = tempfile.mkdtemp(prefix="propagate_frames_")

# ---------------------------------------------------- the frame conversion
note("\nthe frame conversion, against 04a's own principal_angle:\n")

# The check that does not depend on any formula: draw a thin bar at a known
# angle on a w x h box, squash it the way 04a does (resize to a square), and
# 04a's own principal_angle of the squashed bar must be what the conversion
# predicts. A bar, not the section shape: a principal axis is an eigenvector of
# a covariance and anisotropic scaling does not carry eigenvectors along as
# directions, so only a shape that IS a direction can be the probe. Direction
# of the map matters - the inverse map misses by twice the error below.
def bar(w, h, deg):
    yy, xx = np.mgrid[:h, :w]
    t = np.radians(deg)
    u = (xx - w / 2) * np.cos(t) + (yy - h / 2) * np.sin(t)
    v = -(xx - w / 2) * np.sin(t) + (yy - h / 2) * np.cos(t)
    return (np.abs(u) < 0.35 * min(w, h)) & (np.abs(v) < 6)


def axis_diff(a, b):
    d = ang_diff(a, b)
    return min(d, 180.0 - d)


for (w, h) in ((944, 1632), (1400, 1000)):
    phys = 30.0
    sq = np.asarray(Image.fromarray(bar(w, h, phys).astype(np.uint8) * 255)
                    .resize((RF.WORK_SIZE, RF.WORK_SIZE), Image.BILINEAR)) > 127
    want = RF.principal_angle(sq)
    fn = getattr(P, "physical_to_squashed", None)
    if fn is None:
        chk(f"04i has physical_to_squashed  (box {w}x{h})", False, True)
        continue
    got = fn(phys, w, h)
    close(f"physical -> squashed matches 04a  (box {w}x{h})", axis_diff(got, want), 0.0, 1.0)
    chk(f"and the unconverted angle does not   (box {w}x{h})", axis_diff(phys, want) > 5.0, True)
    close(f"round trip                          (box {w}x{h})",
          ang_diff(P.squashed_to_physical(got, w, h), phys), 0.0, 1e-6)

# ------------------------------------------------------- the whole code path
note("\nthe derived correction, pushed through 04a onto the pERK overview:\n")

X = shape()
for i, (theta, box488, box568, tilt488) in enumerate(CASES, 1):
    Xr = ndimage.rotate(X.astype(np.uint8), theta, order=0, reshape=True) > 0
    p488 = os.path.join(tmp, f"c{i}_488.png")
    p568 = os.path.join(tmp, f"c{i}_568.png")
    overview(X, *box488, p488, 1)
    overview(Xr, *box568, p568, 2)

    # The curated PCNA output: 04a with the operator's tilt, as reformat_index
    # records it (angle = total applied).
    r488 = RF.reformat(p488, False, extra_angle=tilt488)
    total488, pcna_mask = float(r488[2]), r488[1]

    d = P.derive_rotation(p488, p568, total488, pcna_mask)
    chk(f"case {i}: derivation succeeded", d is not None, True)
    if d is None:
        continue
    best_iou, best_deg = ceiling(p568, pcna_mask)
    note(f"   case {i}: theta={theta:g} boxes {box488[0]}x{box488[1]} / "
         f"{box568[0]}x{box568[1]}  align_iou={d['align_iou']:.3f}  "
         f"extra={d['extra']:.1f}  final_iou_256={d['final_iou_256']:.3f}  "
         f"ceiling={best_iou:.3f} at {best_deg:g}")
    chk(f"case {i}: the alignment itself is strong", d["align_iou"] > 0.95, True)
    # The 0.95 gate a fixed threshold would want is unreachable here, and that
    # is a property of the reformat, not of this stage: record it so nobody
    # tightens the gate below into something no code can pass.
    chk(f"case {i}: ceiling is below 0.95 (aspect, not angle)", best_iou < 0.95, True)
    close(f"case {i}: derived angle reaches the ceiling angle",
          ang_diff(d["extra"], best_deg), 0.0, 4.0)
    chk(f"case {i}: final_iou_256 within 0.025 of the ceiling",
        d["final_iou_256"] >= best_iou - 0.025, True)
    chk(f"case {i}: the reported final_iou_256 is what reformat gives",
        abs(d["final_iou_256"]
            - iou(RF.reformat(p568, False, extra_angle=d["extra"])[1], pcna_mask)) < 1e-9,
        True)


print()
print("--- the overview is where focus.csv says it is, not under two literals ---")

# 04i read the real channel out of focus.csv at :325-326 and then discarded it:
#
#     animal488, _ = chan.get(uid, (NM.subject_of(uid), "AF488"))
#     p488 = os.path.join(OVERVIEW_DIR, animal488, "AF488", uid + "_DAPI.png")
#     p568 = os.path.join(OVERVIEW_DIR, animal,    "AF568", u568 + "_DAPI.png")
#
# Overviews live in overviews/<animal>/<marker_channel>/, so for any study but
# LS both of those name directories that do not exist. Every section then fails
# the existence check, rotation_overrides_<marker>.csv comes out holding only
# the exclusion rows, `04a --apply-overrides` applies zero rotations, and every
# section is reformatted at its raw automatic angle - unaligned with the
# partner it was supposed to be aligned to. Nothing errors, and the summary
# prints a plausible "failed to reformat" count.
#
# 04i also read pairs.csv's `af488_scene_uid` / `af568_scene_uid` by literal.
# Those column names are now derived in 02 from the marker names, so reading
# them by literal here would be the same bug moved one file along.

from _fixture import temp_study, load_stage                  # noqa: E402
import csv                                                   # noqa: E402


def _wcsv(path, rows, cols):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


with temp_study(acquisition={"layout": "paired",
                             "markers": ["Mk1", "Mk2"]}) as MK:
    P4 = load_stage("04i_propagate_to_perk.py", name="lsstage_04i_mk")

    # Mk2 is the geometry source - the SECOND declared - so it is the curated
    # pass, and Mk1 is the one being propagated onto.
    chk("the target is the pass that does not own the unsuffixed names",
        P4.TARGET_MARKER, "Mk1")

    SRC, TGT = "Mk2", "Mk1"
    u_src, u_tgt = "AB12_1b-s0", "AB12_1a-s0"
    reformat_dir = P4.REFORMAT_DIR

    _wcsv(P4.PAIRS_CSV,
          [{"section_uid": "AB12_sec001", "status": "matched",
            "mk1_scene_uid": u_tgt, "mk2_scene_uid": u_src}],
          ["section_uid", "status", "mk1_scene_uid", "mk2_scene_uid"])
    _wcsv(os.path.join(reformat_dir, "reformat_index.csv"),
          [{"id": u_src, "kind": "section", "angle": "12.0"}],
          ["id", "kind", "angle"])
    _wcsv(os.path.join(reformat_dir, "excluded_sections.csv"), [], ["scene_uid"])
    _wcsv(os.path.join(P4.OUT_ROOT, "qc", "focus.csv"),
          [{"scene_uid": u_src, "animal": "AB12", "marker_channel": SRC},
           {"scene_uid": u_tgt, "animal": "AB12", "marker_channel": TGT}],
          ["scene_uid", "animal", "marker_channel"])
    for _animal, _marker, _uid in (("AB12", SRC, u_src), ("AB12", TGT, u_tgt)):
        d = os.path.join(P4.OVERVIEW_DIR, _animal, _marker)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, _uid + "_DAPI.png"), "wb").close()

    seen = []

    def _derive(p_source, p_target, total_source, curated_mask=None):
        seen.append((p_source, p_target))
        return {"extra": 3.0, "deg": 0.0, "auto_target": 0.0, "align_iou": 0.9,
                "flip_margin": 0.0, "final_iou_256": 0.88}

    _saved = P4.derive_rotation
    try:
        P4.derive_rotation = _derive
        P4.main()
    finally:
        P4.derive_rotation = _saved

    def _parts(p):
        return p.replace(os.sep, "/").split("/")

    chk("the curated pass's overview is reached at all", len(seen), 1)
    if seen:
        src_p, tgt_p = seen[0]
        chk("the source overview sits under focus.csv's channel for that uid",
            _parts(src_p)[-3:], ["AB12", SRC, u_src + "_DAPI.png"])
        chk("...and so does the target's",
            _parts(tgt_p)[-3:], ["AB12", TGT, u_tgt + "_DAPI.png"])

    with open(P4.OUT_CSV, newline="", encoding="utf-8") as fh:
        written = list(csv.DictReader(fh))
    chk("a rotation was derived and written", len(written), 1)
    chk("...for the target pass's scene", written[0]["perk_scene_uid"] if written
        else "", u_tgt)

    # 04i:74 defined REPORT_DIR = qc/perk and :284 created it. Nothing in the
    # repo ever wrote a file into it - grep for REPORT_DIR - so every run left
    # an empty directory in out_root that looked like a report that had failed
    # to be produced.
    chk("04i no longer defines a report directory nothing writes to",
        hasattr(P4, "REPORT_DIR"), False)
    chk("...and does not create qc/perk",
        os.path.exists(os.path.join(P4.OUT_ROOT, "qc", "perk")), False)

print("\n" + (f"{fails} FAILED" if fails else "ALL PASS"))
sys.exit(1 if fails else 0)
