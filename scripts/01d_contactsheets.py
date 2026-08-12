"""Stage 1 - per-animal contact sheets and a browsable gallery.

Turns ~2,570 section overviews into a handful of pages you can actually flip
through, ordered rostro-caudal within each animal so a signal gradient along the
brain reads as a gradient across the page.

Because Stage 1 froze the display range across the whole dataset, brightness
differences between sections here are real differences in signal, not
auto-contrast artifacts. That is what makes the sheets worth looking at.

Sections flagged by QC (out of focus, saturated, almost no tissue) are marked
rather than dropped, so a gap in the series is never silently invented.

Run:  python 01d_contactsheets.py
      python 01d_contactsheets.py --kind MARK     # marker channel only
      python 01d_contactsheets.py --cols 6 --thumb 260
"""

import argparse
import csv
import html
import json
import os
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
SHEET_DIR = os.path.join(OUT_ROOT, "contactsheets")
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")

# QC limits, expressed relative to the dataset so they adapt to the data rather
# than to a number picked in advance.
FOCUS_LOW_QUANTILE = 0.05
MIN_TISSUE_FRACTION = 0.01
MAX_SATURATED_FRACTION = 0.02

LABEL_H = 22
PAD = 6
HEADER_H = 46

# Display-only levels adjustment, applied identically to every thumbnail.
# The exported PNGs put background near 8-bit value 10, which the yellow marker
# channel renders as a washed olive field across the whole frame. Lifting the
# black point and applying a mild gamma makes tissue legible. It is a single
# fixed transform, so it does NOT reintroduce the per-image auto-contrast that
# would destroy cross-section comparability - two sections that differ in
# brightness still differ by the same amount afterwards.
BLACK_POINT = 12
GAMMA = 0.75
DISPLAY_LUT = [
    min(255, int(round(255.0 * (max(0, v - BLACK_POINT) / (255.0 - BLACK_POINT)) ** GAMMA)))
    for v in range(256)
]


def _font(size, bold=False):
    names = [r"C:\Windows\Fonts\arialbd.ttf"] if bold else [r"C:\Windows\Fonts\arial.ttf"]
    names.append(r"C:\Windows\Fonts\arial.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_LABEL = _font(12)
FONT_HEADER = _font(19, bold=True)
FONT_FLAG = _font(12, bold=True)


def chosen_variants():
    """(animal, slide, marker) -> variant, from Stage 2's re-scan resolution.

    Five slides were scanned twice (LS45_8b/8c, LS45_9b/9c, LS61_2b/2c,
    LS61_4b/4c, LS85_7a/7b-). Both copies carry their own 1..N section_order,
    so including both interleaves two series into one sheet - which is exactly
    what the alternating sl1/sl8 labels revealed.
    """
    path = os.path.join(OUT_ROOT, "manifest", "variant_choices.csv")
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {
            (r["animal"], r["slide"], r["marker_channel"]): r["chosen_variant"]
            for r in csv.DictReader(fh)
        }


def load_qc():
    if not os.path.exists(QC_CSV):
        raise SystemExit(f"{QC_CSV} not found - run 01_overviews.groovy first.")
    with open(QC_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    picks = chosen_variants()
    if picks:
        before = len(rows)
        rows = [
            r for r in rows
            if picks.get((r["animal"], r["slide"], r["marker_channel"]), r["variant"]) == r["variant"]
        ]
        if before != len(rows):
            print(f"  dropped {before - len(rows)} sections from superseded re-scans")
    for r in rows:
        for key in ("focus_score", "tissue_fraction", "tissue_area_mm2", "saturated_fraction"):
            try:
                r[key] = float(r[key])
            except (TypeError, ValueError):
                r[key] = 0.0
        r["section_order"] = int(r["section_order"] or 0)
        r["slide"] = int(r["slide"] or 0)
    return rows


def quantile(values, q):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def flag(row, focus_floor):
    """Short QC tag, or empty when the section is fine."""
    tags = []
    if row["tissue_fraction"] < MIN_TISSUE_FRACTION:
        tags.append("EMPTY")
    if row["focus_score"] < focus_floor:
        tags.append("BLUR?")
    if row["saturated_fraction"] > MAX_SATURATED_FRACTION:
        tags.append("SAT")
    return "/".join(tags)


def thumb_path(row, kind):
    return os.path.join(
        OVERVIEW_DIR, row["animal"], row["marker_channel"], f"{row['scene_uid']}_{kind}.png"
    )


def build_sheet(rows, animal, marker, kind, cols, thumb_w, out_dir):
    """Paged montage of one animal's series in one marker."""
    rows = sorted(rows, key=lambda r: (r["section_order"], r["slide"]))
    focus_floor = quantile([r["focus_score"] for r in rows], FOCUS_LOW_QUANTILE)

    entries = []
    for r in rows:
        path = thumb_path(r, kind)
        if os.path.exists(path):
            entries.append((r, path))
    if not entries:
        return []

    # Page height follows the tallest thumbnail so portrait sections are not
    # squeezed and landscape ones do not leave a band of white.
    with Image.open(entries[0][1]) as probe:
        aspect = probe.height / probe.width
    thumb_h = int(round(thumb_w * aspect))
    per_page = cols * max(1, int(1400 / (thumb_h + LABEL_H + PAD)))

    written = []
    for page_no, start in enumerate(range(0, len(entries), per_page), start=1):
        chunk = entries[start:start + per_page]
        n_rows = -(-len(chunk) // cols)
        width = cols * (thumb_w + PAD) + PAD
        height = HEADER_H + n_rows * (thumb_h + LABEL_H + PAD) + PAD

        canvas = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (PAD + 2, 10),
            f"{animal}   {marker}   {kind}   sections {chunk[0][0]['section_order']}"
            f"-{chunk[-1][0]['section_order']} of {entries[-1][0]['section_order']}"
            f"   (page {page_no})   rostro-caudal order, fixed display range",
            fill="black", font=FONT_HEADER,
        )

        for i, (row, path) in enumerate(chunk):
            cx = PAD + (i % cols) * (thumb_w + PAD)
            cy = HEADER_H + (i // cols) * (thumb_h + LABEL_H + PAD)
            try:
                with Image.open(path) as im:
                    im = im.convert("RGB").resize((thumb_w, thumb_h), Image.LANCZOS)
                    im = im.point(DISPLAY_LUT * 3)
                    canvas.paste(im, (cx, cy))
            except OSError:
                draw.rectangle([cx, cy, cx + thumb_w, cy + thumb_h], outline="#c00000")

            tag = flag(row, focus_floor)
            label = f"{row['section_order']:>3}  sl{row['slide']}  s{row['scene_index']}"
            draw.text((cx + 2, cy + thumb_h + 3), label, fill="#303030", font=FONT_LABEL)
            if tag:
                draw.text(
                    (cx + thumb_w - 4 - 7 * len(tag), cy + thumb_h + 3),
                    tag, fill="#c00000", font=FONT_FLAG,
                )
                draw.rectangle(
                    [cx, cy, cx + thumb_w - 1, cy + thumb_h - 1], outline="#c00000", width=2
                )

        out = os.path.join(out_dir, f"{animal}_{marker}_{kind}_p{page_no:02d}.png")
        canvas.save(out)
        written.append(out)
    return written


def build_gallery(by_key, sheets, kind):
    """Single HTML index linking every sheet and every full-size overview."""
    parts = [
        "<meta charset='utf-8'><title>LS section gallery</title>",
        "<style>",
        "body{font:14px system-ui,sans-serif;margin:24px;background:#fafafa;color:#222}",
        "h1{font-size:20px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}",
        ".grid{display:flex;flex-wrap:wrap;gap:6px}",
        ".cell{width:150px;text-align:center;font-size:11px;color:#555}",
        ".cell img{width:150px;border:1px solid #ccc;background:#fff;display:block}",
        ".cell.flag img{border:2px solid #c00}",
        ".sheets a{display:inline-block;margin-right:10px}",
        "</style>",
        "<h1>LS whole-brain section gallery</h1>",
        f"<p>Display range frozen across the dataset, so brightness differences are real. "
        f"Showing <b>{kind}</b>. Red border = QC flag.</p>",
    ]

    for (animal, marker) in sorted(by_key, key=lambda k: (int(k[0][2:]), k[1])):
        rows = sorted(by_key[(animal, marker)], key=lambda r: r["section_order"])
        focus_floor = quantile([r["focus_score"] for r in rows], FOCUS_LOW_QUANTILE)
        parts.append(f"<h2>{html.escape(animal)} &mdash; {html.escape(marker)} "
                     f"({len(rows)} sections)</h2>")

        mine = [s for s in sheets if os.path.basename(s).startswith(f"{animal}_{marker}_{kind}")]
        if mine:
            parts.append("<p class='sheets'>contact sheets: " + " ".join(
                f"<a href='{html.escape(os.path.basename(s))}'>page {i + 1}</a>"
                for i, s in enumerate(sorted(mine))
            ) + "</p>")

        parts.append("<div class='grid'>")
        for r in rows:
            rel = os.path.relpath(thumb_path(r, kind), SHEET_DIR).replace("\\", "/")
            tag = flag(r, focus_floor)
            parts.append(
                f"<div class='cell{' flag' if tag else ''}'>"
                f"<a href='{html.escape(rel)}'><img loading='lazy' src='{html.escape(rel)}'></a>"
                f"{r['section_order']} sl{r['slide']} {html.escape(tag)}</div>"
            )
        parts.append("</div>")

    out = os.path.join(SHEET_DIR, "gallery.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="RGB", choices=["RGB", "MARK", "DAPI"])
    ap.add_argument("--cols", type=int, default=8)
    ap.add_argument("--thumb", type=int, default=200)
    args = ap.parse_args()

    os.makedirs(SHEET_DIR, exist_ok=True)
    rows = load_qc()
    print(f"{len(rows)} sections in focus.csv")

    by_key = defaultdict(list)
    for r in rows:
        by_key[(r["animal"], r["marker_channel"])].append(r)

    sheets = []
    for (animal, marker), group in sorted(by_key.items(), key=lambda kv: (int(kv[0][0][2:]), kv[0][1])):
        written = build_sheet(group, animal, marker, args.kind, args.cols, args.thumb, SHEET_DIR)
        sheets.extend(written)
        print(f"  {animal:<7} {marker:<6} {len(group):>4} sections -> {len(written)} page(s)")

    gallery = build_gallery(by_key, sheets, args.kind)

    flagged = 0
    for (animal, marker), group in by_key.items():
        floor = quantile([r["focus_score"] for r in group], FOCUS_LOW_QUANTILE)
        flagged += sum(1 for r in group if flag(r, floor))

    print()
    print("=" * 72)
    print(f"contact sheet pages : {len(sheets)}")
    print(f"QC-flagged sections : {flagged} of {len(rows)}")
    print(f"gallery             : {gallery}")
    print("=" * 72)


if __name__ == "__main__":
    main()
