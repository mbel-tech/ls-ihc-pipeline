"""Stage 0d - self-test of the assumptions this pipeline makes about its CZIs.

Every stage that reads pixels assumes four things about the files. This stage
checks all four and is a GATE over the ones that are structural assumptions -
if a file breaks one, the stage exits 2 so a later dataset that breaks it fails
loudly here instead of quietly in a figure. It is an INVENTORY over the ones
that are properties of a healthy dataset rather than defects in a file - those
are measured and reported prominently, but never fail the run.

  GATED (exit 2 if any file fails one of these):

    frame drift       `scenes_bounding_rectangle` includes pyramid layers;
                       `..._no_pyramid` does not. If their origins ever differ,
                       or the two report different scenes at all, every stored
                       ROI coordinate is anchored to the wrong frame.
    bit depth          `pixel_types` reports the container, not the sensor.
                       ComponentBitCount must be present at the image level,
                       and every channel's own ComponentBitCount must agree
                       with it - a stage that reads only the image-level count
                       would otherwise get the wrong clip ceiling for a channel
                       that disagrees.
    unreadable file     any exception opening or inspecting a file.
    no files found       an empty source directory is not "zero problems".

  REPORTED, NOT GATED (true of this dataset, which later stages must handle):

    scene overlap      Scene bounding rectangles may overlap even where their
                        layer-0 subblocks do not. Where they do, a read that
                        does not pass `scene=` composites a neighbouring
                        section's tissue into the array. On this dataset: 219
                        of 222 files, 87% of scenes - gating on this would make
                        the stage permanently red. See
                        docs/czi-reading-audit.md finding 1; later tasks make
                        the reader respect it.
    pyramid levels      A read at zoom < 1 is served from a stored pyramid
                        layer, not a fresh resample of layer 0. Clipping
                        measured on such a read is diluted by whatever
                        averaging produced that layer.
    strip maxima        A native-resolution (zoom=1.0), per-channel sample of
                        the top STRIP_ROWS rows of the largest scene - a strip,
                        not the whole scene - checked against the nominal
                        ceiling and against the signature of a sensor shallower
                        than ComponentBitCount declares.
    bit count range     `BitCountRange` in the display settings is a second,
                        independent statement of the sensor depth. Compared
                        against ComponentBitCount and reported when the two
                        disagree, but not gated: it is a display setting, so a
                        disagreement is metadata worth a human's eye rather
                        than something that breaks a read.

Run:  work/appenv/Scripts/python.exe scripts/00d_czi_selftest.py
      ... --limit 20            check only the first 20 files
      ... --pixels 6            also sample N files, spread across the
                                 dataset, for observed maxima
"""

import argparse
import glob
import importlib.util
import json
import os
import xml.etree.ElementTree as ET

CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

SOURCE_DIR = CONFIG["source_dir"]
OUT_ROOT = CONFIG["out_root"]
QC_DIR = os.path.join(OUT_ROOT, "qc")
OUT_CSV = os.path.join(QC_DIR, "czi_selftest.csv")

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

# One strip off the TOP of the scene, not the whole scene: bounds the memory of
# a native-resolution (zoom=1.0) read regardless of how tall the scene is. It is
# a minority of the scene - about 27% on the files sampled here, less on taller
# ones - and it comes off the TOP edge, which on a slide scan is often bare
# glass. So every number derived from it is a lower bound on the scene value,
# not the scene value. Everything it feeds is named `strip_*` for that reason,
# and `summarise()` states the coverage per file so the bound is visible.
STRIP_ROWS = 4096

# A strip maximum only carries a shallow-bit signature if it lands within this
# many bits of the declared depth. Two reasons for a floor, both consequences of
# reading a strip rather than a scene. First, a background-only strip maxes out
# at a few hundred counts, and a maximum that happens to be 255 or 1023 is
# exactly 2**n - 1 by coincidence: without a floor the stage prints a shallow-bit
# signature for a perfectly healthy 16-bit sensor. Second, four bits brackets the
# depths that can physically hide inside a wider container: CZI offers Gray8 and
# Gray16 and nothing between, so a shallow sensor in a Gray16 file is a 12- or
# 14-bit camera, never a 4-bit one. The cost is that a genuine 8- or
# 10-bit-in-Gray16 file would not be flagged - its low strip_max_by_channel is
# still in the CSV, where it is conspicuous next to a nominal ceiling of 65535.
SHALLOW_MAX_BITS_BELOW = 4

KEYS = ["file", "error", "violations",
        "n_scenes", "overlapping_pairs", "scenes_in_overlap", "max_overlap_frac",
        "pyramid_levels",
        "frames_compared", "frame_key_mismatch", "origin_drift", "extent_drift",
        "image_bit_count", "channel_bit_counts", "channel_pixel_types",
        "bit_count_disagreement", "nominal_ceiling",
        "bitcount_ranges", "bitcount_range_mismatch",
        "shading", "online_stitching",
        "strip_rows", "strip_frac_of_scene",
        "strip_max_by_channel", "clipped_at_ceiling_by_channel",
        "shallow_signature_by_channel"]


# ---------------------------------------------------------------- pure geometry

def rect_overlap(a, b):
    """Intersection area in pixels of two (x, y, w, h) rectangles."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ox = min(ax + aw, bx + bw) - max(ax, bx)
    oy = min(ay + ah, by + bh) - max(ay, by)
    return ox * oy if ox > 0 and oy > 0 else 0


def scene_overlaps(rects):
    """Every overlapping pair in a {scene_index: (x, y, w, h)} mapping.

    Reported once per pair, as a fraction of the SMALLER scene: a 1000 px
    overlap means something quite different against a large scene than a small
    one, and the small one is the one at risk of being swamped.
    """
    hits = []
    items = sorted(rects.items())
    for i in range(len(items)):
        ka, a = items[i]
        for j in range(i + 1, len(items)):
            kb, b = items[j]
            px = rect_overlap(a, b)
            if px:
                smaller = min(a[2] * a[3], b[2] * b[3])
                # `if smaller` is belt-and-braces, not a case that reaches here:
                # a zero-area rectangle cannot intersect anything, so rect_overlap
                # would have returned 0 and `if px` would already have skipped it.
                hits.append({"a": ka, "b": kb, "px": px,
                             "frac_of_smaller": px / smaller if smaller else 0.0})
    return hits


def _find_anchored(root, anchored, loose):
    """`root.findtext(anchored)`, falling back to the unanchored `loose` path.

    Anchoring avoids matching the wrong element when the tag name repeats
    elsewhere in the document; the fallback means a differently-shaped file
    degrades to the old behaviour instead of reporting nothing.
    """
    val = root.findtext(anchored)
    return val if val is not None else root.findtext(loose)


def _findall_anchored(root, anchored, loose):
    found = root.findall(anchored)
    return found if found else root.findall(loose)


def bit_depth(raw_xml):
    """Sensor bit depth and the settings that would make the ceiling per-pixel."""
    root = ET.fromstring(raw_xml)

    def as_int(text):
        try:
            return int(text)
        except (TypeError, ValueError):
            return None

    channel_elems = _findall_anchored(
        root, "Metadata/Information/Image/Dimensions/Channels/Channel",
        ".//Dimensions/Channels/Channel")
    channels = [
        {"name": ch.get("Name"),
         "component_bit_count": as_int(ch.findtext("ComponentBitCount")),
         "pixel_type": ch.findtext("PixelType")}
        for ch in channel_elems
    ]
    image_bc = as_int(_find_anchored(
        root, "Metadata/Information/Image/ComponentBitCount",
        ".//Information/Image/ComponentBitCount"))
    shading = _find_anchored(
        root, "Metadata/HardwareSetting/SelectedShadingReferenceMode",
        ".//SelectedShadingReferenceMode")
    online_stitching = _find_anchored(
        root, "Metadata/HardwareSetting/IsOnlineStitchingEnabled",
        ".//IsOnlineStitchingEnabled")
    return {
        "image_component_bit_count": image_bc,
        "channels": channels,
        "shading": shading,
        "online_stitching": online_stitching,
        "bitcount_ranges": sorted({e.text for e in root.iter("BitCountRange") if e.text}),
    }


def nominal_ceiling(bits):
    """Highest value a right-aligned sample of this depth can hold.

    None for anything that is not a positive int - absent, zero, negative, or
    a value that was never parsed to a count in the first place. Task 3 reuses
    this, so the input contract is exact rather than "whatever int() accepts".

    Nominal, not observed: a sensor whose samples are left-shifted into a
    wider container clips below this. `--pixels` compares the observed maximum
    against it, and `shallow_bit_signature` catches the direction this check
    cannot: a maximum that never gets close to the declared ceiling at all.
    """
    if not isinstance(bits, int) or bits <= 0:
        return None
    return (1 << bits) - 1


def bit_count_disagreement(image_bc, channel_bcs):
    """None when every present ComponentBitCount agrees; else 'image=X channels=...'.

    `nominal_ceiling` is derived from the image-level count alone - every read
    site that clips against it is trusting that every channel shares it. This
    is the check that trust deserves.
    """
    if image_bc is None:
        return None
    present = [c for c in channel_bcs if c is not None]
    if not present or all(c == image_bc for c in present):
        return None
    return f"image={image_bc} channels={','.join(str(c) for c in channel_bcs)}"


def bitcount_range_disagreement(image_bc, ranges):
    """None when every `BitCountRange` matches the image ComponentBitCount.

    `BitCountRange` lives in the display settings and is a second, independent
    statement of the same fact the audit checks ComponentBitCount for. Comparing
    them is the whole value of recording it: agreement is corroboration, and a
    disagreement means the file contradicts itself about its own sensor depth.

    Reported, not gated. A display setting does not decide what any read
    returns, so a mismatch is a "look at this file" rather than a broken
    structural assumption, and gating on it would let a cosmetic metadata quirk
    turn a whole run red.
    """
    if image_bc is None or not ranges:
        return None
    odd = sorted({r for r in ranges if r != str(image_bc)})
    if not odd:
        return None
    return f"image={image_bc} BitCountRange={','.join(odd)}"


def shallow_bit_signature(observed_max, declared_bits):
    """The n < declared_bits such that observed_max == 2**n - 1, or None.

    `observed_max > nominal_ceiling(declared_bits)` catches a sensor reporting
    ABOVE its declared depth; it is unsatisfiable in the other, more likely
    direction. A maximum that lands exactly on a lower power-of-two-minus-one
    ceiling is the signature of a sensor whose true depth is n bits, stored
    inside a wider container than it fills.

    `observed_max` here is a STRIP maximum, so n is also floored at
    `declared_bits - SHALLOW_MAX_BITS_BELOW`; see that constant for why.
    """
    if not isinstance(declared_bits, int) or declared_bits <= 0:
        return None
    if observed_max is None or observed_max < 0:
        return None
    k = observed_max + 1
    if k > 0 and (k & (k - 1)) == 0:
        n = k.bit_length() - 1
        if declared_bits - SHALLOW_MAX_BITS_BELOW <= n < declared_bits and n > 0:
            return n
    return None


def pick_sample_indices(n_files, n_pixels):
    """`n_pixels` file indices spread evenly across `range(n_files)`.

    Evenly spaced rather than the first N, so a `--pixels` run samples across
    the whole dataset - every animal, not just whichever files sort first -
    for the same number of reads.
    """
    if n_pixels <= 0 or n_files <= 0:
        return set()
    n_pixels = min(n_pixels, n_files)
    return {(i * n_files) // n_pixels for i in range(n_pixels)}


# ---------------------------------------------------------------- per file

def _blank_row(name):
    row = {k: "" for k in KEYS}
    row["file"] = name
    return row


def inspect(path, pyczi, want_pixels):
    """Everything this stage checks about one CZI. Header-only unless want_pixels."""
    row = _blank_row(os.path.basename(path))
    with pyczi.open_czi(path) as d:
        sr = {int(k): (r.x, r.y, r.w, r.h)
              for k, r in d.scenes_bounding_rectangle.items()}
        sr0 = {int(k): (r.x, r.y, r.w, r.h)
               for k, r in d.scenes_bounding_rectangle_no_pyramid.items()}
        ov = scene_overlaps(sr)
        touched = set()
        for o in ov:
            touched.add(o["a"])
            touched.add(o["b"])
        common = set(sr) & set(sr0)

        row["n_scenes"] = len(sr)
        row["overlapping_pairs"] = len(ov)
        row["scenes_in_overlap"] = len(touched)
        row["max_overlap_frac"] = round(max((o["frac_of_smaller"] for o in ov), default=0.0), 5)
        row["frames_compared"] = len(common)
        row["frame_key_mismatch"] = int(set(sr) != set(sr0))
        row["origin_drift"] = sum(1 for k in common if sr[k][:2] != sr0[k][:2])
        # Recorded and summarised, but deliberately NOT gated: every coordinate
        # mapping in 05a_roi_geometry.py is anchored on the rectangle's ORIGIN,
        # so a few pixels of pyramid padding at the far edge misplaces nothing.
        # Audit finding 5 saw 0-28 px over the 496 scene rectangles it checked
        # by hand; this stage checks all 2572 and the worst is 40 px. Surfaced
        # in the FRAME DRIFT line so a dataset where it jumps gets noticed
        # rather than sitting unread in a CSV column.
        row["extent_drift"] = max(
            (max(abs(sr[k][2] - sr0[k][2]), abs(sr[k][3] - sr0[k][3])) for k in common),
            default=0)

        levels = {}

        def tally(_idx, info):
            ps = info.physicalSize
            if ps.w:
                f = round(info.logicalRect.w / ps.w)
                levels[f] = levels.get(f, 0) + 1
            return True

        d.enumerate_subblocks(tally)
        row["pyramid_levels"] = ",".join(str(k) for k in sorted(levels))

        bd = bit_depth(d.raw_metadata)
        image_bc = bd["image_component_bit_count"]
        channel_bcs = [c["component_bit_count"] for c in bd["channels"]]
        row["image_bit_count"] = image_bc
        row["channel_bit_counts"] = ",".join(str(c) for c in channel_bcs)
        row["channel_pixel_types"] = ",".join(str(c["pixel_type"]) for c in bd["channels"])
        row["bitcount_ranges"] = ",".join(bd["bitcount_ranges"])
        row["shading"] = bd["shading"]
        row["online_stitching"] = bd["online_stitching"]
        row["nominal_ceiling"] = nominal_ceiling(image_bc)
        disagreement = bit_count_disagreement(image_bc, channel_bcs)
        row["bit_count_disagreement"] = disagreement or ""
        row["bitcount_range_mismatch"] = bitcount_range_disagreement(
            image_bc, bd["bitcount_ranges"]) or ""

        violations = []
        if row["origin_drift"]:
            violations.append("origin_drift")
        if row["frame_key_mismatch"]:
            violations.append("frame_key_mismatch")
        if image_bc is None:
            violations.append("bit_count_missing")
        elif disagreement:
            violations.append("bit_count_disagreement")
        row["violations"] = ";".join(violations)

        if want_pixels and sr:
            import numpy as np
            largest = max(sr, key=lambda k: sr[k][2] * sr[k][3])
            x, y, w, h = sr[largest]
            strip_h = min(h, STRIP_ROWS)
            row["strip_rows"] = strip_h
            row["strip_frac_of_scene"] = round(strip_h / h, 5) if h else ""
            n_channels = len(bd["channels"]) or 1
            maxima, clipped, shallow = [], [], []
            for c_idx in range(n_channels):
                arr = np.asarray(d.read(roi=(x, y, w, strip_h), plane={"C": c_idx},
                                         scene=largest, zoom=1.0))
                obs_max = int(arr.max())
                ch_bits = channel_bcs[c_idx] if c_idx < len(channel_bcs) else image_bc
                ceiling = nominal_ceiling(ch_bits) if ch_bits is not None else row["nominal_ceiling"]
                n_at_ceiling = int((arr == ceiling).sum()) if ceiling is not None else 0
                sig = shallow_bit_signature(obs_max, ch_bits)
                maxima.append(str(obs_max))
                clipped.append(str(n_at_ceiling))
                shallow.append(str(sig) if sig is not None else "")
                del arr
            row["strip_max_by_channel"] = ",".join(maxima)
            row["clipped_at_ceiling_by_channel"] = ",".join(clipped)
            row["shallow_signature_by_channel"] = ",".join(shallow)
    return row


def build_error_row(name, exc):
    """The row for a file that raised. Always a full row, never a bare stdout line -
    the CSV row count must equal the file count, or an all-failed run looks like a
    healthy empty one to app/stages.py's existence-only `done()`.
    """
    row = _blank_row(name)
    row["error"] = repr(exc)[:200]
    row["violations"] = "error"
    return row


# ---------------------------------------------------------------- summary

def summarise(rows):
    """Human-readable report lines and the process exit code for these rows.

    Structural violations - an unreadable file, drifted or mismatched frames, a
    missing or self-contradictory bit count - make this 2: a broken assumption
    every pixel-reading stage relies on. Scene overlap, pyramid levels and
    observed maxima are properties of a healthy dataset, not defects, so they
    are always reported but never change the exit code.
    """
    lines = []
    if not rows:
        lines.append("No CZIs were found - nothing to check.")
        return lines, 2

    error_rows = [r for r in rows if r["error"]]
    ok_rows = [r for r in rows if not r["error"]]
    violation_rows = [r for r in ok_rows if r["violations"]]

    if ok_rows:
        with_ov = [r for r in ok_rows if r["overlapping_pairs"]]
        scenes = sum(r["n_scenes"] for r in ok_rows)
        in_ov = sum(r["scenes_in_overlap"] for r in ok_rows)
        lines.append(f"SCENE OVERLAP   {len(with_ov)}/{len(ok_rows)} files, "
                      f"{in_ov}/{max(scenes, 0)} scenes "
                      f"({100 * in_ov / max(scenes, 1):.1f}%), "
                      f"worst {max((r['max_overlap_frac'] for r in ok_rows), default=0.0):.1%} "
                      f"of the smaller scene")
        if with_ov:
            lines.append("                -> reads must pass scene=; "
                          "see docs/czi-reading-audit.md finding 1")

        levels = sorted({int(v) for r in ok_rows for v in r["pyramid_levels"].split(",") if v})
        lines.append(f"PYRAMID         levels seen: {levels}")

        lines.append(f"FRAME DRIFT     frames compared: "
                      f"{sum(r['frames_compared'] for r in ok_rows)}, "
                      f"origin drift: {sum(r['origin_drift'] for r in ok_rows)}, "
                      f"key mismatches: "
                      f"{sum(1 for r in ok_rows if r['frame_key_mismatch'])}, "
                      f"worst extent drift: "
                      f"{max((r['extent_drift'] or 0 for r in ok_rows), default=0)} px "
                      f"(not gated - only the origin anchors coordinates)")

        ceilings = sorted({r["nominal_ceiling"] for r in ok_rows if r["nominal_ceiling"] is not None})
        bit_counts = sorted({r["image_bit_count"] for r in ok_rows if r["image_bit_count"] is not None})
        lines.append(f"CEILING         nominal {ceilings} from ComponentBitCount {bit_counts}")
        shadings = sorted({r["shading"] for r in ok_rows if r["shading"] is not None})
        stitching = sorted({r["online_stitching"] for r in ok_rows if r["online_stitching"] is not None})
        lines.append(f"                shading {shadings}, online stitching {stitching}")
        range_rows = [r for r in ok_rows if r["bitcount_range_mismatch"]]
        with_ranges = [r for r in ok_rows if r["bitcount_ranges"]]
        if range_rows:
            lines.append(f"                !! BitCountRange disagrees with ComponentBitCount "
                          f"in {len(range_rows)} file(s) - reported, not gated:")
            for r in range_rows[:20]:
                lines.append(f"                   {r['file']}: {r['bitcount_range_mismatch']}")
        elif with_ranges:
            lines.append(f"                BitCountRange corroborates ComponentBitCount in all "
                          f"{len(with_ranges)} file(s) carrying one")

        maxima_rows = [r for r in ok_rows if r["strip_max_by_channel"]]
        if maxima_rows:
            lines.append(f"STRIP MAX       native resolution (zoom=1.0), per channel, over the top "
                          f"{STRIP_ROWS} rows at most")
            lines.append("                of the largest scene - a STRIP, not the whole scene, so "
                          "each max is a lower")
            lines.append("                bound on the scene max: a top edge of bare glass biases "
                          "it down. Coverage")
            lines.append("                of the scene is stated per file below.")
            for r in maxima_rows:
                sig = r["shallow_signature_by_channel"]
                frac = r["strip_frac_of_scene"]
                cover = f"{float(frac):.1%}" if frac != "" else "?"
                lines.append(f"                {r['file']}: max={r['strip_max_by_channel']}  "
                              f"at-ceiling={r['clipped_at_ceiling_by_channel']}  "
                              f"strip={r['strip_rows']} rows = {cover} of the scene"
                              + (f"  !! shallow-bit signature: {sig}" if sig.strip(",") else ""))

    if error_rows:
        lines.append("")
        lines.append(f"ERRORS          {len(error_rows)} file(s) raised while being inspected:")
        for r in error_rows[:50]:
            lines.append(f"                !! {r['file']}: {r['error']}")

    if violation_rows:
        lines.append("")
        lines.append(f"VIOLATIONS      {len(violation_rows)} file(s) broke a structural assumption:")
        for r in violation_rows[:50]:
            lines.append(f"                !! {r['file']}: {r['violations']}")

    exit_code = 2 if (error_rows or violation_rows) else 0
    return lines, exit_code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pixels", type=int, default=0,
                    help="also read N files, spread across the dataset, "
                         "to compare observed maxima against the ceiling")
    args = ap.parse_args()

    from pylibCZIrw import czi as pyczi

    files = sorted(glob.glob(os.path.join(SOURCE_DIR, "*.czi")))
    if args.limit:
        files = files[:args.limit]
    print(f"{len(files)} CZIs in {SOURCE_DIR}")

    sample = pick_sample_indices(len(files), args.pixels)
    rows = []
    for i, path in enumerate(files):
        try:
            rows.append(inspect(path, pyczi, i in sample))
        except Exception as exc:  # noqa: BLE001 - one bad file must not kill the run
            rows.append(build_error_row(os.path.basename(path), exc))
        print(f"\r  {i + 1}/{len(files)}", end="")
    if files:
        print()

    os.makedirs(QC_DIR, exist_ok=True)
    IO.atomic_write_csv(OUT_CSV, rows, KEYS)
    print(f"  wrote {OUT_CSV}  ({len(rows)} rows)")
    print()

    lines, exit_code = summarise(rows)
    print("\n".join(lines))
    if exit_code:
        print(f"\n  !! self-test FAILED - exit {exit_code}")
    # RAISE, never return. app/runner.py:205 runs stages in-process as `mod.main()`
    # and treats any plain return as SUCCESS; it learns about failure only by
    # catching SystemExit. A returned exit code therefore gates the CLI and not
    # the GUI - and app/stages.py's `done()` is existence-only over a CSV this
    # function has already written, so the app would show the stage green on a
    # dataset that broke a structural assumption. That is the exact hazard this
    # gate exists to close.
    raise SystemExit(exit_code)


if __name__ == "__main__":
    # Bare call: main() raises SystemExit itself, on success as well as failure,
    # so both entry points get the same verdict from the same line of code.
    main()
