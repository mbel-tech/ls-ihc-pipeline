"""Stage 4q - the ROI curator's exported CSVs, turned back into its seed state.

The inverse of `04l_roi_curator.py`'s export(). The curator keeps its work in
localStorage and 04l seeds a fresh page from `curation/ls_roi_curator_v1.json`;
export writes three CSVs and, until this stage, nothing read them back. Work
done in a browser could only return to disk by hand.

That gap matters because localStorage is partitioned per origin AND per browser
profile. Curation done in one browser is invisible to the app and to the same
file opened anywhere else, so the CSVs are the only way it travels - and a
one-way door means the exports pile up in a Downloads folder while the page
keeps re-seeding from whatever the app last wrote.

Reads `roi_plates.csv` (one row per touched section), `roi_landmarks.csv` (every
landmark pair) and `roi_regions.csv` (the background discs live here too, told
apart by `roi_kind`, and the drawn REGIONS, told apart by `roi_shape`). Writes
the seed JSON 04l embeds.

A polygon is the one thing `roi_regions.csv` holds that the landmarks file
cannot supply. A disc row is a landmark seen from the other side; a polygon
answers no single point on the plate, so it exists in that file alone and a
round trip that ignored it would quietly undo an operator's region work.

THE SCALE IS PER SECTION
------------------------

Export divides section coordinates by `K = secImg.naturalWidth / SEC_GRID` so
the CSVs are always in canonical 256-pixel space. K is NOT a constant: the page
shows the 768px RGB composite where one exists and the 256px greyscale
otherwise, so K is 3 for most sections and 1 for the rest - and the two markers
do not share a directory (`sections_AF568{,_rgb}` against `sections{,_rgb}`).

A single global K is the quiet failure this stage exists to avoid: it reproduces
one set exactly and displaces every ROI in the other by 3x, on a page that loads
without complaint and puts the discs somewhere plausible. So K is resolved the
way 04l resolves it, per section, from the image the page would actually load.

Plate coordinates are in the plate's own frame and are NOT scaled. Only
`sec_x`, `sec_y` and `sec_r` pass through K.

WHAT IS NOT RECOVERABLE
-----------------------

`assigned` is read as "the export named a plate". Export collapses
`s.assigned || n > 0` into one plate_id column, so a section that got its plate
by having landmarks placed on it cannot be told from one assigned outright. A
section carrying landmarks had its plate chosen in the only sense that matters,
so that is how it is read.

Sections with no decision at all are absent from the export by design, and stay
absent here. Nothing is invented for them.

Writes `curation/ls_roi_curator_v1.json`. Reports and exits without writing
unless `--write` is passed; backs the old file up first.

Run:  python 04q_import_curation.py --plates roi_plates.csv
          --landmarks roi_landmarks.csv --regions roi_regions.csv --write
"""

import sys
import argparse
import csv
import json
import os
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_paths as LP  # noqa: E402

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")

# The one place the "sections/ or sections_<marker>/" rule lives. See
# marker_dir below for what this stage got wrong while it had its own copy.
NAMES = LP.for_config(CONFIG)
SEED_JSON = os.path.join(OUT_ROOT, "curation", "ls_roi_curator_v1.json")

# Mirrors 04l: the pair array is
# [sec_x, sec_y, plate_x, plate_y, seed_n, radius] and a background disc carries
# BG_MARK at index 6. A drawn region is NOT a pair - it sits in `polys` as
# {v:[x,y,...], region, part} - because a pair is a correspondence and a polygon
# corresponds to no single plate point. pairR() reads index 5, isBg() reads index 6; nothing else
# in the page inspects the tail, so a pair that is one element short silently
# becomes an ROI with a default radius.
BG_MARK = "bg"
SEC_GRID = 256

# The decision fields 04l keeps per section.
STATE_FIELDS = ("plate", "pairs", "polys", "assigned", "noroi", "fav", "rot", "excl")


def num(v, default=0.0):
    """CSV cells are text and blanks are ordinary here - a section with no plate
    has no plate_index, a landmark with no seed has no seed_n."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def tidy(x):
    """0.0 -> 0, so the file reads like the one the page writes."""
    f = float(x)
    return int(f) if f.is_integer() else f


def marker_dir(marker):
    """The directory 04a wrote this marker's sections into. Not restated here.

    This function used to BE the rule, as `"sections_AF568" if marker ==
    "AF568" else "sections"` - the LS study's answer written out as though it
    were everyone's. For any other study every marker resolved to `sections`,
    so `k_from_disk` probed a directory 04o had not written, missed the 768-px
    composite, and fell back to k=1.0 while the page had drawn at K=3. Every
    imported disc, landmark and polygon vertex then landed at one THIRD of its
    true coordinate, on a page that loads without complaint and puts them
    somewhere plausible - which is verbatim the failure the docstring at the
    top of this file says this stage exists to prevent.

    `including()` because `marker` comes out of a CSV a browser wrote, and a
    row naming a marker this config does not declare must not take down an
    import that has 400 good rows in it.
    """
    return NAMES.including(marker).basename("sections", marker)


def k_from_disk(reformat_dir=REFORMAT_DIR, rgb=True):
    """Build the k_of() the real page implies: the width of the image 04l would
    load for a section, over SEC_GRID.

    Returned as a callable so build() stays pure and the tests can pin the scale
    without needing images on disk.
    """
    cache = {}

    def k_of(uid, marker):
        if uid in cache:
            return cache[uid]
        from PIL import Image
        base = marker_dir(marker)
        subs = ((base + "_rgb",) if rgb else ()) + (base,)
        k = 1.0
        for sub in subs:
            path = os.path.join(reformat_dir, sub, uid + ".png")
            if os.path.exists(path):
                try:
                    k = Image.open(path).size[0] / float(SEC_GRID)
                except OSError:
                    k = 1.0
                break
        cache[uid] = k
        return k

    return k_of


def load(path):
    """utf-8-sig because these arrive via a browser download, and Excel is a
    common stop on the way back."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def cell(row, name):
    return (row.get(name) or "").strip()


def build(plates, landmarks, regions, k_of):
    """Rebuild the seed state. `k_of(uid, marker)` gives the section's scale.

    Returns (state, skipped); `skipped` lists (kind, uid) for coordinate rows
    naming a section with no plates row - which should not happen, since export
    writes a plates row for anything it emits coordinates for, and means the
    three files did not come from one export.
    """
    state, marker_of, skipped = {}, {}, []

    for r in plates:
        uid = cell(r, "scene_uid")
        if not uid:
            continue
        marker_of[uid] = cell(r, "marker")
        idx = cell(r, "plate_index")
        state[uid] = {
            "plate": int(num(idx)) if idx else 0,
            "pairs": [],
            "polys": [],
            # Export collapses `assigned || n > 0` into plate_id - see the
            # module docstring; a named plate is read as a chosen one.
            "assigned": bool(cell(r, "plate_id")),
            "noroi": cell(r, "status") == "no_roi",
            "fav": cell(r, "favorite") == "1",
            "rot": tidy(num(cell(r, "view_rotation_deg"))),
            "excl": cell(r, "excluded") == "1",
        }

    def scaled(uid, r, key):
        # Round to the export's own 2dp: K is a small integer and the value it
        # multiplies already carries 2 decimals, so this removes float noise
        # (97.28 * 3 = 291.84000000000003) rather than losing precision.
        return tidy(round(num(cell(r, key)) * k_of(uid, marker_of.get(uid, "")), 2))

    for r in landmarks:
        uid = cell(r, "scene_uid")
        if uid not in state:
            skipped.append(("landmark", uid))
            continue
        sn = cell(r, "seed_n")
        state[uid]["pairs"].append([
            scaled(uid, r, "sec_x"), scaled(uid, r, "sec_y"),
            # The plate frame is the plate's own; K is a property of how the
            # SECTION is displayed and has nothing to say about it.
            tidy(num(cell(r, "plate_x"))), tidy(num(cell(r, "plate_y"))),
            int(num(sn)) if sn else 0,
            scaled(uid, r, "sec_r"),
        ])

    for r in regions:
        uid = cell(r, "scene_uid")
        # A drawn REGION is the one thing in this file that roi_landmarks.csv
        # cannot supply. A disc row is a landmark seen from the other side and
        # is already covered by the pairs above; a polygon answers no single
        # plate point and exists only here, so losing it would quietly undo an
        # operator's region work on every round trip.
        if cell(r, "roi_shape") == "polygon":
            if uid not in state:
                skipped.append(("polygon", uid))
                continue
            k = k_of(uid, marker_of.get(uid, ""))
            v = []
            for vtx in cell(r, "sec_poly").split(";"):
                xy = vtx.split()
                if len(xy) != 2:
                    continue
                v.append(tidy(round(num(xy[0]) * k, 2)))
                v.append(tidy(round(num(xy[1]) * k, 2)))
            # Under three corners is not a polygon. A row that lost its vertex
            # list somewhere would come back as a shape enclosing nothing, and
            # 05a would hand 05c a box with no area in it.
            if len(v) < 6:
                skipped.append(("polygon", uid))
                continue
            pt, rn = cell(r, "part"), cell(r, "roi_n")
            poly = {
                "v": v, "region": cell(r, "region"),
                "part": int(num(pt)) if pt else 1,
                # Which numbered ROI on the plate this area answers. Without it
                # the guided cursor cannot tell a re-imported section is already
                # done and would ask for every region again.
                "roi": int(num(rn)) if rn else 0,
            }
            # The order stamp, when the export carried one. An export written
            # before the column existed has no answer, and absent has to stay
            # absent: the curator reads an unstamped region as the newer of the
            # two, and a number invented here would assert an order the file
            # never recorded. "0" is a real stamp - a region drawn before any
            # landmark - so this tests for an empty cell, not for falsity.
            at = cell(r, "landmarks_at_draw")
            if at != "":
                poly["n"] = int(num(at))
            state[uid].setdefault("polys", []).append(poly)
            continue
        # roi_kind is the only thing separating a background disc from an ROI:
        # same columns, same units, same meaning. The ROI rows here are already
        # covered by roi_landmarks.csv, which carries every placed pair.
        if cell(r, "roi_kind") != "background":
            continue
        if uid not in state:
            skipped.append(("background", uid))
            continue
        state[uid]["pairs"].append([
            scaled(uid, r, "sec_x"), scaled(uid, r, "sec_y"),
            0, 0, 0,                      # a disc answers no plate point
            scaled(uid, r, "sec_r"), BG_MARK,
        ])

    return state, skipped


def compare(state, path):
    """What adopting this would change about the file already on disk."""
    try:
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        return None
    return {
        "old": len(old),
        "added": sorted(set(state) - set(old)),
        "only_on_disk": sorted(set(old) - set(state)),
        "changed": sorted(u for u in set(old) & set(state) if old[u] != state[u]),
    }


def counts(state):
    vals = state.values()
    return {
        "sections": len(state),
        "excluded": sum(1 for v in vals if v["excl"]),
        "favourites": sum(1 for v in vals if v["fav"]),
        "assigned": sum(1 for v in vals if v["assigned"]),
        "landmarks": sum(1 for v in vals for p in v["pairs"] if len(p) <= 6),
        "background": sum(1 for v in vals for p in v["pairs"] if len(p) > 6),
        "regions": sum(len(v.get("polys") or ()) for v in vals),
        "region_sections": sum(1 for v in vals if v.get("polys")),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plates", required=True, help="roi_plates.csv")
    ap.add_argument("--landmarks", required=True, help="roi_landmarks.csv")
    ap.add_argument("--regions", required=True, help="roi_regions.csv")
    ap.add_argument("--out", default=SEED_JSON, help="default " + SEED_JSON)
    ap.add_argument("--reformat-dir", default=REFORMAT_DIR)
    ap.add_argument("--no-rgb", action="store_true",
                    help="the page was built without --rgb, so K is 1 everywhere")
    ap.add_argument("--write", action="store_true",
                    help="write --out; without this the run only reports")
    args = ap.parse_args(argv)

    k_of = k_from_disk(args.reformat_dir, not args.no_rgb)
    state, skipped = build(load(args.plates), load(args.landmarks),
                           load(args.regions), k_of)
    c = counts(state)
    print("rebuilt {sections} sections: {excluded} excluded, {favourites} "
          "favourite, {assigned} with a plate".format(**c))
    print("  {landmarks} landmark pairs, {background} background discs".format(**c))
    # Said out loud rather than left to be inferred from the file size: a drawn
    # region exists in roi_regions.csv alone, so if this line reads 0 after an
    # export that had regions in it, the round trip lost them.
    if c["regions"]:
        print("  {regions} drawn regions on {region_sections} sections".format(**c))

    scales = {}
    for uid, v in state.items():
        if v["pairs"]:
            k = k_of(uid, "")
            scales[k] = scales.get(k, 0) + 1
    if scales:
        print("  scale on sections carrying pairs: "
              + ", ".join("K=%g on %d" % (k, n) for k, n in sorted(scales.items())))

    for kind, uid in skipped:
        print("  WARNING: %s row for %s, which has no roi_plates row - dropped "
              "(are these three files from one export?)" % (kind, uid))

    d = compare(state, args.out)
    if d:
        print("\nagainst %s: %d sections on disk" % (args.out, d["old"]))
        print("  %d new, %d only on disk, %d changed"
              % (len(d["added"]), len(d["only_on_disk"]), len(d["changed"])))
        # Work that exists ONLY on disk is the one thing this can destroy, so it
        # is named rather than counted.
        for uid in d["only_on_disk"]:
            print("  ONLY ON DISK, would be lost: " + uid)

    if not args.write:
        print("\n(report only - pass --write to save)")
        return 0

    if os.path.exists(args.out):
        bak = args.out + ".backup"
        shutil.copy2(args.out, bak)
        print("\nbacked up %s -> %s"
              % (os.path.basename(args.out), os.path.basename(bak)))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    print("wrote " + args.out)
    print("Regenerate the page to pick it up: python scripts/04l_roi_curator.py ...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
