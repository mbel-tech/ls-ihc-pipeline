"""Stage 4a - pull the labelled plate series out of Salmon Atlas.pdf.

The atlas is a working document, not a scan: every region marker is a vector
dot with a distinct fill colour, and each page carries its own legend mapping
those colours to region names. That makes the whole thing machine-readable.

Page geometry (verified against pages 5, 9, 10, 18, 20, 25):
  - legend swatches sit in the left margin at centre x < ~105
  - legend labels start beside their swatch and are read rightward to the first
    wide gap. They are NOT confined to x ~ 89: that holds for the single-word
    telencephalic names, but the caudal ones are phrases running past x = 240
  - plate bitmaps are separate image XObjects with non-overlapping bboxes
  - in-figure dots fall inside a plate bbox; markers are a uniform 22.7 pt,
    drawn as a fill plus a slightly larger outline
  - in-figure text (e.g. "Optic Chiasm") is annotation, not legend

Markers are found by SIZE, not by colour. Two of the atlas's own region colours
defeat a colour filter: **black** is Posterior tuberculum on pages 18-20, and the
**hatched** Anterior tuberal nucleus is a pattern fill that reports as black too.
Both were being discarded, which is why every plate caudal to plate_025 came out
with no regions at all. The visible colour is read from a render of the page,
since for a pattern fill the declared fill and what you see are different.

Outputs to atlas/plates/:
  plate_###_p<page>_<n>.<ext>   the plate bitmap, losslessly re-extracted
  seeds.csv                     region seed points in plate pixel coordinates
  text_labels.csv               in-figure text annotations
  legend_by_page.csv            colour -> region, per page
  gaps.csv                      plates carrying no seeds, i.e. still unlabelled
  qc/plate_###_overlay.png      seeds drawn back onto the plate

Run:  python 04a_atlas_extract.py
"""

import csv
import io
import os
from collections import Counter, defaultdict

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- configuration

ATLAS_PDF = r"D:\SLIDES HE DEC 2025 LS\General atlases & reviews\Salmon Atlas.pdf"
OUT_DIR = r"D:\LS-analysis\atlas\plates"
QC_DIR = os.path.join(OUT_DIR, "qc")

# Everything left of this page x is margin, i.e. a legend swatch rather than a
# figure marker. Swatches sit at x 30-48 depending on the page; markers never do.
LEGEND_MAX_X = 105.0
# A swatch and its label are on the same line if their centres are this close.
LEGEND_LINE_TOL = 16.0
# Words this close vertically belong to the same label.
WORD_LINE_TOL = 6.0
# Reading a label rightward from its swatch, a horizontal gap wider than this
# ends it. That is what keeps an in-figure annotation sharing the line - the
# "Dm OC" case - from being swallowed into the region name.
LABEL_GAP_MAX = 30.0

# Region markers are a uniform ~22.7 pt, drawn as a fill plus a slightly larger
# outline. Selecting on size is what separates them from the page-sized
# background rectangle; selecting on colour is not, because **black is a real
# region colour** on the caudal pages (Posterior tuberculum), and the earlier
# rule that "pure black and white are outlines and page background, never region
# markers" silently dropped every marker on pages 18-20 and 25-28.
MARKER_SIZE = (15.0, 40.0)
# A fill and its outline sit at the same spot; this collapses the pair.
MARKER_DEDUP_TOL = 3.0
# Page render zoom used to read a marker's true colour. Needed because a hatched
# marker (Anterior tuberal nucleus) has a *pattern* fill, which the drawing
# reports as plain black - the declared fill and the visible colour differ.
COLOUR_ZOOM = 4.0

# Labels that mark an explicit unknown rather than a region.
UNKNOWN_LABELS = {"??", "?"}

# The atlas writes one nucleus three different ways across consecutive pages -
# "Rm (Raphe) ??", "Rm (Raphe)", "Raphe (Rm)" - which downstream would count as
# three separate regions. Canonicalised here, with the verbatim label kept in
# `region_raw` so nothing about the source is lost. "nucelus" is the atlas's own
# typo. Only exact matches are rewritten; an unlisted label passes through
# untouched, so a new region cannot be silently absorbed into an existing one.
REGION_CANONICAL = {
    "Rm (Raphe) ??": "Rm",
    "Rm (Raphe)": "Rm",
    "Raphe (Rm)": "Rm",
    "Anterior tuberal nucelus": "Anterior tuberal nucleus",
}


def hexify(rgb):
    """0-255 RGB tuple to hex."""
    return "#%02x%02x%02x" % tuple(int(round(c)) for c in rgb)


# ---------------------------------------------------------------- page parsing


def group_words(words, tol=WORD_LINE_TOL):
    """Collapse words into lines, returning (text, x0, y_centre)."""
    lines = []
    for x0, y0, x1, y1, text, *_ in sorted(words, key=lambda w: (round(w[1], 1), w[0])):
        yc = (y0 + y1) / 2.0
        if lines and abs(lines[-1]["yc"] - yc) <= tol:
            lines[-1]["parts"].append((x0, text))
            lines[-1]["x0"] = min(lines[-1]["x0"], x0)
        else:
            lines.append({"parts": [(x0, text)], "x0": x0, "yc": yc})
    return [
        (" ".join(t for _, t in sorted(ln["parts"])), ln["x0"], ln["yc"]) for ln in lines
    ]


def render_page(page, zoom=COLOUR_ZOOM):
    """The page as an RGB array, for reading what a marker actually looks like."""
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    return np.asarray(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")).astype(int)


def sample_colour(render, cx, cy, size, zoom=COLOUR_ZOOM):
    """The visible colour at a marker centre, as a 0-255 RGB tuple.

    Read from the render rather than from the drawing's declared fill, because a
    hatched marker is a pattern fill that reports as black. White is skipped so a
    hatch reads as its ink colour rather than as the gaps between the strokes; a
    marker that really is white falls through to white.
    """
    rad = max(2, int(size * zoom * 0.30))
    y, x = int(cy * zoom), int(cx * zoom)
    patch = render[max(y - rad, 0):y + rad, max(x - rad, 0):x + rad].reshape(-1, 3)
    if not len(patch):
        return None
    for colour, _ in Counter(map(tuple, patch)).most_common():
        if colour != (255, 255, 255):
            return colour
    return (255, 255, 255)


def page_dots(page, render):
    """Every region marker on the page, deduplicated, with its rendered colour.

    Selected by size, not by colour - see MARKER_SIZE. Each marker is drawn twice,
    as a fill and a slightly larger outline, so coincident pairs are collapsed.
    """
    found = []
    for item in page.get_drawings():
        if not item.get("fill"):
            continue
        rect = item["rect"]
        size = max(rect.width, rect.height)
        if not (MARKER_SIZE[0] <= size <= MARKER_SIZE[1]):
            continue
        found.append(
            {
                "cx": (rect.x0 + rect.x1) / 2.0,
                "cy": (rect.y0 + rect.y1) / 2.0,
                "size": size,
                "x1": rect.x1,
            }
        )

    out = []
    for dot in sorted(found, key=lambda d: d["size"]):     # the fill, before its outline
        if any(abs(dot["cx"] - o["cx"]) <= MARKER_DEDUP_TOL
               and abs(dot["cy"] - o["cy"]) <= MARKER_DEDUP_TOL for o in out):
            continue
        colour = sample_colour(render, dot["cx"], dot["cy"], dot["size"])
        if colour is None:
            continue
        dot["colour"] = colour
        out.append(dot)
    return out


def label_right_of(page, swatch, tol=LEGEND_LINE_TOL, gap=LABEL_GAP_MAX):
    """The region name written beside a legend swatch.

    Read rightward from the swatch and stopped by the first wide horizontal gap,
    rather than taken from a fixed x window. The window was `x <= 105`, which
    holds only while the names are short: the telencephalic labels are single
    words at x = 89, but the caudal ones are phrases - "Anterior tuberal nucelus"
    runs from x = 64 to past x = 240. That window began *after* the first word and
    ended mid-phrase, so those legends came out empty or truncated to "Posterior".

    The gap test is what the old x bound was really buying: it keeps an in-figure
    annotation that happens to share the line - the "Dm OC" case - out of the name.
    """
    yc = (swatch["cy"] + swatch["cy"]) / 2.0
    words = [w for w in page.get_text("words")
             if abs((w[1] + w[3]) / 2.0 - yc) <= tol and w[0] >= swatch["x1"] - 2]
    words.sort(key=lambda w: w[0])
    parts, prev_x1 = [], None
    for x0, _y0, x1, _y1, text, *_ in words:
        if prev_x1 is not None and x0 - prev_x1 > gap:
            break
        parts.append(text)
        prev_x1 = x1
    return " ".join(parts).strip()


def figure_lines(page):
    """In-figure words only, grouped into lines."""
    words = [w for w in page.get_text("words") if w[0] > LEGEND_MAX_X]
    return group_words(words)


def build_legend(page, dots):
    """colour -> region name, from the left-margin swatch/label pairs."""
    legend = {}
    for dot in dots:
        if dot["cx"] >= LEGEND_MAX_X:
            continue
        name = label_right_of(page, dot)
        if name:
            legend[dot["colour"]] = name
    return legend


def plate_boxes(page):
    """Plate bitmaps on the page, ordered top to bottom."""
    plates = []
    for item in page.get_images(full=True):
        xref = item[0]
        try:
            bbox = page.get_image_bbox(item)
        except (ValueError, RuntimeError):
            continue
        if bbox.is_empty or bbox.width <= 0 or bbox.height <= 0:
            continue
        plates.append({"xref": xref, "bbox": bbox, "px_w": item[2], "px_h": item[3]})
    plates.sort(key=lambda p: (round(p["bbox"].y0, 1), round(p["bbox"].x0, 1)))
    return plates


def to_plate_pixels(plate, x, y):
    """Page point coordinates -> pixel coordinates inside the plate bitmap."""
    bbox = plate["bbox"]
    fx = (x - bbox.x0) / bbox.width
    fy = (y - bbox.y0) / bbox.height
    return fx * plate["px_w"], fy * plate["px_h"], fx, fy


# ---------------------------------------------------------------- QC overlay

def _font(size):
    for candidate in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_SEED = _font(26)


def write_overlay(image_bytes, seeds, texts, path):
    """Draw the extracted seeds back onto the plate so they can be eyeballed."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except OSError:
        return False
    draw = ImageDraw.Draw(img)
    radius = max(8, int(min(img.size) * 0.012))

    for seed in seeds:
        x, y = seed["x_px"], seed["y_px"]
        draw.ellipse(
            [x - radius, y - radius, x + radius, y + radius],
            outline=seed["colour_hex"],
            width=max(3, radius // 3),
        )
        draw.text((x + radius + 3, y - radius), seed["region"], fill=seed["colour_hex"], font=FONT_SEED)

    for text in texts:
        draw.text((text["x_px"], text["y_px"]), text["text"], fill="#00a0ff", font=FONT_SEED)

    img.save(path)
    return True


# ---------------------------------------------------------------- main


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(QC_DIR, exist_ok=True)

    doc = pymupdf.open(ATLAS_PDF)
    print(f"Opened {os.path.basename(ATLAS_PDF)} - {doc.page_count} pages")

    seed_rows, text_rows, legend_rows, plate_rows, gap_rows = [], [], [], [], []
    colour_usage = defaultdict(set)
    plate_seq = 0

    for page_no in range(doc.page_count):
        page = doc[page_no]
        render = render_page(page)
        dots = page_dots(page, render)
        legend = build_legend(page, dots)
        plates = plate_boxes(page)

        for colour, region in sorted(legend.items(), key=lambda kv: kv[1]):
            legend_rows.append(
                {"page": page_no + 1, "colour_hex": hexify(colour), "region": region}
            )
            colour_usage[hexify(colour)].add(region)

        figure_dots = [d for d in dots if d["cx"] >= LEGEND_MAX_X]
        figure_text = figure_lines(page)

        for plate_index, plate in enumerate(plates):
            plate_seq += 1
            plate_id = f"plate_{plate_seq:03d}"
            bbox = plate["bbox"]

            my_seeds = []
            for dot in figure_dots:
                if not (bbox.x0 <= dot["cx"] <= bbox.x1 and bbox.y0 <= dot["cy"] <= bbox.y1):
                    continue
                region = legend.get(dot["colour"])
                x_px, y_px, fx, fy = to_plate_pixels(plate, dot["cx"], dot["cy"])
                my_seeds.append(
                    {
                        "plate_id": plate_id,
                        "page": page_no + 1,
                        "plate_seq": plate_seq,
                        "region": REGION_CANONICAL.get(region, region) or "UNMAPPED",
                        "region_raw": region or "",
                        # "Rm (Raphe) ??" is a named region the author was unsure
                        # of, not an unnamed one - flagged, but kept with its name.
                        "is_unknown": int(region is None
                                          or region in UNKNOWN_LABELS
                                          or region.rstrip().endswith("??")),
                        "colour_hex": hexify(dot["colour"]),
                        "x_px": round(x_px, 1),
                        "y_px": round(y_px, 1),
                        "x_frac": round(fx, 4),
                        "y_frac": round(fy, 4),
                    }
                )

            my_texts = []
            for text, x0, yc in figure_text:
                if not (bbox.x0 <= x0 <= bbox.x1 and bbox.y0 <= yc <= bbox.y1):
                    continue
                x_px, y_px, _, _ = to_plate_pixels(plate, x0, yc)
                my_texts.append(
                    {
                        "plate_id": plate_id,
                        "page": page_no + 1,
                        "text": text,
                        "x_px": round(x_px, 1),
                        "y_px": round(y_px, 1),
                    }
                )

            extracted = doc.extract_image(plate["xref"])
            ext = extracted.get("ext", "png")
            image_path = os.path.join(OUT_DIR, f"{plate_id}_p{page_no + 1:02d}_{plate_index}.{ext}")
            with open(image_path, "wb") as fh:
                fh.write(extracted["image"])

            overlay_ok = write_overlay(
                extracted["image"],
                my_seeds,
                my_texts,
                os.path.join(QC_DIR, f"{plate_id}_overlay.png"),
            )

            seed_rows.extend(my_seeds)
            text_rows.extend(my_texts)
            plate_rows.append(
                {
                    "plate_id": plate_id,
                    "page": page_no + 1,
                    "index_on_page": plate_index,
                    "image_file": os.path.basename(image_path),
                    "px_w": plate["px_w"],
                    "px_h": plate["px_h"],
                    "n_seeds": len(my_seeds),
                    "n_text_labels": len(my_texts),
                    "regions": "|".join(sorted({s["region"] for s in my_seeds})),
                    "overlay_written": int(overlay_ok),
                }
            )
            if not my_seeds:
                gap_rows.append(
                    {
                        "plate_id": plate_id,
                        "page": page_no + 1,
                        "image_file": os.path.basename(image_path),
                        "reason": "no region seeds on this plate",
                    }
                )

    _write_csv(os.path.join(OUT_DIR, "plates.csv"), plate_rows)
    _write_csv(os.path.join(OUT_DIR, "seeds.csv"), seed_rows)
    _write_csv(os.path.join(OUT_DIR, "text_labels.csv"), text_rows)
    _write_csv(os.path.join(OUT_DIR, "legend_by_page.csv"), legend_rows)
    _write_csv(os.path.join(OUT_DIR, "gaps.csv"), gap_rows)

    _report(plate_rows, seed_rows, text_rows, gap_rows, colour_usage)


def _write_csv(path, rows):
    if not rows:
        print(f"  (nothing to write for {os.path.basename(path)})")
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {os.path.basename(path)}  ({len(rows)} rows)")


def _report(plate_rows, seed_rows, text_rows, gap_rows, colour_usage):
    print()
    print("=" * 72)
    print(f"plates extracted     : {len(plate_rows)}")
    print(f"region seed points   : {len(seed_rows)}")
    print(f"in-figure text labels: {len(text_rows)}")

    by_region = defaultdict(int)
    for s in seed_rows:
        by_region[s["region"]] += 1
    print(f"seeds per region     : {dict(sorted(by_region.items(), key=lambda kv: -kv[1]))}")

    unmapped = [s for s in seed_rows if s["region"] == "UNMAPPED"]
    print(f"seeds with no legend entry: {len(unmapped)}")

    inconsistent = {c: r for c, r in colour_usage.items() if len(r) > 1}
    print(f"colours reused for different regions: {len(inconsistent)}")
    for colour, regions in sorted(inconsistent.items()):
        print(f"    {colour} -> {sorted(regions)}")

    print(f"plates with no seeds : {len(gap_rows)}  <- still need labelling")
    pages = sorted({g["page"] for g in gap_rows})
    print(f"    on pages: {pages}")

    print("=" * 72)
    print("NEXT: check atlas/plates/qc/ overlays - seeds must land on the right")
    print("      structures before any of this is registered to the template.")


if __name__ == "__main__":
    main()
