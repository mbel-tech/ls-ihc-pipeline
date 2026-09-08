#!/usr/bin/env bash
# Run the curator suites and the Python suites.
#
#   bash tests/run.sh
#
# The curators are generated pages, so there is a build step: each page is
# regenerated INTO tests/build/ with --out, its <script> is lifted out, and the
# suites run against that. The operator's live pages under out_root are never
# touched, so a test run cannot rewrite or downgrade a file someone is curating
# in.
#
# --no-seed matters for the ROI curator. The page normally embeds whatever
# curation is in out_root/curation; a suite reading that would start with
# hundreds of sections it knows nothing about, and its counts would change every
# time someone curated. --no-proposals does the same for the rotation curator.
# Tests must not depend on the operator's data.
#
# What these cover: state, ordering and what reaches the exports. What they do
# not: anything visual. Canvas calls are swallowed by the stub, so rendering is
# checked in a real browser instead.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TESTS="$REPO/tests"
BUILD="$TESTS/build"

# Prefer the app venv, since that is the interpreter the pipeline is built on.
PY="${PY:-$REPO/work/appenv/Scripts/python.exe}"

# A suite that does not name its own config would fall through to the
# operator's live config.json and then pass or fail on their data rather
# than on its own. This makes that fallback an error instead. Suites that
# want a config write one - see tests/_fixture.py.
export LS_CONFIG_STRICT=1
[ -x "$PY" ] || PY="python"

mkdir -p "$BUILD"

# build_page <script> <name> [args...]: generate scripts/<script> to
# tests/build/<name>.html and lift its largest <script> block to <name>.js.
build_page () {
  local script="$1" name="$2"; shift 2
  echo "building $name..."
  LS_CONFIG="$BUILD_CONFIG" "$PY" "$REPO/scripts/$script" "$@" --out "$BUILD/$name.html" > /dev/null || {
    echo "could not generate $name"; exit 2; }
  "$PY" - "$BUILD/$name.html" "$BUILD/$name.js" <<'PYEOF' || exit 2
import io, re, sys
html = io.open(sys.argv[1], encoding="utf-8").read()
js = max(re.findall(r"<script>(.*?)</script>", html, re.S), key=len)
io.open(sys.argv[2], "w", encoding="utf-8", newline="").write(js)
print(f"  {len(js)} chars -> {sys.argv[2]}")
PYEOF
}

# The three page builds are the one part of this run that cannot use a
# throwaway study: --worklist reads reformatted/roi_worklist.csv, so a page is
# generated from real pipeline outputs. They are handed the repo config
# EXPLICITLY rather than inheriting it, so that dependency is stated rather
# than accidental - and if there is no config, the page suites are skipped and
# the Python suites still run, which is what a fresh clone gets.
BUILD_CONFIG="${LS_BUILD_CONFIG:-$REPO/config.json}"
SKIP_PAGES=0
if [ ! -f "$BUILD_CONFIG" ]; then
  echo "no $BUILD_CONFIG - skipping the curator page suites"
  SKIP_PAGES=1
else
  # A config that exists but points at an out_root that does not is the state
  # this machine is in whenever the data drive is unplugged, and the drive here
  # does not merely drop writes - it goes away (see scripts/ls_io.py). The
  # pages are generated from real pipeline outputs, so there is nothing to
  # build; the Python suites do not need them and must still run.
  #
  # LS_CONFIG is named here for the same reason build_page names it: this
  # question is about the config the pages are built against, not about
  # whichever config a bare ls_config would find. Naming it is also what makes
  # the read work at all under the LS_CONFIG_STRICT set above - strict mode
  # forbids the repo-config fallback, so the un-named form exited 1 and printed
  # nothing on EVERY machine, which made BUILD_OUT always empty and skipped
  # these three suites unconditionally from 3e6c250 until now.
  BUILD_OUT="$(LS_CONFIG="$BUILD_CONFIG" "$PY" "$REPO/scripts/ls_config.py" \
                 --print out_root 2>/dev/null)"
  if [ -z "$BUILD_OUT" ]; then
    # Two different faults, two different remedies, so say which one it is.
    echo "could not read out_root from $BUILD_CONFIG - skipping the curator page suites"
    SKIP_PAGES=1
  elif [ ! -d "$BUILD_OUT" ]; then
    echo "out_root $BUILD_OUT does not exist - skipping the curator page suites"
    SKIP_PAGES=1
  fi
fi

if [ "$SKIP_PAGES" = "0" ]; then
  build_page 04l_roi_curator.py curator --marker AF568 --worklist --rgb --no-seed
  build_page 04d_rotation_curator.py rotation_curator --no-proposals
  build_page 04k_level_curator.py level_curator
fi

fail=0
if [ "$SKIP_PAGES" = "0" ]; then
for t in "$TESTS"/*.test.js; do
  echo
  echo "=== $(basename "$t") ==="
  node "$t" || fail=1
done
fi

# The Python suites run alongside rather than inside the Node harness: they
# exercise the scripts directly and have no browser stub to share.
for t in "$TESTS"/test_*.py; do
  [ -e "$t" ] || continue
  echo
  echo "=== $(basename "$t") ==="
  "$PY" "$t" || fail=1
done

echo
if [ "$fail" -eq 0 ]; then echo "ALL SUITES PASS"; else echo "SUITE FAILURES"; fi
exit "$fail"
