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

# --- nominal_ceiling hardening (carried forward from Task 1's code review) --
chk("nominal_ceiling(16)", CM.nominal_ceiling(16), 65535)
chk("nominal_ceiling(0) is None", CM.nominal_ceiling(0), None)
chk("nominal_ceiling(-1) is None", CM.nominal_ceiling(-1), None)
chk("nominal_ceiling('16') is None", CM.nominal_ceiling("16"), None)
chk("nominal_ceiling(None) is None", CM.nominal_ceiling(None), None)

print()
print("FAILURES" if fails else "ALL PASS")
sys.exit(1 if fails else 0)
