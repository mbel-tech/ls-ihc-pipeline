# CZI Reading Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the ten defects in `docs/czi-reading-audit.md`, staged so the seven that move no published number land first and the three that do are gated behind a measured decision.

**Architecture:** Stage A fixes hygiene and adds the recorded provenance the later stages depend on, changing no output value. Stage B is a single probe that measures how many curated sections would have their ROI geometry shift once the `scene=` fix lands — the number that decides how Stage C is done. Stage C applies the three number-changing fixes together, each with a before/after diff against the preserved current CSVs.

**Tech Stack:** Python 3.13 in `work/appenv`, pylibCZIrw 6.1.0, numpy, Pillow. Tests are plain scripts under `tests/test_*.py`, auto-discovered by `bash tests/run.sh`, using the repo's `chk(label, got, want)` / `fails` counter convention and exiting non-zero on failure.

---

## DANGER — `--force` with `--limit` truncates `focus.csv`

Found while executing Task 5, after the pattern had already been written into
four steps. **Do not run `01_overviews.py --limit N --force`.**

`export()` (`01_overviews.py:251-256`) loads the existing `focus.csv` into
`qc_rows` only when `force` is false. With `--force` it starts from an empty
list, `--limit N` stops it after N sections, and `write_qc` then *atomically
replaces* `focus.csv` with those N rows. On this dataset that turns 2572 rows
into 8. `focus.csv` feeds 01d, 01g, 04j, 04a and 05a.

The same trap applies to `01k_saturation_raw.py --force`.

Steps 5-4, 6-7, 9-5 and 11-4 as originally written all carried it. Each has been
replaced with one of:

- **in-process verification** — import the module and call the function under
  test directly, touching no output (the approach the operator's standing rule
  already requires for exploratory runs); or
- **a scratch `out_root`** — point `LS_CONFIG` at a temporary config whose
  `out_root` is a scratch directory, copying in whatever inputs the stage needs.

Back up `focus.csv` before any run that writes it, regardless.

## Preconditions

- Work on a branch off `quantify-the-marker`, not on it directly.
- `scripts/04l_roi_curator.py` is already modified and `tests/polygon.test.js` is already untracked in the working tree. **Every commit in this plan uses explicit `git add <paths>`** so those are never swept in.
- The interpreter is `work/appenv/Scripts/python.exe`. Note that `run_all.sh:18` and `requirements-czi.txt` both name `work/czienv`, which does not exist — Task 7 fixes that.

- [ ] **Step 0: Create the branch**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git checkout -b czi-audit-fixes
```

Expected: `Switched to a new branch 'czi-audit-fixes'`

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `scripts/00d_czi_selftest.py` | **New.** Re-runs the audit's probes on any dataset: scene-rect overlap, pyramid levels, bit depth, and the Stage B reformat-impact measurement. | 1, 8 |
| `tests/test_czi_selftest.py` | **New.** Pure-geometry and XML-parsing tests for the above; dataset checks skip themselves. | 1 |
| `tests/test_czi_meta.py` | **New.** Tests `summarise()` against synthetic metadata XML. | 2 |
| `tests/test_read_scene.py` | **New.** Tests the shared read helper against a fake reader. | 4 |
| `scripts/czi_meta.py` | Adds `component_bit_count` and per-channel pixel type; anchors the instrument XPaths. | 2 |
| `scripts/00_manifest.py` | Records bit depth, per-channel pixel type and the derived clip ceiling per file. | 3 |
| `scripts/01_overviews.py` | Shared `read_scene()` gains a pixel-type assertion and a `scene=` parameter; ceiling comes from the manifest; the scene rectangle is recorded into `focus.csv`; the two pyramid claims are corrected. | 4, 5, 6, 7, 9 |
| `scripts/01k_saturation_raw.py` | Ceiling from the manifest; native-resolution tiled clipping; coverage denominator. | 5, 9, 10, 11 |
| `scripts/05a_roi_geometry.py` | Prefers the recorded scene rectangle over re-deriving it. | 6, 9 |
| `scripts/05c_detect_rois.py` | Uses the shared helper and passes `scene=`. | 4, 9 |
| `scripts/01e_tile_geometry.py` | Pyramid detection by `!=` rather than integer division. | 7 |
| `app/stages.py` | Registers `00d` so `tests/test_stages.py` passes. | 1 |

---

# Stage A — no published number moves

## Task 1: The audit's probes as a repeatable QC stage

**Files:**
- Create: `scripts/00d_czi_selftest.py`
- Create: `tests/test_czi_selftest.py`
- Modify: `app/stages.py` (stage list)

- [ ] **Step 1: Write the failing test**

Create `tests/test_czi_selftest.py`:

```python
"""The CZI self-test's geometry and metadata parsing.

The pure functions are checked here; anything needing the 222 CZIs skips itself
with a note, so this suite still runs on a machine with the repo and no images.

Run:  python tests/test_czi_selftest.py
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

_spec = importlib.util.spec_from_file_location(
    "st", os.path.join(SCRIPTS, "00d_czi_selftest.py"))
ST = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ST)

fails = 0


def chk(label, got, want):
    global fails
    ok = str(got) == str(want)
    print(f"{'ok  ' if ok else 'FAIL'} {label:58} {'' if ok else f'{got!r} != {want!r}'}")
    if not ok:
        fails += 1


# --- rect_overlap: (x, y, w, h) tuples, area in pixels -----------------------
chk("disjoint rects overlap 0", ST.rect_overlap((0, 0, 10, 10), (20, 20, 5, 5)), 0)
chk("edge-touching rects overlap 0", ST.rect_overlap((0, 0, 10, 10), (10, 0, 10, 10)), 0)
chk("full containment is the inner area", ST.rect_overlap((0, 0, 10, 10), (2, 2, 3, 4)), 12)
chk("partial overlap", ST.rect_overlap((0, 0, 10, 10), (8, 5, 10, 10)), 10)
chk("negative origins work", ST.rect_overlap((-10, -10, 10, 10), (-5, -5, 10, 10)), 25)
chk("order does not matter",
    ST.rect_overlap((8, 5, 10, 10), (0, 0, 10, 10)),
    ST.rect_overlap((0, 0, 10, 10), (8, 5, 10, 10)))

# --- scene_overlaps: pairs, each reported once ------------------------------
rects = {0: (0, 0, 100, 100), 1: (90, 0, 100, 100), 2: (500, 500, 10, 10)}
ov = ST.scene_overlaps(rects)
chk("one overlapping pair found", len(ov), 1)
chk("pair is (0, 1)", (ov[0]["a"], ov[0]["b"]), (0, 1))
chk("overlap area", ov[0]["px"], 1000)
chk("fraction is of the smaller scene", round(ov[0]["frac_of_smaller"], 4), 0.1)
chk("no overlaps in a disjoint set", ST.scene_overlaps({0: (0, 0, 5, 5), 1: (9, 9, 5, 5)}), [])

# --- bit_depth: parsed out of the metadata XML ------------------------------
XML = """<ImageDocument><Metadata><Information><Image>
  <ComponentBitCount>16</ComponentBitCount>
  <Dimensions><Channels>
    <Channel Name="DAPI"><ComponentBitCount>16</ComponentBitCount><PixelType>Gray16</PixelType></Channel>
    <Channel Name="AF568"><ComponentBitCount>14</ComponentBitCount><PixelType>Gray16</PixelType></Channel>
  </Channels></Dimensions>
</Image></Information>
<DisplaySetting><Channels>
  <Channel><BitCountRange>16</BitCountRange></Channel>
</Channels></DisplaySetting>
<HardwareSetting><SelectedShadingReferenceMode>None</SelectedShadingReferenceMode>
  <IsOnlineStitchingEnabled>false</IsOnlineStitchingEnabled></HardwareSetting>
</Metadata></ImageDocument>"""

bd = ST.bit_depth(XML)
chk("image-level bit count", bd["image_component_bit_count"], 16)
chk("two channels parsed", len(bd["channels"]), 2)
chk("channel 0 name", bd["channels"][0]["name"], "DAPI")
chk("channel 1 bit count", bd["channels"][1]["component_bit_count"], 14)
chk("channel 1 pixel type", bd["channels"][1]["pixel_type"], "Gray16")
chk("shading mode", bd["shading"], "None")
chk("online stitching", bd["online_stitching"], "false")
chk("bitcount ranges", bd["bitcount_ranges"], ["16"])

# --- nominal_ceiling --------------------------------------------------------
chk("16 bits -> 65535", ST.nominal_ceiling(16), 65535)
chk("14 bits -> 16383", ST.nominal_ceiling(14), 16383)
chk("12 bits -> 4095", ST.nominal_ceiling(12), 4095)
chk("missing bit count -> None", ST.nominal_ceiling(None), None)

# --- dataset checks skip when the images are not present --------------------
if not os.path.isdir(ST.SOURCE_DIR):
    print(f"note  source dir absent, dataset checks skipped ({ST.SOURCE_DIR})")

print()
print("FAILURES" if fails else "ALL PASS")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_czi_selftest.py
```

Expected: FAIL — `FileNotFoundError` on `scripts/00d_czi_selftest.py`, which does not exist yet.

- [ ] **Step 3: Write the implementation**

Create `scripts/00d_czi_selftest.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_czi_selftest.py
```

Expected: every line `ok`, final line `ALL PASS`, exit 0.

- [ ] **Step 5: Register the stage so test_stages.py still passes**

In `app/stages.py`, insert this entry immediately after the `Stage("verify", "00b  Verify extraction", ...)` entry:

```python
    Stage("czi_selftest", "00d  CZI self-test", "Ingest and QC",
          script="00d_czi_selftest.py", reader="pylibCZIrw",
          outputs=["qc/czi_selftest.csv"],
          needs=["manifest"],
          blurb="Checks the four assumptions every pixel stage makes about the "
                "CZIs: scene-rectangle overlap, stored pyramid levels, sensor "
                "bit depth, and whether the pyramid and layer-0 frames share an "
                "origin. See docs/czi-reading-audit.md."),
```

- [ ] **Step 6: Run the stage test**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_stages.py
```

Expected: `ALL PASS` (or the suite's existing pass line), exit 0. If it reports `00d_czi_selftest.py` as unlisted, the entry above was not added.

- [ ] **Step 7: Run the stage against the real data**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/00d_czi_selftest.py --pixels 4
```

Expected, reproducing the audit: `SCENE OVERLAP 219/222 files, 2241/2572 scenes (87.1%), worst 41.3%`; pyramid levels `['1','16','2','4','8']`; frame drift `0`; nominal ceiling `[65535]`; shading `['None']`; online stitching `['false']`; each observed max at or below 65535.

- [ ] **Step 8: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/00d_czi_selftest.py tests/test_czi_selftest.py app/stages.py && git commit -m "00d: CZI self-test for scene overlap, pyramid levels, bit depth and frame drift"
```

### Review outcome — the listing above was wrong in six places

Code review of the first commit found that the source listed in Step 3 was
transcribed byte-for-byte and is still defective. Recorded here because Task 8
extends this same file and would otherwise inherit the ambiguity.

**The root error: this task specified an *inventory* while the docstring promised
a *gate*.** Resolved as a gate, but only over the right things:

- **Exit 2 — a structural assumption is broken:** no files found; any per-file
  exception; `origin_drift > 0`; the two rectangle frames having different key
  sets; `ComponentBitCount` missing; image-level and per-channel bit counts
  disagreeing.
- **Exit 0, reported prominently — a dataset property the pipeline must handle:**
  scene overlap, pyramid levels, observed maxima. Scene overlap holds on 219 of
  222 files today, so gating on it would make the stage permanently red and break
  `run_all.sh`.

The other five: `main()` could never exit non-zero and an empty CSV marked the
stage green; a missing `ComponentBitCount` raised `TypeError` out of
`sorted({None, 65535})`; `origin_drift`/`extent_drift` silently passed on disjoint
keys; per-channel bit counts were recorded but never checked against the image
level, which is the check the stage exists for; and the CSV bypassed
`IO.atomic_write_csv`, breaking the invariant `tests/test_atomic_adoption.py`
enforces.

**The `observed_max` read as specified was a no-op that read gigabytes.** The data
is `uint16` and the 16-bit nominal ceiling is 65535, so `observed_max >
nominal_ceiling` is unsatisfiable; the informative direction — a maximum sitting
*below* the declared ceiling, the signature of a shallower sensor — is destroyed
because a `zoom=0.125` read is served from an averaged pyramid layer; and it
sampled `C: 0`, DAPI, the channel least likely to clip. Replaced with a single
native-resolution strip over both channels, recording the observed maximum and
the count of pixels exactly at the ceiling.

---

## Task 2: `czi_meta` records bit depth and per-channel pixel type

> **Carry forward from Task 1's review:** the `(1 << bits) - 1` derivation
> specified in Step 3 below has the same hardening gap — `bits=0` returns `None`
> indistinguishably from absent, a negative raises `ValueError: negative shift
> count`, and a non-numeric string raises. Guard it with
> `isinstance(bits, int) and bits > 0`. Task 3 reuses this derivation again.

**Files:**
- Modify: `scripts/czi_meta.py:64-122`
- Create: `tests/test_czi_meta.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_czi_meta.py`:

```python
"""What summarise() pulls out of a CZI metadata XML.

Synthetic XML rather than a real file: the point is the field mapping, and a
fixture that needs a 3 GB image cannot run on a machine without the dataset.
The instrument block is deliberately preceded by a hardware block carrying the
same tag names, because `.//` matches anywhere and takes the first hit.

Run:  python tests/test_czi_meta.py
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

_spec = importlib.util.spec_from_file_location(
    "cm", os.path.join(SCRIPTS, "czi_meta.py"))
CM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CM)

import xml.etree.ElementTree as ET                          # noqa: E402

fails = 0


def chk(label, got, want):
    global fails
    ok = str(got) == str(want)
    print(f"{'ok  ' if ok else 'FAIL'} {label:58} {'' if ok else f'{got!r} != {want!r}'}")
    if not ok:
        fails += 1


XML = """<ImageDocument><Metadata>
<HardwareSetting>
  <Objectives><Objective><NominalMagnification>99</NominalMagnification>
    <LensNA>9.9</LensNA></Objective></Objectives>
  <SelectedShadingReferenceMode>None</SelectedShadingReferenceMode>
  <IsOnlineStitchingEnabled>false</IsOnlineStitchingEnabled>
</HardwareSetting>
<Information>
  <Instrument>
    <Objectives><Objective><NominalMagnification>20</NominalMagnification>
      <LensNA>0.8</LensNA></Objective></Objectives>
    <Detectors><Detector><CameraName>Axiocam 705</CameraName></Detector></Detectors>
  </Instrument>
  <Image>
    <SizeX>1000</SizeX><SizeY>800</SizeY><SizeC>2</SizeC>
    <SizeS>3</SizeS><SizeM>70</SizeM>
    <PixelType>Gray16</PixelType>
    <ComponentBitCount>16</ComponentBitCount>
    <AcquisitionDateAndTime>2026-01-02T03:04:05.678Z</AcquisitionDateAndTime>
    <Dimensions>
      <Channels>
        <Channel Id="Channel:0" Name="DAPI">
          <ExposureTime>5000000</ExposureTime>
          <ComponentBitCount>16</ComponentBitCount>
          <PixelType>Gray16</PixelType>
        </Channel>
        <Channel Id="Channel:1" Name="AF568">
          <ExposureTime>1000000000</ExposureTime>
          <ComponentBitCount>14</ComponentBitCount>
          <PixelType>Gray16</PixelType>
        </Channel>
      </Channels>
      <S><Scenes>
        <Scene Index="0" Name="S1"><CenterPosition>10.5,20.5</CenterPosition>
          <ContourSize>100.0,200.0</ContourSize></Scene>
      </Scenes></S>
    </Dimensions>
  </Image>
</Information>
<Scaling><Items>
  <Distance Id="X"><Value>6.5E-07</Value></Distance>
  <Distance Id="Y"><Value>6.5E-07</Value></Distance>
</Items></Scaling>
</Metadata></ImageDocument>"""

s = CM.summarise(ET.fromstring(XML))

# --- fields that already existed must not have moved ------------------------
chk("size_x", s["size_x"], 1000)
chk("size_s", s["size_s"], 3)
chk("size_m", s["size_m"], 70)
chk("image pixel_type", s["pixel_type"], "Gray16")
chk("acquired truncated to seconds", s["acquired"], "2026-01-02T03:04:05")
chk("px_um_x from metres", round(s["px_um_x"], 3), 0.65)
chk("exposure ns -> ms", s["channels"][0]["exposure_ms"], 5.0)
chk("scene centre", s["scenes"][0]["center_x_um"], 10.5)

# --- new: bit depth ---------------------------------------------------------
chk("image component_bit_count", s["component_bit_count"], 16)
chk("channel 0 bit count", s["channels"][0]["component_bit_count"], 16)
chk("channel 1 bit count", s["channels"][1]["component_bit_count"], 14)
chk("nominal ceiling from image bits", s["clip_ceiling"], 65535)

# --- new: per-channel pixel type -------------------------------------------
chk("channel 0 pixel type", s["channels"][0]["pixel_type"], "Gray16")
chk("channel 1 pixel type", s["channels"][1]["pixel_type"], "Gray16")

# --- anchored XPaths take the instrument block, not the hardware block ------
chk("objective magnification is the instrument's", s["objective_mag"], "20")
chk("objective NA is the instrument's", s["objective_na"], "0.8")
chk("camera name found", s["camera"], "Axiocam 705")

# --- the loose fallback still works when there is no Instrument block -------
LOOSE = """<ImageDocument><Metadata><Information><Image>
  <Dimensions><Channels><Channel Name="DAPI"/></Channels></Dimensions>
</Image></Information>
<Objectives><Objective><NominalMagnification>10</NominalMagnification></Objective></Objectives>
</Metadata></ImageDocument>"""
loose = CM.summarise(ET.fromstring(LOOSE))
chk("fallback finds the loose objective", loose["objective_mag"], "10")
chk("missing bit count is None", loose["component_bit_count"], None)
chk("missing bit count gives no ceiling", loose["clip_ceiling"], None)

print()
print("FAILURES" if fails else "ALL PASS")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_czi_meta.py
```

Expected: FAIL on `component_bit_count`, `clip_ceiling`, per-channel `pixel_type`, and `objective_mag` (which currently returns `99` from the hardware block).

- [ ] **Step 3: Write the implementation**

In `scripts/czi_meta.py`, add these two helpers immediately after `_float_pair` (after line 61):

```python
def _int_or_none(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _first(root, *paths):
    """First non-empty match. Anchored paths are tried before loose ones.

    `.//` matches anywhere in the tree and `findtext` takes the first hit in
    document order, so a hardware-settings block that repeats a tag name can
    shadow the instrument block. Naming the anchored path first removes the
    ambiguity without breaking files that lack the anchor.
    """
    for p in paths:
        found = root.findtext(p)
        if found:
            return found
    return None
```

In the channel loop (currently lines 73-84), add the two new fields:

```python
    channels = []
    for ch in root.findall(".//Dimensions/Channels/Channel"):
        exposure_ns = ch.findtext("ExposureTime")
        channels.append(
            {
                "id": ch.get("Id"),
                "name": ch.get("Name"),
                "exposure_ms": float(exposure_ns) / 1e6 if exposure_ns else None,
                "excitation_nm": ch.findtext("ExcitationWavelength"),
                "emission_nm": ch.findtext("EmissionWavelength"),
                "contrast_method": ch.findtext("ContrastMethod"),
                # The container is Gray16 whatever the sensor did; this is the
                # sensor. A channel that clips does so at 2**bits - 1, not at
                # 65535, unless the two happen to coincide as they do here.
                "component_bit_count": _int_or_none(ch.findtext("ComponentBitCount")),
                "pixel_type": ch.findtext("PixelType"),
            }
        )
```

In the returned dict (currently lines 105-122), add `component_bit_count` and `clip_ceiling` after `pixel_type`, and replace the three loose instrument lookups:

```python
    bits = _int_or_none(txt(img + "ComponentBitCount"))
    return {
        "size_x": int(txt(img + "SizeX", 0)),
        "size_y": int(txt(img + "SizeY", 0)),
        "size_c": int(txt(img + "SizeC", 0)),
        "size_s": int(txt(img + "SizeS", 0)),
        "size_m": int(txt(img + "SizeM", 0)),
        "pixel_type": txt(img + "PixelType"),
        "component_bit_count": bits,
        # Nominal: the highest value a right-aligned sample of this depth holds.
        # 00d_czi_selftest.py checks it against the observed maximum.
        "clip_ceiling": (1 << bits) - 1 if bits else None,
        "acquired": (txt(img + "AcquisitionDateAndTime") or "")[:19],
        "px_um_x": float(px_x) * 1e6 if px_x else None,
        "px_um_y": float(px_y) * 1e6 if px_y else None,
        "objective_mag": _first(root,
                                ".//Information/Instrument/Objectives/Objective/NominalMagnification",
                                ".//Objectives/Objective/NominalMagnification"),
        "objective_na": _first(root,
                               ".//Information/Instrument/Objectives/Objective/LensNA",
                               ".//Objectives/Objective/LensNA"),
        "camera": _first(root,
                         ".//Information/Instrument/Detectors/Detector/CameraName",
                         ".//CameraName"),
        "shading_reference_mode": root.findtext(".//SelectedShadingReferenceMode"),
        "online_stitching": root.findtext(".//IsOnlineStitchingEnabled"),
        "channels": channels,
        "scenes": scenes,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_czi_meta.py
```

Expected: `ALL PASS`, exit 0.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/czi_meta.py tests/test_czi_meta.py && git commit -m "czi_meta: record ComponentBitCount and per-channel pixel type; anchor the instrument XPaths"
```

### Review outcome — the camera XPath above is wrong

Verified against real ZEN metadata during implementation. On these files
`Information/Instrument/Detectors/Detector` exists but carries **no**
`CameraName` child; the only one in the document is at
`Scaling/AutoScaling/CameraName`. So the anchored path listed in Step 3 never
matches and every file silently falls through to the loose `.//CameraName`.

The camera lookup takes three paths in order: the Instrument path first (so a
file that does populate it wins), then `.//Scaling/AutoScaling/CameraName`, then
the loose fallback. The objective anchoring is unaffected and is doing real work
— a real file carries seven `HardwareSetting/.../ChangerElements/Objective`
nodes.

Also settled here: `nominal_ceiling` is **duplicated** into `czi_meta.py` rather
than imported from `00d_czi_selftest.py`. `czi_meta.py` is the dependency-light
module — stdlib only, so it can run against a zip member — while `00d` is a
numbered stage script that has to be loaded through `importlib` and pulls in
numpy and pylibCZIrw. Importing a leaf stage from the foundational module would
invert the dependency. Both copies are pinned by tests.

---

## Task 3: The manifest carries the clip ceiling

**Files:**
- Modify: `scripts/00_manifest.py:478-500` (the `row` dict)

`_write_csv` derives its column list from the row dicts, so no separate key list needs updating.

- [ ] **Step 1: Add the fields**

In `scripts/00_manifest.py`, in the `row = {` literal, immediately after the `"pixel_type": info["pixel_type"],` line, insert:

```python
                "component_bit_count": info["component_bit_count"],
                # Every stage that asks "is this pixel clipped?" reads this
                # rather than a literal. It is 65535 on this dataset because
                # the sensor is genuinely 16-bit, not by assumption.
                "clip_ceiling": info["clip_ceiling"],
                "channel_pixel_types": "|".join(
                    str(c["pixel_type"]) for c in info["channels"]),
                "channel_bit_counts": "|".join(
                    str(c["component_bit_count"]) for c in info["channels"]),
```

- [ ] **Step 2: Verify the manifest still builds**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/00_manifest.py
```

Expected: `wrote D:\LS-analysis\manifest\manifest_files.csv` with the same row count as before, and no failures listed.

- [ ] **Step 3: Confirm the new columns are populated**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "import csv;r=list(csv.DictReader(open(r'D:\LS-analysis\manifest\manifest_files.csv',newline='',encoding='utf-8')));print(len(r),'rows');print(sorted({x['clip_ceiling'] for x in r}), sorted({x['channel_bit_counts'] for x in r}))"
```

Expected: `65535` as the only ceiling and `16|16` as the only bit-count pair.

- [ ] **Step 4: Run the full suite**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh
```

Expected: `ALL SUITES PASS`.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/00_manifest.py && git commit -m "00_manifest: record bit depth, per-channel pixel type and the derived clip ceiling"
```

---

## Task 4: The shared read helper asserts its pixel type and accepts a scene

**Files:**
- Modify: `scripts/01_overviews.py:153-157`
- Modify: `scripts/05c_detect_rois.py:421-423`
- Create: `tests/test_read_scene.py`

`scene=` defaults to `None`, which is the current behaviour exactly. Task 9 flips the call sites. Splitting it this way keeps this task free of any number change.

- [ ] **Step 1: Write the failing test**

Create `tests/test_read_scene.py`:

```python
"""The shared CZI read helper.

A fake reader stands in for pylibCZIrw: what matters is the arguments the helper
passes down and the shape it hands back, neither of which needs a real file.

Run:  python tests/test_read_scene.py
"""

import importlib.util
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

_spec = importlib.util.spec_from_file_location(
    "ov", os.path.join(SCRIPTS, "01_overviews.py"))
OV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(OV)

fails = 0


def chk(label, got, want):
    global fails
    ok = str(got) == str(want)
    print(f"{'ok  ' if ok else 'FAIL'} {label:58} {'' if ok else f'{got!r} != {want!r}'}")
    if not ok:
        fails += 1


class Rect:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


class FakeCzi:
    """Records the kwargs it was called with; returns pylibCZIrw's real shapes."""

    def __init__(self, pixel_types):
        self.pixel_types = pixel_types
        self.calls = []

    def read(self, roi=None, plane=None, scene=None, zoom=None):
        self.calls.append({"roi": roi, "plane": plane, "scene": scene, "zoom": zoom})
        depth = 3 if self.pixel_types[plane["C"]].startswith("Bgr") else 1
        return np.zeros((7, 5, depth), dtype=np.uint16)


rect = Rect(-100, 20, 5, 7)

# --- grayscale: 3-D in, 2-D out --------------------------------------------
fake = FakeCzi({0: "Gray16", 1: "Gray16"})
out = OV.read_scene(fake, rect, 1, 0.125)
chk("returns 2-D", out.ndim, 2)
chk("shape is (y, x)", out.shape, (7, 5))
chk("roi taken from the rect, origin included", fake.calls[0]["roi"], (-100, 20, 5, 7))
chk("plane names the channel", fake.calls[0]["plane"], {"C": 1})
chk("zoom passed through", fake.calls[0]["zoom"], 0.125)
chk("scene defaults to None", fake.calls[0]["scene"], None)

# --- scene is forwarded when given -----------------------------------------
OV.read_scene(fake, rect, 0, 1.0, scene=4)
chk("scene forwarded", fake.calls[1]["scene"], 4)

# --- a colour channel raises rather than silently returning 3-D -------------
colour = FakeCzi({0: "Bgr24"})
try:
    OV.read_scene(colour, rect, 0, 1.0)
    chk("colour channel raises", "no exception", "ValueError")
except ValueError as exc:
    chk("colour channel raises ValueError", "Bgr24" in str(exc), True)

# --- a 1-pixel-wide read keeps both spatial axes ----------------------------
class ThinCzi(FakeCzi):
    def read(self, roi=None, plane=None, scene=None, zoom=None):
        self.calls.append({"roi": roi, "plane": plane, "scene": scene, "zoom": zoom})
        return np.zeros((9, 1, 1), dtype=np.uint16)


thin = OV.read_scene(ThinCzi({0: "Gray16"}), Rect(0, 0, 1, 9), 0, 1.0)
chk("1 px wide read stays 2-D", thin.shape, (9, 1))

print()
print("FAILURES" if fails else "ALL PASS")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_read_scene.py
```

Expected: FAIL — `read_scene() got an unexpected keyword argument 'scene'`, and the colour and 1-px checks fail because `np.squeeze` collapses them.

- [ ] **Step 3: Write the implementation**

Replace `scripts/01_overviews.py:153-157` entirely with:

```python
def read_scene(czidoc, rect, channel, zoom, scene=None):
    """One scene, one channel, at the requested zoom, as 2-D uint16.

    `read` returns [y, x, 1] for a grayscale channel and [y, x, 3] for a colour
    one, so indexing the last axis is the shape-safe form. `np.squeeze` was used
    here before and would silently hand a 3-D array to 2-D code on a colour
    channel, and would drop a spatial axis on a one-pixel-wide ROI.

    `scene` restricts the composite to one scene's subblocks. Without it every
    scene contributes, and scene bounding rectangles overlap on 87% of the
    sections here - see docs/czi-reading-audit.md finding 1.
    """
    pixel_type = czidoc.pixel_types.get(channel, "")
    if not str(pixel_type).startswith("Gray"):
        raise ValueError(
            f"channel {channel} is {pixel_type!r}; read_scene returns 2-D grayscale only")
    arr = czidoc.read(roi=(rect.x, rect.y, rect.w, rect.h),
                      plane={"C": channel}, scene=scene, zoom=zoom)
    return arr[..., 0]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_read_scene.py
```

Expected: `ALL PASS`, exit 0.

- [ ] **Step 5: Route 05c through the same helper**

`05c_detect_rois.py:49-51` already loads `05a_roi_geometry.py` as `G5`, but `05a` does
not itself load `01_overviews`, so `G5.OV` does not exist. 05c loads it directly.

In `scripts/05c_detect_rois.py`, immediately after the existing `G5` loader block
(after line 51), add:

```python
_ovspec = importlib.util.spec_from_file_location(
    "_ov", os.path.join(_HERE, "01_overviews.py"))
OV = importlib.util.module_from_spec(_ovspec)
_ovspec.loader.exec_module(OV)


class _Rect:
    """The four fields read_scene wants, for a box that did not come from libCZI."""

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h
```

Then replace lines 421-423:

```python
                dapi = np.squeeze(doc.read(roi=roi, plane={"C": DAPI_C})).astype(np.float32)
                mark = np.squeeze(doc.read(roi=roi, plane={"C": MARK_C})).astype(np.float32)
                if dapi.ndim != 2 or dapi.shape != mark.shape:
```

with:

```python
                box = _Rect(x0, y0, bw, bh)
                dapi = OV.read_scene(doc, box, DAPI_C, 1.0).astype(np.float32)
                mark = OV.read_scene(doc, box, MARK_C, 1.0).astype(np.float32)
                if dapi.shape != mark.shape:
```

The `roi = (x0, y0, bw, bh)` line above them becomes unused; delete it. The dropped
`dapi.ndim != 2` guard is now redundant — `read_scene` raises on a non-grayscale
channel rather than letting the section be silently skipped.

- [ ] **Step 6: Verify 05c still imports and runs its help**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/05c_detect_rois.py --help
```

Expected: the argparse help text, exit 0. An `ImportError` or `NameError` here means the import block above was not added.

- [ ] **Step 7: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/01_overviews.py scripts/05c_detect_rois.py tests/test_read_scene.py && git commit -m "read_scene: assert grayscale and index the last axis; accept scene=; 05c uses the shared helper"
```

---

## Task 5: The clip ceiling comes from the manifest

**Files:**
- Modify: `scripts/01_overviews.py` (new loader; lines 295-296 and 340)
- Modify: `scripts/01k_saturation_raw.py:73` and `:99-104`

- [ ] **Step 1: Add the loader to `01_overviews.py`**

Immediately after `load_tile_fields()` (after line 176), add:

```python
def load_ceilings():
    """file name -> clip ceiling, from the manifest.

    Recorded rather than assumed: 65535 is right here only because every channel
    of every file is genuinely 16-bit. A manifest written before 00_manifest
    recorded the column falls back to 65535 with a warning, so an old output
    directory still runs.
    """
    path = os.path.join(OUT_ROOT, "manifest", "manifest_files.csv")
    out = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    out[r["file"]] = int(r["clip_ceiling"])
                except (KeyError, TypeError, ValueError):
                    continue
    if not out:
        print("  !! no clip_ceiling in the manifest - falling back to 65535; "
              "re-run 00_manifest.py to record it")
    return out


def ceiling_for(ceilings, fname):
    return ceilings.get(fname, 65535)
```

- [ ] **Step 2: Use it in the export pass**

In `scripts/01_overviews.py`, in `export()`, add one line immediately after `marker = rows[0]["marker_channel"]`:

```python
        ceiling = ceiling_for(ceilings, fname)
```

Change the `export` signature from `def export(scenes, fields, ranges, zoom, limit, force):` to:

```python
def export(scenes, fields, ranges, zoom, limit, force, ceilings):
```

and its call site in `main()` from `export(scenes, fields, ranges, zoom, args.limit, args.force)` to:

```python
    export(scenes, fields, ranges, zoom, args.limit, args.force, load_ceilings())
```

Then replace the three literals. Lines 295-296 become:

```python
                    sat_mark_raw = float((mark_raw >= ceiling).mean())
                    sat_dapi_raw = float((dapi_raw >= ceiling).mean())
```

and line 340 becomes:

```python
                        "saturated_fraction": f"{float((mark >= ceiling).mean()):.6f}",
```

- [ ] **Step 3: Use it in `01k_saturation_raw.py`**

Replace line 73:

```python
CEILING = 65535
```

with:

```python
# Fallback only. The real value per file comes from the manifest via
# OV.ceiling_for(); see docs/czi-reading-audit.md finding 4.
CEILING = 65535
```

Change `measure()` to take the ceiling rather than close over the module constant. Replace lines 95-107 with:

```python
def measure(czidoc, rect, fields, zoom, want_mask, ceiling=CEILING):
    """Raw clipping for both channels, and the corrected figure for comparison."""
    dapi_raw = OV.read_scene(czidoc, rect, 0, zoom)
    mark_raw = OV.read_scene(czidoc, rect, 1, zoom)
    clipped = mark_raw >= ceiling
    corrected = OV.apply_tile_field(mark_raw, fields.get(1), 1 / zoom)
    return {
        "raw": float(clipped.mean()),
        "dapi_raw": float((dapi_raw >= ceiling).mean()),
        "corrected": float((corrected >= ceiling).mean()),
        "shape": mark_raw.shape,
        "mask": clipped if want_mask else None,
    }
```

In `main()`, immediately after `fields = OV.load_tile_fields()` add:

```python
    ceilings = OV.load_ceilings()
```

and at the `measure` call site (line 254), pass it:

```python
                    m = measure(czidoc, rects[s], fields, zoom, want,
                                OV.ceiling_for(ceilings, fname))
```

In `native_sample()`, replace the two `>= CEILING` comparisons at lines 146 and 150 with a ceiling looked up per file. Immediately after `path = os.path.join(SOURCE_DIR, fname)` add:

```python
        ceiling = OV.ceiling_for(ceilings, fname)
```

change the signature to `def native_sample(scenes, n, ceilings, seed=20260901):`, its call site in `main()` to `native_sample(scenes, args.native_sample, ceilings)`, and the two comparisons to `>= ceiling`.

- [ ] **Step 4: Verify in-process — do NOT run the stage**

This task is a pure refactor: the same 65535, now sourced from the manifest
rather than three literals. It needs no stage run, and running one would trip
the truncation trap documented at the top of this plan.

Verify by importing the module and calling the new functions against the real
manifest:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import importlib.util
s=importlib.util.spec_from_file_location('ov','scripts/01_overviews.py')
OV=importlib.util.module_from_spec(s); s.loader.exec_module(OV)
c=OV.load_ceilings()
print(len(c),'files carry a ceiling')
print('distinct ceilings:',sorted(set(c.values())))
print('known file      ->',OV.ceiling_for(c,'LS105_1a.czi'))
print('unknown file    ->',OV.ceiling_for(c,'NOT_A_FILE.czi'),'(must be 65535)')
print('empty mapping   ->',OV.ceiling_for({},'anything.czi'),'(must be 65535)')"
```

Expected: 222 files, `[65535]` as the only distinct ceiling, 65535 for the known
file, and 65535 from both fallback paths.

Then confirm the literals are gone:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && grep -n "65535" scripts/01_overviews.py scripts/01k_saturation_raw.py
```

Expected: the only remaining occurrences are the documented `CEILING = 65535`
fallback in `01k`, the `load_ceilings` fallback and its warning in
`01_overviews.py`, and the `np.clip(out, 0, 65535)` in `apply_tile_field` — which
is a dtype bound on the uint16 container, not a clipping threshold, and must NOT
be changed. No comparison of the form `>= 65535` may remain.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/01_overviews.py scripts/01k_saturation_raw.py && git commit -m "01/01k: clip ceiling read from the manifest instead of three literals"
```

---

## Task 6: The scene rectangle is recorded, not re-derived

**Files:**
- Modify: `scripts/01_overviews.py:69-74` (QC_KEYS) and the `qc_rows.append` block
- Modify: `scripts/05a_roi_geometry.py:308-318`
- Modify: `tests/test_roi_geometry.py` (add a check)

- [ ] **Step 1: Widen QC_KEYS**

In `scripts/01_overviews.py`, replace the `QC_KEYS` list at lines 69-74 with:

```python
QC_KEYS = ["scene_uid", "file", "animal", "slide", "variant", "marker_channel",
           "scene_index", "section_order", "width", "height", "um_px",
           # The frame every stored ROI coordinate is anchored to. Recorded
           # because 05a used to recover it by reopening the CZI, which silently
           # re-anchors everything if the library or the property ever changes.
           "rect_x", "rect_y", "rect_w", "rect_h", "zoom", "rect_source",
           "tissue_threshold", "tissue_fraction", "tissue_area_mm2", "tissue_mean",
           "background_mean", "contrast", "focus_score", "saturated_fraction",
           "saturated_fraction_raw", "saturated_fraction_dapi_raw",
           "tilefield_applied", "reader"]

# Which property the rectangle came from. Stored per row so a future switch to
# the layer-0 frame is visible in the data rather than inferred from a date.
RECT_SOURCE = "scenes_bounding_rectangle"
```

- [ ] **Step 2: Record the rectangle**

In the `qc_rows.append({` block, immediately after the `"width": w, "height": h, "um_px": f"{um_px:.2f}",` line, insert:

```python
                        "rect_x": rects[s].x, "rect_y": rects[s].y,
                        "rect_w": rects[s].w, "rect_h": rects[s].h,
                        "zoom": f"{zoom:.6f}", "rect_source": RECT_SOURCE,
```

- [ ] **Step 3: Write the failing test**

Append to `tests/test_roi_geometry.py`, immediately before its final summary/exit lines:

```python
# --- the recorded rectangle is preferred over re-deriving it ----------------
# scene_rects_recorded reads focus.csv; a section it does not know must return
# None so the caller falls back rather than inventing a frame.
import csv as _csv                                          # noqa: E402
import tempfile                                             # noqa: E402

_tmp = tempfile.mkdtemp()
_focus = os.path.join(_tmp, "focus.csv")
with open(_focus, "w", newline="", encoding="utf-8") as _fh:
    _w = _csv.DictWriter(_fh, fieldnames=["scene_uid", "file", "scene_index",
                                          "rect_x", "rect_y", "rect_w", "rect_h",
                                          "zoom", "rect_source"])
    _w.writeheader()
    _w.writerow({"scene_uid": "LSX_s01a_sc00", "file": "LSX_1a.czi", "scene_index": "0",
                 "rect_x": "-86292", "rect_y": "1836", "rect_w": "9392", "rect_h": "11232",
                 "zoom": "0.125000", "rect_source": "scenes_bounding_rectangle"})

_rec = G5.scene_rects_recorded(_focus)
chk("recorded rect keyed by file and scene", _rec[("LSX_1a.czi", 0)], (-86292, 1836, 9392, 11232))
chk("unknown section absent", ("LSY_1a.czi", 0) in _rec, False)
chk("negative origin survives the round trip", _rec[("LSX_1a.czi", 0)][0], -86292)

_empty = os.path.join(_tmp, "empty.csv")
with open(_empty, "w", newline="", encoding="utf-8") as _fh:
    _fh.write("scene_uid,file\n")
chk("a focus.csv without the columns yields nothing", G5.scene_rects_recorded(_empty), {})
chk("a missing focus.csv yields nothing",
    G5.scene_rects_recorded(os.path.join(_tmp, "nope.csv")), {})
```

- [ ] **Step 4: Run test to verify it fails**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_roi_geometry.py
```

Expected: FAIL — `AttributeError: module 'g5' has no attribute 'scene_rects_recorded'`.

- [ ] **Step 5: Write the implementation**

In `scripts/05a_roi_geometry.py`, add immediately before `scene_rects` (before line 308):

```python
def scene_rects_recorded(focus_csv=None):
    """(file, scene_index) -> (x, y, w, h), as recorded by the overview export.

    Preferred over reopening the CZI. The rectangle is the frame every stored
    ROI coordinate is anchored to, so recovering it from the library on demand
    means a library upgrade can move every ROI with nothing raised. Returns an
    empty mapping for a focus.csv written before the columns existed, and the
    caller falls back to `scene_rects`.
    """
    path = focus_csv or os.path.join(OUT_ROOT, "qc", "focus.csv")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                out[(r["file"], int(r["scene_index"]))] = (
                    int(r["rect_x"]), int(r["rect_y"]),
                    int(r["rect_w"]), int(r["rect_h"]))
            except (KeyError, TypeError, ValueError):
                continue
    return out
```

Then in the geometry build, replace the `rect_cache` lookup at lines 435-447 with a recorded-first version. Immediately before the loop that fills `rect_cache`, add:

```python
    recorded = scene_rects_recorded()
    if recorded:
        print(f"  scene rectangles: {len(recorded)} read from focus.csv")
```

and replace the body that resolves `rx, ry, rw, rh` with:

```python
        si = int(m["scene_index"])
        hit = recorded.get((czi, si))
        if hit is None:
            if czi not in rect_cache:
                path = os.path.join(CONFIG["source_dir"], czi)
                try:
                    rect_cache[czi] = scene_rects(path)
                except Exception as exc:                      # noqa: BLE001
                    rect_cache[czi] = {"_error": str(exc)}
            rects = rect_cache[czi]
            if "_error" in rects or si not in rects:
                skipped.append((uid, "no scene rectangle: "
                                + rects.get("_error", f"scene {si} absent")))
                continue
            hit = rects[si]
        rx, ry, rw, rh = hit
```

- [ ] **Step 6: Run test to verify it passes**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_roi_geometry.py
```

Expected: `ALL PASS`, exit 0.

- [ ] **Step 7: Confirm the recorded and re-derived rectangles agree**

Re-export a few sections so `focus.csv` carries the new columns, then check they match what the library returns:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/01_overviews.py --limit 8 --force && work/appenv/Scripts/python.exe -c "
import csv, importlib.util, os
s=importlib.util.spec_from_file_location('g5', r'scripts/05a_roi_geometry.py'); G=importlib.util.module_from_spec(s); s.loader.exec_module(G)
rec=G.scene_rects_recorded(); print(len(rec),'recorded')
bad=0
for (f,si),got in list(rec.items())[:8]:
    live=G.scene_rects(os.path.join(G.CONFIG['source_dir'],f))
    if live.get(si)!=got: bad+=1; print('MISMATCH',f,si,got,live.get(si))
print('mismatches:',bad)"
```

Expected: `mismatches: 0`.

- [ ] **Step 8: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/01_overviews.py scripts/05a_roi_geometry.py tests/test_roi_geometry.py && git commit -m "01/05a: record the scene rectangle in focus.csv and prefer it over re-deriving"
```

---

## Task 7: Correct the claims that are no longer true

**Files:**
- Modify: `scripts/01_overviews.py:15-18` and `:370`
- Modify: `scripts/01_overviews.py:25` (the czienv path)
- Modify: `scripts/01e_tile_geometry.py:94`
- Modify: `requirements.txt:13`, `README.md:33`, `scripts/run_all.sh:18-20`

- [ ] **Step 1: Correct the pyramid claim in the docstring**

In `scripts/01_overviews.py`, replace the `exactness` paragraph at lines 15-18:

```
  exactness    `zoom` is continuous, so sections come out at exactly 5.20 um/px
               instead of "nearest stored pyramid level", which is why
               tissue_area_mm2 previously ranged 0.18-28.83 mm2 within one brain.
```

with:

```
  exactness    `zoom` is continuous, so a section comes out at exactly the
               requested um/px whatever the file stores, which is why
               tissue_area_mm2 previously ranged 0.18-28.83 mm2 within one brain.
               Note that the pixels themselves are not necessarily a fresh
               resample: these files store a 1/2/4/8/16 pyramid, and 5.20 um/px
               is exactly 1/8 of 0.65, so libCZI serves this read from the
               stored layer 8. The scale is exact; the provenance is ZEISS's
               downsampling. This matters for clipping and nothing else - see
               docs/czi-reading-audit.md finding 2.
```

- [ ] **Step 2: Correct the print at line 370**

Replace:

```python
    print(f"target {TARGET_UM} um/px -> zoom {zoom:.4f} (exact, not a pyramid level)")
```

with:

```python
    pyr = "" if zoom <= 0 or round(1 / zoom) * zoom != 1.0 else \
        f", served from stored pyramid layer {round(1 / zoom)}"
    print(f"target {TARGET_UM} um/px -> zoom {zoom:.4f} (exact scale{pyr})")
```

- [ ] **Step 3: Correct the interpreter path**

In `scripts/01_overviews.py`, replace line 25:

```
Requires the Python 3.13 venv at <root>/work/czienv (pylibCZIrw has no cp314 wheel).

Run:  <root>/work/czienv/Scripts/python.exe 01_overviews.py
```

with:

```
Requires a Python 3.13 venv with pylibCZIrw (no cp314 wheel exists). That is
<root>/work/appenv, which is also what tests/run.sh and app/runner.py use.

Run:  <root>/work/appenv/Scripts/python.exe 01_overviews.py
```

In `scripts/run_all.sh`, replace lines 18-20:

```bash
# pylibCZIrw has no cp314 wheel, so the CZI stages run in a 3.13 venv.
CZIPY="${CZIPY:-$ROOT/work/czienv/Scripts/python.exe}"
```

with:

```bash
# pylibCZIrw has no cp314 wheel, so the CZI stages run in a 3.13 venv. That is
# work/appenv - the separate work/czienv named here previously was never built.
CZIPY="${CZIPY:-$ROOT/work/appenv/Scripts/python.exe}"
```

In `requirements-czi.txt`, replace the two lines naming `work/czienv`:

```
#   py -3.13 -m venv work/czienv
#   work/czienv/Scripts/python -m pip install -r requirements-czi.txt
```

with:

```
#   py -3.13 -m venv work/appenv
#   work/appenv/Scripts/python -m pip install -r requirements-czi.txt
```

- [ ] **Step 4: Verify the interpreter path resolves**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && grep -rn "czienv" scripts/ app/ docs/ README.md requirements*.txt | grep -v czi-reading-audit
```

Expected: no output. Any remaining hit is a path that does not exist on this machine.

- [ ] **Step 5: Fix the pyramid detection in 01e**

In `scripts/01e_tile_geometry.py`, replace lines 93-95:

```python
            # Downsampled pyramid tiles store fewer pixels than they span.
            if x["stored"] and x["size"] // x["stored"] != 1:
                continue
```

with:

```python
            # Downsampled pyramid tiles store fewer pixels than they span.
            # Compared with != rather than by integer division: 2041 // 2040 is
            # 1, so a one-pixel discrepancy would read as a layer-0 tile.
            if x["stored"] and x["size"] != x["stored"]:
                continue
```

- [ ] **Step 6: Verify 01e still finds the same geometry**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/01e_tile_geometry.py 2>&1 | tail -20
```

Expected: 2040 px tiles on an 1836 px pitch, the same counts as before the change. `00d_czi_selftest.py` reports the same tile geometry independently.

- [ ] **Step 7: Align the czifile pin**

In `requirements.txt`, replace `czifile>=2026.6.12` with `czifile>=2026.8.16`, and in `README.md:33` replace `2026.6.12` with `2026.8.16` so the pin matches `docs/software_versions.md`, which is generated from what is installed.

- [ ] **Step 8: Run the full suite and commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh
```

Expected: `ALL SUITES PASS`.

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/01_overviews.py scripts/01e_tile_geometry.py scripts/run_all.sh requirements.txt requirements-czi.txt README.md && git commit -m "docs and pins: correct the pyramid-level claim, the czienv path, 01e pyramid detection and the czifile pin"
```

---

# Stage B — measure before deciding

## Task 8: How many curated sections would the `scene=` fix move?

**Files:**
- Modify: `scripts/00d_czi_selftest.py` (add `--reformat-impact`)

This is the decision gate. `05a_roi_geometry.py:28-30` states the dependency plainly: *"The mask decides the angle and the angle decides the crop, so a second opinion about the mask would move every ROI on the section."* Removing a neighbour's tissue is exactly such a second opinion — but only where the foreign blob survives `04a`'s debris filter, which drops components under `MIN_COMPONENT_FRACTION = 0.12` of the largest. Some sections will move and some will not, and the count decides how Stage C is done.

- [ ] **Step 1: Add the mode**

Append to `scripts/00d_czi_selftest.py`:

```python
def reformat_impact(pyczi, limit):
    """Would removing the neighbours' tissue move a curated section's ROIs?

    04a decides the angle from the tissue mask and the crop from the angle, so a
    changed mask moves every ROI on that section. Foreign tissue only reaches the
    mask if its component survives 04a's debris filter, so this is measured, not
    assumed: reformat geometry is recomputed from a scene-filtered read and from
    an unfiltered one, and the two angles and bounding boxes compared.
    """
    import csv as _csv
    import importlib.util

    import numpy as np

    here = os.path.dirname(os.path.abspath(__file__))

    def _load(name, mod):
        spec = importlib.util.spec_from_file_location(mod, os.path.join(here, name))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    RF = _load("04a_reformat.py", "_rf")
    OV = _load("01_overviews.py", "_ov")

    focus = os.path.join(OUT_ROOT, "qc", "focus.csv")
    with open(focus, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))

    # Only sections that were actually curated can have ROIs to move, and 05a's
    # geometry CSV is exactly the list of those - one row per curated section,
    # per marker. Read through 05a rather than guessing at a path, because the
    # file is marker-scoped and use_marker() is what resolves it.
    G5 = _load("05a_roi_geometry.py", "_g5")
    curated = set()
    for marker in G5.MARKERS:
        G5.use_marker(marker)
        if os.path.exists(G5.GEOM_CSV):
            with open(G5.GEOM_CSV, newline="", encoding="utf-8") as fh:
                curated |= {r["scene_uid"] for r in _csv.DictReader(fh)}
    rows = [r for r in rows if not curated or r["scene_uid"] in curated]
    if limit:
        rows = rows[:limit]
    print(f"{len(rows)} curated sections to check"
          if curated else f"{len(rows)} sections to check (no curation found)")

    with open(os.path.join(OUT_ROOT, "qc", "display_ranges.json"), encoding="utf-8") as fh:
        ranges = json.load(fh)
    d_lo, d_hi = ranges["DAPI"]["lo"], ranges["DAPI"]["hi"]

    def geometry(arr8):
        """04a's angle and tissue bounding box for one 8-bit DAPI image."""
        work = np.asarray(
            RF.Image.fromarray(arr8).resize((RF.WORK_SIZE, RF.WORK_SIZE)))
        mask = RF.tissue_mask(work, light_background=False)
        if mask is None:
            return None
        ys, xs = np.nonzero(mask)
        return (RF.principal_angle(mask),
                (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))

    moved, checked, unchanged = [], 0, 0
    by_file = {}
    for r in rows:
        by_file.setdefault(r["file"], []).append(r)

    for fname, rs in by_file.items():
        path = os.path.join(SOURCE_DIR, fname)
        if not os.path.exists(path):
            continue
        with pyczi.open_czi(path) as d:
            rects = d.scenes_bounding_rectangle
            for r in rs:
                s = int(r["scene_index"])
                if s not in rects:
                    continue
                zoom = float(r.get("zoom") or 0.125)
                before = OV.read_scene(d, rects[s], 0, zoom)
                after = OV.read_scene(d, rects[s], 0, zoom, scene=s)
                gb = geometry(OV.to_8bit(before, d_lo, d_hi))
                ga = geometry(OV.to_8bit(after, d_lo, d_hi))
                checked += 1
                if gb is None or ga is None:
                    moved.append((r["scene_uid"], "mask lost", "", ""))
                    continue
                d_ang = abs((ga[0] - gb[0] + 180) % 360 - 180)
                d_box = max(abs(a - b) for a, b in zip(ga[1], gb[1]))
                if d_ang > 0.5 or d_box > 2:
                    moved.append((r["scene_uid"], f"{d_ang:.2f} deg", f"{d_box} px", ""))
                else:
                    unchanged += 1
                print(f"\r  {checked}/{len(rows)}", end="")
    print()
    print(f"REFORMAT IMPACT  {len(moved)} of {checked} sections would move "
          f"(angle > 0.5 deg or bbox > 2 px); {unchanged} unchanged")
    for uid, ang, box, _ in moved[:25]:
        print(f"                 {uid}  angle {ang}  bbox {box}")
    if len(moved) > 25:
        print(f"                 ... and {len(moved) - 25} more")
    return moved
```

In `main()`, add the flag and the branch. After the `--pixels` argument add:

```python
    ap.add_argument("--reformat-impact", type=int, nargs="?", const=-1, default=0,
                    metavar="N",
                    help="measure how many curated sections the scene= fix would "
                         "move; N limits the count, bare flag checks all")
```

and immediately after `from pylibCZIrw import czi as pyczi` add:

```python
    if args.reformat_impact:
        reformat_impact(pyczi, 0 if args.reformat_impact < 0 else args.reformat_impact)
        return
```

- [ ] **Step 2: Smoke-test the mode on a handful**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/00d_czi_selftest.py --reformat-impact 6
```

Expected: a `REFORMAT IMPACT n of 6 sections would move` line. A `KeyError` on `tissue_mask` or `principal_angle` means the names in `04a_reformat.py` differ from those used above — check them at `04a_reformat.py:83` and `:115` and correct the calls.

- [ ] **Step 3: Run it over every curated section**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/00d_czi_selftest.py --reformat-impact 2>&1 | tail -40
```

Expected: a count out of roughly 130 curated sections. **Stop here and report the number.**

- [ ] **Step 4: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/00d_czi_selftest.py && git commit -m "00d: --reformat-impact measures how many curated sections the scene= fix would move"
```

- [ ] **Step 5: Decision point — do not proceed without it**

Report the count and take the decision before starting Task 9:

- **Zero or near-zero move** → apply Stage C as written; re-run 01, 01k, 04a, 04j, 06f; no re-curation.
- **A handful move** → apply Stage C, then re-curate the named sections. List them from the output.
- **Many move** → do not re-run 04a globally. Pin angle and crop from the stored 04a report for already-curated sections so their ROIs cannot move, and let the corrected mask apply only to uncurated ones. That is a different plan and should be written as one.

---

# Stage C — published numbers move

Do not begin until Task 8's count is known and the decision in its Step 5 is taken.

## Task 9: Pass `scene=` at every call site

**Files:**
- Modify: `scripts/01_overviews.py` (both `read_scene` call sites)
- Modify: `scripts/01k_saturation_raw.py:99-100` and `:145,149`
- Modify: `scripts/05a_roi_geometry.py:685`
- Modify: `scripts/05c_detect_rois.py` (the two reads)

- [ ] **Step 1: Preserve the current outputs**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && mkdir -p "D:/LS-analysis/qc/before-scene-filter" && cp "D:/LS-analysis/qc/focus.csv" "D:/LS-analysis/qc/saturation_raw.csv" "D:/LS-analysis/qc/saturation_raw_native.csv" "D:/LS-analysis/qc/before-scene-filter/"
```

Expected: three files copied. These are the "before" side of every diff below.

- [ ] **Step 2: Thread the scene index through `01_overviews.py`**

In the sampling pass, replace lines 221-222:

```python
                dapi = apply_tile_field(read_scene(czidoc, rects[s], 0, zoom), fields.get(0), 1 / zoom)
                mark = apply_tile_field(read_scene(czidoc, rects[s], 1, zoom), fields.get(1), 1 / zoom)
```

with:

```python
                dapi = apply_tile_field(read_scene(czidoc, rects[s], 0, zoom, scene=s), fields.get(0), 1 / zoom)
                mark = apply_tile_field(read_scene(czidoc, rects[s], 1, zoom, scene=s), fields.get(1), 1 / zoom)
```

In the export pass, replace lines 287-288:

```python
                    dapi_raw = read_scene(czidoc, rects[s], 0, zoom)
                    mark_raw = read_scene(czidoc, rects[s], 1, zoom)
```

with:

```python
                    dapi_raw = read_scene(czidoc, rects[s], 0, zoom, scene=s)
                    mark_raw = read_scene(czidoc, rects[s], 1, zoom, scene=s)
```

- [ ] **Step 3: Thread it through `01k_saturation_raw.py`**

Change `measure()` to take the scene index. Replace its signature and first two lines:

```python
def measure(czidoc, rect, fields, zoom, want_mask, ceiling=CEILING, scene=None):
    """Raw clipping for both channels, and the corrected figure for comparison."""
    dapi_raw = OV.read_scene(czidoc, rect, 0, zoom, scene=scene)
    mark_raw = OV.read_scene(czidoc, rect, 1, zoom, scene=scene)
```

and its call site:

```python
                    m = measure(czidoc, rects[s], fields, zoom, want,
                                OV.ceiling_for(ceilings, fname), scene=s)
```

In `native_sample()`, replace this whole block (lines 144-150 as they stand after
Task 5 renamed the ceiling):

```python
                roi = (rects[s].x, rects[s].y, rects[s].w, rects[s].h)
                low = np.squeeze(czidoc.read(roi=roi, plane={"C": 1}, zoom=0.125))
                f_low = float((low >= ceiling).mean())
                if f_low <= 0:
                    continue
                hi = np.squeeze(czidoc.read(roi=roi, plane={"C": 1}, zoom=1.0))
                f_hi = float((hi >= ceiling).mean())
```

with:

```python
                low = OV.read_scene(czidoc, rects[s], 1, 0.125, scene=s)
                f_low = float((low >= ceiling).mean())
                if f_low <= 0:
                    continue
                hi = OV.read_scene(czidoc, rects[s], 1, 1.0, scene=s)
                f_hi = float((hi >= ceiling).mean())
```

The `roi` local is gone; nothing else in the function used it. Task 10 deletes
`native_sample()` outright, so this edit exists only to keep the function
consistent with `measure()` in between — do not skip it, or a run made between
the two tasks would mix filtered and unfiltered numbers in one CSV.

- [ ] **Step 4: Thread it through 05a and 05c**

In `scripts/05a_roi_geometry.py`, replace lines 684-686:

```python
        with pyczi.open_czi(path) as doc:
            a = np.squeeze(doc.read(roi=(rx, ry, rw, rh), plane={"C": 0},
                                    zoom=zoom)).astype(np.float64)
```

with:

```python
        with pyczi.open_czi(path) as doc:
            box = type("R", (), {"x": rx, "y": ry, "w": rw, "h": rh})()
            a = OV.read_scene(doc, box, 0, zoom,
                              scene=int(g["scene_index"])).astype(np.float64)
```

adding the `01_overviews` import at the top of `05a_roi_geometry.py` if it is not already present, using the same `importlib` pattern as `01k_saturation_raw.py:56-58`.

In `scripts/05c_detect_rois.py`, pass the section's scene index to both reads:

```python
                dapi = OV.read_scene(doc, box, DAPI_C, 1.0, scene=int(g["scene_index"])).astype(np.float32)
                mark = OV.read_scene(doc, box, MARK_C, 1.0, scene=int(g["scene_index"])).astype(np.float32)
```

- [ ] **Step 5: Re-export a sample and diff**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/01_overviews.py --limit 20 --force
```

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import csv
a={r['scene_uid']:r for r in csv.DictReader(open(r'D:\LS-analysis\qc\before-scene-filter\focus.csv',newline='',encoding='utf-8'))}
b={r['scene_uid']:r for r in csv.DictReader(open(r'D:\LS-analysis\qc\focus.csv',newline='',encoding='utf-8'))}
shared=sorted(a.keys()&b.keys())
for c in ('tissue_fraction','tissue_area_mm2','saturated_fraction_raw','focus_score'):
    d=[(u,float(a[u][c] or 0),float(b[u][c] or 0)) for u in shared if a[u][c]!=b[u][c]]
    print(f'{c}: {len(d)}/{len(shared)} changed')
    for u,x,y in sorted(d,key=lambda t:-abs(t[2]-t[1]))[:5]:
        print(f'   {u}  {x:.6f} -> {y:.6f}  ({(y-x)/x*100 if x else float(\"nan\"):+.1f}%)')"
```

Expected: `saturated_fraction_raw` and `tissue_area_mm2` both change on a substantial fraction of the 20; the audit predicts clipped fractions falling, by up to 2.6x on the worst.

- [ ] **Step 6: Confirm the geometry did not move**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import csv
a={r['scene_uid']:r for r in csv.DictReader(open(r'D:\LS-analysis\qc\before-scene-filter\focus.csv',newline='',encoding='utf-8'))}
b={r['scene_uid']:r for r in csv.DictReader(open(r'D:\LS-analysis\qc\focus.csv',newline='',encoding='utf-8'))}
bad=[u for u in a.keys()&b.keys() if (a[u]['width'],a[u]['height'])!=(b[u]['width'],b[u]['height'])]
print('sections whose array size changed:',len(bad))"
```

Expected: `0`. `scene=` filters which subblocks contribute; it must not change the ROI or the output size. Anything other than zero means a rectangle moved and the change should be stopped and investigated.

- [ ] **Step 7: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/01_overviews.py scripts/01k_saturation_raw.py scripts/05a_roi_geometry.py scripts/05c_detect_rois.py && git commit -m "01/01k/05a/05c: pass scene= so a read cannot composite a neighbouring section"
```

---

## Task 10: Measure clipping at native resolution

**Files:**
- Modify: `scripts/01k_saturation_raw.py` (`measure`, `native_sample`, `main`)

The stored mask must stay on the 0.125 grid, because `06f_recensor_nuclei.py:128-130` maps a nucleus into it by `(czi_x - rect_x) * zoom`. So clipping is counted at native resolution and the mask is block-reduced with `any` — which is strictly more inclusive than the current mask, since a block containing one clipped native pixel is now marked.

- [ ] **Step 1: Add the tiled measurement**

In `scripts/01k_saturation_raw.py`, add immediately after `measure()`:

```python
# One strip of native-resolution rows at a time. A whole section at 0.65 um/px
# is ~100 megapixels; strips keep peak memory at a few hundred megabytes.
STRIP_ROWS = 4096


def measure_native(czidoc, rect, zoom, ceiling, scene, want_mask):
    """Clipping counted on pyramid layer 0, with the mask on the overview grid.

    A clipped pixel survives downsampling only if its whole neighbourhood was
    clipped, so the 0.125 read that produces the overview understates clipping
    by a factor measured at 1.08 to 22.99 across this dataset. Counting at
    native resolution removes the dilution instead of estimating it.

    The returned mask is on the 0.125 grid because 06f maps nuclei into it by
    the recorded zoom. It is the block-wise OR of the native mask, so a block
    holding a single clipped pixel is marked - deliberately more inclusive than
    the block mean the downsampled read produced.
    """
    out_h, out_w = int(round(rect.h * zoom)), int(round(rect.w * zoom))
    mask = np.zeros((out_h, out_w), dtype=bool) if want_mask else None
    n_clip = n_cov = n_tot = 0

    for y0 in range(0, rect.h, STRIP_ROWS):
        h = min(STRIP_ROWS, rect.h - y0)
        strip = type("R", (), {"x": rect.x, "y": rect.y + y0, "w": rect.w, "h": h})()
        a = OV.read_scene(czidoc, strip, 1, 1.0, scene=scene)
        clipped = a >= ceiling
        n_clip += int(clipped.sum())
        n_cov += int((a > 0).sum())
        n_tot += a.size
        if want_mask and clipped.any():
            ys, xs = np.nonzero(clipped)
            ry = np.clip(((ys + y0) * zoom).astype(np.int64), 0, out_h - 1)
            rx = np.clip((xs * zoom).astype(np.int64), 0, out_w - 1)
            mask[ry, rx] = True
        del a, clipped

    return {"clipped": n_clip, "covered": n_cov, "total": n_tot, "mask": mask}
```

- [ ] **Step 2: Add the columns**

Replace the `KEYS` list so the native figures sit alongside the existing ones rather than redefining them:

```python
KEYS = ["scene_uid", "file", "animal", "slide", "variant", "marker_channel",
        "scene_index", "section_order", "width", "height", "um_px", "zoom",
        # The scene origin in CZI stage pixels. Recorded here so 06f can map a
        # nucleus from czi_x/czi_y into this mask without reopening 222 CZIs.
        "rect_x", "rect_y", "rect_w", "rect_h",
        "saturated_fraction_raw", "saturated_fraction_dapi_raw",
        "saturated_fraction_corrected", "raw_over_corrected",
        # Measured on pyramid layer 0 rather than on the 0.125 overview read.
        # `_native` is over the whole rectangle, `_native_scanned` over the
        # scanned area only; the pair is the honest numerator and denominator.
        "saturated_fraction_native", "saturated_fraction_native_scanned",
        "native_over_overview", "scanned_fraction",
        "mask_path", "tilefield_applied", "reader"]
```

- [ ] **Step 3: Use it in the measuring loop**

In `main()`, at the `measure` call site, add the native pass and merge the results:

```python
                    m = measure(czidoc, rects[s], fields, zoom, want,
                                OV.ceiling_for(ceilings, fname), scene=s)
                    nat = measure_native(czidoc, rects[s], zoom,
                                         OV.ceiling_for(ceilings, fname), s, want)
                    m["mask"] = nat["mask"] if want else None
```

and in the row that is appended, add the four new fields:

```python
                        "saturated_fraction_native": "%.8f" % (nat["clipped"] / max(nat["total"], 1)),
                        "saturated_fraction_native_scanned": "%.8f" % (nat["clipped"] / max(nat["covered"], 1)),
                        "native_over_overview": ("%.4f" % ((nat["clipped"] / max(nat["total"], 1)) / m["raw"]))
                                                if m["raw"] else "",
                        "scanned_fraction": "%.6f" % (nat["covered"] / max(nat["total"], 1)),
```

- [ ] **Step 4: Retire the global dilution factor**

Delete `native_sample()` and its `--native-sample` argument, and delete the `NATIVE_CSV` constant and its write. Every section now carries its own `native_over_overview`, so a 30-section sample generalised to the dataset is no longer needed. Replace the `--native-sample` argument with nothing; if anything still reads `saturation_raw_native.csv`, point it at the per-section column instead.

Verify nothing else reads it:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && grep -rn "saturation_raw_native\|native_sample" scripts/ app/ tests/ docs/ | grep -v czi-reading-audit
```

Expected: no output outside `01k_saturation_raw.py` itself. Any hit must be updated in this step.

- [ ] **Step 5: Run on a sample and check the ratio**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/01k_saturation_raw.py --limit 12 --force 2>&1 | tail -20
```

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import csv
r=[x for x in csv.DictReader(open(r'D:\LS-analysis\qc\saturation_raw.csv',newline='',encoding='utf-8')) if x.get('native_over_overview')]
v=sorted(float(x['native_over_overview']) for x in r)
print(len(v),'sections with a ratio; min %.3f median %.3f max %.3f'%(v[0],v[len(v)//2],v[-1]))
print('native >= overview on all:', all(float(x['saturated_fraction_native'])>=float(x['saturated_fraction_raw'])-1e-9 for x in r))"
```

Expected: ratios at or above 1.0 on every section — downsampling can only lose clipped pixels, never invent them. A ratio below 1 means the block reduction or the strip loop is wrong.

- [ ] **Step 6: Confirm 06f still maps into the mask**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/06f_recensor_nuclei.py --dry-run 2>&1 | tail -15
```

Expected: it reports the scenes carrying a mask and a censored-count change, without shape errors. The mask grid is unchanged, so 06f's arithmetic is untouched; only the mask's content is more inclusive.

- [ ] **Step 7: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/01k_saturation_raw.py && git commit -m "01k: count clipping on pyramid layer 0 in strips; per-section dilution ratio replaces the global factor"
```

---

## Task 11: Report clipping against the scanned area

**Files:**
- Modify: `scripts/01_overviews.py` (the `qc_rows.append` block and `QC_KEYS`)

`04j_censor_clipped.py:230` and `:324-325` already divide by tissue, so its gate is unaffected. This task fixes the reported `focus.csv` columns, which currently divide by the whole rectangle including the unscanned margin.

- [ ] **Step 1: Add the column**

In `QC_KEYS`, add `"saturated_fraction_raw_scanned"` immediately after `"saturated_fraction_raw"`.

- [ ] **Step 2: Compute it**

The `scanned` mask already exists at `01_overviews.py:306`. Move the two `sat_*_raw` computations to just after it, and add the scanned-denominator variant:

```python
                    scanned = (dapi > 0) | (mark > 0)
                    background = (~mask) & scanned
                    n_scanned = int(scanned.sum())
                    # The frame denominator counts the unscanned margin of the
                    # scene rectangle as if it were imaged and unclipped, which
                    # understates clipping by about 14% on this dataset. Both
                    # are reported: the frame column so nothing downstream
                    # breaks, the scanned column because it is the honest one.
                    sat_mark_raw = float((mark_raw >= ceiling).mean())
                    sat_dapi_raw = float((dapi_raw >= ceiling).mean())
                    sat_mark_raw_scanned = (
                        float((mark_raw >= ceiling)[scanned].mean()) if n_scanned else 0.0)
```

Note that `mask`, `scanned` and `background` are currently computed after the `sat_*` lines; the reordering above keeps `thr`/`mask`/`scanned` before them.

- [ ] **Step 3: Record it**

In the `qc_rows.append({` block, immediately after the `"saturated_fraction_raw": f"{sat_mark_raw:.6f}",` line:

```python
                        "saturated_fraction_raw_scanned": f"{sat_mark_raw_scanned:.6f}",
```

- [ ] **Step 4: Run and check the direction**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/01_overviews.py --limit 20 --force && work/appenv/Scripts/python.exe -c "
import csv
r=list(csv.DictReader(open(r'D:\LS-analysis\qc\focus.csv',newline='',encoding='utf-8')))
r=[x for x in r if x.get('saturated_fraction_raw_scanned')]
up=[x for x in r if float(x['saturated_fraction_raw_scanned'])>=float(x['saturated_fraction_raw'])]
print(f'{len(up)}/{len(r)} sections: scanned denominator >= frame denominator')
rat=[float(x['saturated_fraction_raw_scanned'])/float(x['saturated_fraction_raw']) for x in r if float(x['saturated_fraction_raw'])>0]
print('median ratio %.3f'%(sorted(rat)[len(rat)//2]) if rat else 'no clipping in the sample')"
```

Expected: every section satisfies `scanned >= frame` — a smaller denominator cannot give a smaller fraction — and a median ratio near 1.14.

- [ ] **Step 5: Run the full suite**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh
```

Expected: `ALL SUITES PASS`.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add scripts/01_overviews.py && git commit -m "01: report clipping against the scanned area alongside the frame"
```

---

## Task 12: Re-run the affected stages and update the audit

**Files:**
- Modify: `docs/czi-reading-audit.md` (status table)

- [ ] **Step 1: Full re-run of the pixel stages**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/01_overviews.py --force 2>&1 | tail -5
```

Expected: all sections exported, no failures.

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/01k_saturation_raw.py --force 2>&1 | tail -5
```

Expected: all sections measured, masks written.

- [ ] **Step 2: Re-run the downstream stages that read them**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/04a_reformat.py && work/appenv/Scripts/python.exe scripts/04j_censor_clipped.py && work/appenv/Scripts/python.exe scripts/06f_recensor_nuclei.py --dry-run
```

Expected: each completes. **04j's kept/set-aside counts will differ from the memo'd 570/605/634/655/681 at 0.2/0.5/1/2/5%** — that is the point of the change. Record the new counts.

- [ ] **Step 3: Report the corrected clipping distribution**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe -c "
import csv, statistics as st
r=list(csv.DictReader(open(r'D:\LS-analysis\qc\saturation_raw.csv',newline='',encoding='utf-8')))
for c in ('saturated_fraction_raw','saturated_fraction_native','saturated_fraction_native_scanned'):
    v=sorted(float(x[c]) for x in r if x.get(c))
    if v: print(f'{c:38} n={len(v)} median={v[len(v)//2]:.6f} p90={v[int(.9*len(v))]:.6f} max={v[-1]:.6f}')"
```

Expected: three distributions, each shifted up from the last. This is what the 04j tolerance should be re-argued against.

- [ ] **Step 4: Mark the audit's findings resolved**

In `docs/czi-reading-audit.md`, update the Summary table's Status column for findings 1, 2 and 3 to `Fixed 2026-09-03`, and add one line under each of those findings recording the observed effect from Step 3.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git add docs/czi-reading-audit.md && git commit -m "audit: record findings 1-3 as fixed, with the corrected clipping distribution"
```

---

## Not in this plan

- **Switching to `scenes_bounding_rectangle_no_pyramid`** (audit finding 5). The origins are identical across all 496 scenes checked, so nothing is misplaced; the only gain is a few pixels of margin, and the migration would re-anchor stored coordinates for no measurable benefit. Task 6 records `rect_source` so that a later switch is visible in the data.
- **Replacing `01e_tile_geometry.py`'s binary parser with `enumerate_subblocks_subset`** (audit finding 10). `00d_czi_selftest.py` now derives the same geometry through the supported call, so the parser has an independent check standing beside it. Replacing it is a separate change with its own regression risk and no defect driving it.
- **Anything about scaled output shapes** (audit finding 6). Checked at all three configured zooms on nine sections: the returned shape equalled `round(h * zoom), round(w * zoom)` in all 27 reads. The `±2` tolerance already in `05a_roi_geometry.py:449-455` is harmless and stays. `00d_czi_selftest.py` would surface a regression if a future dataset had rectangles that are not clean multiples.
- **The Groovy path's unchecked 16-bit assumption** (audit finding 10). `01_overviews.groovy:189-199` reads two bytes per pixel without consulting `getPixelType()`. It is retired from the data path and no number it produces reaches a result, so the fix is not worth the risk of touching a script nobody runs. It stays recorded in the audit. If `run_all.sh` step 4 is ever revived, fix it first.
- **Re-tuning the 04j tolerance.** Task 12 produces the corrected distribution; arguing the threshold against it is the next piece of work, not this one.
- **A subblock cache for `05c_detect_rois.py`** (audit finding 10). `open_czi()` accepts `cache_options`, but no measurement says the stage is slow enough to need it. Benchmark first.
