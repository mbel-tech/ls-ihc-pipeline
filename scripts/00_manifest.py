"""Stage 0 - manifest, slide-grid reconstruction, and slide-map figures.

Reads every CZI header (loose files and STORED zip entries alike) without
extracting or decoding a single pixel, then:

  1. manifest/manifest_files.csv   one row per CZI
  2. manifest/manifest_scenes.csv  one row per brain section, with the
                                   reconstructed slide grid and the serial
                                   number under each candidate convention
  3. qc/slidemaps/<file>.png       one panel per candidate mounting
                                   convention, for the user to confirm once
  4. qc/slide_layout_summary.csv   grid shape per file, so odd slides stand out
  5. qc/slide_layout_review.csv    slides whose row count needs a human

Nothing downstream may assume a mounting convention until the user picks one.

Run:  python 00_manifest.py
      python 00_manifest.py --accept-suggestions   # write suggested row counts
"""

import csv
import glob
import json
import os
import re
import sys
import zipfile
from collections import defaultdict

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from czi_meta import read_metadata, summarise  # noqa: E402

# ---------------------------------------------------------------- configuration

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

SOURCE_DIR = CONFIG["source_dir"]
OUT_ROOT = CONFIG["out_root"]
# Confirmed mounting convention; section_order is written from this column.
ORDER_CONVENTION = CONFIG["section_order_convention"]

MANIFEST_DIR = os.path.join(OUT_ROOT, "manifest")
SLIDEMAP_DIR = os.path.join(OUT_ROOT, "qc", "slidemaps")
QC_DIR = os.path.join(OUT_ROOT, "qc")

# Filenames look like LS45_8b.czi, LS85_7b-.czi, LS53_2b-_A568.czi
NAME_RE = re.compile(r"^(LS\d+)_(\d+)([a-z])(-?)(_[A-Za-z0-9]+)?\.czi$", re.IGNORECASE)

# A gap larger than this fraction of the median scene dimension starts a new
# row/column. Scenes on a slide are separated by far more than their own size,
# so this is not a sensitive parameter.
GAP_FRACTION = 0.6

CONVENTIONS = [
    ("S_scan_order", "Scan order: scene index as acquired  <- leading candidate"),
    ("A_rows_LR", "Rows: left -> right, top row first"),
    ("B_cols_TB", "Columns: top -> bottom, left column first"),
    ("C_rows_serpentine", "Serpentine rows: L->R, then R->L"),
    ("D_cols_serpentine", "Serpentine columns: T->B, then B->T"),
]

PANEL_W = 560
MARGIN = 34
PANEL_COLS = 2
TITLE_H = 30

# Cycled per detected row so grouping errors are visible in the figure.
ROW_COLOURS = [
    "#e8f0fb", "#fdeee6", "#eaf6ec", "#f6ecf7",
    "#fdf6e0", "#e6f6f8", "#f9e9ec", "#eeeef8",
]

# Slides whose automatic row count is wrong. Columns: file, n_rows
OVERRIDES_CSV = os.path.join(MANIFEST_DIR, "layout_overrides.csv")

# A within-row Y spread this large relative to section height usually means two
# rows were merged into one.
ROW_SPREAD_FLAG = 0.8


# ---------------------------------------------------------------- source discovery


def discover_sources():
    """Yield (source, member, opener) for every CZI, loose files first.

    `source` is either "LOOSE" or the zip filename; `opener` returns a fresh
    binary file object positioned at 0.
    """
    entries = []

    for path in sorted(glob.glob(os.path.join(SOURCE_DIR, "*.czi"))):
        name = os.path.basename(path)
        entries.append(("LOOSE", name, path, (lambda p: (lambda: open(p, "rb")))(path)))

    for zpath in sorted(glob.glob(os.path.join(SOURCE_DIR, "*.zip"))):
        zname = os.path.basename(zpath)
        try:
            zf = zipfile.ZipFile(zpath)
        except zipfile.BadZipFile:
            print(f"  !! cannot open {zname}, skipping")
            continue
        for info in zf.infolist():
            if not info.filename.lower().endswith(".czi"):
                continue
            entries.append(
                (
                    zname,
                    info.filename,
                    zpath,
                    (lambda z, n: (lambda: z.open(n)))(zf, info.filename),
                )
            )
    return entries


def parse_name(member):
    base = os.path.basename(member)
    m = NAME_RE.match(base)
    if not m:
        return None
    return {
        "animal": m.group(1).upper(),
        "slide": int(m.group(2)),
        "variant": m.group(3).lower(),
        "name_suffix": (m.group(4) or "") + (m.group(5) or ""),
    }


# ---------------------------------------------------------------- slide grid


def adaptive_threshold(values, fallback):
    """Find the natural break between within-column and between-column gaps.

    Scene size is a poor scale for this: some slides have scan regions drawn
    tightly around small sections, others generously around large ones, and
    sections are often staggered. The spacing between scenes is far more
    reliable, so the threshold is read off the gap distribution itself.
    """
    gaps = np.diff(np.sort(np.asarray(values, dtype=float)))
    gaps = gaps[gaps > 0]
    if len(gaps) < 2:
        return fallback

    ordered = np.sort(gaps)
    k = int(np.argmax(np.diff(ordered)))
    lo, hi = ordered[k], ordered[k + 1]
    if hi < 2.0 * lo:
        # No natural break in the gap distribution. That is ambiguous between
        # "all one group" and "all separate groups", so defer to the physical
        # scale: rows cannot sit closer together than a fraction of a section.
        return fallback
    return (lo + hi) / 2.0


def group_by_threshold(values, threshold):
    """Split sorted-adjacent values wherever the gap exceeds threshold.

    Returned group ids are ranked by position, so 0 is leftmost/topmost.
    """
    values = np.asarray(values, dtype=float)
    order = np.argsort(values)
    groups = np.empty(len(values), dtype=int)
    current = 0
    groups[order[0]] = 0
    for i in range(1, len(order)):
        if values[order[i]] - values[order[i - 1]] > threshold:
            current += 1
        groups[order[i]] = current
    return groups


def split_at_largest_gaps(values, n_groups):
    """Force exactly n_groups by cutting at the (n_groups - 1) largest gaps."""
    values = np.asarray(values, dtype=float)
    order = np.argsort(values)
    ordered = values[order]
    gaps = np.diff(ordered)
    cuts = set(np.argsort(gaps)[-(n_groups - 1):].tolist()) if n_groups > 1 else set()

    groups = np.empty(len(values), dtype=int)
    current = 0
    for position, i in enumerate(order):
        if position > 0 and (position - 1) in cuts:
            current += 1
        groups[i] = current
    return groups


def build_grid(scenes, forced_rows=None):
    """Assign a (row, col) to each scene from its stage centre coordinates.

    Rows first. Sections are laid down in rows along the slide, and rows are
    frequently staggered in X (LS105_8a's two rows are offset by ~3 mm), which
    a column-first model cannot represent at all. Columns are then just the
    rank across each row, which tolerates any amount of stagger.

    `forced_rows` comes from manifest/layout_overrides.csv for the minority of
    slides where the automatic row count is wrong.
    """
    xs = np.array([s["center_x_um"] for s in scenes], dtype=float)
    ys = np.array([s["center_y_um"] for s in scenes], dtype=float)
    hs = np.array([s["height_um"] or 0.0 for s in scenes], dtype=float)

    if forced_rows:
        rows = split_at_largest_gaps(ys, forced_rows)
    else:
        fallback = GAP_FRACTION * (np.median(hs) if np.median(hs) > 0 else 1000.0)
        rows = group_by_threshold(ys, adaptive_threshold(ys, fallback))

    cols = np.zeros(len(scenes), dtype=int)
    for r in np.unique(rows):
        members = np.where(rows == r)[0]
        for rank, i in enumerate(members[np.argsort(xs[members])]):
            cols[i] = rank
    return rows, cols


def suggest_rows(scenes, max_rows=6):
    """Fewest rows that keep every row's Y spread physically plausible.

    Splitting more finely always reduces spread, so the smallest workable row
    count is the honest answer rather than the best-scoring one.
    """
    ys = np.array([s["center_y_um"] for s in scenes], dtype=float)
    for n in range(1, min(max_rows, len(scenes)) + 1):
        candidate = split_at_largest_gaps(ys, n)
        if row_spread_ratio(scenes, candidate) <= ROW_SPREAD_FLAG:
            return n
    return None


def row_spread_ratio(scenes, rows):
    """Widest within-row Y spread as a fraction of section height.

    Two rows merged into one shows up here as a ratio near or above 1, which is
    the failure mode worth flagging for manual review.
    """
    ys = np.array([s["center_y_um"] for s in scenes], dtype=float)
    hs = np.array([s["height_um"] or 0.0 for s in scenes], dtype=float)
    median_h = np.median(hs) if np.median(hs) > 0 else 1.0
    spreads = [
        ys[rows == r].max() - ys[rows == r].min()
        for r in np.unique(rows)
        if (rows == r).sum() > 1
    ]
    return (max(spreads) / median_h) if spreads else 0.0


def serial_numbers(rows, cols, scenes):
    """Serial number per scene under each candidate mounting convention.

    S_scan_order is the order the scan regions were acquired in. Operators draw
    those regions systematically, so on slides where no clean grid exists it is
    usually the only ordering that reflects how the sections were actually laid
    down - the geometry alone cannot recover that.
    """
    n_rows, n_cols = int(rows.max()) + 1, int(cols.max()) + 1
    idx = np.arange(len(rows))
    out = {}

    scan_rank = {s["index"]: r for r, s in enumerate(sorted(scenes, key=lambda s: s["index"]))}
    out["S_scan_order"] = np.array([scan_rank[s["index"]] + 1 for s in scenes])

    def assign(keyfunc):
        order = sorted(idx, key=keyfunc)
        serial = np.empty(len(idx), dtype=int)
        for position, i in enumerate(order):
            serial[i] = position + 1
        return serial

    out["A_rows_LR"] = assign(lambda i: (rows[i], cols[i]))
    out["B_cols_TB"] = assign(lambda i: (cols[i], rows[i]))
    out["C_rows_serpentine"] = assign(
        lambda i: (rows[i], cols[i] if rows[i] % 2 == 0 else n_cols - 1 - cols[i])
    )
    out["D_cols_serpentine"] = assign(
        lambda i: (cols[i], rows[i] if cols[i] % 2 == 0 else n_rows - 1 - rows[i])
    )
    return out


# ---------------------------------------------------------------- slide-map figure


def _font(size):
    for candidate in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_TITLE = _font(15)
FONT_LABEL = _font(11)
FONT_SERIAL = _font(20)


def render_slidemap(path, member, scenes, rows, cols, serials):
    """One panel per candidate convention, sized to the slide's own aspect."""
    xs = np.array([s["center_x_um"] for s in scenes])
    ys = np.array([s["center_y_um"] for s in scenes])
    ws = np.array([s["width_um"] or 0.0 for s in scenes])
    hs = np.array([s["height_um"] or 0.0 for s in scenes])

    x0, x1 = (xs - ws / 2).min(), (xs + ws / 2).max()
    y0, y1 = (ys - hs / 2).min(), (ys + hs / 2).max()
    span_x = max(x1 - x0, 1.0)
    span_y = max(y1 - y0, 1.0)

    # Scale to panel width and let height follow, so wide slides do not leave
    # two thirds of every panel empty.
    scale = (PANEL_W - 2 * MARGIN) / span_x
    panel_h = max(int(MARGIN + 18 + span_y * scale + MARGIN), 140)

    n_panel_rows = -(-len(CONVENTIONS) // PANEL_COLS)
    canvas = Image.new(
        "RGB", (PANEL_W * PANEL_COLS, panel_h * n_panel_rows + TITLE_H), "white"
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (12, 8),
        f"{member}   -   {len(scenes)} scenes   -   detected {rows.max() + 1} row(s) x "
        f"{cols.max() + 1} col(s)   -   stage X right, stage Y down   -   fill colour = detected row",
        fill="black",
        font=FONT_TITLE,
    )

    for panel, (key, description) in enumerate(CONVENTIONS):
        ox = (panel % PANEL_COLS) * PANEL_W
        oy = (panel // PANEL_COLS) * panel_h + TITLE_H
        draw.rectangle([ox + 2, oy + 2, ox + PANEL_W - 3, oy + panel_h - 3], outline="#c8c8c8")
        draw.text(
            (ox + MARGIN, oy + 8),
            f"{key}   {description}",
            fill="#a03000" if key == "S_scan_order" else "#0050a0",
            font=FONT_LABEL,
        )

        for i, sc in enumerate(scenes):
            left = ox + MARGIN + (xs[i] - ws[i] / 2 - x0) * scale
            top = oy + MARGIN + 16 + (ys[i] - hs[i] / 2 - y0) * scale
            right = left + max(ws[i] * scale, 6)
            bottom = top + max(hs[i] * scale, 6)
            # Fill encodes the detected row, so a mis-grouped slide is obvious
            # at a glance rather than hidden inside the numbering.
            draw.rectangle(
                [left, top, right, bottom],
                outline="#3c3c3c",
                fill=ROW_COLOURS[int(rows[i]) % len(ROW_COLOURS)],
            )
            draw.text(
                ((left + right) / 2 - 9, (top + bottom) / 2 - 12),
                str(serials[key][i]),
                fill="#c00000",
                font=FONT_SERIAL,
            )
            draw.text(
                (left + 3, top + 2),
                f"s{sc['index']}",
                fill="#707070",
                font=FONT_LABEL,
            )

    # Trailing empty slot carries the reading instructions.
    if len(CONVENTIONS) % PANEL_COLS:
        ox = (len(CONVENTIONS) % PANEL_COLS) * PANEL_W
        oy = (len(CONVENTIONS) // PANEL_COLS) * panel_h + TITLE_H
        for line_no, line in enumerate(
            [
                "Grey s0, s1, ... = scene index inside the CZI.",
                "Red number = serial position under that convention.",
                "",
                "Pick the panel whose red numbers run rostral -> caudal",
                "in the order the sections were mounted.",
            ]
        ):
            draw.text((ox + MARGIN, oy + 30 + line_no * 17), line, fill="#505050", font=FONT_LABEL)

    canvas.save(path)


# ---------------------------------------------------------------- main


def load_overrides():
    """Optional per-slide row-count corrections: file,n_rows."""
    if not os.path.exists(OVERRIDES_CSV):
        return {}
    out = {}
    with open(OVERRIDES_CSV, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("file") or "").strip()
            value = (row.get("n_rows") or "").strip()
            if name and value:
                out[name] = int(value)
    print(f"Loaded {len(out)} layout override(s) from {OVERRIDES_CSV}")
    return out


def main():
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    os.makedirs(SLIDEMAP_DIR, exist_ok=True)

    accept_suggestions = "--accept-suggestions" in sys.argv
    overrides = load_overrides()
    accepted = {}
    entries = discover_sources()
    print(f"Discovered {len(entries)} CZI entries across loose files and zips.")

    file_rows = []
    scene_rows = []
    layout_rows = []
    seen_names = {}
    failures = []

    for source, member, container, opener in entries:
        base = os.path.basename(member)
        parsed = parse_name(member)
        if parsed is None:
            failures.append((source, member, "filename did not match LS<animal>_<slide><variant>"))
            continue

        if base in seen_names:
            # Loose copies duplicate zip members byte for byte; record and move on.
            file_rows.append(
                {
                    **seen_names[base],
                    "source": source,
                    "container": container,
                    "is_redundant_copy": 1,
                }
            )
            continue

        try:
            with opener() as fh:
                info = summarise(read_metadata(fh))
        except Exception as exc:  # noqa: BLE001 - want the reason in the report
            failures.append((source, member, repr(exc)[:120]))
            continue

        channel_names = [c["name"] for c in info["channels"]]
        marker = channel_names[1] if len(channel_names) > 1 else None
        marker_exposure = info["channels"][1]["exposure_ms"] if len(info["channels"]) > 1 else None

        row = {
            "file": base,
            "source": source,
            "container": container,
            "animal": parsed["animal"],
            "slide": parsed["slide"],
            "variant": parsed["variant"],
            "name_suffix": parsed["name_suffix"],
            "marker_channel": marker,
            "marker_exposure_ms": marker_exposure,
            "dapi_exposure_ms": info["channels"][0]["exposure_ms"] if info["channels"] else None,
            "acquired": info["acquired"],
            "size_x": info["size_x"],
            "size_y": info["size_y"],
            "size_c": info["size_c"],
            "size_s": info["size_s"],
            "n_tiles_m": info["size_m"],
            "n_scenes": len(info["scenes"]),
            "pixel_type": info["pixel_type"],
            "px_um": info["px_um_x"],
            "objective_mag": info["objective_mag"],
            "objective_na": info["objective_na"],
            "camera": info["camera"],
            "shading_reference_mode": info["shading_reference_mode"],
            "online_stitching": info["online_stitching"],
            "is_redundant_copy": 0,
        }
        seen_names[base] = {k: row[k] for k in row if k not in ("source", "container", "is_redundant_copy")}
        file_rows.append(row)

        scenes = info["scenes"]
        if not scenes:
            failures.append((source, member, "no scenes in metadata"))
            continue

        forced = overrides.get(base)
        rows_idx, cols_idx = build_grid(scenes, forced)
        spread = row_spread_ratio(scenes, rows_idx)
        suggestion = suggest_rows(scenes) if (spread > ROW_SPREAD_FLAG and not forced) else None

        if suggestion and accept_suggestions:
            forced = suggestion
            accepted[base] = suggestion
            rows_idx, cols_idx = build_grid(scenes, forced)
            spread = row_spread_ratio(scenes, rows_idx)
            suggestion = None

        serials = serial_numbers(rows_idx, cols_idx, scenes)

        for i, sc in enumerate(scenes):
            scene_rows.append(
                {
                    "scene_uid": f"{parsed['animal']}_s{parsed['slide']:02d}{parsed['variant']}_sc{sc['index']:02d}",
                    "file": base,
                    "animal": parsed["animal"],
                    "slide": parsed["slide"],
                    "variant": parsed["variant"],
                    "marker_channel": marker,
                    "scene_index": sc["index"],
                    "scene_name": sc["name"],
                    "center_x_um": round(sc["center_x_um"], 2) if sc["center_x_um"] is not None else "",
                    "center_y_um": round(sc["center_y_um"], 2) if sc["center_y_um"] is not None else "",
                    "width_um": round(sc["width_um"], 2) if sc["width_um"] else "",
                    "height_um": round(sc["height_um"], 2) if sc["height_um"] else "",
                    "slide_row": int(rows_idx[i]),
                    "slide_col": int(cols_idx[i]),
                    **{f"serial_{k}": int(serials[k][i]) for k, _ in CONVENTIONS},
                }
            )

        row_counts = np.bincount(rows_idx).tolist()
        layout_rows.append(
            {
                "file": base,
                "animal": parsed["animal"],
                "slide": parsed["slide"],
                "variant": parsed["variant"],
                "n_scenes": len(scenes),
                "n_rows": int(rows_idx.max()) + 1,
                "n_cols": int(cols_idx.max()) + 1,
                "row_counts": "|".join(str(c) for c in row_counts),
                "row_spread_ratio": round(float(spread), 2),
                "rows_forced": forced or "",
                "suggested_rows": suggestion or "",
                "needs_review": int(suggestion is not None),
            }
        )

        render_slidemap(
            os.path.join(SLIDEMAP_DIR, base.replace(".czi", ".png")),
            base,
            scenes,
            rows_idx,
            cols_idx,
            serials,
        )

    if accepted:
        merged = dict(overrides)
        merged.update(accepted)
        _write_csv(
            OVERRIDES_CSV,
            [{"file": k, "n_rows": v} for k, v in sorted(merged.items())],
        )
        print(f"  accepted {len(accepted)} row-count suggestion(s) into layout_overrides.csv")

    # Rostro-caudal position across the whole animal: slide number first, then
    # position within the slide under the confirmed convention. Kept per
    # variant series so the duplicate re-scans each get a clean 1..N and the
    # choice between them stays a Stage 1 decision.
    order_key = f"serial_{ORDER_CONVENTION}"
    series = defaultdict(list)
    for row in scene_rows:
        series[(row["animal"], row["marker_channel"], row["variant"])].append(row)
    for rows_in_series in series.values():
        rows_in_series.sort(key=lambda r: (r["slide"], r[order_key]))
        for position, row in enumerate(rows_in_series, start=1):
            row["slide_serial"] = row[order_key]
            row["section_order"] = position

    print(f"  section_order written from {order_key} across {len(series)} variant series")

    _write_csv(os.path.join(MANIFEST_DIR, "manifest_files.csv"), file_rows)
    _write_csv(os.path.join(MANIFEST_DIR, "manifest_scenes.csv"), scene_rows)
    _write_csv(os.path.join(QC_DIR, "slide_layout_summary.csv"), layout_rows)

    _report(file_rows, scene_rows, layout_rows, failures)


def _write_csv(path, rows):
    if not rows:
        print(f"  !! nothing to write for {path}")
        return
    keys = list(rows[0].keys())
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {path}  ({len(rows)} rows)")


def _report(file_rows, scene_rows, layout_rows, failures):
    unique = [r for r in file_rows if not r["is_redundant_copy"]]
    print()
    print("=" * 72)
    print(f"unique CZI files parsed : {len(unique)}")
    print(f"redundant loose copies  : {len(file_rows) - len(unique)}")
    print(f"sections (scenes) total : {len(scene_rows)}")
    print(f"failures                : {len(failures)}")
    for f in failures:
        print(f"    !! {f[0]} :: {f[1]} :: {f[2]}")

    by_marker = defaultdict(int)
    for r in unique:
        by_marker[r["marker_channel"]] += 1
    print(f"files per marker channel: {dict(by_marker)}")

    # Any file whose header disagrees with the pipeline's assumptions is worth
    # surfacing now rather than discovering halfway through Stage 1.
    odd_px = {round(r["px_um"], 4) for r in unique if r["px_um"]}
    print(f"distinct pixel sizes     : {sorted(odd_px)}")
    shading = {r["shading_reference_mode"] for r in unique}
    print(f"shading reference modes  : {shading}")

    mismatched = [r for r in unique if r["n_scenes"] != r["size_s"]]
    print(f"n_scenes != SizeS        : {len(mismatched)}  <- must be 0")
    for r in mismatched[:5]:
        print(f"    {r['file']}: {r['n_scenes']} scenes vs SizeS {r['size_s']}")

    exposures = defaultdict(set)
    for r in unique:
        exposures[r["marker_channel"]].add(r["marker_exposure_ms"])
        exposures["DAPI"].add(r["dapi_exposure_ms"])
    print(f"exposures (ms) per channel: { {k: sorted(v) for k, v in exposures.items()} }")

    row_hist = defaultdict(int)
    for r in layout_rows:
        row_hist[r["n_rows"]] += 1
    print(f"rows per slide           : {dict(sorted(row_hist.items()))}")

    review = sorted(
        (r for r in layout_rows if r["needs_review"]),
        key=lambda r: -r["row_spread_ratio"],
    )
    _write_csv(os.path.join(QC_DIR, "slide_layout_review.csv"), review)
    print(f"slides needing row review: {len(review)}  (worst first, see qc/slide_layout_review.csv)")
    for r in review[:10]:
        print(
            f"    {r['file']}: {r['n_scenes']} scenes, detected {r['n_rows']} row(s) {r['row_counts']}, "
            f"spread {r['row_spread_ratio']}x section height -> suggest {r['suggested_rows']} rows"
        )
    if len(review) > 10:
        print(f"    ... and {len(review) - 10} more")
    if review:
        print(f"    -> accept every suggestion with:  python 00_manifest.py --accept-suggestions")
        print(f"    -> or hand-edit {OVERRIDES_CSV}")

    dupes = defaultdict(list)
    for r in unique:
        dupes[(r["animal"], r["slide"], r["marker_channel"])].append(r["file"])
    real_dupes = {k: v for k, v in dupes.items() if len(v) > 1}
    print(f"duplicate animal+slide+marker units: {len(real_dupes)}")
    for k, v in sorted(real_dupes.items()):
        print(f"    {k[0]} slide {k[1]} {k[2]}: {v}")

    print("=" * 72)
    print("NEXT: open qc/slidemaps/, compare a few against the physical slides,")
    print("      and tell me which convention (A/B/C/D) is correct.")


if __name__ == "__main__":
    main()
