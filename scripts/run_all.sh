#!/usr/bin/env bash
# Full pipeline, in dependency order. Every stage is resumable, so a failure
# part-way through does not cost the completed work - re-running skips it.
#
# Run:  bash run_all.sh              # everything
#       bash run_all.sh from 5       # resume from step 5
#
set -u

# Everything is derived from this script's own location so the pipeline is
# portable; each value can still be overridden from the environment.
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPTS/.." && pwd)"
LOGS="${LS_LOGS:-$ROOT/logs}"
# Groovy cannot resolve its own path, so the config location is passed in.
export LS_CONFIG="${LS_CONFIG:-$ROOT/config.json}"
FIJI="${FIJI:-C:/Users/marti/Fiji.app/ImageJ-win64.exe}"
# pylibCZIrw has no cp314 wheel, so the CZI stages run in a 3.13 venv.
CZIPY="${CZIPY:-$ROOT/work/czienv/Scripts/python.exe}"
# Every stage writes under config.out_root, which is NOT the repo. Steps 4 and
# 8 used $ROOT/qc/... and so handed Fiji a list that did not exist and 01c a
# glob that matched nothing - hidden by the `|| true` on step 8.
OUT="$(python -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8'))['out_root'])" "$LS_CONFIG")" || exit 1
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
  export EX_LIST="$OUT/qc/tilefield_sample.csv"
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
  python 01c_measure_tile_artifact.py "$OUT/qc/test_sections_corrected/*.tif" || true

# Every section at exactly 5.2 um/px. Ported from Fiji to pylibCZIrw:
# ~36 min instead of ~306, no Memoizer to silently hand back a tile-mode reader
# (which cost 238 sections), and a continuous zoom rather than snapping to the
# nearest stored pyramid level (which made tissue_area_mm2 range 0.18-28.83
# within a single brain).
step 9 "export overviews for every section" \
  "$CZIPY" 01_overviews.py || exit 1

# Clipping measured BEFORE the tile field, per section, with the raw mask 04j
# censors from. Dividing by a gain above 1 lifts a pixel off the ceiling, so
# the count taken after correction was roughly half the truth (LOGS
# 2026-09-02). pylibCZIrw again, so the same interpreter as step 9.
step 10 "measure clipping on the raw plane" \
  "$CZIPY" 01k_saturation_raw.py || exit 1

step 11 "build contact sheets and gallery" \
  python 01d_contactsheets.py || exit 1

step 12 "pair the AF568 and AF488 passes" \
  python 02_pair_passes.py || exit 1

step 13 "extract the atlas plates and seeds" \
  python 04a_atlas_extract.py || exit 1

# Reports the call and writes the evidence figure, but does not commit the
# names to config.json - that needs a human look, so no --accept here.
step 14 "infer which fluorophore is pERK and which is PCNA" \
  python 00c_channel_identity.py || true

# The 04-series curation chain and the quantification that follows it are not
# run here: they need the operator between the steps - assigning plates, placing
# ROIs - so there is nothing to batch. 05a is the exception worth naming, since
# it is the first step after curation and takes no decisions of its own.
#
#   python 05a_roi_geometry.py --verify        check the map, run this first
#   python 05a_roi_geometry.py <roi_regions.csv>
step 15 "place the curated ROIs on the slide (needs a curator export)" \
  python 05a_roi_geometry.py || true

# 05c is NOT run here. It needs StarDist and TensorFlow, which the packaged app
# deliberately does not carry, and it is the one stage measured in hours rather
# than minutes. Run the rest once a curation pass has been exported:
#
#   python 05c_detect_rois.py     nuclei on DAPI, marker measured in them.
#                                 Resumable per section - safe to interrupt.
#   python 06a_roi_dataset.py     counts and positivity. Still blind.
#   python 06b_join_sampling.py   the unblinding join. See config.blinding.

printf '\n========================================================================\n'
printf 'PIPELINE COMPLETE\n'
printf '  contact sheets : %s/contactsheets/\n' "$OUT"
printf '  gallery        : %s/contactsheets/gallery.html\n' "$OUT"
printf '  tile artifact  : compare step 7 (before) against step 8 (after)\n'
printf '  raw clipping   : %s/qc/saturation_raw.csv\n' "$OUT"
printf '  channel call   : %s/qc/channel_identity/channel_identity.png\n' "$OUT"
printf '  logs           : %s\n' "$LOGS"
printf '========================================================================\n'
