"""Stage 0d - self-test of the assumptions this pipeline makes about its CZIs.

Every stage that reads pixels assumes four things about the files. This stage
checks all four and writes the answers down, so that a later dataset which
breaks one of them fails loudly here instead of quietly in a figure.

  scene overlap   Scene bounding rectangles may overlap even where their
                  layer-0 subblocks may not. Where they do, a read that does
                  not pass `scene=` composites a neighbouring section's tissue
                  into the array. Measured on this dataset: 219 of 222 files,
                  87% of scenes. See docs/czi-reading-audit.md finding 1.

  pyramid levels  A read at zoom < 1 is served from a stored pyramid layer, not
                  from a fresh resample of layer 0. Clipping measured on such a
                  read is diluted by whatever averaging produced that layer.

  bit depth       `pixel_types` reports the container, not the sensor. The clip
                  ceiling follows ComponentBitCount, and is only 65535 because
                  every channel of every file here is genuinely 16-bit.

  frame drift     `scenes_bounding_rectangle` includes pyramid layers;
                  `..._no_pyramid` does not. If their origins ever differ, every
                  stored ROI coordinate is anchored to the wrong frame.

Run:  work/appenv/Scripts/python.exe scripts/00d_czi_selftest.py
      ... --limit 20            check only the first 20 files
      ... --pixels 6            also sample N files for observed maxima
"""

import argparse
import csv
import glob
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

KEYS = ["file", "n_scenes", "overlapping_pairs", "scenes_in_overlap",
        "max_overlap_frac", "pyramid_levels", "origin_drift", "extent_drift",
        "image_bit_count", "channel_bit_counts", "channel_pixel_types",
        "nominal_ceiling", "observed_max", "shading", "online_stitching"]


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
                hits.append({"a": ka, "b": kb, "px": px,
                             "frac_of_smaller": px / smaller if smaller else 0.0})
    return hits


def bit_depth(raw_xml):
    """Sensor bit depth and the settings that would make the ceiling per-pixel."""
    root = ET.fromstring(raw_xml)

    def as_int(text):
        try:
            return int(text)
        except (TypeError, ValueError):
            return None

    channels = [
        {"name": ch.get("Name"),
         "component_bit_count": as_int(ch.findtext("ComponentBitCount")),
         "pixel_type": ch.findtext("PixelType")}
        for ch in root.findall(".//Dimensions/Channels/Channel")
    ]
    return {
        "image_component_bit_count": as_int(root.findtext(".//Information/Image/ComponentBitCount")),
        "channels": channels,
        "shading": root.findtext(".//SelectedShadingReferenceMode"),
        "online_stitching": root.findtext(".//IsOnlineStitchingEnabled"),
        "bitcount_ranges": sorted({e.text for e in root.iter("BitCountRange") if e.text}),
    }


def nominal_ceiling(bits):
    """Highest value a right-aligned sample of this depth can hold.

    Nominal, not observed: a sensor whose samples are left-shifted into a wider
    container clips below this. `--pixels` checks the observed maximum against
    it and the report flags any file where the two disagree.
    """
    return (1 << int(bits)) - 1 if bits else None


# ---------------------------------------------------------------- per file

def inspect(path, pyczi, want_pixels):
    """Everything this stage checks about one CZI. Header-only unless want_pixels."""
    row = {"file": os.path.basename(path)}
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

        row["n_scenes"] = len(sr)
        row["overlapping_pairs"] = len(ov)
        row["scenes_in_overlap"] = len(touched)
        row["max_overlap_frac"] = round(max((o["frac_of_smaller"] for o in ov), default=0.0), 5)
        row["origin_drift"] = sum(1 for k in sr if k in sr0 and sr[k][:2] != sr0[k][:2])
        row["extent_drift"] = max(
            (max(abs(sr[k][2] - sr0[k][2]), abs(sr[k][3] - sr0[k][3]))
             for k in sr if k in sr0), default=0)

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
        row["image_bit_count"] = bd["image_component_bit_count"]
        row["channel_bit_counts"] = ",".join(
            str(c["component_bit_count"]) for c in bd["channels"])
        row["channel_pixel_types"] = ",".join(str(c["pixel_type"]) for c in bd["channels"])
        row["shading"] = bd["shading"]
        row["online_stitching"] = bd["online_stitching"]
        row["nominal_ceiling"] = nominal_ceiling(bd["image_component_bit_count"])

        row["observed_max"] = ""
        if want_pixels and sr:
            import numpy as np
            s = sorted(sr)[0]
            x, y, w, h = sr[s]
            a = d.read(roi=(x, y, w, h), plane={"C": 0}, scene=s, zoom=0.125)
            row["observed_max"] = int(np.asarray(a).max())
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pixels", type=int, default=0,
                    help="also read N files to compare observed max against the ceiling")
    args = ap.parse_args()

    from pylibCZIrw import czi as pyczi

    files = sorted(glob.glob(os.path.join(SOURCE_DIR, "*.czi")))
    if args.limit:
        files = files[:args.limit]
    print(f"{len(files)} CZIs in {SOURCE_DIR}")

    rows, failures = [], []
    for n, path in enumerate(files, 1):
        try:
            rows.append(inspect(path, pyczi, n <= args.pixels))
        except Exception as exc:  # noqa: BLE001 - one bad file must not kill the run
            failures.append((os.path.basename(path), repr(exc)[:120]))
        print(f"\r  {n}/{len(files)}", end="")
    print()

    os.makedirs(QC_DIR, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=KEYS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {OUT_CSV}  ({len(rows)} rows)")

    if not rows:
        return
    with_ov = [r for r in rows if r["overlapping_pairs"]]
    scenes = sum(r["n_scenes"] for r in rows)
    in_ov = sum(r["scenes_in_overlap"] for r in rows)
    print()
    print(f"SCENE OVERLAP   {len(with_ov)}/{len(rows)} files, "
          f"{in_ov}/{scenes} scenes ({100 * in_ov / max(scenes, 1):.1f}%), "
          f"worst {max(r['max_overlap_frac'] for r in rows):.1%} of the smaller scene")
    if with_ov:
        print("                -> reads must pass scene=; see docs/czi-reading-audit.md finding 1")
    print(f"PYRAMID         levels seen: "
          f"{sorted({v for r in rows for v in r['pyramid_levels'].split(',') if v})}")
    print(f"FRAME DRIFT     scenes whose origin differs between frames: "
          f"{sum(r['origin_drift'] for r in rows)} (must be 0)")
    ceilings = sorted({r["nominal_ceiling"] for r in rows})
    print(f"CEILING         nominal {ceilings} from ComponentBitCount "
          f"{sorted({r['image_bit_count'] for r in rows})}")
    print(f"                shading {sorted({r['shading'] for r in rows})}, "
          f"online stitching {sorted({r['online_stitching'] for r in rows})}")
    obs = [r for r in rows if r["observed_max"] != ""]
    for r in obs:
        flag = "" if r["observed_max"] <= r["nominal_ceiling"] else "  !! ABOVE CEILING"
        print(f"                {r['file']}: observed max {r['observed_max']}{flag}")
    for name, exc in failures:
        print(f"  !! {name}: {exc}")


if __name__ == "__main__":
    main()
