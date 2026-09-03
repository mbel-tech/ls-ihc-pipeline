"""Draw the pipeline workflow figure for docs/pipeline-methods.md.

Writes docs/img/workflow.png (300 dpi, for the DOCX) and docs/img/workflow.pdf
(vector, for print).

The layout is a hand-written table rather than a graph-layout engine: the flow is
a single column, the order is the pipeline's own, and hand coordinates are easier
to nudge than a solver is to argue with. Nothing here reads the pipeline - the
STAGES table below is the thing to edit when a stage changes.

Three visual channels carry information and none are decoration:

  fill colour     which reader touched the pixels. The README rule - "if a number
                  derived from a pixel appears in a figure or table, that pixel
                  was read by pylibCZIrw" - is a property of the workflow, so the
                  figure shows it.
  bold outline    an operator decides here. These are the steps that cannot be
                  batched, and they are why the 04-series is not in run_all.sh.
  dashed box      downstream of the scope of this document.

Run:  python docs/make_workflow_figure.py
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "img")

# ---------------------------------------------------------------- palette ----
# The three reader fills differ in lightness as well as hue, because this figure
# will be printed and may be printed in grey.
C_NONE = "#e8e8ea"        # no pixel decoded - headers, tables, geometry
C_CZIFILE = "#f6dfae"     # czifile: raw tiles, instrument characterisation only
C_PYLIB = "#bcd7ee"       # pylibCZIrw: every pixel that becomes a number
C_EDGE = "#3a3a3e"
C_OPERATOR = "#a4262c"    # outline colour for operator-in-the-loop steps
C_TAG = "#6a6a70"
C_KEY = "#a4262c"         # roi_nuclei.csv, the artefact that matters

PHASES = [
    ("Acquisition", "#f2f2f4"),
    ("Ingest and QC", "#eaf1f7"),
    ("Normalisation\nand curation", "#f4eef2"),
    ("Quantification", "#eaf2ec"),
    ("Beyond this document", "#f2f2f4"),
]

# phase index, title, body, fill, operator?, dashed?, artefact tag
STAGES = [
    (0, "Whole-slide acquisition",
        "Zeiss CZI | 10x/0.45 NA | 0.65 um/px | 16-bit | tiled mosaic\n"
        "DAPI + one marker | 222 files | 2,572 sections | 12 animals",
        C_NONE, False, False, ""),

    (1, "00  Manifest and slide reconstruction",
        "Every CZI header read without decoding a pixel;\n"
        "slide grid rebuilt under five mounting conventions",
        C_NONE, False, False, "manifest_scenes.csv  (2,572)"),

    (1, "00b / 00c  Verification and channel identity",
        "Extracted files checked against the archive CRCs;\n"
        "fluorophore to marker inferred from spatial signature",
        C_NONE, False, False, "channel_identity.png"),

    (1, "01  Overview export",
        "Every section at exactly 5.20 um/px, display range\n"
        "frozen dataset-wide from tissue pixels; per-section QC",
        C_PYLIB, False, False, "overviews/*.png\noverview_qc.csv"),

    (1, "01c-01k  Instrument characterisation",
        "Tile geometry from the subblock directory; illumination\n"
        "field by folding at the tile pitch; saturation mapped",
        C_CZIFILE, False, False, "tilefield_c*.npy"),

    (1, "01d  Contact sheets",
        "Per-animal montages in rostro-caudal order, plus a\n"
        "browsable gallery - the first look at all 2,572",
        C_NONE, False, False, "contactsheets/gallery.html"),

    (1, "02  Pair the two marker passes",
        "Reload offset recovered by translation voting, then\n"
        "optimal assignment; yields the canonical section_uid",
        C_NONE, False, False, "pairs.csv"),

    (2, "04a  Atlas extraction",
        "101 plates and 356 region seed points pulled out of the\n"
        "salmon atlas PDF; markers found by size, not by colour",
        C_NONE, False, False, "atlas/plates_final/\nseeds.csv"),

    (2, "04a  Section reformatting",
        "Debris removed, rotated onto the principal axis, centred,\n"
        "cropped, padded square, resized to 256 px - all on DAPI",
        C_NONE, False, False, "reformatted/\nreformat_index_*.csv"),

    (2, "04f  Exclusion proposals, adjudicated",
        "Unmeasurable sections proposed conservatively; every call\n"
        "carries its numbers and every one is reversible",
        C_NONE, True, False, "1,066 of 2,572 excluded"),

    (2, "04g  Artifact masking",
        "Bright objects strictly inside the tissue masked rather\n"
        "than excluded; median 0.13% of tissue area",
        C_NONE, False, False, "*_artifact.npy  (2,099)"),

    (2, "04j / 06f  Clipped-pixel censoring",
        "Sections above a 1% clipped tolerance set aside; surviving\n"
        "clipped pixels flagged right-censored, not masked",
        C_NONE, False, False, "*_censor.npy\nperk_analysis_set.csv"),

    (2, "04l  ROI curation",
        "Operator assigns an atlas plate and clicks landmark pairs;\n"
        "region seeds warp live onto the section (affine, then TPS)",
        C_NONE, True, False, "roi_regions.csv\nroi_landmarks.csv"),

    (3, "05a  ROI geometry",
        "The six-step reformat inverted to one 2x3 affine per section;\n"
        "each curated disc becomes a box in native CZI pixels",
        C_NONE, False, False, "roi_boxes_*.csv"),

    (3, "05c  Nuclei detection and measurement",
        "Each box read at 0.65 um/px; nuclei segmented on DAPI with\n"
        "StarDist; the marker measured inside each nuclear mask",
        C_PYLIB, False, False, "roi_nuclei.csv"),

    (3, "06a  Per-ROI dataset  (still blind)",
        "Positivity cut from each section's own background discs;\n"
        "false-positive rate measured; Abercrombie correction applied",
        C_NONE, False, False, "roi_measurements.csv\ndetector_specificity.csv"),

    (4, "06b to 06e  Unblinding, workbooks, figures",
        "Treatment group joined at 06b; spreadsheets and R figures follow",
        C_NONE, False, True, ""),
]

BOX_H = 4.5
GAP = 1.35
PHASE_GAP = 1.5
X0, X1 = 9.0, 62.0        # main column
X_TAG = 64.0              # artefact rail
X_PHASE0, X_PHASE1 = 0.6, 6.6


def layout():
    """Assign a y centre to every stage, top-down, with a gap between phases."""
    rows, y = [], 0.0
    prev_phase = None
    for st in STAGES:
        if prev_phase is not None and st[0] != prev_phase:
            y -= PHASE_GAP
        y -= BOX_H
        rows.append((st, y + BOX_H / 2.0))
        y -= GAP
        prev_phase = st[0]
    return rows, y


def draw():
    rows, y_end = layout()
    top, bottom = 1.0, y_end - 7.5        # room for the legend
    height = top - bottom

    fig_w = 7.5
    fig_h = fig_w * (height / 100.0) * 1.55
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, 101)
    ax.set_ylim(bottom, top)
    ax.axis("off")

    # ---- phase bands, sized to the stages they contain ---------------------
    for idx, (name, colour) in enumerate(PHASES):
        ys = [yc for st, yc in rows if st[0] == idx]
        if not ys:
            continue
        hi, lo = max(ys) + BOX_H / 2, min(ys) - BOX_H / 2
        ax.add_patch(Rectangle((X_PHASE0, lo), X_PHASE1 - X_PHASE0, hi - lo,
                               facecolor=colour, edgecolor="none", zorder=0))
        ax.text((X_PHASE0 + X_PHASE1) / 2, (hi + lo) / 2, name.upper(),
                rotation=90, ha="center", va="center", fontsize=7.2,
                color="#4a4a52", fontweight="bold", linespacing=1.35)

    # ---- the stage boxes ---------------------------------------------------
    for st, yc in rows:
        _, title, body, fill, operator, dashed, tag = st
        edge = C_OPERATOR if operator else C_EDGE
        lw = 1.8 if operator else 0.9
        ls = (0, (4, 2)) if dashed else "solid"
        ax.add_patch(FancyBboxPatch(
            (X0, yc - BOX_H / 2), X1 - X0, BOX_H,
            boxstyle="round,pad=0,rounding_size=0.7",
            facecolor=fill, edgecolor=edge, linewidth=lw, linestyle=ls, zorder=2))
        ax.text(X0 + 1.6, yc + BOX_H / 2 - 1.25, title, fontsize=8.1,
                fontweight="bold", va="center", ha="left", color="#1c1c20", zorder=3)
        ax.text(X0 + 1.6, yc - 0.75, body, fontsize=6.9, va="center", ha="left",
                color="#33333a", linespacing=1.45, zorder=3)
        if tag:
            key = "roi_nuclei" in tag
            ax.text(X_TAG, yc, tag, fontsize=6.4, va="center", ha="left",
                    family="DejaVu Sans Mono", color=C_KEY if key else C_TAG,
                    fontweight="bold" if key else "normal",
                    linespacing=1.5, zorder=3)

    # ---- arrows between consecutive stages ---------------------------------
    xm = (X0 + X1) / 2
    for (sa, ya), (sb, yb) in zip(rows, rows[1:]):
        dashed = sb[5]
        ax.add_patch(FancyArrowPatch(
            (xm, ya - BOX_H / 2), (xm, yb + BOX_H / 2),
            arrowstyle="-|>", mutation_scale=9, linewidth=0.9,
            linestyle=(0, (3, 2)) if dashed else "solid",
            color="#8a8a92" if dashed else C_EDGE, zorder=1))

    # ---- the blinding boundary ---------------------------------------------
    y_blind = (rows[-1][1] + BOX_H / 2 + rows[-2][1] - BOX_H / 2) / 2
    ax.plot([X_PHASE0, 100.5], [y_blind, y_blind], linestyle=(0, (5, 3)),
            linewidth=1.0, color=C_OPERATOR, zorder=4)
    ax.text(100.5, y_blind + 0.55,
            "blinding ends here  -  treatment group is first read at 06b",
            fontsize=6.6, ha="right", va="bottom", color=C_OPERATOR, style="italic")

    # ---- legend ------------------------------------------------------------
    y_leg = rows[-1][1] - BOX_H / 2 - 3.2
    items = [
        (C_PYLIB, C_EDGE, 0.9, "pixels read by pylibCZIrw"),
        (C_CZIFILE, C_EDGE, 0.9, "raw tiles read by czifile\n(instrument only)"),
        (C_NONE, C_EDGE, 0.9, "no pixel decoded"),
        ("#ffffff", C_OPERATOR, 1.8, "an operator decides here"),
    ]
    x = X0
    for fill, edge, lw, label in items:
        ax.add_patch(FancyBboxPatch(
            (x, y_leg - 1.0), 3.0, 2.0,
            boxstyle="round,pad=0,rounding_size=0.5",
            facecolor=fill, edgecolor=edge, linewidth=lw))
        ax.text(x + 3.9, y_leg, label, fontsize=6.5, va="center", ha="left",
                color="#33333a", linespacing=1.4)
        x += 23.0

    ax.text(X_PHASE0, y_leg - 4.4,
            "Right-hand column: the file each stage leaves behind. "
            "roi_nuclei.csv is the artefact everything after it is arithmetic on.",
            fontsize=6.4, ha="left", va="center", color=C_TAG, style="italic")

    fig.subplots_adjust(left=0.005, right=0.995, top=0.995, bottom=0.005)
    os.makedirs(OUT, exist_ok=True)
    for ext, kw in (("png", {"dpi": 300}), ("pdf", {})):
        path = os.path.join(OUT, "workflow." + ext)
        fig.savefig(path, facecolor="white", **kw)
        print("wrote " + path)
    plt.close(fig)


if __name__ == "__main__":
    draw()
