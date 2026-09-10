"""Stage 4o - colour composites of the curation sections, in the reformatted frame.

The ROI curator was showing `sections_AF568/*.png`: 256x256, greyscale, and
**DAPI**, because that is what `04a_reformat` runs on - the marker channel is a
sparse signal and a poor silhouette, so geometry is decided on the counterstain.
Those images are already cut and tilted; what they are not is the two-colour
picture the section is actually read as, and the marker channel - the thing being
quantified - is not in them at all.

This writes the same sections as RGB composites in the *same* frame: the
counterstain in its colour - blue unless `display.nuclear_colour` says
otherwise, and it is the geometry channel, exactly what the curator showed
before - plus ONE marker in its own, from `display.colours`.

One marker, because this stage builds one marker per run (`--marker`) into that
marker's own `sections*_rgb/`. Under the paired layout a composite is therefore
a marker and the counterstain, never two markers: the two markers are separate
physical sections and have separate directories. The set across two runs is
red-and-green; no single picture is. An earlier version of this docstring
listed both markers here, which is how a reader comes to believe otherwise.

The frame has to be identical or every landmark placed on it is placed on the
wrong picture, so the marker is not reformatted separately. It rides through
`reformat(companion=...)` as a passenger on the geometry channel's own rotation,
flip, crop, pad and resize - the same trick the artifact and censor masks already
use - and the blue channel of the output is the byte-for-byte image the curator
was showing. `--verify` checks exactly that rather than assuming it.

Only the sections in `roi_worklist.csv` are built by default, so that covers the
curation job rather than all 718 reformatted sections. `--all` builds the
marker's whole reformat index instead, and `--include-excluded` builds every
scanned section in `focus.csv` - including the 1,066 the pipeline threw out.

Those excluded sections are exactly why this reaches past the index. They have a
greyscale image (`04a --render-excluded` writes one so they can be LOOKED at in
Review mode) but no composite, so the review grid showed them in grey next to
colour neighbours - which reads as a rendering fault rather than as "this one
was excluded". Being in `sections_*_rgb/` still puts nothing into the analysis -
the index is what does that, and this does not touch it.

AN EXCLUDED SECTION IS BUILT UNMASKED, because that is what its greyscale is.
04a masks only under `--mask-artifacts`, and the excluded ones were rendered
before `04g --include-excluded` gave them artifact masks at all - so their
stored image has no masking in it, while every section in the index does.
Applying the mask here anyway made 848 of the 1,066 fail `--verify` against the
picture the grid actually shows: same frame, different pixels.

It is also the better picture to review. An excluded section is on screen so
somebody can decide whether to reinstate it, and a base image with the artifact
already painted black cannot answer that - the mask is a layer you switch on in
Review mode, and it has nothing to show if it has been baked in.

Thumbnails
----------

`--thumbs` writes a `RF.GRID`-sized copy of each composite into
`<sections>_rgb_thumb/`. The review grid draws a few hundred cells at 78px, and
a 768px composite is 448 KB against 21 KB for the greyscale it replaced - one
animal's grid went from 4.7 MB to 56.6 MB for pictures nobody sees at that size.
That is the same mistake the grid already made once with the 1632x1862
overviews, which left most cells blank behind `loading="lazy"` and looked broken
rather than slow.

A thumbnail is a DOWNSCALE OF THE COMPOSITE, never a re-render. Re-rendering
would put a second code path between the picture and the frame it was built in,
and the only thing that makes these safe to show next to landmark work is that
they are the same image, smaller.

Run:  python 04o_section_rgb.py
      python 04o_section_rgb.py --tier core
      python 04o_section_rgb.py --verify
      python 04o_section_rgb.py --thumbs --all --marker AF488
"""

import sys
import argparse
import csv
import importlib.util
import os

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_channels as CH  # noqa: E402

# The markers this study measures, in declared order. ls_channels is the
# single source of that list; naming a fluorophore here would pin the stage
# to one study.
MARKERS = list(CH.marker_names(CONFIG))

_spec = importlib.util.spec_from_file_location("_rf", os.path.join(_HERE, "04a_reformat.py"))
RF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RF)

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(_HERE, "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

OUT_ROOT = RF.OUT_ROOT
REFORMAT_DIR = RF.REFORMAT_DIR
WORKLIST_CSV = os.path.join(REFORMAT_DIR, "roi_worklist.csv")
FOCUS_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")

# Marker -> the colour it is drawn in, and the counterstain's own colour.
# Positional by default - first marker shown red, second green, which is what
# this stage has always written - and named by `display.colours` when a study
# wants otherwise. ls_channels owns the rule, and the curator's Review pane
# reads the SAME function: naming a fluorophore or a plane index here is how
# the pane and the composites came to disagree about what colour a section is.
MARKER_COLOURS = CH.marker_colours(CONFIG)
NUCLEAR_COLOUR = CH.nuclear_colour(CONFIG)


def composite(marker_img, dapi_img, colour, nuclear=(0., 0., 1.)):
    """One marker in its own colour, over the counterstain in its own.

    Per plane the two contributions are combined with MAX, not sum. For a
    marker with no blue in it - which is every marker this pipeline has ever
    had - max(0, dapi) is dapi exactly, so the blue plane is still the
    byte-for-byte greyscale the geometry was decided on and --verify still
    means what it meant.

    Where they DO share a plane - a magenta marker is red plus blue, and blue
    is the counterstain - max keeps both readable and never clips. Sum was the
    alternative: it makes overlap brighter, the conventional way to read
    co-localisation, but it saturates to 255 and then a very bright marker and
    a marker-over-counterstain look identical. This picture exists so somebody
    can judge whether a section is measurable, so not clipping wins.

    Both images are uint8 and both coefficients are exact in binary for every
    colour in the table, so a plane whose coefficient is 1.0 comes back as the
    input array byte for byte. tests/test_composite.py pins that with
    np.array_equal against the plane assignment this replaced, because the
    constants probe cannot see pixels and 130 curated sections carry landmark
    coordinates placed on the composites already on disk.
    """
    mark = np.asarray(marker_img, dtype=np.float64)
    dapi = np.asarray(dapi_img, dtype=np.float64)
    rgb = np.zeros(mark.shape + (3,), np.uint8)
    for p in range(3):
        plane = np.maximum(colour[p] * mark, nuclear[p] * dapi)
        rgb[..., p] = np.clip(np.rint(plane), 0, 255).astype(np.uint8)
    return rgb


def worklist_uid_column(marker, fields):
    """Which `roi_worklist.csv` column carries this marker's scene uid.

    The worklist is keyed on the pass being quantified, and reaches the other
    pass only through the pairing - so one marker reads the row's own uid and
    the other reads the partner's. Which is which was `args.marker == "AF488"`,
    a literal that was true for exactly one study; every marker of any other
    study took the `else` branch and both passes were built from the SAME uids,
    silently.

    `RF.DEFAULT_MARKER` is the comparison, not `MARKERS[1]` spelled out here:
    the partner column belongs to whichever pass owns the unsuffixed outputs,
    and 04a is where that is decided.

    NOT `RF.marker_paths(marker)["uid_col"]`, which the plan for this change
    suggested. That table names 04a's OVERRIDE columns - `perk_scene_uid` for
    the non-default marker, `scene_uid` for the default - and this file's
    columns are `scene_uid` and `partner_scene_uid`. Taking the name from
    there would ask a header that has never had a `perk_scene_uid` column for
    one, which `pick_column` would refuse, and would hand the DEFAULT marker
    `scene_uid`, which is the other pass's section.

    `pick_column`, not a literal and not `.get()`: 04n renamed this column from
    `pcna_scene_uid` to `partner_scene_uid`, so a worklist under either
    spelling has to keep working, and a `.get()` on the wrong one yields an
    empty uid list and a run that builds no composites at all without saying so.
    """
    if marker == RF.DEFAULT_MARKER:
        return IO.pick_column(fields, "partner_scene_uid", "pcna_scene_uid",
                              what=os.path.basename(WORKLIST_CSV))
    return "scene_uid"


def write_thumbs(rgb_dir, size=RF.GRID, force=False):
    """Downscale every composite in `rgb_dir` into `<rgb_dir>_thumb`.

    Reads the composites rather than rebuilding from the overviews: a thumbnail
    that went through its own render could differ from the picture the landmarks
    were placed on, and the whole point is that it cannot.

    LANCZOS because this is a 3:1 reduction of a sparse fluorescent signal -
    nearest or bilinear drop isolated positive nuclei entirely, which is exactly
    the thing the grid is being scanned for.
    """
    out_dir = rgb_dir + "_thumb"
    os.makedirs(out_dir, exist_ok=True)
    made = existing = failed = 0
    for name in sorted(os.listdir(rgb_dir)):
        if not name.endswith(".png"):
            continue
        dst = os.path.join(out_dir, name)
        if os.path.exists(dst) and not force:
            existing += 1
            continue
        try:
            with Image.open(os.path.join(rgb_dir, name)) as im:
                im.convert("RGB").resize((size, size), Image.LANCZOS).save(dst)
            made += 1
        except OSError:
            failed += 1
    print(f"wrote {made} thumbnails ({size}px) to {out_dir}")
    if existing:
        print(f"  {existing} already there, left alone (--force rebuilds them)")
    if failed:
        print(f"  {failed} could not be read")
    return made, existing, failed


def main():
    ap = argparse.ArgumentParser()
    _default = MARKERS[0] if MARKERS else None
    ap.add_argument("--marker", choices=MARKERS, default=_default,
                    help=f"which marker to process (default {_default})")
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
    ap.add_argument("--include-excluded", action="store_true",
                    help="build every SCANNED section for this marker, not just the "
                         "ones that survived. The excluded ones already have a "
                         "greyscale image from 04a --render-excluded and are shown "
                         "in Review mode; without this they are the only grey cells "
                         "in a colour grid. Adds no index row, so nothing downstream "
                         "picks them up")
    ap.add_argument("--force", action="store_true",
                    help="rebuild composites that already exist (default is to skip "
                         "them, so topping a set up costs only the missing ones)")
    ap.add_argument("--verify", action="store_true",
                    help="check the blue plane still equals the existing greyscale section")
    ap.add_argument("--thumbs", action="store_true",
                    help="downscale the composites already built for this marker to "
                         f"{RF.GRID}px for the review grid, and do nothing else")
    ap.add_argument("--thumb-size", type=int, default=RF.GRID, metavar="N",
                    help=f"thumbnail edge in pixels (default {RF.GRID})")
    args = ap.parse_args()

    paths = RF.marker_paths(args.marker)
    src_dir = paths["sections"]
    out_dir = src_dir + "_rgb"
    index_path = paths["index"]

    # Thumbnails are a resize of what is already on disk, so they need none of
    # the overrides, focus table or worklist below.
    if args.thumbs:
        if not os.path.isdir(out_dir):
            print(f"no composites to shrink: {out_dir} does not exist")
            return
        write_thumbs(out_dir, args.thumb_size, args.force)
        return

    overrides, _ = RF.load_overrides(paths)
    os.makedirs(out_dir, exist_ok=True)

    with open(FOCUS_CSV, newline="", encoding="utf-8") as fh:
        secs = {r["scene_uid"]: r for r in csv.DictReader(fh)
                if r["marker_channel"] == args.marker}

    if args.include_excluded:
        # focus.csv is the whole scanned set for this marker - the same list 04p
        # walks - so this reaches the sections the index deliberately omits.
        uids = sorted(secs)
    elif args.all:
        with open(paths["index"], newline="", encoding="utf-8") as fh:
            uids = [r["id"] for r in csv.DictReader(fh) if r["kind"] == "section"]
    else:
        with open(WORKLIST_CSV, newline="", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            fields = list(rd.fieldnames or [])
            want = [r for r in rd if not args.tier or r["tier"] == args.tier]
        # The worklist is keyed on the measured pass. Building the other side
        # from it means following the pairing to the partner scene, which the
        # 30 unpaired sections do not have - hence --all, which reads the
        # marker's own index. Which column that is, see worklist_uid_column.
        uid_col = worklist_uid_column(args.marker, fields)
        uids = [u for u in ((w.get(uid_col) or "").strip() for w in want) if u]

    # The index is the definition of "survived", so it is also the definition of
    # "was masked on the way in" - 04a writes an index row for exactly the
    # sections it reformatted under the analysis flags.
    with open(index_path, newline="", encoding="utf-8") as fh:
        in_index = {r["id"] for r in csv.DictReader(fh) if r["kind"] == "section"}

    colour = MARKER_COLOURS.get(args.marker)
    if colour is None:
        # Measured, but this study never said what colour to draw it in. Not a
        # loop body - this stage builds one marker per run - so it stops here
        # and says which markers DO have a colour. Picking one for it would be
        # a marker silently wearing another marker's colour, which is the
        # fault `display.colours` exists to remove; drawing it black would be
        # a picture of nothing that looks like a failed render.
        shown = ", ".join(sorted(MARKER_COLOURS))
        print(f"{args.marker} is not composited: this study gives a colour to "
              f"{shown or 'no marker'}, and the first two markers shown get "
              f"red and green by default.")
        print(f"  Give it one: `display.colours: {{\"{args.marker}\": "
              f"\"magenta\"}}` in config.json.")
        return
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
        # Masked exactly as this section's own greyscale was - see the module
        # docstring. Not a preference: the blue plane has to equal the picture
        # already on disk, and for an excluded section that picture is raw.
        excluded_here = uid not in in_index
        art = None if excluded_here else RF.load_artifact(uid, (RF.WORK_SIZE, RF.WORK_SIZE))
        cen = None if excluded_here else RF.load_censor(uid, (RF.WORK_SIZE, RF.WORK_SIZE))
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

        Image.fromarray(composite(comp, img, colour, NUCLEAR_COLOUR)).save(out_path)
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
