"""Stage 5c - count nuclei in every placed ROI, and measure the marker in them.

Reads the CZI at native 0.65 um/px over the boxes `05a` computed, segments
nuclei on DAPI, and measures the marker channel inside each nuclear mask.

**Segment on DAPI, never on the marker.** Detecting on the marker channel would
define "number of pERK+ cells" by the threshold twice over: once to find the
object and again to call it positive, so the count and the cut could never be
varied independently. Nuclei come from the counterstain; the marker is measured
afterwards; positivity is decided last and can be changed without re-reading a
single CZI. The rest of the pipeline already leans on DAPI for the same reason -
`04a_reformat` decides all its geometry there because "the marker channel is a
sparse signal and a poor silhouette".

**StarDist, not threshold-and-watershed.** Not a general preference: watershed
under-segments where nuclei touch, and Vv, Vd and POA are periventricular. The
error would be worst in exactly those ROIs and mild in Dm and Dl, and a
region-correlated counting bias survives into the results looking like an
anatomical finding.

**What a background disc is for.** It is measured by this stage identically to a
real ROI - same read, same segmentation, same statistics, distinguished only by
`roi_kind`. Two things come out of that: a per-section reference level measured
rather than inferred, and a false-positive rate, since the same detector runs
over tissue the operator called empty. It is NOT a negative control: the primary
antibody is on that tissue too, so it measures non-specific binding plus
autofluorescence, not zero.

Writes `results/roi_nuclei.csv`, one row per nucleus. That is the artefact that
matters - with per-nucleus intensities on disk the positivity cut becomes a
decision about a table rather than a reason to re-read 128 CZI scenes.

Run:  python 05c_detect_rois.py
      python 05c_detect_rois.py --limit 5
      python 05c_detect_rois.py --qc            # also write overlay crops
"""

import argparse
import csv
import importlib.util
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_g5", os.path.join(_HERE, "05a_roi_geometry.py"))
G5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G5)

CONFIG = G5.CONFIG
OUT_ROOT = G5.OUT_ROOT
REFORMAT_DIR = G5.REFORMAT_DIR
RESULTS = os.path.join(OUT_ROOT, "results")
NUCLEI_CSV = os.path.join(RESULTS, "roi_nuclei.csv")
QC_DIR = os.path.join(OUT_ROOT, "qc", "roi_detections")

BASE_PX_UM = CONFIG["pixel_size_um"]
DAPI_C = CONFIG["channels"]["dapi_index"]
MARK_C = CONFIG["channels"]["marker_index"]
NUC_UM = CONFIG["detection"]["nucleus_diameter_um"]

COLUMNS = ["scene_uid", "animal", "marker", "roi_kind", "region", "seed_n",
           "roi_index", "nucleus_id",
           "czi_x", "czi_y", "sec_x", "sec_y",
           "area_um2", "equiv_diam_um",
           "dapi_mean", "marker_mean", "marker_median", "marker_p90",
           "censored", "artifact"]


def load_model():
    """StarDist's pretrained fluorescence model.

    Downloaded on first use, so the first run needs network access.

    `from_pretrained` finishes by creating a SYMLINK next to the extracted
    weights, and Windows refuses that without Developer Mode or elevation -
    WinError 1314, "a required privilege is not held by the client". The
    download and extraction have already succeeded by then, so the fallback
    below opens the extracted folder directly and needs no privilege at all.
    Same weights, same thresholds; only the convenience link is missing.
    """
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    from stardist.models import StarDist2D
    print("loading StarDist 2D_versatile_fluo (downloads on first use)...")
    try:
        return StarDist2D.from_pretrained("2D_versatile_fluo")
    except OSError as exc:
        base = os.path.expanduser("~/.keras/models/StarDist2D/2D_versatile_fluo")
        extracted = os.path.join(base, "2D_versatile_fluo_extracted")
        if not os.path.exists(os.path.join(extracted, "weights_best.h5")):
            raise
        print(f"  ({exc.__class__.__name__}: {exc.strerror or exc}) "
              f"- loading the extracted weights directly")
        return StarDist2D(None, name="2D_versatile_fluo_extracted", basedir=base)


def mask_at(uid, kind):
    """The 256-frame artifact or censor mask, or None."""
    p = os.path.join(REFORMAT_DIR, "sections_AF568", f"{uid}_{kind}.npy")
    if not os.path.exists(p):
        p = os.path.join(REFORMAT_DIR, "sections", f"{uid}_{kind}.npy")
    return np.load(p) if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only the first N sections")
    ap.add_argument("--qc", action="store_true", help="write overlay crops")
    ap.add_argument("--force", action="store_true", help="redo finished sections")
    args = ap.parse_args()

    if not os.path.exists(G5.BOX_CSV):
        print(f"no {G5.BOX_CSV} - run 05a_roi_geometry.py first")
        return 1
    boxes = G5.load_csv(G5.BOX_CSV)
    geom = {g["scene_uid"]: g for g in G5.load_csv(G5.GEOM_CSV)}
    os.makedirs(RESULTS, exist_ok=True)
    if args.qc:
        os.makedirs(QC_DIR, exist_ok=True)

    # Resume by section, because a section is the unit that costs something:
    # one CZI open and a model call per ROI in it.
    done = set()
    if os.path.exists(NUCLEI_CSV) and not args.force:
        done = {r["scene_uid"] for r in G5.load_csv(NUCLEI_CSV)}
        print(f"resuming: {len(done)} sections already measured")

    by_sec = {}
    for b in boxes:
        by_sec.setdefault(b["scene_uid"], []).append(b)
    todo = [u for u in sorted(by_sec) if u not in done]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("nothing to do")
        return 0
    print(f"{len(todo)} sections, {sum(len(by_sec[u]) for u in todo)} ROIs")

    model = load_model()
    from csbdeep.utils import normalize
    from pylibCZIrw import czi as pyczi
    from skimage.measure import regionprops

    new = not os.path.exists(NUCLEI_CSV) or args.force
    fh = open(NUCLEI_CSV, "w" if new else "a", newline="", encoding="utf-8")
    w = csv.writer(fh)
    if new:
        w.writerow(COLUMNS)

    px_area = BASE_PX_UM ** 2
    total_nuc = 0
    for n, uid in enumerate(todo, 1):
        g = geom[uid]
        M = np.array([[float(g["m00"]), float(g["m01"]), float(g["m02"])],
                      [float(g["m10"]), float(g["m11"]), float(g["m12"])]])
        Minv = G5.invert_affine(M)              # CZI px -> 256 grid
        art = mask_at(uid, "artifact")
        cen = mask_at(uid, "censor")
        path = os.path.join(CONFIG["source_dir"], g["czi_file"])
        rows = []
        with pyczi.open_czi(path) as doc:
            for bi, b in enumerate(by_sec[uid], 1):
                x0, y0 = int(b["czi_x0"]), int(b["czi_y0"])
                bw, bh = int(b["czi_w"]), int(b["czi_h"])
                if bw < 8 or bh < 8:
                    continue
                roi = (x0, y0, bw, bh)
                dapi = np.squeeze(doc.read(roi=roi, plane={"C": DAPI_C})).astype(np.float32)
                mark = np.squeeze(doc.read(roi=roi, plane={"C": MARK_C})).astype(np.float32)
                if dapi.ndim != 2 or dapi.shape != mark.shape:
                    continue
                # ALWAYS TILE. Untiled, StarDist takes 121 s on a 1.22 Mpx ROI;
                # at n_tiles=(2,2) it takes 4.1 s and returns the identical 1177
                # nuclei. The cost is wildly non-linear in image size - a
                # quarter of the pixels ran in 0.7 s - so this is 30x on a
                # typical ROI and the difference between a 75-minute run and a
                # 62-hour one. Nothing about the answer changes.
                #
                # Tiles of roughly 300k px, never fewer than 2x2. More tiles
                # than that is slower again (5.1 s at 4x4, 11.1 s at 8x8): the
                # per-tile overhead takes over.
                nt = max(2, int(np.ceil(np.sqrt(dapi.size / 300_000))))
                labels, _ = model.predict_instances(
                    normalize(dapi, 1, 99.8), n_tiles=(nt, nt),
                    verbose=False, show_tile_progress=False)
                if labels.max() == 0:
                    continue

                # Which nuclei are actually IN the ROI. The disc is a circle on
                # the 256 grid and an ellipse here, so membership is decided by
                # mapping the centroid back rather than by any radius in CZI px.
                sx, sy, sr = float(b["sec_x"]), float(b["sec_y"]), float(b["sec_r"])
                props = regionprops(labels, intensity_image=mark)
                dprops = {p.label: p for p in regionprops(labels, intensity_image=dapi)}
                for p in props:
                    cy, cx = p.centroid
                    gx, gy = G5.apply_affine(Minv, x0 + cx, y0 + cy)
                    if (gx - sx) ** 2 + (gy - sy) ** 2 > sr * sr:
                        continue
                    vals = p.image_intensity[p.image]
                    ix, iy = int(round(gx)), int(round(gy))
                    inb = lambda m: (m is not None and 0 <= iy < m.shape[0]
                                     and 0 <= ix < m.shape[1] and bool(m[iy, ix]))
                    rows.append([
                        uid, b["animal"], b["marker"], b["roi_kind"], b["region"],
                        b["seed_n"], bi, p.label,
                        round(x0 + cx, 1), round(y0 + cy, 1),
                        round(float(gx), 2), round(float(gy), 2),
                        round(p.area * px_area, 2),
                        round(2 * np.sqrt(p.area * px_area / np.pi), 2),
                        round(float(dprops[p.label].image_intensity[
                            dprops[p.label].image].mean()), 1),
                        round(float(vals.mean()), 1),
                        round(float(np.median(vals)), 1),
                        round(float(np.percentile(vals, 90)), 1),
                        int(inb(cen)), int(inb(art))])
        w.writerows(rows)
        fh.flush()
        total_nuc += len(rows)
        print(f"\r  {n}/{len(todo)}  {uid}  {len(rows)} nuclei  "
              f"({total_nuc} total)          ", end="")
    fh.close()
    print(f"\n{total_nuc} nuclei -> {NUCLEI_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
