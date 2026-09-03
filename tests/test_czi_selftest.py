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
