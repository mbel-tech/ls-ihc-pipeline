"""No stage offers a fixed list of markers.

A stage whose --marker choices are a literal cannot be pointed at a study with
different markers: argparse rejects the value before any code runs, so the
failure is a usage error about an unrelated fluorophore.
"""

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


# A choices= list holding a bare fluorophore-looking literal.
LIT = re.compile(r"choices\s*=\s*[\[(][^\])]*[\"']AF\d+[\"']")
offenders = []
for path in sorted(glob.glob(os.path.join(REPO, "scripts", "*.py"))):
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if LIT.search(line):
                offenders.append(f"{os.path.basename(path)}:{n}")

chk("no stage hardcodes its marker choices", offenders, [])
for o in offenders:
    print(f"     {o}")

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
