#!/usr/bin/env bash
# Run the ROI curator suites.
#
#   bash tests/run.sh
#
# The curator is a generated page, so there is a build step: regenerate it with
# --no-seed, lift out its <script>, and run the suites against that.
#
# --no-seed matters. The page normally embeds whatever curation is in
# out_root/curation so a browser copy opens with the real work; a suite reading
# that would start with hundreds of sections it knows nothing about, and its
# counts would change every time someone curated. Tests must not depend on the
# operator's data. The page is regenerated WITH the seed afterwards, so running
# the tests does not quietly downgrade the file being used.
#
# What these cover: seed ordering, guided placement, landmark radius, both
# markers in one page, the filters, rotation, and what reaches the exports.
# What they do not: anything visual. Canvas calls are swallowed by the stub, so
# rendering is checked in a real browser instead.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TESTS="$REPO/tests"
BUILD="$TESTS/build"
CURATOR="$REPO/scripts/04l_roi_curator.py"

# Prefer the app venv, since that is the interpreter the pipeline is built on.
PY="${PY:-$REPO/work/appenv/Scripts/python.exe}"
[ -x "$PY" ] || PY="python"

ARGS=(--marker AF568 --worklist --rgb)

mkdir -p "$BUILD"

echo "building the curator page without embedded curation..."
"$PY" "$CURATOR" "${ARGS[@]}" --no-seed > /dev/null || {
  echo "could not generate the curator page"; exit 2; }

"$PY" - "$REPO" <<'PYEOF' || exit 2
import io, json, os, re, sys
repo = sys.argv[1]
with open(os.path.join(repo, "config.json"), encoding="utf-8") as fh:
    out_root = json.load(fh)["out_root"]
page = os.path.join(out_root, "reformatted", "roi_curator.html")
html = io.open(page, encoding="utf-8").read()
js = max(re.findall(r"<script>(.*?)</script>", html, re.S), key=len)
dst = os.path.join(repo, "tests", "build", "curator.js")
io.open(dst, "w", encoding="utf-8", newline="").write(js)
print(f"  {len(js)} chars -> tests/build/curator.js")
PYEOF

fail=0
for t in "$TESTS"/*.test.js; do
  echo
  echo "=== $(basename "$t") ==="
  node "$t" || fail=1
done

# The Python suites run alongside rather than inside the Node harness: they
# exercise app/ modules directly and have no browser stub to share.
for t in "$TESTS"/test_*.py; do
  [ -e "$t" ] || continue
  echo
  echo "=== $(basename "$t") ==="
  "$PY" "$t" || fail=1
done

echo
echo "restoring the page with its curation..."
"$PY" "$CURATOR" "${ARGS[@]}" | grep -i "carrying" || true

echo
if [ "$fail" -eq 0 ]; then echo "ALL SUITES PASS"; else echo "SUITE FAILURES"; fi
exit "$fail"
