"""Stage 6g - flag nuclei that are not on the section, in an existing roi_nuclei.csv.

`05c_detect_rois.py` decided membership on the ROI disc alone: a nucleus was
kept if its centroid mapped inside the disc on the 256 grid. Nothing checked
that it was on the tissue, or even inside the scanned scene. A disc overhanging
the silhouette therefore contributed objects segmented on glass or mounting
medium, and they were quantified like any other.

Measured over the 895,548 nuclei present on 2026-09-02: **2,576 (0.29%)** sit
outside the DAPI tissue silhouette - 1,969 of 621,906 in ROI discs (0.32%) and
607 of 273,642 in background discs (0.22%), across 87 of 130 sections. **430 are
not merely off the tissue but outside the 256 frame entirely**, 429 of them one
background disc in `LS37_s05a_sc06` sitting about 2.6 mm above the top edge of
its own scene - measured on an area the scanner never visited.

**Background discs are where this costs something.** `06a_roi_dataset.py` sets
each section's positivity cut from its own background discs, as
`median + 3 * 1.4826 * MAD`. Objects found on glass are dim, so they pull the
median and the cut DOWN, and a lower cut makes that section look more positive.
In `LS37_s05a_sc06` the off-scan disc is 429 of that section's 4,813 background
nuclei - 8.9% of the population setting its cut.

`05c` now records an `off_tissue` column itself. This backfills that column onto
a table written before it did, so old and new files mean the same thing.

The tissue definition is deliberately the one everything else uses: the DAPI
silhouette from `04a_reformat.py`'s `tissue_mask()`, carried through the same
rotation and crop into the 256 frame as `<uid>_mask.npy`. Using a different
definition here would let 05c reject a nucleus the operator placed a disc over
in the curator, which showed that very mask.

**Its resolution is a real limit and not hidden.** The 256 frame is about 31 um
per cell against a 7 um nucleus, so a nucleus within roughly one cell of the
silhouette edge is judged by which cell its centroid lands in. That is coarse at
the boundary and exact in the interior, which is where the problem cases are -
`LS37_s05a_sc06` is off by 69 cells, not one.

Run:  python 06g_flag_off_tissue.py --dry-run
      python 06g_flag_off_tissue.py --verify
"""

import argparse
import csv
import json
import os
import shutil
import sys
from collections import Counter

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_paths as LP  # noqa: E402

OUT_ROOT = CONFIG["out_root"]
RESULTS_DIR = os.path.join(OUT_ROOT, "results")
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
NUCLEI_CSV = os.path.join(RESULTS_DIR, "roi_nuclei.csv")
BACKUP_DIR = os.path.join(RESULTS_DIR, "_pre_06g_backup")

# The section-directory rule, borrowed rather than restated. See section_dirs.
NAMES = LP.for_config(CONFIG)

COLUMN = "off_tissue"
LF = chr(10)
CRLF = chr(13) + LF


def section_dirs():
    """Every directory 04a may have written a section into, in marker order.

    The same list `05c.section_dirs` builds, from the same table - what is
    duplicated here is one import, not a second copy of the rule. The literal
    this replaces was `("sections_AF568", "sections")`, which for any study
    whose markers are not AF568/AF488 named one directory that has never
    existed and one holding only the geometry source's sections. Every other
    marker's silhouette was then missing, `off_tissue` came back None for all
    of its nuclei, and nothing was flagged - which reads exactly like a clean
    dataset.

    The unsuffixed directory is kept on the end for the pre-rename layout; see
    05c.section_dirs for why that is not redundant.
    """
    dirs = [NAMES.path("sections", m) for m in NAMES.markers]
    dirs.append(os.path.join(REFORMAT_DIR, "sections"))
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def tissue_mask(uid):
    """The DAPI silhouette in the 256 frame - 05c's `mask_at(uid, "mask")`."""
    for d in section_dirs():
        p = os.path.join(d, f"{uid}_mask.npy")
        if os.path.exists(p):
            return np.load(p)
    return None


class Cache:
    """One mask at a time; roi_nuclei.csv is already grouped by scene."""

    def __init__(self):
        self.uid = None
        self.mask = None
        self.missing = set()

    def off(self, uid, sx, sy):
        """True if this nucleus is not on the section. None if unknowable."""
        if uid != self.uid:
            self.uid, self.mask = uid, tissue_mask(uid)
            if self.mask is None:
                self.missing.add(uid)
        if self.mask is None:
            return None
        x, y = int(round(sx)), int(round(sy))
        if not (0 <= x < self.mask.shape[1] and 0 <= y < self.mask.shape[0]):
            return True, True          # off tissue, and off the frame entirely
        return (not bool(self.mask[y, x])), False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(NUCLEI_CSV):
        sys.exit(f"{NUCLEI_CSV} not found")

    # roi_nuclei.csv is written by csv.writer on Windows, so its lines end
    # CRLF. Stripping only the newline leaves a bare CR on the LAST field,
    # and appending a column after that puts the CR mid-line - which
    # Python's universal-newline reader then treats as a line break,
    # doubling the row count and handing 06a a None. That is exactly what
    # the first attempt did. Detect the terminator, strip both, write it back.
    with open(NUCLEI_CSV, encoding="utf-8", newline="") as fh:
        raw = fh.readline()
    NL = CRLF if raw.endswith(CRLF) else LF
    header = raw.rstrip(CRLF)
    cols = header.split(",")
    for need in ("scene_uid", "roi_kind", "sec_x", "sec_y"):
        if need not in cols:
            sys.exit(f"roi_nuclei.csv has no '{need}' column")
    already = COLUMN in cols
    if already:
        print(f"'{COLUMN}' already present - recomputing it in place")
    i_uid, i_kind = cols.index("scene_uid"), cols.index("roi_kind")
    i_x, i_y = cols.index("sec_x"), cols.index("sec_y")
    i_off = cols.index(COLUMN) if already else None
    out_cols = cols if already else cols + [COLUMN]
    n_in, n_out = len(cols), len(out_cols)

    cache = Cache()
    counts = Counter()
    per_kind = {}
    per_scene = Counter()
    tmp = NUCLEI_CSV + ".tmp"

    out = None if args.dry_run else open(tmp, "w", encoding="utf-8", newline="")
    try:
        if out:
            out.write(",".join(out_cols) + NL)
        with open(NUCLEI_CSV, encoding="utf-8", newline="") as fh:
            fh.readline()
            for n, line in enumerate(fh, 1):
                row = line.rstrip(CRLF).split(",")
                if len(row) != n_in:
                    counts["malformed"] += 1
                    if out:
                        out.write(line)
                    continue
                got = cache.off(row[i_uid], float(row[i_x]), float(row[i_y]))
                if got is None:
                    # No silhouette means the question cannot be answered. Keep
                    # the old value if there was one, else leave it blank - not
                    # 0, which would assert "on tissue" without having looked.
                    counts["unknown"] += 1
                    val = row[i_off] if already else ""
                else:
                    off, oob = got
                    val = "1" if off else "0"
                    k = row[i_kind]
                    d = per_kind.setdefault(k, Counter())
                    d["n"] += 1
                    d["off"] += off
                    d["oob"] += oob
                    counts["total"] += 1
                    counts["off"] += off
                    counts["oob"] += oob
                    if off:
                        per_scene[row[i_uid]] += 1
                if out:
                    if already:
                        row[i_off] = val
                    else:
                        row.append(val)
                    out.write(",".join(row) + NL)
                if n % 200000 == 0:
                    print(f"\r  {n} nuclei", end="")
    finally:
        if out:
            out.close()
    print(f"\r  {counts['total']} nuclei judged            ")

    print()
    print("=" * 74)
    print(f"  off the tissue : {counts['off']} of {counts['total']} "
          f"({100 * counts['off'] / max(counts['total'], 1):.2f}%)")
    print(f"    of those, outside the 256 frame entirely: {counts['oob']}")
    if counts["unknown"]:
        print(f"  !! {counts['unknown']} nuclei have no tissue mask for their scene "
              f"and were left blank, not 0")
    if cache.missing:
        print(f"  !! scenes with no mask: {len(cache.missing)}  "
              f"e.g. {sorted(cache.missing)[:4]}")
    if counts["malformed"]:
        print(f"  !! {counts['malformed']} malformed rows passed through untouched")
    print("=" * 74)

    print()
    print(f"  {'roi_kind':<12}{'nuclei':>10}{'off':>8}{'%':>8}{'off-frame':>11}")
    for k in sorted(per_kind):
        c = per_kind[k]
        print(f"  {k:<12}{c['n']:>10}{c['off']:>8}{100 * c['off'] / max(c['n'], 1):>7.2f}%"
              f"{c['oob']:>11}")

    print()
    print("  worst sections:")
    for uid, n in per_scene.most_common(10):
        print(f"    {uid:<24}{n:>6}")

    if args.dry_run:
        print("\ndry run - nothing written")
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
    print(f"  rewrote {NUCLEI_CSV} with {n_out} columns")
    if args.verify:
        bad = 0
        with open(NUCLEI_CSV, encoding="utf-8", newline="") as fh:
            h = fh.readline().rstrip(CRLF).split(",")
            rows = 0
            for line in fh:
                rows += 1
                if len(line.rstrip(CRLF).split(",")) != n_out:
                    bad += 1
        print(f"  verify: {rows} rows, {len(h)} columns, {bad} malformed")
    print()
    print("  next: 06a_roi_dataset.py, then 06c / 06d and the analysis/ figures")


if __name__ == "__main__":
    main()
