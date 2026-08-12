#!/usr/bin/env bash
# Full pipeline, in dependency order. Every stage is resumable, so a failure
# part-way through does not cost the completed work - re-running skips it.
#
# Run:  bash run_all.sh              # everything
#       bash run_all.sh from 5       # resume from step 5
#
set -u

FIJI="C:/Users/marti/Fiji.app/ImageJ-win64.exe"
# pylibCZIrw has no cp314 wheel, so the CZI stages run in a 3.13 venv.
CZIPY="D:/LS-analysis/work/czienv/Scripts/python.exe"
SCRIPTS="D:/LS-analysis/scripts"
LOGS="D:/LS-analysis/logs"
mkdir -p "$LOGS"

START_AT=1
if [ "${1:-}" = "from" ]; then START_AT="${2:-1}"; fi

step() {
  local n="$1"; shift
  local name="$1"; shift
  if [ "$n" -lt "$START_AT" ]; then
    printf '\n[%s] SKIP  %s\n' "$n" "$name"
    return 0
  fi
  printf '\n========================================================================\n'
  printf '[%s] %s\n' "$n" "$name"
  printf '========================================================================\n'
  local log="$LOGS/step${n}_$(echo "$name" | tr ' /' '__').log"
  local t0=$SECONDS
  if "$@" > >(tee "$log") 2>&1; then
    printf '\n[%s] done in %s min\n' "$n" "$(( (SECONDS - t0) / 60 ))"
  else
    printf '\n[%s] FAILED (see %s)\n' "$n" "$log"
    return 1
  fi
}

fiji() {
  # pipefail matters here: without it the exit status is grep's, so a Fiji
  # crash mid-run reports success and the pipeline marches straight past it.
  # That is exactly what masked the step 9 failure of 2026-08-11, where the
  # drive vanished and 306 minutes of work was reported as "done".
  set -o pipefail
  "$FIJI" --ij2 --headless --console --run "$1" 2>&1 | grep -v "^OpenJDK"
  local rc=$?
  set +o pipefail
  return $rc
}

cd "$SCRIPTS" || exit 1

step 1 "manifest, slide grid, slide maps" \
  python 00_manifest.py || exit 1

step 2 "verify extraction against the zips" \
  python 00b_verify_extraction.py || exit 1

step 3 "pick sections for the tile field" \
  python 01b_pick_sections.py --n 96 --scenes-per-file 4 || exit 1

if [ "$START_AT" -le 4 ]; then
  export EX_LIST="D:/LS-analysis/qc/tilefield_sample.csv"
  export EX_UMPX=2.6
  step 4 "export sample sections at 2.6 um px" \
    fiji "$SCRIPTS/01b_export_section.groovy" || exit 1
  unset EX_LIST EX_UMPX
fi

step 5 "build the tile-correction field" \
  python 01f_tilefield.py build || exit 1

step 6 "apply the field to the sample" \
  python 01f_tilefield.py verify || exit 1

step 7 "measure the tile artifact BEFORE correction" \
  python 01c_measure_tile_artifact.py || true

step 8 "measure the tile artifact AFTER correction" \
  bash -c 'python 01c_measure_tile_artifact.py "D:/LS-analysis/qc/test_sections_corrected"/*.tif' || true

# Every section at exactly 5.2 um/px. Ported from Fiji to pylibCZIrw:
# ~36 min instead of ~306, no Memoizer to silently hand back a tile-mode reader
# (which cost 238 sections), and a continuous zoom rather than snapping to the
# nearest stored pyramid level (which made tissue_area_mm2 range 0.18-28.83
# within a single brain).
step 9 "export overviews for every section" \
  "$CZIPY" 01_overviews.py || exit 1

step 10 "build contact sheets and gallery" \
  python 01d_contactsheets.py || exit 1

step 11 "pair the AF568 and AF488 passes" \
  python 02_pair_passes.py || exit 1

step 12 "extract the atlas plates and seeds" \
  python 04a_atlas_extract.py || exit 1

# Reports the call and writes the evidence figure, but does not commit the
# names to config.json - that needs a human look, so no --accept here.
step 13 "infer which fluorophore is pERK and which is PCNA" \
  python 00c_channel_identity.py || true

printf '\n========================================================================\n'
printf 'PIPELINE COMPLETE\n'
printf '  contact sheets : D:/LS-analysis/contactsheets/\n'
printf '  gallery        : D:/LS-analysis/contactsheets/gallery.html\n'
printf '  tile artifact  : compare step 7 (before) against step 8 (after)\n'
printf '  channel call   : D:/LS-analysis/qc/channel_identity/channel_identity.png\n'
printf '  logs           : %s\n' "$LOGS"
printf '========================================================================\n'
