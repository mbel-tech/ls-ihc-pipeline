"""Stage 4a - pull the labelled plate series out of the salmon atlas PDF.

The atlas is a working document, not a scan: every region marker is a vector
dot with a distinct fill colour, and each page carries its own legend mapping
those colours to region names. That makes the whole thing machine-readable.

Page geometry (verified against pages 5, 6, 9, 18, 20, 21, 25 of the 2026-09
atlas):
  - legend swatches sit in the left margin at centre x < ~105, OR in the band
    above the topmost plate. Both carry their label to the right
  - legend labels are read rightward from their swatch to the first wide gap.
    They are NOT confined to x ~ 89: that holds for the single-word
    telencephalic names, but the caudal ones are phrases running past x = 240
  - plate bitmaps are image XObjects, once overlay insets and marker stamps are
    filtered out - see atlas_pdf.py. With that filter their bboxes do not overlap
  - in-figure dots fall inside a plate bbox; markers are a uniform 22.7 pt
  - in-figure text (e.g. "Optic Chiasm") is annotation, not legend

Markers are found by SIZE, not by colour, and deduplicated by OVERLAP.

By size, because a colour filter used to discard two of the atlas's own region
colours: historically black was the posterior tuberculum, and the hatched
anterior tuberal nucleus was a pattern fill that reported as black too. Neither
is true of the 2026-09 atlas, where the author redrew both in solid colour, but
the size rule costs nothing and the colour rule has failed here before. The
visible colour is still read from a render of the page, since for a pattern fill
the declared fill and what you see are different.

By overlap, because the PowerPoint re-export draws each marker as THREE stacked
paths spread over ~9.5 pt, where the old Ghostscript export drew two coincident
to within 0.08 pt. A fixed 3 pt tolerance merges two of the three and counts
every marker twice - Dl came out at 182 rather than 142. Two paths are one
marker when their centres are closer than half the larger one's size, which is
12.4 pt for a 24.7 pt marker and still separates the closest genuinely distinct
pair in the atlas, 32.4 pt apart on page 21.

Some markers survive only as pixels. Where PowerPoint flattened part of a plate
into an overlay inset it took the vector dots with it - 66 of them over pages
5 to 8. Those are recovered from the render by colour, against the page's own
legend; see `recover_raster_seeds`. Without that step the telencephalic counts
come out a third short.

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
import importlib.util
import io
import json
import os
from collections import Counter, defaultdict

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

# Which images on a page count as plates is shared with 04a2, which re-derives
# the same boxes from the PDF and pairs them with this stage's rows by position.
# One definition, so the two cannot drift apart.
_spec = importlib.util.spec_from_file_location(
    "_atlas_pdf", os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlas_pdf.py"))
ATLAS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ATLAS)

# ---------------------------------------------------------------- configuration

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# The atlas path was hardcoded here until 2026-09-06, while 04a2 and 04a4 read it
# from config - so pointing config at a new atlas moved those two stages and left
# this one parsing the old PDF, with nothing to say the sets had diverged.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

ATLAS_PDF = CONFIG["atlas_pdf"]
OUT_DIR = os.path.join(CONFIG["out_root"], "atlas", "plates")
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
# One marker is drawn as several stacked paths - two in the old export, three in
# the 2026-09 one, spread over ~9.5 pt. Two paths are the same marker when their
# centres are closer than this fraction of the larger one's size; at 0.5 the
# smaller centre lies inside the larger disc. A fixed pt tolerance cannot do
# this - 3.0 caught the old coincident pair and read the new triple as two.
MARKER_OVERLAP_FRAC = 0.5
# A marker's nominal diameter, used to size the search for one in a raster.
MARKER_NOMINAL_PT = 22.7
# Page render zoom used to read a marker's true colour. Needed because a hatched
# marker (Anterior tuberal nucleus) has a *pattern* fill, which the drawing
# reports as plain black - the declared fill and the visible colour differ.
COLOUR_ZOOM = 4.0
# Recovering a marker from a raster: how far a pixel may sit from a legend colour
# (0-255 per channel - JPEG-tolerant, but well inside the gap between any two of
# this atlas's colours), and the fraction of a marker's area a blob must cover.
# The area range is wide because an inset crops some markers at its edge.
RASTER_COLOUR_TOL = 12
RASTER_AREA_RANGE = (0.45, 1.8)

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
}
# The "nucelus" typo entry retired 2026-09-06: the 2026-09 atlas spells that
# region "Nucleus Anterior tuberal", with no typo and in a different word order,
# so the old rewrite could never fire again. Region names are otherwise carried
# exactly as the atlas writes them - no abbreviating, no reinterpreting.

# A second shade used for a region the legend keys only once. On page 20 the
# migrated posterior tuberal nucleus is marked in two peach shades, one per
# section, and only #fbd4b5 carries the legend swatch. Confirmed by the operator
# 2026-09-06. Keyed by page, so a shade cannot leak into another page's palette,
# and applied when looking the colour up - `colour_hex` still records what was
# actually drawn, so the substitution stays visible in the output.
COLOUR_ALIAS = {
    (20, "#f9c090"): "#fbd4b5",
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

    Selected by size, not by colour - see MARKER_SIZE. One marker is drawn as
    several stacked paths, so overlapping paths are collapsed: two belong to the
    same marker when their centres are closer than MARKER_OVERLAP_FRAC of the
    larger one's size.

    Which path of a cluster IS the marker is then settled by size, not by
    position. The 2026-09 export spreads a marker's three paths over 9.5 pt, so
    taking the largest or the smallest displaces every seed by 2.8 or 6.4 pt.
    The path nearest MARKER_NOMINAL_PT is the marker; the others are its outline
    and its drop shadow. Over the 133 markers on the pages whose layout did not
    change, that choice reproduces the previous atlas's seed positions to 0.00 pt,
    where taking the largest gives 2.78 and the smallest 6.40.
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

    clusters = []
    for path in sorted(found, key=lambda d: -d["size"]):   # the widest path leads
        for cluster in clusters:
            lead = cluster[0]
            gap = ((path["cx"] - lead["cx"]) ** 2 + (path["cy"] - lead["cy"]) ** 2) ** 0.5
            if gap < MARKER_OVERLAP_FRAC * max(path["size"], lead["size"]):
                cluster.append(path)
                break
        else:
            clusters.append([path])

    out = []
    for cluster in clusters:
        dot = min(cluster, key=lambda d: abs(d["size"] - MARKER_NOMINAL_PT))
        colour = sample_colour(render, dot["cx"], dot["cy"], dot["size"])
        if colour is None:
            continue
        dot["colour"] = colour
        dot["n_paths"] = len(cluster)
        out.append(dot)
    return out


def recover_raster_seeds(page, render, legend, known, zoom=COLOUR_ZOOM):
    """Region markers that survive only as pixels, read back out of the render.

    Where PowerPoint flattened part of a plate into an overlay inset it took the
    vector dots inside it with it - 66 markers over pages 5 to 8 of the 2026-09
    atlas, a third of the telencephalic seeds. Those areas are exactly
    `atlas_pdf.inset_boxes`, and the markers in them are still drawn in the
    page's own legend colours at the usual size, so they can be read back:
    threshold the render on each legend colour inside an inset, keep the
    connected components that are marker-sized, take their centroids.

    Deliberately narrow. It looks only inside insets, matches only colours this
    page's legend already names, and drops anything within half a marker of a
    dot the drawing list already supplied. So it can restore a marker the export
    lost, but it cannot invent a region, and it cannot double-count one.
    """
    insets = ATLAS.inset_boxes(page)
    if not insets or not legend:
        return []

    mask = np.zeros(render.shape[:2], bool)
    for rect in insets:
        mask[int(rect.y0 * zoom):int(rect.y1 * zoom),
             int(rect.x0 * zoom):int(rect.x1 * zoom)] = True

    marker_area = np.pi * (MARKER_NOMINAL_PT * zoom / 2.0) ** 2
    seen = list(known)
    found = []
    for colour in legend:
        hit = (np.abs(render - np.array(colour)).max(axis=2) <= RASTER_COLOUR_TOL) & mask
        labels, count = ndimage.label(hit)
        if not count:
            continue
        sizes = ndimage.sum(hit, labels, range(1, count + 1))
        for index, size in enumerate(sizes, start=1):
            if not (marker_area * RASTER_AREA_RANGE[0] <= size
                    <= marker_area * RASTER_AREA_RANGE[1]):
                continue
            cy, cx = ndimage.center_of_mass(hit, labels, index)
            cx, cy = cx / zoom, cy / zoom
            if any(((cx - d["cx"]) ** 2 + (cy - d["cy"]) ** 2) ** 0.5
                   < MARKER_NOMINAL_PT / 2.0 for d in seen):
                continue
            dot = {"cx": cx, "cy": cy, "size": MARKER_NOMINAL_PT,
                   "x1": cx + MARKER_NOMINAL_PT / 2.0,
                   "colour": colour, "from_raster": True}
            found.append(dot)
            seen.append(dot)
    return found


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


def is_legend_key(dot, plate_top):
    """True when a dot is a legend swatch rather than a region marker.

    Swatches sit in the left margin, or - for the two regions the 2026-09 atlas
    keys inside the figure area rather than in the margin - in the band above the
    topmost plate on the page. Both are places a region marker cannot be, since a
    marker lies inside a plate. Before that second test the swatches for
    "Migrated posterior tuberal nucleus" (page 20, cx 290) and "Nucleus Posterior
    Tuberal" (page 21, cx 161) read as figure markers, so neither region was ever
    named and all ten of their seeds came out UNMAPPED.
    """
    return dot["cx"] < LEGEND_MAX_X or dot["cy"] < plate_top


def build_legend(page, dots, plate_top):
    """colour -> region name, from the swatch/label pairs."""
    legend = {}
    for dot in dots:
        if not is_legend_key(dot, plate_top):
            continue
        name = label_right_of(page, dot)
        if name:
            legend[dot["colour"]] = name
    return legend


def plate_boxes(page):
    """Plate bitmaps on the page, ordered top to bottom.

    Shared with 04a2, so the two stages cannot disagree about what a plate is.
    The rule - and why an image XObject is not automatically one - is in
    atlas_pdf.py.
    """
    return ATLAS.plate_boxes(page)


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
    raster_pages = {}

    for page_no in range(doc.page_count):
        page = doc[page_no]
        render = render_page(page)
        dots = page_dots(page, render)
        # The plates are needed before the legend now: a swatch is recognised by
        # sitting above the topmost plate as well as by sitting in the margin.
        plates = plate_boxes(page)
        plate_top = min((p["bbox"].y0 for p in plates), default=float("inf"))
        legend = build_legend(page, dots, plate_top)
        by_hex = {hexify(colour): region for colour, region in legend.items()}

        for colour, region in sorted(legend.items(), key=lambda kv: kv[1]):
            legend_rows.append(
                {"page": page_no + 1, "colour_hex": hexify(colour), "region": region}
            )
            colour_usage[hexify(colour)].add(region)

        figure_dots = [d for d in dots if not is_legend_key(d, plate_top)]
        recovered = recover_raster_seeds(page, render, legend, figure_dots)
        if recovered:
            raster_pages[page_no + 1] = len(recovered)
            figure_dots = figure_dots + recovered
        figure_text = figure_lines(page)

        for plate_index, plate in enumerate(plates):
            plate_seq += 1
            plate_id = f"plate_{plate_seq:03d}"
            bbox = plate["bbox"]

            my_seeds = []
            for dot in figure_dots:
                if not (bbox.x0 <= dot["cx"] <= bbox.x1 and bbox.y0 <= dot["cy"] <= bbox.y1):
                    continue
                colour_hex = hexify(dot["colour"])
                # A shade the legend does not key in its own right resolves to the
                # colour it belongs to; colour_hex below still records what was drawn.
                region = by_hex.get(COLOUR_ALIAS.get((page_no + 1, colour_hex), colour_hex))
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
                        "colour_hex": colour_hex,
                        # 1 where the marker was read back out of a flattened
                        # inset rather than from the PDF drawing list.
                        "from_raster": int(bool(dot.get("from_raster"))),
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
                    "n_seeds_raster": sum(s["from_raster"] for s in my_seeds),
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

    _report(plate_rows, seed_rows, text_rows, gap_rows, colour_usage, raster_pages)


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


def _report(plate_rows, seed_rows, text_rows, gap_rows, colour_usage, raster_pages):
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

    # Say so out loud. A fallback that quietly stops firing is worse than none:
    # if a future atlas stops flattening its plates this drops to zero and the
    # seed count drops with it, and that has to be visible here.
    recovered = sum(s["from_raster"] for s in seed_rows)
    print(f"seeds recovered from flattened insets: {recovered}"
          + (f"  on pages {sorted(raster_pages)}" if raster_pages else ""))

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
