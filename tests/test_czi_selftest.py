"""The CZI self-test's geometry, metadata parsing, and exit policy.

The pure functions and the fake-reader `inspect()` cases are checked here;
anything needing the 222 real CZIs skips itself with a note, so this suite
still runs on a machine with the repo and no images.

Run:  python tests/test_czi_selftest.py
"""

import importlib.util
import os
import sys

import numpy as np

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

# --- bit_depth: anchored XPath still finds a differently-shaped document ---
# No <Metadata> wrapper at all - the anchored path misses and must fall back
# to the loose (pre-existing) one rather than reporting nothing.
LOOSE_XML = """<Something><Information><Image>
  <ComponentBitCount>12</ComponentBitCount>
</Image></Information>
<SelectedShadingReferenceMode>Full</SelectedShadingReferenceMode>
</Something>"""
bd_loose = ST.bit_depth(LOOSE_XML)
chk("anchored miss falls back: bit count", bd_loose["image_component_bit_count"], 12)
chk("anchored miss falls back: shading", bd_loose["shading"], "Full")

# --- nominal_ceiling --------------------------------------------------------
chk("16 bits -> 65535", ST.nominal_ceiling(16), 65535)
chk("14 bits -> 16383", ST.nominal_ceiling(14), 16383)
chk("12 bits -> 4095", ST.nominal_ceiling(12), 4095)
chk("missing bit count -> None", ST.nominal_ceiling(None), None)
chk("zero bits -> None", ST.nominal_ceiling(0), None)
chk("negative bits -> None (not a ValueError)", ST.nominal_ceiling(-4), None)
chk("non-int bits -> None", ST.nominal_ceiling("16"), None)

# --- bit_count_disagreement --------------------------------------------------
chk("agreeing counts -> None", ST.bit_count_disagreement(16, [16, 16]), None)
chk("a channel disagrees with the image level",
    ST.bit_count_disagreement(16, [16, 14]) is None, False)
chk("disagreement text names both", "14" in ST.bit_count_disagreement(16, [16, 14]), True)
chk("no image-level count -> None (handled as bit_count_missing instead)",
    ST.bit_count_disagreement(None, [16, 14]), None)
chk("no channel counts at all -> None", ST.bit_count_disagreement(16, [None, None]), None)

# --- bitcount_range_disagreement: the display-setting cross-check ------------
chk("BitCountRange matching the image count -> None",
    ST.bitcount_range_disagreement(16, ["16"]), None)
chk("no ranges recorded -> None", ST.bitcount_range_disagreement(16, []), None)
chk("no image-level count -> None", ST.bitcount_range_disagreement(None, ["16"]), None)
chk("a disagreeing range is reported",
    ST.bitcount_range_disagreement(16, ["14"]) is None, False)
chk("the report names both sides",
    ST.bitcount_range_disagreement(16, ["14"]), "image=16 BitCountRange=14")
chk("only the odd ones out are named",
    ST.bitcount_range_disagreement(16, ["16", "12"]), "image=16 BitCountRange=12")

# --- shallow_bit_signature ---------------------------------------------------
# The floor (SHALLOW_MAX_BITS_BELOW) exists because the input is a STRIP maximum:
# a strip of bare glass maxes at a few hundred counts, and 255 or 1023 is
# 2**n - 1 by coincidence, not because the sensor is 8- or 10-bit.
chk("14-bit ceiling under a 16-bit declaration", ST.shallow_bit_signature(16383, 16), 14)
chk("12-bit ceiling under 16 is still within the floor",
    ST.shallow_bit_signature(4095, 16), 12)
chk("full-scale max is not a shallow signature", ST.shallow_bit_signature(65535, 16), None)
chk("a max that isn't 2**n - 1 at all", ST.shallow_bit_signature(50000, 16), None)
chk("no declared bit count -> None", ST.shallow_bit_signature(16383, None), None)
chk("no observed max -> None", ST.shallow_bit_signature(None, 16), None)
chk("a background-only strip maxing at 1023 does not fire",
    ST.shallow_bit_signature(1023, 16), None)
chk("nor one maxing at 255", ST.shallow_bit_signature(255, 16), None)
chk("nor an all-zero strip", ST.shallow_bit_signature(0, 16), None)
chk("the floor is relative to the declaration, not absolute",
    ST.shallow_bit_signature(255, 8 + ST.SHALLOW_MAX_BITS_BELOW), 8)

# --- pick_sample_indices: spreads across the file list, not the first N ----
chk("4 of 222 spreads out", sorted(ST.pick_sample_indices(222, 4)), [0, 55, 111, 166])
chk("0 requested -> empty", ST.pick_sample_indices(222, 0), set())
chk("0 files -> empty", ST.pick_sample_indices(0, 4), set())
chk("more requested than exist is capped", len(ST.pick_sample_indices(3, 10)), 3)

# --- summarise: the exit-code policy, asserted rather than eyeballed -------
_, code = ST.summarise([])
chk("no rows at all -> exit 2 (no files found)", code, 2)


def _row(**over):
    r = {k: "" for k in ST.KEYS}
    r.update(n_scenes=0, overlapping_pairs=0, scenes_in_overlap=0, max_overlap_frac=0.0,
              pyramid_levels="", frames_compared=0, frame_key_mismatch=0,
              origin_drift=0, extent_drift=0, nominal_ceiling=None,
              image_bit_count=16, shading="None", online_stitching="false",
              violations="", error="")
    r.update(over)
    return r


_, code = ST.summarise([_row(file="a.czi")])
chk("one clean row -> exit 0", code, 0)

_, code = ST.summarise([_row(file="a.czi", origin_drift=1, violations="origin_drift")])
chk("origin drift on any file -> exit 2", code, 2)

_, code = ST.summarise([_row(file="a.czi", frame_key_mismatch=1, violations="frame_key_mismatch")])
chk("frame key mismatch -> exit 2", code, 2)

_, code = ST.summarise([_row(file="a.czi", image_bit_count=None, violations="bit_count_missing")])
chk("missing ComponentBitCount -> exit 2", code, 2)

_, code = ST.summarise([_row(file="a.czi", violations="bit_count_disagreement",
                              bit_count_disagreement="image=16 channels=16,14")])
chk("bit count disagreement -> exit 2", code, 2)

_, code = ST.summarise([_row(file="a.czi", error="boom", violations="error")])
chk("a per-file exception -> exit 2", code, 2)

_, code = ST.summarise([_row(file="a.czi", overlapping_pairs=1, scenes_in_overlap=2, n_scenes=2)])
chk("scene overlap ALONE does not gate the exit code", code, 0)

lines, code = ST.summarise([_row(file="a.czi", pyramid_levels="1,2,4")])
chk("pyramid levels alone do not gate the exit code", code, 0)
chk("pyramid levels are reported", any("PYRAMID" in l for l in lines), True)


# --- inspect(): a fake reader, no CZI files needed --------------------------

class _Rect:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


class _Size:
    def __init__(self, w):
        self.w = w


class _Rect2:
    def __init__(self, w):
        self.w = w


class _SubblockInfo:
    def __init__(self, physical_w, logical_w):
        self.physicalSize = _Size(physical_w)
        self.logicalRect = _Rect2(logical_w)


def _xml(image_bits="16", channels=(("DAPI", "16", "Gray16"), ("AF568", "16", "Gray16"))):
    def bc(b):
        return f"<ComponentBitCount>{b}</ComponentBitCount>" if b is not None else ""
    ch_xml = "".join(
        f'<Channel Name="{n}">{bc(b)}<PixelType>{pt}</PixelType></Channel>'
        for n, b, pt in channels)
    return f"""<ImageDocument><Metadata><Information><Image>
      {bc(image_bits)}
      <Dimensions><Channels>{ch_xml}</Channels></Dimensions>
    </Image></Information>
    <HardwareSetting><SelectedShadingReferenceMode>None</SelectedShadingReferenceMode>
      <IsOnlineStitchingEnabled>false</IsOnlineStitchingEnabled></HardwareSetting>
    </Metadata></ImageDocument>"""


class _FakeCzi:
    def __init__(self, scenes, scenes_no_pyramid, subblocks, raw_xml, channel_arrays=None):
        self.scenes_bounding_rectangle = scenes
        self.scenes_bounding_rectangle_no_pyramid = scenes_no_pyramid
        self._subblocks = subblocks
        self.raw_metadata = raw_xml
        self._channel_arrays = channel_arrays or {}
        self.read_calls = []

    def enumerate_subblocks(self, cb):
        for idx, info in self._subblocks:
            if not cb(idx, info):
                break

    def read(self, roi, plane, scene, zoom):
        self.read_calls.append({"roi": roi, "plane": dict(plane), "scene": scene, "zoom": zoom})
        return self._channel_arrays[plane["C"]]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakePyczi:
    def __init__(self, czi):
        self._czi = czi

    def open_czi(self, path):
        return self._czi


# 1. zero scenes - must not crash, must not report a false violation
c = _FakeCzi({}, {}, [], _xml())
row = ST.inspect("x.czi", _FakePyczi(c), False)
chk("zero scenes: n_scenes", row["n_scenes"], 0)
chk("zero scenes: frames_compared", row["frames_compared"], 0)
chk("zero scenes: no violation", row["violations"], "")

# 2. one scene, matching frames
c = _FakeCzi({0: _Rect(0, 0, 100, 100)}, {0: _Rect(0, 0, 100, 100)},
             [(0, _SubblockInfo(100, 100))], _xml())
row = ST.inspect("x.czi", _FakePyczi(c), False)
chk("one scene: n_scenes", row["n_scenes"], 1)
chk("one scene: pyramid level 1 seen", row["pyramid_levels"], "1")
chk("one scene: no violation", row["violations"], "")

# 3. enumerate_subblocks yields nothing - must not crash
c = _FakeCzi({0: _Rect(0, 0, 100, 100)}, {0: _Rect(0, 0, 100, 100)}, [], _xml())
row = ST.inspect("x.czi", _FakePyczi(c), False)
chk("no subblocks: pyramid_levels empty, no crash", row["pyramid_levels"], "")

# 4. physicalSize.w == 0 - the div-by-zero guard
c = _FakeCzi({0: _Rect(0, 0, 100, 100)}, {0: _Rect(0, 0, 100, 100)},
             [(0, _SubblockInfo(0, 100))], _xml())
row = ST.inspect("x.czi", _FakePyczi(c), False)
chk("physicalSize.w == 0: no crash, no level tallied", row["pyramid_levels"], "")

# 5. disjoint keys between the two frames -> flagged, not a silent pass
c = _FakeCzi({0: _Rect(0, 0, 10, 10)}, {1: _Rect(0, 0, 10, 10)}, [], _xml())
row = ST.inspect("x.czi", _FakePyczi(c), False)
chk("disjoint frame keys: frames_compared", row["frames_compared"], 0)
chk("disjoint frame keys: frame_key_mismatch", row["frame_key_mismatch"], 1)
chk("disjoint frame keys: flagged as a violation", "frame_key_mismatch" in row["violations"], True)

# 6. missing ComponentBitCount -> flagged, not silently None
c = _FakeCzi({0: _Rect(0, 0, 10, 10)}, {0: _Rect(0, 0, 10, 10)}, [], _xml(image_bits=None))
row = ST.inspect("x.czi", _FakePyczi(c), False)
chk("missing bit count: image_bit_count", row["image_bit_count"], None)
chk("missing bit count: flagged as a violation", "bit_count_missing" in row["violations"], True)

# 7. bit-count disagreement (the test fixture's own XML shape) -> flagged
c = _FakeCzi({0: _Rect(0, 0, 10, 10)}, {0: _Rect(0, 0, 10, 10)}, [],
             _xml(channels=(("DAPI", "16", "Gray16"), ("AF568", "14", "Gray16"))))
row = ST.inspect("x.czi", _FakePyczi(c), False)
chk("bit count disagreement: column set", row["bit_count_disagreement"] != "", True)
chk("bit count disagreement: flagged as a violation",
    "bit_count_disagreement" in row["violations"], True)

# 8. origin drift between the two frames -> flagged
c = _FakeCzi({0: _Rect(5, 5, 10, 10)}, {0: _Rect(0, 0, 10, 10)}, [], _xml())
row = ST.inspect("x.czi", _FakePyczi(c), False)
chk("origin drift: count", row["origin_drift"], 1)
chk("origin drift: flagged as a violation", "origin_drift" in row["violations"], True)

# 9. pixel sampling: native zoom, largest scene, both channels, bounded reads
scenes = {0: _Rect(0, 0, 10, 10), 1: _Rect(0, 0, 1000, 1000)}
arrays = {
    0: np.array([[65535, 65535], [0, 0]], dtype=np.uint16),
    1: np.array([[16383, 100], [0, 0]], dtype=np.uint16),
}
c = _FakeCzi(scenes, scenes, [(0, _SubblockInfo(1000, 1000))], _xml(), channel_arrays=arrays)
row = ST.inspect("x.czi", _FakePyczi(c), True)
chk("pixel sample: reads the larger scene", c.read_calls[0]["scene"], 1)
chk("pixel sample: native zoom", c.read_calls[0]["zoom"], 1.0)
chk("pixel sample: reads both channels", len(c.read_calls), 2)
chk("pixel sample: strip max per channel", row["strip_max_by_channel"], "65535,16383")
chk("pixel sample: pixels at ceiling per channel", row["clipped_at_ceiling_by_channel"], "2,0")
chk("pixel sample: shallow signature per channel", row["shallow_signature_by_channel"], ",14")
# The strip is what was actually read, and the row must say so: the column names
# and the summary claim a strip, not a scene, and these two make that auditable.
chk("pixel sample: strip height recorded", row["strip_rows"], 1000)
chk("pixel sample: strip height is what was read", c.read_calls[0]["roi"][3], 1000)
chk("pixel sample: strip coverage of the scene recorded", row["strip_frac_of_scene"], 1.0)

# 10. a scene taller than STRIP_ROWS - coverage is a fraction, not 100%
tall = {0: _Rect(0, 0, 100, ST.STRIP_ROWS * 4)}
c = _FakeCzi(tall, tall, [], _xml(), channel_arrays={0: np.zeros((2, 2), np.uint16),
                                                      1: np.zeros((2, 2), np.uint16)})
row = ST.inspect("x.czi", _FakePyczi(c), True)
chk("tall scene: read is capped at STRIP_ROWS", c.read_calls[0]["roi"][3], ST.STRIP_ROWS)
chk("tall scene: coverage is a quarter of the scene", row["strip_frac_of_scene"], 0.25)

# 11. bitcount_range_mismatch: recorded per row, and not a gating violation
BCR_XML = _xml().replace(
    "</Metadata>",
    "<DisplaySetting><Channels><Channel><BitCountRange>14</BitCountRange>"
    "</Channel></Channels></DisplaySetting></Metadata>")
c = _FakeCzi({0: _Rect(0, 0, 10, 10)}, {0: _Rect(0, 0, 10, 10)}, [], BCR_XML)
row = ST.inspect("x.czi", _FakePyczi(c), False)
chk("BitCountRange mismatch: recorded", row["bitcount_range_mismatch"] != "", True)
chk("BitCountRange mismatch: not a gating violation", row["violations"], "")
_, code = ST.summarise([row])
chk("BitCountRange mismatch: does not change the exit code", code, 0)

# --- the gate must fire in-process, not only from the command line ----------
# app/runner.py runs a stage as `mod.main()` and calls a plain return SUCCESS;
# it detects failure only by catching SystemExit. A main() that RETURNS its exit
# code therefore gates `python scripts/00d_czi_selftest.py` and not the GUI, and
# app/stages.py's existence-only done() over an already-written CSV then shows
# the stage green on a dataset that broke a structural assumption. This asserts
# the in-process path, so that regression cannot happen silently again.
try:
    import pylibCZIrw                                        # noqa: F401
    _HAVE_PYCZI = True
except Exception:                                            # noqa: BLE001
    _HAVE_PYCZI = False

if _HAVE_PYCZI:
    import contextlib
    import io
    import tempfile

    with tempfile.TemporaryDirectory() as _tmp:
        _empty = os.path.join(_tmp, "empty-source")
        os.makedirs(_empty)
        # SOURCE_DIR/QC_DIR/OUT_CSV are redirected so this never reads the real
        # dataset nor overwrites the real qc/czi_selftest.csv.
        _saved = (ST.SOURCE_DIR, ST.QC_DIR, ST.OUT_CSV, sys.argv)
        ST.SOURCE_DIR = _empty
        ST.QC_DIR = os.path.join(_tmp, "qc")
        ST.OUT_CSV = os.path.join(ST.QC_DIR, "czi_selftest.csv")
        sys.argv = ["00d_czi_selftest.py"]
        raised, returned = None, "did not return"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                returned = ST.main()
        except SystemExit as _e:
            raised = _e.code
        finally:
            ST.SOURCE_DIR, ST.QC_DIR, ST.OUT_CSV, sys.argv = _saved

    chk("in-process main() on an empty source dir RAISES SystemExit", raised is None, False)
    chk("in-process main() raises exit code 2", raised, 2)
    chk("in-process main() never falls through to a return", returned, "did not return")
else:
    print("note  pylibCZIrw absent, in-process gate check skipped")


# --- dataset checks skip when the images are not present --------------------
if not os.path.isdir(ST.SOURCE_DIR):
    print(f"note  source dir absent, dataset checks skipped ({ST.SOURCE_DIR})")

print()
print("FAILURES" if fails else "ALL PASS")
sys.exit(1 if fails else 0)
