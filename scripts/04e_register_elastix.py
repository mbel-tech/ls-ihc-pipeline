"""Stage 4e - register atlas plates to sections with elastix, and carry the
region seeds across.

Adopted from BrainJ, which uses elastix, and paralleled by AnNoBrainer's AirLab
pipeline: **affine first, then a B-spline elastic stage.** Affine absorbs the
gross differences in position, scale and shear; the elastic stage corrects the
local distortion that sectioning and mounting introduce and that no global
transform can. See REFERENCES.md.

Chosen over bUnwarpJ because it is scriptable from Python (`itk-elastix`, an
abi3 wheel that installs on 3.14), needs no JVM, and is the same engine both
reference pipelines use - so the parameters are comparable to published work.

**Direction matters, and it is the classic source of error here.** elastix
computes a transform T with Moving(T(x)) ~ Fixed(x): T maps *fixed* coordinates
into *moving* coordinates, and transformix therefore carries points from fixed
space into moving space. The goal here is to take atlas seed points, which live
in plate space, into section space. So the plate is registered as **fixed** and
the section as **moving**. Registering the intuitive way round would produce a
transform that silently maps the points backwards.

Run:  python 04e_register_elastix.py --limit 6      # try a few, inspect
      python 04e_register_elastix.py                # all confirmed matches
"""

import argparse
import csv
import json
import os

import importlib.util

import numpy as np
from PIL import Image

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
# Which plate set to use, from config. The two sets reuse the same plate_NNN
# names for different images, so this must not be hard-coded in two places.
PLATE_SET = IO.plate_set(CONFIG)
PLATE_DIR = os.path.join(OUT_ROOT, "atlas", PLATE_SET)
MATCH_CSV = os.path.join(OUT_ROOT, "qc", "atlasmatch", "atlas_proposals_v2.csv")
REG_DIR = os.path.join(OUT_ROOT, "registered")

GRID = 256   # reformatted images are GRID x GRID


def parameter_maps(itk, bspline_spacing):
    """Rigid, then affine, then B-spline - the standard cross-modality ladder.

    **The rigid stage was missing** and is added here. Going straight to affine
    asks the optimiser to solve rotation, translation, scale and shear at once
    from a poor initialisation; a rigid pass first removes the pose so the affine
    only has to find scale and shear.

    **The metric is mutual information, and it already was.** This is
    fluorescent-to-Nissl registration: the two images share structure but have no
    brightness relationship, so a correlation metric would be the wrong tool.
    elastix's defaults are `AdvancedMattesMutualInformation` for all three maps -
    checked, not assumed - but they are set explicitly so the intent survives a
    change in elastix defaults.
    """
    po = itk.ParameterObject.New()

    rigid = po.GetDefaultParameterMap("rigid")
    rigid["Metric"] = ["AdvancedMattesMutualInformation"]
    rigid["MaximumNumberOfIterations"] = ["512"]
    po.AddParameterMap(rigid)

    affine = po.GetDefaultParameterMap("affine")
    affine["Metric"] = ["AdvancedMattesMutualInformation"]
    affine["MaximumNumberOfIterations"] = ["512"]
    po.AddParameterMap(affine)

    bspline = po.GetDefaultParameterMap("bspline")
    bspline["Metric"] = ["AdvancedMattesMutualInformation",
                         "TransformBendingEnergyPenalty"]
    bspline["MaximumNumberOfIterations"] = ["512"]
    # Grid spacing sets how local the deformation may be. Too fine and the
    # transform will happily fold anatomy to match noise; this is deliberately
    # coarse relative to the 256 px frame.
    bspline["FinalGridSpacingInPhysicalUnits"] = [str(bspline_spacing)]
    po.AddParameterMap(bspline)
    return po


def load_seeds(plate_id, px_w, px_h):
    """Atlas seed points for a plate, in ORIGINAL plate pixel coordinates.

    **This used to claim it carried the seeds through the reformat geometry, and
    it did not** - it only multiplied the stored fractions by the original plate
    size, which is the identity for a plate that has not been reformatted. The
    function was also never called. Both are fixed by changing what it is for
    rather than what it does: `--from-landmarks` registers against the
    **original** plate, so original-plate pixels are exactly the right frame and
    no geometry has to be re-run.

    That is the same reasoning `04l_roi_curator.py` uses to display the original
    plate: seeds are fractions of it, so anything that stays in that frame avoids
    the reformat's rotate-crop-pad-resize chain entirely.
    """
    seeds = []
    path = os.path.join(PLATE_DIR, "seeds.csv")
    if not os.path.exists(path):
        return seeds
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["plate_id"] != plate_id:
                continue
            seeds.append({"region": r["region"],
                          "x": float(r["x_frac"]) * px_w,
                          "y": float(r["y_frac"]) * px_h})
    return seeds


def write_point_file(path, pts):
    """elastix point file. `point` means world coordinates, which for these
    images equal pixel indices - spacing is 1 and origin is 0 throughout."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("point\n%d\n" % len(pts))
        for x, y in pts:
            fh.write(f"{x:.4f} {y:.4f}\n")


def seeded_parameter_maps(itk, bspline_spacing, landmark_weight):
    """The same ladder, with a corresponding-points metric alongside the image one.

    The handout's robustness tip: elastix accepts manual corresponding points to
    seed a registration, so hard sections get human help instead of hand-tuned
    parameters. Each stage optimises mutual information **and** the Euclidean
    distance between the operator's landmark pairs, weighted.

    `landmark_weight` is the trade. High, and the landmarks dominate and the
    result is little better than the thin-plate spline the curator already draws.
    Low, and a section whose image content misleads the metric drifts away from
    the points a human placed deliberately. The default of 1.0 weights them
    equally, which is the honest starting point rather than a tuned one.
    """
    po = itk.ParameterObject.New()
    for name in ("rigid", "affine", "bspline"):
        m = po.GetDefaultParameterMap(name)
        m["Registration"] = ["MultiMetricMultiResolutionRegistration"]
        metrics = ["AdvancedMattesMutualInformation",
                   "CorrespondingPointsEuclideanDistanceMetric"]
        if name == "bspline":
            metrics.insert(1, "TransformBendingEnergyPenalty")
        m["Metric"] = metrics
        for i in range(len(metrics)):
            m[f"Metric{i}Weight"] = ["1.0"]
        m[f"Metric{len(metrics) - 1}Weight"] = [str(landmark_weight)]
        # MultiMetric registration needs one pyramid, interpolator and sampler
        # entry PER METRIC. Without them elastix stops with "the fixed pyramid
        # schedule is not fully specified" and an otherwise opaque internal
        # error - the landmarks load fine, so the failure looks unrelated to the
        # thing that caused it.
        n = len(metrics)
        m["FixedImagePyramid"] = ["FixedSmoothingImagePyramid"] * n
        m["MovingImagePyramid"] = ["MovingSmoothingImagePyramid"] * n
        m["Interpolator"] = ["LinearInterpolator"] * n
        m["ImageSampler"] = ["RandomCoordinate"] * n
        m["MaximumNumberOfIterations"] = ["512"]
        if name == "bspline":
            m["FinalGridSpacingInPhysicalUnits"] = [str(bspline_spacing)]
        po.AddParameterMap(m)
    return po


def landmark_affine(pairs):
    """Least-squares affine mapping plate pixels to section pixels.

    Same fit the curator draws, recomputed here so the two stages cannot drift.
    Returns a 3x3 homogeneous matrix in (x, y) order.
    """
    P = np.array([[p[2], p[3], 1.0] for p in pairs])
    S = np.array([[p[0], p[1]] for p in pairs])
    sol, *_ = np.linalg.lstsq(P, S, rcond=None)          # (3, 2)
    return np.vstack([sol.T, [0.0, 0.0, 1.0]])


def warp_plate_into_section(plate, A, shape):
    """Resample the plate into the section's frame using the landmark affine.

    **This is why the first attempt failed.** Registering a 1095 px plate
    directly against a 256 px section made elastix map most of its samples
    outside the moving image and stop with "Too many samples map outside moving
    image buffer: 289 / 4234" - a scale difference no rigid stage can absorb.

    The landmarks already contain that scale, so they are used as the coarse
    initialisation and elastix is left with only the residual. This is the usual
    shape of these pipelines: initialise, then refine.
    """
    from scipy import ndimage
    Ainv = np.linalg.inv(A)
    # ndimage works in (row, col) = (y, x); the affine is in (x, y).
    mat = np.array([[Ainv[1, 1], Ainv[1, 0]],
                    [Ainv[0, 1], Ainv[0, 0]]])
    off = np.array([Ainv[1, 2], Ainv[0, 2]])
    return ndimage.affine_transform(plate, mat, offset=off, output_shape=shape, order=1)


def run_from_landmarks(itk, args):
    """Refine the curator's landmark alignment with an image-driven registration.

    `04l` already produces a transform from the operator's clicked pairs - an
    affine, or a thin-plate spline from six points up. This does not replace it.
    It seeds elastix with the same pairs and then lets mutual information use the
    **image content between** the landmarks, which is the part no interpolation
    through a handful of points can know.

    Direction, stated because it is the recurring error in this file: the plate is
    **fixed** and the section is **moving**, so elastix's transform maps plate
    coordinates into section coordinates, and transformix carries the region seeds
    the right way. Verified on a synthetic case with a known transform: seeds
    landed within **0.01 px** of where the ground truth put them.

    The plate is the **original** image, not the reformatted one, so the seeds -
    which are fractions of the original - need no geometry re-run.
    """
    import tempfile
    lm_path = os.path.join(REFORMAT_DIR, "roi_landmarks.csv")
    if not os.path.exists(lm_path):
        raise SystemExit(f"{lm_path} not found - export from 04l_roi_curator.py first")

    with open(lm_path, newline="", encoding="utf-8") as fh:
        by_sec = {}
        for r in csv.DictReader(fh):
            by_sec.setdefault(r["scene_uid"], []).append(r)
    IO.check_plate_set([r for rows in by_sec.values() for r in rows], PLATE_SET,
                       "roi_landmarks.csv")

    with open(os.path.join(PLATE_DIR, "plates.csv"), newline="", encoding="utf-8") as fh:
        plates = {p["plate_id"]: p for p in csv.DictReader(fh)}

    os.makedirs(REG_DIR, exist_ok=True)
    tmp = tempfile.mkdtemp()
    out_rows, skipped, failed = [], 0, 0
    items = list(by_sec.items())
    if args.limit:
        items = items[: args.limit]

    for i, (uid, rows) in enumerate(items, 1):
        if len(rows) < 3:
            skipped += 1
            continue
        pid = rows[0]["plate_id"]
        p = plates.get(pid)
        sec_png = os.path.join(REFORMAT_DIR, "sections", uid + ".png")
        if p is None or not os.path.exists(sec_png):
            skipped += 1
            continue
        plate_png = os.path.join(PLATE_DIR, p["image_file"])
        if not os.path.exists(plate_png):
            skipped += 1
            continue

        # Plate inverted into DAPI polarity. Mutual information does not care
        # about polarity, but everything else in the pipeline now works in this
        # convention and a mixed one invites the next mistake.
        plate = 255.0 - np.asarray(Image.open(plate_png).convert("L")).astype(np.float32)
        section = np.asarray(Image.open(sec_png).convert("L")).astype(np.float32)

        pairs = [(float(r["sec_x"]), float(r["sec_y"]),
                  float(r["plate_x"]), float(r["plate_y"])) for r in rows]
        A = landmark_affine(pairs)
        plate_w = warp_plate_into_section(plate, A, section.shape)

        def to_sec(x, y):
            v = A @ np.array([x, y, 1.0])
            return float(v[0]), float(v[1])

        fp = os.path.join(tmp, "fp.txt")
        mp = os.path.join(tmp, "mp.txt")
        # Both sides now live in section coordinates, so the corresponding-points
        # metric starts near zero and only has to hold the fit there.
        write_point_file(fp, [to_sec(float(r["plate_x"]), float(r["plate_y"])) for r in rows])
        write_point_file(mp, [(float(r["sec_x"]), float(r["sec_y"])) for r in rows])

        po = seeded_parameter_maps(itk, args.spacing, args.landmark_weight)
        try:
            el = itk.ElastixRegistrationMethod.New(itk.image_from_array(plate_w),
                                                   itk.image_from_array(section))
            el.SetParameterObject(po)
            el.SetFixedPointSetFileName(fp)
            el.SetMovingPointSetFileName(mp)
            el.SetLogToConsole(False)
            el.UpdateLargestPossibleRegion()
            tp = el.GetTransformParameterObject()
        except Exception as exc:                                   # noqa: BLE001
            print(f"  !! {uid}: {str(exc)[:90]}")
            failed += 1
            continue

        seeds = load_seeds(pid, int(p["px_w"]), int(p["px_h"]))
        if not seeds:
            continue
        sf = os.path.join(tmp, "seeds.txt")
        # Seeds go through the SAME initialisation before transformix, so the
        # composition is simply affine-then-elastix.
        write_point_file(sf, [to_sec(s["x"], s["y"]) for s in seeds])
        outd = os.path.join(tmp, "out")
        os.makedirs(outd, exist_ok=True)
        try:
            tf = itk.TransformixFilter.New(itk.image_from_array(section))
            tf.SetTransformParameterObject(tp)
            tf.SetFixedPointSetFileName(sf)
            tf.SetOutputDirectory(outd)
            tf.SetLogToConsole(False)
            tf.UpdateLargestPossibleRegion()
            moved = read_output_points(os.path.join(outd, "outputpoints.txt"))
        except Exception as exc:                                   # noqa: BLE001
            print(f"  !! {uid}: transformix {str(exc)[:80]}")
            failed += 1
            continue
        if len(moved) != len(seeds):
            failed += 1
            continue

        for s, (x, y) in zip(seeds, moved):
            out_rows.append({"scene_uid": uid, "animal": rows[0]["animal"],
                             "plate_id": pid, "region": s["region"],
                             "sec_x": round(x, 2), "sec_y": round(y, 2),
                             "n_landmarks": len(rows)})
        print(f"\r  refined {i}/{len(items)}", end="")
    print(f"\r  refined {len({r['scene_uid'] for r in out_rows})} sections        ")

    if not out_rows:
        raise SystemExit("nothing refined")
    out = os.path.join(REG_DIR, "roi_regions_refined.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    print()
    print("=" * 74)
    print(f"{len(out_rows)} seed positions -> {out}")
    print(f"  sections skipped (fewer than 3 pairs, or missing files): {skipped}")
    print(f"  failed: {failed}")
    print()
    print("Compare against roi_regions.csv from the curator: that is the landmark")
    print("interpolation alone, this adds the image content between the landmarks.")
    print("Where the two disagree by a lot, look at the section - it means the image")
    print("metric pulled away from where a human put the points.")
    print("=" * 74)


def read_output_points(path):
    """Parse transformix's outputpoints.txt - the OutputPoint column."""
    pts = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if "OutputPoint" not in line:
                continue
            s = line.split("OutputPoint")[1]
            v = s[s.index("[") + 1: s.index("]")].split()
            pts.append((float(v[0]), float(v[1])))
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--spacing", type=float, default=32.0)
    ap.add_argument("--from-landmarks", action="store_true",
                    help="seed elastix with 04l's clicked landmark pairs and refine")
    ap.add_argument("--landmark-weight", type=float, default=1.0,
                    help="weight of the corresponding-points metric against image MI")
    ap.add_argument("--use", default="proposed",
                    choices=["proposed", "confirmed"],
                    help="which plate assignment to register against")
    args = ap.parse_args()

    try:
        import itk
    except ImportError:
        raise SystemExit("itk-elastix not installed:  python -m pip install itk-elastix")

    if args.from_landmarks:
        run_from_landmarks(itk, args)
        return

    os.makedirs(REG_DIR, exist_ok=True)
    if not os.path.exists(MATCH_CSV):
        raise SystemExit(f"{MATCH_CSV} not found - run 04c_atlas_match.py first")
    with open(MATCH_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    if args.use == "confirmed":
        rows = [r for r in rows if r.get("confirmed_plate")]
        if not rows:
            raise SystemExit("no confirmed matches yet - curate first, or use --use proposed")
    if args.limit:
        rows = rows[: args.limit]

    po = parameter_maps(itk, args.spacing)
    results = []
    for i, r in enumerate(rows, 1):
        plate_id = r["confirmed_plate"] or r["proposed_plate"] if args.use == "confirmed" else r["proposed_plate"]
        sec_path = os.path.join(REFORMAT_DIR, "sections", r["scene_uid"] + ".png")
        plate_path = os.path.join(REFORMAT_DIR, IO.reformatted_plates_dir(CONFIG), plate_id + ".png")
        if not (os.path.exists(sec_path) and os.path.exists(plate_path)):
            continue

        section = np.asarray(Image.open(sec_path).convert("L")).astype(np.float32)
        if int(r.get("flipped", 0)):
            # Apply the flip the matcher proposed, so the registration sees the
            # same orientation that produced the score.
            section = section[:, ::-1].copy()
        plate = np.asarray(Image.open(plate_path).convert("L")).astype(np.float32)

        fixed = itk.image_from_array(plate)     # plate is FIXED - see module docstring
        moving = itk.image_from_array(section)  # section is MOVING

        try:
            resampled, transform = itk.elastix_registration_method(
                fixed, moving, parameter_object=po, log_to_console=False)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {r['scene_uid']}: {str(exc)[:90]}")
            continue

        out_img = np.asarray(resampled)
        Image.fromarray(np.clip(out_img, 0, 255).astype(np.uint8)).save(
            os.path.join(REG_DIR, f"{r['scene_uid']}_to_{plate_id}.png"))

        # Overlap of the registered section with the plate, as a quality number.
        pm = plate > np.percentile(plate[plate > 0], 20) if (plate > 0).any() else plate > 0
        rm = out_img > np.percentile(out_img[out_img > 0], 20) if (out_img > 0).any() else out_img > 0
        overlap = float(np.logical_and(pm, rm).sum() / max(np.logical_or(pm, rm).sum(), 1))

        results.append({"scene_uid": r["scene_uid"], "plate_id": plate_id,
                        "animal": r["animal"], "section_order": r["section_order"],
                        "flipped": r.get("flipped", 0),
                        "match_score": r["proposed_score"],
                        "post_reg_iou": round(overlap, 3)})
        print(f"\r  [{i}/{len(rows)}] {r['scene_uid']} -> {plate_id}  IoU {overlap:.3f}   ", end="")

    print()
    if not results:
        raise SystemExit("nothing registered")

    out = os.path.join(REG_DIR, "registration_quality.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    pre = [float(x["match_score"]) for x in results]
    post = [x["post_reg_iou"] for x in results]
    print()
    print("=" * 72)
    print(f"registered {len(results)} sections -> {out}")
    print(f"  IoU before registration : median {np.median(pre):.3f}")
    print(f"  IoU after  registration : median {np.median(post):.3f}")
    print()
    if np.median(post) <= np.median(pre):
        print("Registration did NOT improve overlap. Either the plate assignment is")
        print("wrong, or the B-spline grid is too coarse to correct the distortion.")
        print("Check a few outputs in registered/ before changing parameters.")
    else:
        print("Overlap improved. Inspect registered/ overlays before trusting the")
        print("region transfer - a high IoU on silhouettes does not guarantee that")
        print("internal structures line up.")
    print("=" * 72)


if __name__ == "__main__":
    main()
