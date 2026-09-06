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
[ -x "$PY" ] || PY="python"

mkdir -p "$BUILD"

# build_page <script> <name> [args...]: generate scripts/<script> to
# tests/build/<name>.html and lift its largest <script> block to <name>.js.
build_page () {
  local script="$1" name="$2"; shift 2
  echo "building $name..."
  "$PY" "$REPO/scripts/$script" "$@" --out "$BUILD/$name.html" > /dev/null || {
    echo "could not generate $name"; exit 2; }
  "$PY" - "$BUILD/$name.html" "$BUILD/$name.js" <<'PYEOF' || exit 2
import io, re, sys
html = io.open(sys.argv[1], encoding="utf-8").read()
js = max(re.findall(r"<script>(.*?)</script>", html, re.S), key=len)
io.open(sys.argv[2], "w", encoding="utf-8", newline="").write(js)
print(f"  {len(js)} chars -> {sys.argv[2]}")
PYEOF
}

build_page 04l_roi_curator.py curator --marker AF568 --worklist --rgb --no-seed
build_page 04d_rotation_curator.py rotation_curator --no-proposals
build_page 04k_level_curator.py level_curator

fail=0
for t in "$TESTS"/*.test.js; do
  echo
  echo "=== $(basename "$t") ==="
  node "$t" || fail=1
done

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
