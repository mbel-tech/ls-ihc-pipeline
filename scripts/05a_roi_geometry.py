"""Stage 5a - where each placed ROI actually is on the slide.

The operator draws ROIs on a 256 px normalised frame. Nothing can be counted
there: 256 px spans a whole section, about 25 um per pixel, and a nucleus is
7 um. Detection has to read the CZI at native 0.65 um/px, so every ROI has to
come back out of the normalised frame and land on real slide pixels.

`04a_reformat` built that frame by composing six operations, and this stage
inverts them:

    overview PNG  ->  square 400 grid  ->  rotate  ->  flip  ->  crop to the
    tissue bounding box  ->  square pad  ->  resize to 256

Every one is affine, so the composition is affine, and the whole thing reduces
to one 2x3 matrix per section. Rather than expand that algebra by hand - six
chances to transpose an axis, and a wrong answer that still looks plausible -
the matrix is obtained by evaluating the composition at three points and reading
off the columns.

`--verify` checks it against the real thing: two coordinate planes are pushed
through the SAME rotate, flip, crop, pad and resize, and compared with what the
matrix predicts, over every pixel of the frame. Agreement is 0.04-0.15 px, and
that residual is `reformat`'s own PIL downscale rather than the inverse - the
same filter deviates from an ideal centre-aligned mapping by 0.12 px on a plain
linear ramp with no composition involved at all.

**The parameters come from the run that produced the image, not a recomputation.**
`reformat(report=...)` fills them in as it goes. The mask decides the angle and
the angle decides the crop, so a second opinion about the mask would move every
ROI on the section. The reported angle is checked against the one
`reformat_index` recorded at the time, and a section where they disagree is
refused rather than guessed at.

**A circle here is an ellipse on the slide.** Step one resizes the overview to a
SQUARE 400 grid, and scan boxes are hand-drawn and rarely square - 944x1404 on
the first section tried, a 49% axis ratio. Anything that carries `sec_r` forward
as a radius is wrong. What this stage writes is a bounding box; membership is
decided per pixel by mapping back, which is exact and needs no ellipse algebra.

Reads the ROIs from a `roi_regions.csv` export, which already carries them in
canonical 256 coordinates with their region, seed number and kind.

Writes, PER MARKER - see the note on the paths below, which is the whole
reason the suffix exists:
    reformatted/roi_geometry_<MARKER>.csv   one row per section: the six
                                   parameters, the CZI scene rectangle, and the
                                   composed matrix
    reformatted/roi_boxes_<MARKER>.csv      one row per ROI: its CZI pixel
                                   bounding box
    reformatted/roi_regions_used_<MARKER>.csv  the export these came from

The marker is read from the export's own `marker` column, not passed in.

Run:  python 05a_roi_geometry.py
      python 05a_roi_geometry.py path/to/roi_regions.csv
      python 05a_roi_geometry.py --verify
"""

import sys
import argparse
import csv
import datetime
import glob
import importlib.util
import json
import os
import shutil

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_rf", os.path.join(_HERE, "04a_reformat.py"))
RF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RF)

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
OUT_ROOT = RF.OUT_ROOT
REFORMAT_DIR = RF.REFORMAT_DIR
# Where the curator files its exports, one DD.MM.YYYY_HH.MM folder per export.
# Same key 04l and the app read, so all three look in one place.
EXPORT_DIR = CONFIG.get("export_dir") or os.path.join(OUT_ROOT, "exports")
OVERVIEW_DIR = RF.OVERVIEW_DIR
FOCUS_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
MANIFEST_CSV = os.path.join(OUT_ROOT, "manifest", "manifest_scenes.csv")

# ---- output paths are PER MARKER, and that is not cosmetic ------------------
#
# This stage writes its outputs with mode "w" from ONE roi_regions.csv export.
# While both markers shared `roi_boxes.csv`, running it against a PCNA export
# would have replaced the pERK boxes outright - and roi_nuclei.csv joins to that
# file by (scene_uid, roi_index) in 06a and 06c, so 883,000 measured rows would
# have quietly lost the geometry they were measured against. Nothing would have
# errored.
#
# AF568 and AF488 sections have DISJOINT scene_uids - they are separate
# acquisitions - so the two files never overlap and downstream stages that want
# everything can simply read both.
MARKERS = ("AF568", "AF488")

# Everything written before 2026-09-01 is AF568 and has no suffix. Read as a
# fallback so an existing out_root keeps working; never written to again.
LEGACY_GEOM = os.path.join(REFORMAT_DIR, "roi_geometry.csv")
LEGACY_BOX = os.path.join(REFORMAT_DIR, "roi_boxes.csv")


def geom_csv(marker):
    return os.path.join(REFORMAT_DIR, f"roi_geometry_{marker}.csv")


def box_csv(marker):
    return os.path.join(REFORMAT_DIR, f"roi_boxes_{marker}.csv")


def resolve_paths(marker):
    """The pair to READ for this marker, preferring the suffixed files."""
    g, b = geom_csv(marker), box_csv(marker)
    # Both legacy files or neither. Deciding on the box file alone would hand
    # back LEGACY_GEOM for a repo that already has roi_geometry_AF568.csv, and
    # that path may not exist.
    if (marker == "AF568" and not os.path.exists(b) and not os.path.exists(g)
            and os.path.exists(LEGACY_BOX) and os.path.exists(LEGACY_GEOM)):
        return LEGACY_GEOM, LEGACY_BOX
    return g, b


MARKER = "AF568"
GEOM_CSV, BOX_CSV = resolve_paths(MARKER)


def use_marker(marker):
    """Point the module-level paths at one marker. Importers call this."""
    global MARKER, GEOM_CSV, BOX_CSV
    if marker not in MARKERS:
        raise ValueError(f"unknown marker {marker!r}; expected one of {MARKERS}")
    MARKER = marker
    GEOM_CSV, BOX_CSV = resolve_paths(marker)
    return MARKER


def all_boxes():
    """Every marker's boxes, concatenated, for stages that span both.

    06a, 06c and 06d work off `roi_nuclei.csv`, which holds both markers once
    the PCNA pass has run, so they need every box rather than one marker's.
    Scene uids are disjoint across markers, so this is a union and not a merge.
    """
    out, uids = [], {}
    for m in MARKERS:
        p = resolve_paths(m)[1]
        if not os.path.exists(p):
            continue
        rows = load_csv(p)
        # THE DISJOINTNESS IS CHECKED, NOT ASSUMED. 06a joins a nucleus to its
        # disc by (scene_uid, roi_index), where the index is the position of the
        # box in this list for that uid. If two markers ever shared a uid their
        # boxes would interleave and every nucleus on that section would be
        # measured against the wrong disc - silently, with plausible numbers.
        for r in rows:
            u = r["scene_uid"]
            if uids.get(u, m) != m:
                raise SystemExit(
                    f"scene_uid {u} appears under both {uids[u]} and {m}. "
                    f"The per-marker box files must not overlap - every "
                    f"downstream join is by (scene_uid, roi_index) and would "
                    f"silently pair nuclei with the wrong discs.")
            uids[u] = m
        out.extend(rows)
    return out

BASE_PX_UM = CONFIG["pixel_size_um"]

# The curator writes sec_x/sec_y/sec_r already divided by the render scale, so
# they are canonical-grid pixels and this stage needs no scale factor of its own.
SEC_GRID = RF.GRID


# --------------------------------------------------------------------------
# the composition


def affine_from(fn):
    """The 2x3 matrix of an affine map, read off by evaluating it three times.

    `fn(u, v) -> (x, y)`. Composing six transforms symbolically is six chances
    to flip a sign or swap an axis, and every one of those errors produces a
    matrix that still looks like a matrix. Evaluating instead means the code
    that builds the map and the code that uses it are the same code.
    """
    o = np.asarray(fn(0.0, 0.0), float)
    du = np.asarray(fn(1.0, 0.0), float) - o
    dv = np.asarray(fn(0.0, 1.0), float) - o
    return np.array([[du[0], dv[0], o[0]],
                     [du[1], dv[1], o[1]]], float)


def apply_affine(M, u, v):
    u = np.asarray(u, float)
    v = np.asarray(v, float)
    return (M[0, 0] * u + M[0, 1] * v + M[0, 2],
            M[1, 0] * u + M[1, 1] * v + M[1, 2])


def invert_affine(M):
    A = M[:, :2]
    inv = np.linalg.inv(A)
    t = -inv @ M[:, 2]
    return np.hstack([inv, t.reshape(2, 1)])


def parse_poly(text):
    """The `sec_poly` cell as an (N, 2) array of canonical-grid points, or None.

    The curator writes `"x y;x y;..."` at 2dp in the canonical 256 frame - one
    cell rather than one row per vertex, so `roi_regions.csv` keeps its promise
    of one row per ROI and every downstream join by (scene_uid, roi_index) goes
    on meaning what it meant.

    Under three points is not a polygon and is treated as no polygon at all, so
    the caller refuses the row rather than bounding a shape with no interior.
    """
    if not text:
        return None
    pts = []
    for vtx in str(text).split(";"):
        xy = vtx.split()
        if len(xy) != 2:
            continue
        try:
            pts.append((float(xy[0]), float(xy[1])))
        except ValueError:
            return None
    return np.asarray(pts, float) if len(pts) >= 3 else None


def outline_area(X, Y):
    """Shoelace area of a closed outline, in the units of X and Y.

    Taken AFTER the map rather than before it and scaled: an affine multiplies
    every area by |det A|, so both routes agree, but doing it here means the
    same function measures a mapped circle and a mapped polygon and there is no
    second formula to keep in step.
    """
    return 0.5 * abs(float(np.dot(X, np.roll(Y, -1)) - np.dot(Y, np.roll(X, -1))))


def ellipse_axes(M, sr):
    """The two semi-axes, larger first, of the ellipse a grid circle of radius
    `sr` becomes under `M`, in the units of M's output.

    They are the singular values of the linear part, not the norms of its
    columns. The columns are the images of the grid's unit vectors, and their
    lengths equal the semi-axes only while they stay orthogonal - angle 0, 90,
    180 or 270. Rotate the same rectangular box by 45 degrees and the two
    columns come out the SAME length while the section is exactly as stretched
    as before: the column-norm reading says "circle" and overstates the area
    by 15% on a 944x1632 box. The singular values do not move with the angle.
    """
    s = np.linalg.svd(np.asarray(M, float)[:, :2], compute_uv=False)
    return float(s[0] * sr), float(s[1] * sr)


def anisotropy(M):
    """s_max / s_min of the linear part: 1.0 means a circle stays a circle."""
    a, b = ellipse_axes(M, 1.0)
    return a / b


def grid_to_overview(rep):
    """Map a point on the normalised 256 grid back to a pixel of the overview PNG.

    The inverse of `04a_reformat.reformat`, step by step and in reverse. The
    rotation convention is scipy's, measured rather than assumed: a point offset
    (dx, dy) from the input centre lands at

        x' =  dx*cos(a) + dy*sin(a)
        y' = -dx*sin(a) + dy*cos(a)

    from the centre of the reshaped output. Verified against
    `ndimage.rotate` over 16 angle/point combinations, worst error 0.08 px.
    """
    ws = rep["work_size"]
    th = np.radians(rep["angle"])
    cos, sin = np.cos(th), np.sin(th)
    cx_r, cy_r = (rep["rot_w"] - 1) / 2.0, (rep["rot_h"] - 1) / 2.0
    cw = (ws - 1) / 2.0

    def fn(u, v):
        # 6. resize side -> grid, undone. PIL maps source [0, side] onto
        #    [0, grid], so pixel CENTRES sit at (i + 0.5) * side/grid - 0.5.
        k = rep["side"] / float(rep["grid"])
        x = (u + 0.5) * k - 0.5
        y = (v + 0.5) * k - 0.5
        # 5. square pad
        x -= rep["ox"]
        y -= rep["oy"]
        # 4. crop to the tissue bounding box
        x += rep["x0"]
        y += rep["y0"]
        # 3. horizontal flip
        if rep["flip"]:
            x = (rep["rot_w"] - 1) - x
        # 2. rotation, about the centre of the working grid
        dx, dy = x - cx_r, y - cy_r
        wx = cw + (dx * cos - dy * sin)
        wy = cw + (dx * sin + dy * cos)
        # 1. the square resize of a rectangular overview - the anisotropic step
        px = (wx + 0.5) * rep["src_w"] / float(ws) - 0.5
        py = (wy + 0.5) * rep["src_h"] / float(ws) - 0.5
        return px, py

    return fn


# --------------------------------------------------------------------------
# inputs


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def find_regions_csv(explicit):
    """Where the ROIs come from. The newest export wins.

    The curator runs in a browser and cannot be handed a path, so an export
    turns up in one of three places: the folder the operator picked for it, the
    reformat directory when the app filed it, or the download folder. Since
    2026-09-06 each export goes into its own `DD.MM.YYYY_HH.MM` folder and every
    file in it carries that stamp, so the search runs one level deep as well as
    flat - `roi_regions*.csv` still matches the stamped name, but not through a
    directory.

    Every candidate is collected and the newest mtime wins, rather than the
    reformat directory short-circuiting the search. That mattered the moment
    exports stopped writing an unsuffixed file there: the copy left over from
    the previous run is still on disk, and taking it because it exists would
    quietly analyse the old curation while a fresh export sat unread.
    """
    if explicit:
        return explicit
    roots = [REFORMAT_DIR, EXPORT_DIR, os.path.join(os.path.expanduser("~"), "Downloads")]
    cand = []
    for root in roots:
        if not root:
            continue
        cand += glob.glob(os.path.join(root, "roi_regions*.csv"))
        cand += glob.glob(os.path.join(root, "*", "roi_regions*.csv"))
    if cand:
        return max(cand, key=os.path.getmtime)
    return None


def scene_rects(czi_path):
    """The scene bounding rectangles of one CZI, in native pixels.

    This is the only piece that cannot come from a CSV: the overview export
    read `czidoc.scenes_bounding_rectangle` at the time and did not record it.
    Header read only - it does not decode any pixels.
    """
    from pylibCZIrw import czi as pyczi
    with pyczi.open_czi(czi_path) as doc:
        return {int(k): (int(r.x), int(r.y), int(r.w), int(r.h))
                for k, r in doc.scenes_bounding_rectangle.items()}


# --------------------------------------------------------------------------


def analysis_set(regions, plates):
    """Which sections are measurable, and a full account of what was dropped.

    Three conditions, and each rejects for a different reason:

      * at least one ROI - there is nothing to measure otherwise;
      * at least one BACKGROUND disc - the positivity cut is per section and is
        read against that section's own background, so a section without one has
        no reference of its own. Borrowing another section's would silently
        substitute a different piece of tissue for the control;
      * not excluded - `excluded` is the operator's own judgement recorded in
        roi_plates.csv, and measuring a section they threw out would quietly
        overrule it.

    Reported rather than filtered silently, because the counts are a result in
    their own right: how many sections were curated but cannot be used, and why,
    is exactly what someone reading the dataset will ask.
    """
    roi, bg = {}, {}
    for r in regions:
        u = r["scene_uid"]
        d = bg if r.get("roi_kind") == "background" else roi
        d[u] = d.get(u, 0) + 1
    excluded = {r["scene_uid"] for r in plates if r.get("excluded") == "1"}

    keep, dropped = [], []
    for u in sorted(set(roi) | set(bg)):
        if u in excluded:
            dropped.append((u, "excluded by the operator"))
        elif not roi.get(u):
            dropped.append((u, f"no ROI ({bg.get(u, 0)} background only)"))
        elif not bg.get(u):
            dropped.append((u, f"no background disc ({roi[u]} ROIs)"))
        else:
            keep.append(u)
    return keep, dropped, roi, bg


def build(regions_csv, limit=None, plates_csv=None, require_background=True):
    regions = load_csv(regions_csv)
    plates = load_csv(plates_csv) if (plates_csv and os.path.exists(plates_csv)) else []

    if require_background:
        keep, dropped, n_roi, n_bg = analysis_set(regions, plates)
        by_reason = {}
        for _u, wh in dropped:
            k = wh.split(" (")[0]
            by_reason[k] = by_reason.get(k, 0) + 1
        print(f"analysis set: {len(keep)} sections of {len(keep) + len(dropped)} curated")
        for k, n in sorted(by_reason.items()):
            print(f"    dropped {n:3d}: {k}")
        kept = set(keep)
        regions = [r for r in regions if r["scene_uid"] in kept]
    focus = {r["scene_uid"]: r for r in load_csv(FOCUS_CSV)}
    man = {r["scene_uid"]: r for r in load_csv(MANIFEST_CSV)}

    # manual_rotation / manual_flip are what 04a passed as extra_angle / flip,
    # and `angle` is what came out. Both are needed: the first to reproduce the
    # geometry, the second to prove it was reproduced.
    index = {}
    for marker in ("AF568", "AF488"):
        name = ("reformat_index.csv" if marker == "AF488"
                else f"reformat_index_{marker}.csv")
        p = os.path.join(REFORMAT_DIR, name)
        if os.path.exists(p):
            for r in load_csv(p):
                if r["kind"] == "section":
                    index[r["id"]] = r

    uids = sorted({r["scene_uid"] for r in regions if r.get("scene_uid")})
    if limit:
        uids = uids[:limit]

    geom_rows, box_rows, skipped = [], [], []
    shapeless = []          # ROI rows carrying no geometry at all - see below
    rect_cache = {}

    for n, uid in enumerate(uids, 1):
        f, m, ix = focus.get(uid), man.get(uid), index.get(uid)
        if not (f and m and ix):
            skipped.append((uid, "not in focus.csv / manifest / reformat_index"))
            continue
        src = os.path.join(OVERVIEW_DIR, f["animal"], f["marker_channel"],
                           uid + "_DAPI.png")
        if not os.path.exists(src):
            skipped.append((uid, "overview PNG missing"))
            continue

        extra = float(ix.get("manual_rotation") or 0)
        flip = (ix.get("manual_flip") or "0") == "1"
        art = RF.load_artifact(uid, (RF.WORK_SIZE, RF.WORK_SIZE))
        cen = RF.load_censor(uid, (RF.WORK_SIZE, RF.WORK_SIZE))
        rep = {}
        out = RF.reformat(src, light_background=False, extra_angle=extra, flip=flip,
                          artifact=art, censor=cen, report=rep)
        if out is None:
            skipped.append((uid, "reformat produced no tissue mask"))
            continue

        # The one check that says the geometry reproduced is the RECORDED one.
        # 04a rounded it to 1 dp on the way into the index.
        recorded = float(ix["angle"])
        if abs(((rep["angle"] - recorded + 180) % 360) - 180) > 0.06:
            skipped.append((uid, f"angle {rep['angle']:.2f} != recorded {recorded:.2f}"))
            continue

        # overview pixel -> CZI pixel. The overview was read with
        # zoom = pixel_size_um / um_px over the scene's bounding rectangle, so
        # undoing it is a scale and an origin shift.
        um_px = float(f["um_px"])
        scale = um_px / BASE_PX_UM
        czi = m["file"]
        if czi not in rect_cache:
            path = os.path.join(CONFIG["source_dir"], czi)
            try:
                rect_cache[czi] = scene_rects(path)
            except Exception as exc:                      # noqa: BLE001
                rect_cache[czi] = {"_error": str(exc)}
        rects = rect_cache[czi]
        si = int(m["scene_index"])
        if "_error" in rects or si not in rects:
            skipped.append((uid, "no scene rectangle: "
                            + rects.get("_error", f"scene {si} absent")))
            continue
        rx, ry, rw, rh = rects[si]

        # A cheap consistency check on the whole chain: the overview PNG should
        # be the scene rectangle at the recorded scale. If these disagree the
        # section was exported against a different rectangle than the one being
        # read now, and every coordinate below would be silently offset.
        exp_w, exp_h = round(rw / scale), round(rh / scale)
        if abs(exp_w - rep["src_w"]) > 2 or abs(exp_h - rep["src_h"]) > 2:
            skipped.append((uid, f"overview {rep['src_w']}x{rep['src_h']} does not "
                                 f"match scene rect {exp_w}x{exp_h} at {um_px} um/px"))
            continue

        g2o = grid_to_overview(rep)
        M = affine_from(lambda u, v: (lambda p: (rx + p[0] * scale,
                                                 ry + p[1] * scale))(g2o(u, v)))

        geom_rows.append({
            "scene_uid": uid, "animal": f["animal"], "marker": f["marker_channel"],
            "czi_file": czi, "scene_index": si,
            "scene_x": rx, "scene_y": ry, "scene_w": rw, "scene_h": rh,
            "overview_um_px": um_px, "native_um_px": BASE_PX_UM,
            "src_w": rep["src_w"], "src_h": rep["src_h"],
            "work_size": rep["work_size"],
            "angle_deg": round(rep["angle"], 4), "flip": int(rep["flip"]),
            "manual_rotation_deg": extra,
            "rot_w": rep["rot_w"], "rot_h": rep["rot_h"],
            "crop_x0": rep["x0"], "crop_y0": rep["y0"],
            "crop_w": rep["crop_w"], "crop_h": rep["crop_h"],
            "pad_side": rep["side"], "pad_ox": rep["ox"], "pad_oy": rep["oy"],
            "grid": rep["grid"],
            # grid (u,v) -> CZI absolute pixel (x,y)
            "m00": M[0, 0], "m01": M[0, 1], "m02": M[0, 2],
            "m10": M[1, 0], "m11": M[1, 1], "m12": M[1, 2],
            # How anisotropic this section is: the ratio of the two singular
            # values of the linear part (see `ellipse_axes` for why not the
            # column norms). 1.0 would mean a circle stays a circle.
            "anisotropy": round(anisotropy(M), 4),
        })

        for r in regions:
            if r["scene_uid"] != uid:
                continue
            sx, sy = float(r["sec_x"]), float(r["sec_y"])
            sr = float(r["sec_r"] or 0)
            poly = parse_poly(r.get("sec_poly", ""))
            # The ROI outline mapped point by point, then bounded. Mapping a
            # radius would assume the map is a similarity, and it is not - and
            # that is exactly why a polygon needs nothing new here. A disc was
            # already being turned into a 128-point outline before it was
            # mapped; a drawn region arrives as an outline already.
            if poly is not None:
                U, V = poly[:, 0], poly[:, 1]
            elif sr > 0:
                t = np.linspace(0, 2 * np.pi, 128, endpoint=False)
                U, V = sx + sr * np.cos(t), sy + sr * np.sin(t)
            else:
                # Neither a radius nor a ring. Refused rather than guessed at,
                # the same way a section whose geometry cannot be reconstructed
                # is refused: a zero-area ROI would reach 06a as a division by
                # zero, or worse, as a density of nothing per nothing.
                #
                # Counted apart from `skipped`, which everywhere else in this
                # stage means a whole SECTION was dropped. Folding a bad row
                # into that number would report a section as lost when it was
                # measured perfectly well.
                shapeless.append((uid, r.get("region", "")))
                continue
            X, Y = apply_affine(M, U, V)
            cx, cy = apply_affine(M, sx, sy)
            x0, x1 = int(np.floor(X.min())), int(np.ceil(X.max()))
            y0, y1 = int(np.floor(Y.min())), int(np.ceil(Y.max()))
            # A polygon has no semi-axes. They describe the ellipse a CIRCLE
            # becomes, and leaving them blank is the honest way to say the
            # question does not apply - writing the bounding box's half-widths
            # there would put a number in a column 06a reads as an area.
            ax_a, ax_b = ellipse_axes(M, sr) if poly is None else (None, None)
            box_rows.append({
                "scene_uid": uid, "animal": f["animal"], "marker": f["marker_channel"],
                "roi_kind": r.get("roi_kind") or "roi",
                "region": r.get("region", ""), "seed_n": r.get("seed_n", ""),
                "sec_x": sx, "sec_y": sy, "sec_r": sr,
                "czi_file": czi, "scene_index": si,
                "czi_cx": round(float(cx), 2), "czi_cy": round(float(cy), 2),
                "czi_x0": x0, "czi_y0": y0,
                "czi_w": x1 - x0, "czi_h": y1 - y0,
                # The two semi-axes in um, larger first, so a glance says how
                # big the ROI really is and how far from circular the mapping
                # made it. 06a takes pi*a*b from these as the ROI area.
                "axis_a_um": "" if ax_a is None else round(ax_a * BASE_PX_UM, 1),
                "axis_b_um": "" if ax_b is None else round(ax_b * BASE_PX_UM, 1),
                # The area as measured, whatever the shape. pi*a*b for a disc,
                # the shoelace over the mapped vertices for a polygon - which is
                # the true area of the mapped shape, since an affine scales
                # every area by |det A| and the shoelace is taken AFTER the map.
                "area_um2": round(outline_area(X, Y) * BASE_PX_UM ** 2, 1)
                            if poly is not None
                            else round(np.pi * ax_a * ax_b * BASE_PX_UM ** 2, 1),
                # The shape carried through, so 05c can decide membership with
                # the same outline this box was cut from.
                "roi_shape": "polygon" if poly is not None else "disc",
                "sec_poly": r.get("sec_poly", "") or "",
            })

        if n % 25 == 0:
            print(f"\r  {n}/{len(uids)} sections", end="")

    print(f"\r  {len(uids)} sections                    ")
    if shapeless:
        print(f"  REFUSED {len(shapeless)} ROI rows carrying neither sec_r nor "
              f"sec_poly - no shape, so no area and no box:")
        for _u, _reg in shapeless[:10]:
            print(f"    {_u} {_reg}")
        if len(shapeless) > 10:
            print(f"    ... and {len(shapeless) - 10} more")
    return geom_rows, box_rows, skipped


# --------------------------------------------------------------------------
# verification


def verify(n_sections=6):
    """Check the composed map against the transform it claims to invert.

    Push two coordinate planes - one holding x, one holding y - through the
    SAME rotate, flip, crop, pad and resize that `reformat` applied, then ask
    the analytic map for the same answer. A linear ramp under linear
    interpolation is exact, so in the interior the two should agree to floating
    point. Where the rotation's NaN border bleeds in, the planes go NaN and
    those pixels exclude themselves.

    This replaced a dot-planting test that measured its own noise. Planting a
    bright disc in the overview and finding it again sounds direct, but the
    centroid of a blob that has been rotated, cropped and downsampled twice is
    good to about a pixel, and near the tissue edge - where `reformat` zeroes
    everything outside the silhouette - it is dragged inward by five. That read
    as a 148 um transform error and was nothing of the kind. Coordinate planes
    have no such problem: they perturb nothing and they cover every pixel of the
    frame rather than six of them.

    **The floor is PIL, and it is not zero.** Measured on a pure linear ramp,
    with no composition involved at all:

        ndimage.rotate(order=1)     mean 4.4e-06  max 1.5e-05   (float32 noise)
        PIL resize BILINEAR 313->256  mean 4.0e-02  max 1.2e-01

    So `reformat`'s own downscale deviates from the ideal centre-aligned mapping
    by up to about 0.12 px, and no inverse can do better than that. The whole
    residual below is that filter. 0.15 grid px is 3.7 um on the slide - half a
    nucleus, 1% of an ROI radius - so the tolerance is set to catch a broken
    composition, which would be a whole pixel or more, rather than to chase a
    number the resampler will not give back.
    """
    focus = {r["scene_uid"]: r for r in load_csv(FOCUS_CSV)}
    index = {}
    for name in ("reformat_index.csv", "reformat_index_AF568.csv"):
        p = os.path.join(REFORMAT_DIR, name)
        if os.path.exists(p):
            for r in load_csv(p):
                if r["kind"] == "section":
                    index[r["id"]] = r

    from scipy import ndimage

    # THIS MARKER'S SECTIONS. Both reformat indices are loaded above, so
    # without the filter the sample is whichever uids happen to come first in a
    # merged dict - which made `--verify --marker AF488` print AF488 and then
    # check a mixture. The composed map is the same code for both markers, so
    # this changes nothing about what is being tested; it changes whether the
    # heading is true.
    want = [u for u in index if u in focus
            and focus[u].get("marker_channel") == MARKER]
    uids = (want or [u for u in index if u in focus])[:n_sections]
    if not want:
        print(f"  (no {MARKER} sections in focus.csv - sampling whatever is there)")
    worst = 0.0
    checked = 0
    for uid in uids:
        f, ix = focus[uid], index[uid]
        src = os.path.join(OVERVIEW_DIR, f["animal"], f["marker_channel"],
                           uid + "_DAPI.png")
        if not os.path.exists(src):
            continue
        extra = float(ix.get("manual_rotation") or 0)
        flip = (ix.get("manual_flip") or "0") == "1"
        rep = {}
        if RF.reformat(src, light_background=False, extra_angle=extra, flip=flip,
                       report=rep) is None:
            continue

        ws = rep["work_size"]
        ramp_x = np.tile(np.arange(ws, dtype=np.float32), (ws, 1))
        ramp_y = np.tile(np.arange(ws, dtype=np.float32).reshape(-1, 1), (1, ws))

        def carry(A):
            R = ndimage.rotate(A, rep["angle"], order=1, reshape=True, cval=np.nan)
            if R.shape != (rep["rot_h"], rep["rot_w"]):
                return None
            if rep["flip"]:
                R = R[:, ::-1]
            C = R[rep["y0"]:rep["y0"] + rep["crop_h"],
                  rep["x0"]:rep["x0"] + rep["crop_w"]]
            P = np.full((rep["side"], rep["side"]), np.nan, np.float32)
            P[rep["oy"]:rep["oy"] + rep["crop_h"],
              rep["ox"]:rep["ox"] + rep["crop_w"]] = C
            return np.asarray(Image.fromarray(P).resize(
                (rep["grid"], rep["grid"]), Image.BILINEAR))

        XG, YG = carry(ramp_x), carry(ramp_y)
        if XG is None or YG is None:
            print(f"  {uid}: rotation shape disagreed - skipped")
            continue

        # The analytic map, stopped before the anisotropic overview rescale so
        # both sides are in the same 400-grid units.
        th = np.radians(rep["angle"])
        cos, sin = np.cos(th), np.sin(th)
        cxr, cyr = (rep["rot_w"] - 1) / 2.0, (rep["rot_h"] - 1) / 2.0
        cw = (ws - 1) / 2.0
        k = rep["side"] / float(rep["grid"])
        vs, us = np.mgrid[:rep["grid"], :rep["grid"]]
        x = (us + 0.5) * k - 0.5 - rep["ox"] + rep["x0"]
        y = (vs + 0.5) * k - 0.5 - rep["oy"] + rep["y0"]
        if rep["flip"]:
            x = (rep["rot_w"] - 1) - x
        dx, dy = x - cxr, y - cyr
        pu = cw + (dx * cos - dy * sin)
        pv = cw + (dx * sin + dy * cos)

        ok = np.isfinite(XG) & np.isfinite(YG)
        if ok.sum() < 1000:
            continue
        err = np.hypot(pu - XG, pv - YG)[ok]
        w = float(np.percentile(err, 99.9))
        worst = max(worst, w)
        checked += 1
        print(f"  {uid}  angle {rep['angle']:7.2f}  flip {int(rep['flip'])}  "
              f"{ok.sum():6d} px checked   mean {err.mean():.2e}  "
              f"p99.9 {w:.2e}  max {err.max():.2e}")

    print(f"\n  {checked} sections, worst p99.9 error {worst:.2e} grid px")
    return worst, checked


def verify_czi(limit=4):
    """Check the other half of the chain: overview pixel -> CZI pixel.

    The coordinate-plane test above proves the map from the 256 grid back to the
    overview PNG. It says nothing about the step after it, which is where a
    wrong scene rectangle would hide - and that step is the one carrying every
    coordinate onto the actual slide.

    So re-read the CZI over the recorded scene rectangle at the recorded zoom
    and compare with the overview PNG that was exported at the time. Shape must
    match exactly. Correlation is compared against the same images offset by
    20 px, because a high correlation on its own proves very little about
    alignment: two pictures of the same section correlate whatever the offset,
    and only the DROP when shifted says the registration is real.

    It does not reach 1.0 and should not - the export applied a frozen display
    range and the tile-field correction, so the stored PNG is a processed copy,
    not the raw read.
    """
    if not os.path.exists(GEOM_CSV):
        print(f"  (no {os.path.basename(GEOM_CSV)} yet - run the stage first)")
        return None, 0
    rows = load_csv(GEOM_CSV)[:limit]
    worst_drop = 1.0
    checked = 0
    for g in rows:
        uid = g["scene_uid"]
        ov = os.path.join(OVERVIEW_DIR, g["animal"], g["marker"], uid + "_DAPI.png")
        path = os.path.join(CONFIG["source_dir"], g["czi_file"])
        if not (os.path.exists(ov) and os.path.exists(path)):
            continue
        stored = np.asarray(Image.open(ov).convert("L")).astype(np.float64)
        rx, ry, rw, rh = (int(g[k]) for k in ("scene_x", "scene_y", "scene_w", "scene_h"))
        zoom = float(g["native_um_px"]) / float(g["overview_um_px"])
        from pylibCZIrw import czi as pyczi
        with pyczi.open_czi(path) as doc:
            a = np.squeeze(doc.read(roi=(rx, ry, rw, rh), plane={"C": 0},
                                    zoom=zoom)).astype(np.float64)
        same_shape = a.shape == stored.shape
        h, w = min(stored.shape[0], a.shape[0]), min(stored.shape[1], a.shape[1])
        r = np.corrcoef(stored[:h, :w].ravel(), a[:h, :w].ravel())[0, 1]
        rs = np.corrcoef(stored[:h - 20, :w - 20].ravel(),
                         a[20:h, 20:w].ravel())[0, 1]
        worst_drop = min(worst_drop, r - rs)
        checked += 1
        print(f"  {uid}  shape {'match' if same_shape else 'MISMATCH'} "
              f"{a.shape} vs {stored.shape}   aligned r={r:.3f}  "
              f"shifted r={rs:.3f}   drop {r - rs:.3f}")
        if not same_shape:
            worst_drop = -1.0
    print(f"\n  {checked} sections, smallest alignment margin {worst_drop:.3f}")
    return worst_drop, checked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("regions", nargs="?", help="roi_regions.csv from the curator")
    ap.add_argument("--plates", help="roi_plates.csv, for the excluded flag "
                                     "(default: the sibling of the regions file)")
    ap.add_argument("--all-sections", action="store_true",
                    help="skip the analysis-set rule and take every section with "
                         "an ROI, background disc or not")
    ap.add_argument("--verify", action="store_true",
                    help="check the composed map against the real reformat")
    ap.add_argument("--limit", type=int, help="only the first N sections")
    ap.add_argument("--marker", choices=MARKERS, default=None,
                    help="which marker this export is for; inferred from the "
                         "export's own marker column when omitted")
    args = ap.parse_args()

    if args.verify:
        # --verify reads GEOM_CSV, and the marker is normally inferred from the
        # export - which --verify does not read. Without this it would check the
        # AF568 geometry and print PASS whatever --marker said.
        use_marker(args.marker or "AF568")
        print(f"marker: {MARKER}  ({os.path.basename(GEOM_CSV)})")
        print("grid -> overview  (coordinate planes through the same transform)")
        worst, checked = verify()
        if not checked:
            print("\nnothing could be checked")
            return 1
        # 0.3 grid px = 7.5 um on the slide. The measured floor is 0.15, set
        # entirely by PIL's resize filter (see verify's docstring), so this
        # leaves headroom over the floor while still failing loudly on a
        # composition error - a transposed axis or a dropped flip moves things
        # by tens of pixels, not tenths.
        ok = worst < 0.3
        print("  PASS" if ok else "  FAIL - the composed map does not match reformat")

        # The half the coordinate planes cannot reach.
        print("\noverview -> CZI  (re-read the scene rectangle and compare)")
        drop, n_czi = verify_czi()
        if n_czi:
            czi_ok = drop >= 0.3
            print("  PASS" if czi_ok else
                  "  FAIL - the scene rectangle does not align with the overview")
            ok = ok and czi_ok
        return 0 if ok else 1

    regions = find_regions_csv(args.regions)
    if not regions or not os.path.exists(regions):
        print("no roi_regions.csv found.\n"
              "Export from the ROI curator, then pass the path:\n"
              "    python 05a_roi_geometry.py \"C:/Users/you/Downloads/roi_regions.csv\"")
        return 1
    # THE MARKER COMES FROM THE EXPORT. The curator stamps it into every row
    # (04l --marker), so asking the operator to repeat it here is one more thing
    # to get wrong - and getting it wrong would write one marker's boxes to the
    # other's file, which is the exact failure the per-marker paths exist to
    # prevent. --marker is kept as an assertion, not as the source of truth.
    seen_markers = sorted({(r.get("marker") or "").strip()
                           for r in load_csv(regions)} - {""})
    if len(seen_markers) > 1:
        print(f"the export mixes markers {seen_markers} - it must carry exactly "
              f"one, since the two are separate acquisitions with their own "
              f"sections. Re-export from 04l with a single --marker.")
        return 1
    marker = seen_markers[0] if seen_markers else (args.marker or "AF568")
    if args.marker and args.marker != marker:
        print(f"--marker {args.marker} but the export says {marker}. Refusing "
              f"rather than writing one marker's boxes to the other's file.")
        return 1
    if marker not in MARKERS:
        print(f"the export's marker is {marker!r}, not one of {MARKERS}")
        return 1
    use_marker(marker)
    print(f"marker: {marker}")

    plates = args.plates or regions.replace("roi_regions", "roi_plates")
    print(f"ROIs from {regions}")
    if os.path.exists(plates):
        print(f"exclusions from {plates}")
    else:
        print(f"NO plates CSV beside it ({os.path.basename(plates)}) - the operator's "
              f"exclusions cannot be honoured; pass --plates")

    geom, boxes, skipped = build(regions, limit=args.limit, plates_csv=plates,
                                 require_background=not args.all_sections)
    if not geom:
        print("no section could be placed")
        if skipped:
            for uid, why in skipped[:10]:
                print(f"    {uid}: {why}")
        return 1

    # Written to the SUFFIXED pair always, even when the legacy unsuffixed file
    # is what was read: the point is that a second marker cannot overwrite the
    # first, and that only holds once both live under their own names.
    for path, rows in ((geom_csv(marker), geom), (box_csv(marker), boxes)):
        IO.atomic_write_csv(path, rows, list(rows[0].keys()))

    # Keep the export these boxes were built from, beside them.
    #
    # The default input is the newest ~/Downloads/roi_regions*.csv, which is
    # convenient and is not a record: the operator's download folder is not part
    # of the dataset, the file is one Ctrl+A away from being cleared, and
    # `roi_regions(7).csv` says nothing about which run consumed it. Every
    # number downstream traces back to this one file, so a copy of it lands in
    # out_root with a note saying where it came from and when.
    #
    # Copied, not moved: the browser may still be pointed at the original, and
    # taking it away would be a surprise. Overwritten each run, because the
    # boxes are too - the pair has to stay consistent, and a stale source
    # alongside fresh boxes would be worse than none.
    try:
        used = os.path.join(REFORMAT_DIR, f"roi_regions_used_{marker}.csv")
        if os.path.abspath(regions) != os.path.abspath(used):
            shutil.copyfile(regions, used)
        with open(os.path.join(REFORMAT_DIR, f"roi_regions_used_{marker}.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(
                f"source   : {os.path.abspath(regions)}\n"
                f"modified : {datetime.datetime.fromtimestamp(os.path.getmtime(regions)):%Y-%m-%d %H:%M:%S}\n"
                f"consumed : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
                f"produced : {len(boxes)} boxes over {len(geom)} sections\n")
        print(f"  source     : {regions}")
        print(f"               copied to {used}")
    except OSError as exc:                                   # noqa: BLE001
        # Provenance is worth having and is not worth losing the run over.
        print(f"  (could not archive the source export: {exc})")

    kinds = {}
    for b in boxes:
        kinds[b["roi_kind"]] = kinds.get(b["roi_kind"], 0) + 1
    an = [g["anisotropy"] for g in geom]
    print("=" * 72)
    print(f"{len(geom)} sections -> {geom_csv(marker)}")
    print(f"{len(boxes)} ROIs     -> {box_csv(marker)}")
    print(f"  by kind    : {kinds}")
    print(f"  anisotropy : median {np.median(an):.2f}, range "
          f"{min(an):.2f}-{max(an):.2f}   (1.00 would mean circles stay circles)")
    if boxes:
        wpx = [b["czi_w"] for b in boxes]
        print(f"  ROI boxes  : median {int(np.median(wpx))} px across at "
              f"{BASE_PX_UM} um/px")
    if skipped:
        print(f"  SKIPPED {len(skipped)}:")
        for uid, why in skipped[:10]:
            print(f"    {uid}: {why}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
