"""06e: Rscript by version, and a stall that counts readings.

Run:  python tests/test_refresh_loop.py
"""

import sys
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

# This suite imports stage modules, which read config at import. Without a
# config of its own it would fall through to the operator's live study and
# then pass or fail on their data. See tests/_fixture.py.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _fixture import use_temp_study  # noqa: E402

STUDY = use_temp_study()

_spec = importlib.util.spec_from_file_location("e", os.path.join(SCRIPTS, "06e_refresh_loop.py"))
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


chk("version parsed from the path", E.rscript_version(r"C:\Program Files\R\R-4.10.0\bin\Rscript.exe"), (4, 10, 0))
chk("no version -> lowest", E.rscript_version(r"C:\x\Rscript.exe"), (0, 0, 0))
hits = [r"C:\Program Files\R\R-4.9.1\bin\Rscript.exe", r"C:\Program Files\R\R-4.10.0\bin\Rscript.exe",
        r"C:\Program Files\R\R-4.6.0\bin\Rscript.exe"]
chk("newest by version, not by name", E.newest(hits), hits[1])

# Readings 100, 100, 100 with --stall-cycles 3 stop on the THIRD reading.
stalled, last = 0, None
seen = []
for done in (100, 100, 100):
    stalled = E.stall_count(stalled, done, last)
    last = done
    seen.append(stalled)
chk("three identical readings count three", seen, [1, 2, 3])
chk("progress resets the count", E.stall_count(3, 101, 100), 1)

with open(os.path.join(SCRIPTS, "06e_refresh_loop.py"), encoding="utf-8") as fh:
    src = fh.read()
chk("Rscript output is decoded as UTF-8", 'encoding="utf-8", errors="replace"' in src, True)


# --- which markers the loop re-plots, and in what order ------------------
#
# `marker_list()` had no coverage at all, and it carried three "AF568"
# literals: two fallbacks and the ordering that puts the watched marker first.
# The ordering is the one that degrades silently - it falls back to plain
# alphabetical, and the loop's own note at :137-139 says why that is wrong: a
# plotting failure ends the loop, so an untested marker on the thinnest data
# would take it down before the watched marker's figures had been drawn once.
#
# The study below is chosen so alphabetical and declared order DISAGREE:
# "Zeta" is declared first, "Alpha" sorts first. A study whose declared order
# happens to be alphabetical cannot tell the two implementations apart.
from _fixture import temp_study, load_stage                 # noqa: E402

OUT_OF_ORDER = {"layout": "paired", "markers": ["Zeta", "Alpha"]}
with temp_study(acquisition=OUT_OF_ORDER):
    loop = load_stage("06e_refresh_loop.py")
    meas = loop.G6C.MEAS_CSV
    chk("nothing measured yet: the first declared marker, not a literal",
        loop.marker_list(), ["Zeta"])

    os.makedirs(os.path.dirname(meas), exist_ok=True)
    with open(meas, "w", encoding="utf-8", newline="") as fh:
        fh.write("scene_uid,marker\n")
    chk("a header and no rows is the same answer", loop.marker_list(), ["Zeta"])

    with open(meas, "w", encoding="utf-8", newline="") as fh:
        fh.write("scene_uid,marker\nu1,Alpha\nu2,Zeta\nu3,Alpha\n")
    chk("the watched marker is re-plotted FIRST, whatever it sorts as",
        loop.marker_list(), ["Zeta", "Alpha"])

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
