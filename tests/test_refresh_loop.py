"""06e: Rscript by version, and a stall that counts readings.

Run:  python tests/test_refresh_loop.py
"""

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

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

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
