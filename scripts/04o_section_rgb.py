"""Stage 4o - colour composites of the curation sections, in the reformatted frame.

The ROI curator was showing `sections_AF568/*.png`: 256x256, greyscale, and
**DAPI**, because that is what `04a_reformat` runs on - the marker channel is a
sparse signal and a poor silhouette, so geometry is decided on the counterstain.
Those images are already cut and tilted; what they are not is the two-colour
picture the section is actually read as, and the marker channel - the thing being
quantified - is not in them at all.

This writes the same sections as RGB composites in the *same* frame:

    blue   DAPI    - the geometry channel, exactly what the curator showed before
    red    AF568   - pERK
    green  AF488   - PCNA

The frame has to be identical or every landmark placed on it is placed on the
wrong picture, so the marker is not reformatted separately. It rides through
`reformat(companion=...)` as a passenger on the geometry channel's own rotation,
flip, crop, pad and resize - the same trick the artifact and censor masks already
use - and the blue channel of the output is the byte-for-byte image the curator
was showing. `--verify` checks exactly that rather than assuming it.

Only the sections in `roi_worklist.csv` are built, so this covers the curation
job rather than all 718 reformatted sections.

Run:  python 04o_section_rgb.py
      python 04o_section_rgb.py --tier core
      python 04o_section_rgb.py --verify
"""

import argparse
import csv
import importlib.util
import os

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_rf", os.path.join(_HERE, "04a_reformat.py"))
RF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RF)

OUT_ROOT = RF.OUT_ROOT
REFORMAT_DIR = RF.REFORMAT_DIR
WORKLIST_CSV = os.path.join(REFORMAT_DIR, "roi_worklist.csv")
FOCUS_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")

# Marker channel -> which RGB plane it lands in. DAPI always takes blue.
MARKER_PLANE = {"AF568": 0, "AF488": 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--marker", choices=("AF488", "AF568"), default="AF568")
    ap.add_argument("--tier", default=None, help="only this worklist tier")
    ap.add_argument("--scale", type=int, default=3, metavar="N",
                    help="render at N x the canonical 256 grid (default 3 = 768). "
                         "Sampling only - the mask, angle and frame are decided at "
                         "WORK_SIZE and do not change, so a landmark still means the "
                         "same thing once divided by N")
    ap.add_argument("--all", action="store_true",
                    help="build every section in this marker's own reformat index "
                         "instead of the pERK worklist. The worklist is keyed on "
                         "pERK and reaches PCNA only through the pairing, so it "
                         "cannot define the PCNA job - this can")
    ap.add_argument("--force", action="store_true",
                    help="rebuild composites that already exist (default is to skip "
                         "them, so topping a set up costs only the missing ones)")
    ap.add_argument("--verify", action="store_true",
                    help="check the blue plane still equals the existing greyscale section")
    args = ap.parse_args()

    paths = RF.marker_paths(args.marker)
    overrides, _ = RF.load_overrides(paths)
    src_dir = paths["sections"]
    out_dir = src_dir + "_rgb"
    os.makedirs(out_dir, exist_ok=True)

    with open(FOCUS_CSV, newline="", encoding="utf-8") as fh:
        secs = {r["scene_uid"]: r for r in csv.DictReader(fh)
                if r["marker_channel"] == args.marker}

    if args.all:
        with open(paths["index"], newline="", encoding="utf-8") as fh:
            uids = [r["id"] for r in csv.DictReader(fh) if r["kind"] == "section"]
    else:
        with open(WORKLIST_CSV, newline="", encoding="utf-8") as fh:
            want = [r for r in csv.DictReader(fh) if not args.tier or r["tier"] == args.tier]
        # The worklist is keyed on pERK. Building the PCNA side from it means
        # following the pairing to the partner scene, which the 30 unpaired
        # sections do not have - hence --all, which reads the marker's own index.
        uid_col = "pcna_scene_uid" if args.marker == "AF488" else "scene_uid"
        uids = [u for u in ((w.get(uid_col) or "").strip() for w in want) if u]

    plane = MARKER_PLANE[args.marker]
    made = skipped = mismatched = existing = 0
    missing = []

    for uid in uids:
        out_path = os.path.join(out_dir, uid + ".png")
        if not args.verify and not args.force and os.path.exists(out_path):
            existing += 1
            continue
        r = secs.get(uid)
        if r is None:
            missing.append((uid, "not in focus.csv"))
            continue
        base = os.path.join(OUT_ROOT, "overviews", r["animal"], args.marker, uid)
        dapi, mark = base + "_DAPI.png", base + "_MARK.png"
        if not os.path.exists(dapi) or not os.path.exists(mark):
            missing.append((uid, "overview PNG missing"))
            continue

        extra, flip = overrides.get(uid, (0.0, False))
        art = RF.load_artifact(uid, (RF.WORK_SIZE, RF.WORK_SIZE))
        cen = RF.load_censor(uid, (RF.WORK_SIZE, RF.WORK_SIZE))
        out = RF.reformat(dapi, light_background=False, extra_angle=extra, flip=flip,
                          artifact=art, censor=cen, companion=mark,
                          render_scale=1 if args.verify else args.scale)
        if out is None:
            missing.append((uid, "no tissue mask could be formed"))
            continue
        img, _mask, _angle, _a, _c, comp = out

        # The blue plane must be the image the curator was already showing, or a
        # landmark placed on this picture does not mean what the exports say.
        if args.verify:
            prev = os.path.join(src_dir, uid + ".png")
            if os.path.exists(prev):
                if np.array_equal(img, np.array(Image.open(prev))):
                    skipped += 1
                else:
                    mismatched += 1
                    print(f"  MISMATCH {uid}")
                continue

        rgb = np.zeros(img.shape + (3,), np.uint8)
        rgb[..., plane] = comp
        rgb[..., 2] = img
        Image.fromarray(rgb).save(out_path)
        made += 1

    if args.verify:
        print(f"verified {skipped} sections, {mismatched} mismatched")
    else:
        print(f"wrote {made} composites to {out_dir}")
        if existing:
            print(f"  {existing} already there, left alone (--force rebuilds them)")
    if missing:
        print(f"  {len(missing)} not built:")
        for uid, why in missing[:10]:
            print(f"    {uid}  {why}")


if __name__ == "__main__":
    main()
