#!/usr/bin/env bash
# Rebuild pipeline-methods.docx and pipeline-guide.docx from their .md sources,
# and put copies beside the slide data.
#
# Five steps, in order, because each feeds the next:
#   0. check the stage list against the scripts, the figure and the guide - a
#      guide missing a stage must not be shippable
#   1. redraw the workflow figure
#   2. regenerate the software table FROM the installed environments and splice
#      it into the .md, so a version cannot drift between what is installed and
#      what the document claims
#   3. render both DOCX files through one render() so their flags cannot drift
#   4. copy .md, .docx and the figure to the data drive
#
# ref_styled.docx is pandoc's default reference doc with the theme font
# references (minorHAnsi / majorHAnsi) replaced by named families - LibreOffice
# resolves the theme refs to a slab serif, so the PDF came out looking nothing
# like the DOCX until they were spelled out. Same file the ROI curator guide uses.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PANDOC="${PANDOC:-/c/Users/marti/Downloads/pandoc-3.10.2-windows-x86_64/pandoc-3.10.2/pandoc}"
PYTHON="${PYTHON:-py -3.14}"
SOFFICE="${SOFFICE:-/c/Program Files/LibreOffice/program/soffice.exe}"
# Where the slides live. The document is written here as well as into the repo so
# it sits beside the data it describes.
DATA_DIR="${LS_DATA_DIR:-/d/SLIDES HE DEC 2025 LS}"

cd "$HERE"

echo "[1/5] stage list vs scripts, figure and guide"
$PYTHON "$ROOT/tests/test_stages.py" > /dev/null

echo "[2/5] workflow figure"
$PYTHON make_workflow_figure.py

echo "[3/5] software versions, read from the installed environments"
$PYTHON make_versions_table.py

# One function, two documents: two copies of this flag list would drift, and a
# reader comparing the two files would read the difference as a decision.
render() {
    "$PANDOC" "$1.md" -o "$1.docx" \
        --reference-doc=ref_styled.docx --toc --toc-depth=2 \
        --resource-path=. -f markdown+raw_html
    if [ "${WITH_PDF:-0}" = "1" ]; then
        rm -f "$1.pdf"
        "$SOFFICE" --headless --convert-to pdf --outdir . "$1.docx" >/dev/null 2>&1
        echo "      also wrote $1.pdf"
    fi
}

echo "[4/5] pandoc -> pipeline-methods.docx, pipeline-guide.docx"
render pipeline-methods
render pipeline-guide

echo "[5/5] copy to $DATA_DIR"
if [ -d "$DATA_DIR" ]; then
    mkdir -p "$DATA_DIR/img"
    cp pipeline-methods.md pipeline-guide.md "$DATA_DIR/"
    cp pipeline-methods.docx pipeline-guide.docx "$DATA_DIR/"
    cp img/workflow.png "$DATA_DIR/img/"
    for f in pipeline-methods.pdf pipeline-guide.pdf; do
        [ -f "$f" ] && cp "$f" "$DATA_DIR/"
    done
    echo "      copied"
else
    echo "      SKIPPED - $DATA_DIR is not mounted" >&2
fi

echo "built pipeline-methods.docx and pipeline-guide.docx"
