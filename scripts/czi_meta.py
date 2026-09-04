"""Shared CZI header reader.

Reads the ZISRAWMETADATA XML block out of a CZI without decoding any pixels.
Works on a plain file object or on a zipfile.ZipExtFile, because the transfer
zips are STORED (uncompressed) and therefore seekable.

CZI layout used here:
    FileHeaderSegment   : 32 byte SegmentHeader + FileHeaderSegmentData
                          DirectoryPosition at offset 84, MetadataPosition at 92
    MetadataSegment     : 32 byte SegmentHeader
                          + 256 byte MetadataSegmentData (XmlSize, AttachmentSize, spare)
                          + XML
"""

import struct
import xml.etree.ElementTree as ET

HEADER_LEN = 288
SEGMENT_HEADER_LEN = 32
METADATA_DATA_LEN = 256


def _seek(fh, pos):
    """Seek, falling back to forward streaming for stream-only file objects."""
    try:
        fh.seek(pos)
        return
    except (OSError, AttributeError, ValueError):
        pass
    remaining = pos - fh.tell()
    if remaining < 0:
        raise OSError("cannot rewind this stream")
    while remaining > 0:
        chunk = fh.read(min(remaining, 1 << 22))
        if not chunk:
            raise OSError("unexpected EOF while seeking")
        remaining -= len(chunk)


def read_metadata(fh):
    """Return the parsed metadata XML root for an open CZI file object."""
    head = fh.read(HEADER_LEN)
    if head[:10] != b"ZISRAWFILE":
        raise ValueError("not a CZI file")
    _dir_pos, meta_pos = struct.unpack("<QQ", head[84:100])

    _seek(fh, meta_pos)
    seg = fh.read(SEGMENT_HEADER_LEN)
    if seg[:14] != b"ZISRAWMETADATA":
        raise ValueError("metadata segment not found at declared position")

    xml_size, _attachment_size = struct.unpack("<ii", fh.read(8))
    _seek(fh, meta_pos + SEGMENT_HEADER_LEN + METADATA_DATA_LEN)
    return ET.fromstring(fh.read(xml_size).decode("utf-8", "replace"))


def _float_pair(text):
    if not text:
        return None, None
    a, b = text.split(",")[:2]
    return float(a), float(b)


def _int_or_none(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def nominal_ceiling(bits):
    """Highest value a right-aligned sample of this depth can hold.

    None for anything that is not a positive int - absent, zero, negative, or
    a value that was never parsed to a count in the first place. Duplicated
    from scripts/00d_czi_selftest.py's function of the same name rather than
    imported: czi_meta.py is stdlib-only so it can read a header straight out
    of a STORED transfer zip without decoding pixels, and 00d_czi_selftest.py
    is a numbered stage script (loaded via importlib.util, not a package) that
    imports numpy and pylibCZIrw at call time - depending on it here would run
    the dependency the wrong way. Keep the two guards identical.
    """
    if not isinstance(bits, int) or bits <= 0:
        return None
    return (1 << bits) - 1


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


def summarise(root):
    """Pull the fields the pipeline cares about out of a metadata XML root."""
    img = ".//Information/Image/"

    def txt(path, default=None):
        found = root.findtext(path)
        return found if found is not None else default

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

    px_x = root.findtext('.//Scaling/Items/Distance[@Id="X"]/Value')
    px_y = root.findtext('.//Scaling/Items/Distance[@Id="Y"]/Value')

    scenes = []
    for sc in root.findall(".//Dimensions/S/Scenes/Scene"):
        cx, cy = _float_pair(sc.findtext("CenterPosition"))
        w, h = _float_pair(sc.findtext("ContourSize"))
        scenes.append(
            {
                "index": int(sc.get("Index")),
                "name": sc.get("Name"),
                "center_x_um": cx,
                "center_y_um": cy,
                "width_um": w,
                "height_um": h,
            }
        )
    scenes.sort(key=lambda s: s["index"])

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
        "clip_ceiling": nominal_ceiling(bits),
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
