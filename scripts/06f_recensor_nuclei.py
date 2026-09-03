"""Stage 6f - recompute the per-nucleus `censored` flag from the RAW clipping mask.

`04j_censor_clipped.py` used to build its censor mask by thresholding the
exported 8-bit `_MARK.png` at 255. That image has already been through
`apply_tile_field()`, and dividing by a gain above 1 lifts a pixel off the 16-bit
ceiling so it stops reading as clipped - while its value is exactly as lost as
before. `tilefield_c1` exceeds 1.0 over 54% of its area, so the old mask held
about 46% of the clipped pixels. `05c_detect_rois.py` sampled that mask into the
`censored` column of `roi_nuclei.csv`, and `06a_roi_dataset.py` decides
positive-but-unusable from it, so the undercount reached the results.

**Why this does not re-run StarDist.** Segmentation is unaffected: it runs on
DAPI, which does not clip (raw DAPI clipping measured at a median of 0.00004 and
a corpus maximum of 0.0007). Only the flag is wrong, and `roi_nuclei.csv` already
stores each nucleus at `czi_x, czi_y` in CZI stage pixels. Hours become minutes.

**The sampling frame changed, and it changed for the better.** `05c` sampled a
256x256 mask that `04a_reformat.py` had rotated and cropped out of the overview -
roughly 31 um per cell against a 7 um nucleus. This samples the overview frame
itself at 5.20 um/px, about 6x finer, with no rotation in between: the nucleus
position maps straight into the mask by

    overview_x = (czi_x - rect_x) * zoom

using the scene origin `01k_saturation_raw.py` recorded. Verified on
LS105_s05a_sc06: 5,808 of 5,808 nuclei land inside the frame.

So two things move at once - a mask that is no longer an undercount, and a finer
grid to sample it on. Both directions are reported per animal rather than folded
into a single number, because they are different claims.

**Both markers.** This was pERK-only because "AF488 cannot clip, so there is
nothing to censor" - an inference from the same 8-bit proxy, not a measurement.
AF488's display high is 37,263, so 255 in its overview means "at or above the
display high" and the question was unanswerable. On the raw plane AF488 clips on
most sections, up to 1.3% of frame on the worst. Any nucleus whose scene has a
raw mask is recensored, whatever its marker; one whose scene has none is left
exactly as it was and counted separately, because "measured zero" and "never
measured" are different facts.

Every other column is preserved byte-for-byte: rows are edited as text with only
the one field substituted, and `--verify` re-reads the result and checks it.

Run:  python 06f_recensor_nuclei.py --dry-run
      python 06f_recensor_nuclei.py
      python 06f_recensor_nuclei.py --verify
"""

import argparse
import csv
import json
import os
import shutil
import sys
from collections import Counter

import numpy as np
from PIL import Image

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
QC_DIR = os.path.join(OUT_ROOT, "qc")
RESULTS_DIR = os.path.join(OUT_ROOT, "results")
NUCLEI_CSV = os.path.join(RESULTS_DIR, "roi_nuclei.csv")
SAT_CSV = os.path.join(QC_DIR, "saturation_raw.csv")
BACKUP_DIR = os.path.join(RESULTS_DIR, "_pre_06f_backup")
LF = chr(10)
CRLF = chr(13) + LF

# Every marker that has a raw clipping mask is recensored. This used to be
# AF568-only because "AF488 cannot clip" - which was an inference from the 8-bit
# proxy, not a measurement. AF488's display high is 37,263, so 255 there means
# "at or above the display high", and the question could not be asked. On the raw
# plane AF488 clips on most sections, up to 1.3% of frame on the worst.
# A row whose scene has no mask is left exactly as it was, and counted.


def load_scenes():
    """scene_uid -> (rect_x, rect_y, zoom, mask_path). Only scenes with a mask."""
    if not os.path.exists(SAT_CSV):
        sys.exit(f"{SAT_CSV} not found - run 01k_saturation_raw.py first")
    out = {}
    with open(SAT_CSV, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("mask_path"):
                continue
            out[r["scene_uid"]] = (
                float(r["rect_x"]), float(r["rect_y"]), float(r["zoom"]),
                os.path.join(OUT_ROOT, r["mask_path"]),
            )
    return out


class MaskCache:
    """One mask in memory at a time - roi_nuclei.csv is already grouped by scene."""

    def __init__(self, scenes):
        self.scenes = scenes
        self.uid = None
        self.mask = None
        self.missing = set()

    def get(self, uid):
        if uid == self.uid:
            return self.mask
        self.uid, self.mask = uid, None
        info = self.scenes.get(uid)
        if info is None:
            self.missing.add(uid)
            return None
        path = info[3]
        if not os.path.exists(path):
            self.missing.add(uid)
            return None
        self.mask = np.asarray(Image.open(path).convert("L")) > 0
        return self.mask

    def sample(self, uid, czi_x, czi_y):
        m = self.get(uid)
        if m is None:
            return None
        rx, ry, zoom, _ = self.scenes[uid]
        x = int((czi_x - rx) * zoom)
        y = int((czi_y - ry) * zoom)
        if not (0 <= x < m.shape[1] and 0 <= y < m.shape[0]):
            # A nucleus outside its own scene rectangle cannot be clipped -
            # nothing was scanned there - so False is the right flag. But it is
            # never a rounding artifact at this scale, so it is counted and the
            # scene is named: it means an ROI was placed off the section.
            return False, True
        return bool(m[y, x]), False


def verify(path, n_cols):
    """Re-read the written file and confirm the shape survived."""
    bad = 0
    with open(path, encoding="utf-8", newline="") as fh:
        header = fh.readline().rstrip(CRLF).split(",")
        if len(header) != n_cols:
            sys.exit(f"header has {len(header)} columns, expected {n_cols}")
        n = 0
        for line in fh:
            n += 1
            if len(line.rstrip(CRLF).split(",")) != n_cols:
                bad += 1
    print(f"  verify: {n} data rows, {len(header)} columns, {bad} malformed")
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="re-read the output and check its shape")
    args = ap.parse_args()

    if not os.path.exists(NUCLEI_CSV):
        sys.exit(f"{NUCLEI_CSV} not found")
    scenes = load_scenes()
    print(f"{len(scenes)} scenes carry a raw clipping mask")

    # CRLF, and it matters - see 06g_flag_off_tissue.py for what stripping
    # only the newline does to this file.
    with open(NUCLEI_CSV, encoding="utf-8", newline="") as fh:
        raw = fh.readline()
    NL = CRLF if raw.endswith(CRLF) else LF
    header_line = raw.rstrip(CRLF)
    cols = header_line.split(",")
    n_cols = len(cols)
    for need in ("scene_uid", "marker", "czi_x", "czi_y", "censored"):
        if need not in cols:
            sys.exit(f"roi_nuclei.csv has no '{need}' column")
    i_uid, i_mk = cols.index("scene_uid"), cols.index("marker")
    i_x, i_y, i_cen = cols.index("czi_x"), cols.index("czi_y"), cols.index("censored")

    cache = MaskCache(scenes)
    tmp = NUCLEI_CSV + ".tmp"
    counts = Counter()
    per_animal = {}
    by_marker = {}
    by_marker_nomask = Counter()
    oob_by_scene = Counter()
    oob = 0

    out = None if args.dry_run else open(tmp, "w", encoding="utf-8", newline="")
    try:
        if out:
            out.write(header_line + NL)
        with open(NUCLEI_CSV, encoding="utf-8", newline="") as fh:
            fh.readline()
            for n, line in enumerate(fh, 1):
                row = line.rstrip(CRLF).split(",")
                if len(row) != n_cols:
                    # Never guess at a malformed row; pass it through untouched.
                    counts["malformed"] += 1
                    if out:
                        out.write(line)
                    continue
                old = row[i_cen] == "1"
                new = old
                got = cache.sample(row[i_uid], float(row[i_x]), float(row[i_y]))
                if got is not None:
                    new, was_oob = got
                    oob += was_oob
                    if was_oob:
                        oob_by_scene[row[i_uid]] += 1
                else:
                    counts["no_mask"] += 1
                    by_marker_nomask[row[i_mk]] += 1

                for d in (per_animal.setdefault(row[cols.index("animal")], Counter()),
                          by_marker.setdefault(row[i_mk], Counter())):
                    d["n"] += 1
                    d["old"] += old
                    d["new"] += new
                counts["total"] += 1
                counts["old_censored"] += old
                counts["new_censored"] += new
                if new and not old:
                    counts["gained"] += 1
                elif old and not new:
                    counts["lost"] += 1

                if out:
                    if new != old:
                        row[i_cen] = "1" if new else "0"
                        out.write(",".join(row) + NL)
                    else:
                        out.write(line)
                if n % 200000 == 0:
                    print(f"\r  {n} nuclei", end="")
    finally:
        if out:
            out.close()
    print(f"\r  {counts['total']} nuclei            ")

    print()
    print("=" * 74)
    print(f"  old censored : {counts['old_censored']}")
    print(f"  new censored : {counts['new_censored']}")
    print(f"  gained       : {counts['gained']}   (clipped, and the old mask missed it)")
    print(f"  lost         : {counts['lost']}   (expected 0 unless the finer grid "
          f"resolved a cell the 256 frame smeared)")
    if counts["no_mask"]:
        print(f"  !! {counts['no_mask']} nuclei had no raw mask for their scene "
              f"{dict(by_marker_nomask)}")
    if cache.missing:
        print(f"  !! scenes with no mask: {len(cache.missing)}  "
              f"e.g. {sorted(cache.missing)[:4]}")
    if oob:
        print(f"  !! {oob} nuclei mapped outside their scene frame - an ROI "
              f"placed off the section, not a rounding artifact:")
        for uid, n in sorted(oob_by_scene.items(), key=lambda kv: -kv[1])[:8]:
            print(f"       {uid}  {n}")
    if counts["malformed"]:
        print(f"  !! {counts['malformed']} malformed rows passed through untouched")
    print("=" * 74)

    print()
    print(f"  {'marker':<9}{'nuclei':>10}{'old':>8}{'new':>8}{'delta':>8}")
    for m in sorted(by_marker):
        c = by_marker[m]
        print(f"  {m:<9}{c['n']:>10}{c['old']:>8}{c['new']:>8}{c['new'] - c['old']:>+8}")

    print()
    print(f"  {'animal':<9}{'nuclei':>10}{'old':>8}{'new':>8}{'delta':>8}")
    for a in sorted(per_animal):
        c = per_animal[a]
        print(f"  {a:<9}{c['n']:>10}{c['old']:>8}{c['new']:>8}{c['new'] - c['old']:>+8}")

    if args.dry_run:
        print()
        print("dry run - nothing written")
        return

    if not args.no_backup:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        dst = os.path.join(BACKUP_DIR, "roi_nuclei.csv")
        if not os.path.exists(dst):
            print(f"\n  backing up to {dst} ...")
            shutil.copy2(NUCLEI_CSV, dst)
        else:
            print(f"\n  backup already exists, left alone: {dst}")

    os.replace(tmp, NUCLEI_CSV)
    print(f"  rewrote {NUCLEI_CSV}")
    if args.verify:
        verify(NUCLEI_CSV, n_cols)
    print()
    print("  next: 06a_roi_dataset.py, then 06c / 06d and the analysis/ figures")


if __name__ == "__main__":
    main()
