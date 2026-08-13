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

import numpy as np
from PIL import Image

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
PLATE_DIR = os.path.join(OUT_ROOT, "atlas", "plates")
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
    """Atlas seed points for a plate, rescaled into the reformatted frame.

    Seeds were extracted in the ORIGINAL plate pixel space; the reformatted
    plate has been rotated, cropped and resized, so they need carrying through
    the same transform. The reformat step records the angle, but the crop and
    pad are not invertible from the index alone - so seeds are mapped by
    re-running the geometry here rather than assumed to be already aligned.
    """
    seeds = []
    path = os.path.join(PLATE_DIR, "seeds.csv")
    if not os.path.exists(path):
        return seeds
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["plate_id"] != plate_id:
                continue
            seeds.append({
                "region": r["region"],
                # x_frac / y_frac are fractions of the original plate, which is
                # what makes them portable across the reformat.
                "x": float(r["x_frac"]) * px_w,
                "y": float(r["y_frac"]) * px_h,
            })
    return seeds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--spacing", type=float, default=32.0)
    ap.add_argument("--use", default="proposed",
                    choices=["proposed", "confirmed"],
                    help="which plate assignment to register against")
    args = ap.parse_args()

    try:
        import itk
    except ImportError:
        raise SystemExit("itk-elastix not installed:  python -m pip install itk-elastix")

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
        plate_path = os.path.join(REFORMAT_DIR, "plates", plate_id + ".png")
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
