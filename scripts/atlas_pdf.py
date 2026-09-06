"""Shared geometry for reading plates out of the salmon atlas PDF.

Both 04a (extraction) and 04a2 (remerge) decide for themselves which image
XObjects on a page are plates, and the two must agree: 04a2 pairs its groups
with 04a's rows by position on the page, so a page where they disagree does not
fail, it silently mismaps every seed on that page.

The rule changed with the 2026-09 atlas. The old PDF (Ghostscript) stored each
plate as one or more horizontal strips and nothing else, so "every image is a
plate, modulo strips" held. The PowerPoint re-export stores whole plates - the
strips are gone - but adds two kinds of image that are not plates:

  - **overlay insets** - a crop of the plate pasted back on top of it, lying
    wholly inside the plate's own bbox. Page 6 carries seven of them.
  - **marker stamps** - on pages 25-28 a region dot is a 22.7 pt bitmap rather
    than a vector path, and two of them sit in the left margin, outside any
    plate, so containment alone does not catch them.

Both are rejected here. Measured on `Salmon Atlas full.pdf`: 77 image XObjects,
of which 47 are plates - exactly the figure count the old atlas reached after
04a2 merged its 101 strips.

Imported by path, like every other cross-script import here:

    _spec = importlib.util.spec_from_file_location(
        "_atlas_pdf", os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlas_pdf.py"))
    ATLAS = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(ATLAS)
"""

# A plate is bigger than a region marker. Markers are a uniform 22.7 pt (see
# MARKER_SIZE in 04a_atlas_extract.py) and the smallest real plate is over
# 200 pt wide, so an image no bigger than a marker is a stamp, not a plate.
MARKER_MAX_PT = 40.0

# An inset lies inside its plate. The 1 pt slack absorbs rounding in the stored
# bbox; the 5% area margin stops two images that coincide exactly from each
# deleting the other.
CONTAIN_SLACK_PT = 1.0
CONTAIN_AREA_MARGIN = 1.05


def image_boxes(page):
    """Every image XObject on the page that has a usable bbox. Unfiltered."""
    boxes = []
    for item in page.get_images(full=True):
        try:
            bbox = page.get_image_bbox(item)
        except (ValueError, RuntimeError):
            continue
        if bbox.is_empty or bbox.width <= 0 or bbox.height <= 0:
            continue
        boxes.append({"xref": item[0], "bbox": bbox, "px_w": item[2], "px_h": item[3]})
    return boxes


def is_inside(inner, outer):
    """True when `inner` lies within `outer`, and `outer` is the larger of the two."""
    s = CONTAIN_SLACK_PT
    return (outer.x0 <= inner.x0 + s and outer.y0 <= inner.y0 + s
            and outer.x1 >= inner.x1 - s and outer.y1 >= inner.y1 - s
            and outer.get_area() > inner.get_area() * CONTAIN_AREA_MARGIN)


def plate_boxes(page):
    """The plate bitmaps on the page, ordered top to bottom then left to right.

    Overlay insets and marker stamps are dropped, which restores the invariant
    the rest of the extraction is written against: plate bboxes do not overlap.
    """
    boxes = image_boxes(page)
    plates = []
    for box in boxes:
        rect = box["bbox"]
        if max(rect.width, rect.height) <= MARKER_MAX_PT:
            continue
        if any(other is not box and is_inside(rect, other["bbox"]) for other in boxes):
            continue
        plates.append(box)
    plates.sort(key=lambda p: (round(p["bbox"].y0, 1), round(p["bbox"].x0, 1)))
    return plates


def inset_boxes(page):
    """The overlay insets on the page - images drawn inside a plate.

    Where PowerPoint flattened a region of a plate into a bitmap it took the
    vector region markers with it, so these are the areas where a marker has to
    be recovered from the render rather than from the drawing list.
    """
    boxes = image_boxes(page)
    return [b["bbox"] for b in boxes
            if any(o is not b and is_inside(b["bbox"], o["bbox"]) for o in boxes)]
