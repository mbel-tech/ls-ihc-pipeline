"""04e registers a Wullimann plate's MICROGRAPH half, and carries the regions across.

Built from a synthetic brain with a known transform: a textured "micrograph" on
the right half of a plate, a section that is that micrograph (and its mirror, so
the section is a whole brain) warped by a known affine, and a polygon drawn on
the LEFT half of the plate. The polygon's mirror lies on the micrograph, so its
refined position in the section has a ground truth.

Checks that the crop and its matrix put the micrograph where the landmarks say,
that the coverage mask is the micrograph's footprint and nothing else, and that
the refined point lands near the truth. Skipped when itk-elastix is not installed.

Run:  python tests/test_wullimann_registration.py
"""

import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

fails = 0


def chk(label, got, want=True):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(60) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


try:
    import itk  # noqa: F401
    HAVE_ITK = True
except ImportError:
    HAVE_ITK = False

tmp = tempfile.mkdtemp()
try:
    sys.path.insert(0, HERE)
    from _fixture import write_study
    cfg = write_study(tmp, atlas_source="wullimann1996")
    out_root = json.load(open(cfg))["out_root"]
    os.environ["LS_CONFIG"] = cfg

    spec = importlib.util.spec_from_file_location("r04e", os.path.join(SCRIPTS, "04e_register_elastix.py"))
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)

    # ---- the pure pieces -------------------------------------------------------
    plate = {"px_w": "600", "midline_frac": "0.5"}
    chk("micrograph starts at the midline", R.micrograph_x0(plate), 300)
    chk("--whole-plate keeps the whole image", R.micrograph_x0(plate, whole_plate=True), 0)
    chk("no midline means the whole plate", R.micrograph_x0({"px_w": "600"}), 0)
    A = np.array([[0.4, 0.05, 20.0], [-0.03, 0.4, 10.0], [0, 0, 1.0]])
    Ac = R.crop_affine(A, 300)
    u = Ac @ np.array([10.0, 50.0, 1.0])
    f = A @ np.array([310.0, 50.0, 1.0])
    chk("crop pixel maps where the full-plate pixel does", np.allclose(u, f), True)
    m = R.coverage_mask((100, 100), np.array([[1.0, 0, 50], [0, 1.0, 20], [0, 0, 1]]), (200, 200))
    chk("mask is the crop's footprint", (int(m[20:120, 50:150].sum()), int(m.sum())), (10000, 10000))

    # the crop warped with the crop's matrix is the full plate warped, restricted to the
    # crop's footprint - the property that makes the shift correct rather than merely
    # plausible. A missing shift would put the micrograph x0 * scale (~90 px here) away.
    rng0 = np.random.RandomState(1)
    full_plate = rng0.rand(120, 600).astype(np.float32)
    A2 = np.array([[0.3, 0.02, 15.0], [-0.02, 0.3, 8.0], [0, 0, 1.0]])
    whole = R.warp_plate_into_section(full_plate, A2, (256, 256))
    crop = R.warp_plate_into_section(full_plate[:, 300:], R.crop_affine(A2, 300), (256, 256))
    cm = R.coverage_mask((120, 300), R.crop_affine(A2, 300), (256, 256)).astype(bool)
    chk("cropped warp equals the whole-plate warp inside the footprint",
        bool(np.allclose(whole[cm][::7], crop[cm][::7], atol=0.05)), True)
    chk("and the footprint is the right half of the plate", bool(cm.any()), True)

    # ---- end to end ------------------------------------------------------------
    if not HAVE_ITK:
        print("SKIP end-to-end: itk-elastix not installed")
    else:
        from scipy import ndimage
        rng = np.random.RandomState(3)
        W, H = 600, 400
        tex = ndimage.gaussian_filter(rng.rand(H, W // 2), 6)
        tex = (255 * (tex - tex.min()) / (tex.max() - tex.min())).astype(np.float32)
        right = tex
        full = np.hstack([right[:, ::-1], right])            # a whole brain, mirror-symmetric
        # the plate on disk: line drawing on the left, the micrograph on the right
        # (the registration inverts it; only the right half is read)
        plate_img = full.copy()
        plate_img[:, :W // 2] = 255
        a_true = np.array([[0.30, 0.03, 20.0], [-0.02, 0.30, 12.0], [0, 0, 1.0]])   # plate -> section
        Ainv = np.linalg.inv(a_true)
        mat = np.array([[Ainv[1, 1], Ainv[1, 0]], [Ainv[0, 1], Ainv[0, 0]]])
        off = np.array([Ainv[1, 2], Ainv[0, 2]])
        # the section is dark tissue on light, the opposite of the inverted plate,
        # so mutual information (not correlation) has to do the work
        section = ndimage.affine_transform(255.0 - full, mat, offset=off, output_shape=(256, 256), order=1)

        pdir = os.path.join(out_root, "atlas", "plates_wullimann")
        os.makedirs(pdir)
        Image.fromarray(plate_img.astype(np.uint8)).save(os.path.join(pdir, "wplate_071.png"))
        with open(os.path.join(pdir, "plates.csv"), "w", newline="") as fh:
            fh.write("plate_id,page,image_file,px_w,px_h,n_seeds,regions,section_level,midline_frac\n"
                     "wplate_071,6,wplate_071.png,600,400,0,Dm,71,0.5\n")
        # a reviewed polygon on the LEFT half, a square around (150, 200)
        sq = [(120, 170), (180, 170), (180, 230), (120, 230)]
        with open(os.path.join(pdir, "polygons.csv"), "w", newline="") as fh:
            fh.write("plate_id,roi_number,region,status,label_conf,vertices\n")
            fh.write("wplate_071,1,Dm,reviewed,0.9," + ";".join("%.5f %.5f" % (x / W, y / H) for x, y in sq) + "\n")
        sdir = os.path.join(out_root, "reformatted", "sections")
        os.makedirs(sdir)
        Image.fromarray(np.clip(section, 0, 255).astype(np.uint8)).save(os.path.join(sdir, "S1.png"))
        lm = [(380, 80), (520, 90), (450, 200), (390, 320), (530, 310)]       # on the micrograph
        noisy = []
        with open(os.path.join(out_root, "reformatted", "roi_landmarks.csv"), "w", newline="") as fh:
            fh.write("scene_uid,animal,plate_set,plate_id,sec_x,sec_y,plate_x,plate_y\n")
            for x, y in lm:
                v = a_true @ np.array([x, y, 1.0])
                # a clicked landmark is a few pixels off; the image metric has to pull it back
                sx, sy = v[0] + rng.randn() * 1.5, v[1] + rng.randn() * 1.5
                noisy.append((sx, sy, x, y))
                fh.write("S1,A1,plates_wullimann,wplate_071,%.2f,%.2f,%d,%d\n" % (sx, sy, x, y))
        mir = np.array([W - 150.0, 200.0, 1.0])
        base = R.landmark_affine(noisy) @ mir
        base_err = float(np.hypot(*(base[:2] - (a_true @ mir)[:2])))

        extra = os.environ.get("REG_ARGS", "").split()
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "04e_register_elastix.py"),
                            "--from-landmarks"] + extra, capture_output=True, text=True,
                           env={**os.environ, "LS_CONFIG": cfg})
        chk("04e ran", r.returncode, 0)
        if r.returncode:
            print(r.stdout[-600:], r.stderr[-600:])
        out_csv = os.path.join(out_root, "registered", "roi_regions_refined.csv")
        if os.path.exists(out_csv):
            row = list(csv.DictReader(open(out_csv)))[0]
            mirrored = np.array([W - 150.0, 200.0, 1.0])           # the polygon, reflected about x = 300
            truth = a_true @ mirrored
            err = float(np.hypot(float(row["sec_x"]) - truth[0], float(row["sec_y"]) - truth[1]))
            chk("one region carried across", row["region"], "Dm")
            # On this exact-affine ground truth the landmark fit is already almost perfect, so
            # elastix's elastic stage can only move the point away from it; real sections are
            # not exactly affine. What this pins is the wiring (a missing shift is ~90 px out),
            # not that the refinement helps - see the numbers printed below.
            chk("it lands within 8 px of the truth (section is 256 px)", err < 8.0, True)
            print("     landmarks alone %.2f px, after elastix %.2f px" % (base_err, err))
        else:
            chk("output written", False)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n%s" % ("all passed" if not fails else "%d FAILED" % fails))
raise SystemExit(1 if fails else 0)
