#!/usr/bin/env bash
# Rebuild the ROI curator guide from ROI_curator_guide.md.
#
# ref_styled.docx is pandoc's default reference doc with the theme font
# references (minorHAnsi / majorHAnsi) replaced by named families - LibreOffice
# resolves the theme refs to a slab serif, so the PDF came out looking nothing
# like the DOCX until they were spelled out.
#
# Screenshots in img/ were captured from the live tool served over http, so the
# atlas plates (which sit at ../atlas/) resolve. Re-capture with the page served
# from D:/LS-analysis, not opened as file://.
set -euo pipefail
PANDOC="${PANDOC:-/c/Users/marti/Downloads/pandoc-3.10.2-windows-x86_64/pandoc-3.10.2/pandoc}"
SOFFICE="${SOFFICE:-/c/Program Files/LibreOffice/program/soffice.exe}"

"$PANDOC" ROI_curator_guide.md -o ROI_curator_guide.docx \
    --reference-doc=ref_styled.docx --toc --toc-depth=2 \
    --resource-path=. -f markdown+raw_html

rm -f ROI_curator_guide.pdf
"$SOFFICE" --headless --convert-to pdf --outdir . ROI_curator_guide.docx >/dev/null 2>&1
echo "built ROI_curator_guide.docx and .pdf"
