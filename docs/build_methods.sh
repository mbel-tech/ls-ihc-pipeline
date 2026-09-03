#!/usr/bin/env bash
# Rebuild pipeline-methods.docx from pipeline-methods.md, and put a copy beside
# the slide data.
#
# Three steps, in order, because each feeds the next:
#   1. redraw the workflow figure
#   2. regenerate the software table FROM the installed environments and splice
#      it into the .md, so a version cannot drift between what is installed and
#      what the document claims
#   3. render the DOCX, then copy .md, .docx and the figure to the data drive
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

echo "[1/4] workflow figure"
$PYTHON make_workflow_figure.py

echo "[2/4] software versions, read from the installed environments"
$PYTHON make_versions_table.py

echo "[3/4] pandoc -> pipeline-methods.docx"
"$PANDOC" pipeline-methods.md -o pipeline-methods.docx \
    --reference-doc=ref_styled.docx --toc --toc-depth=2 \
    --resource-path=. -f markdown+raw_html

if [ "${WITH_PDF:-0}" = "1" ]; then
    rm -f pipeline-methods.pdf
    "$SOFFICE" --headless --convert-to pdf --outdir . pipeline-methods.docx >/dev/null 2>&1
    echo "      also wrote pipeline-methods.pdf"
fi

echo "[4/4] copy to $DATA_DIR"
if [ -d "$DATA_DIR" ]; then
    mkdir -p "$DATA_DIR/img"
    cp pipeline-methods.md "$DATA_DIR/"
    cp pipeline-methods.docx "$DATA_DIR/"
    cp img/workflow.png "$DATA_DIR/img/"
    [ -f pipeline-methods.pdf ] && cp pipeline-methods.pdf "$DATA_DIR/"
    echo "      copied"
else
    echo "      SKIPPED - $DATA_DIR is not mounted" >&2
fi

echo "built pipeline-methods.docx"
