"""run_all.sh asks whether a stage applies before running it.

A static check: run_all.sh is bash and running it would run the pipeline.

Only ONE of the two layout-restricted stages is actually batched here.
04i_propagate_to_perk is part of the 04-series curation chain, which run_all.sh
deliberately does not run - it needs the operator between the steps, as the
comment above step 15 says. So this suite does not count occurrences against a
fixed number: it asks ls_layouts which stages are restricted, finds the ones
run_all.sh actually invokes, and requires each of those to be gated. If 04i is
ever batched, this starts demanding a gate for it without anyone editing here.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_layouts as LY                                     # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


with open(os.path.join(REPO, "scripts", "run_all.sh"), encoding="utf-8") as fh:
    src = fh.read()

chk("run_all.sh reads the study's layout", "LAYOUT=" in src, True)
chk("...from the config, not from a literal",
    bool(re.search(r"LAYOUT=.*LS_CONFIG", src, re.S)), True)
chk("the gate asks ls_layouts rather than repeating it",
    "ls_layouts" in src, True)
chk("the gate is defined once", src.count("layout_applies() {"), 1)

print()
print("--- every restricted stage this script runs is gated ---")

# A stage is "invoked" when a line runs it as a command, rather than merely
# naming it in prose - the comments discuss stages they do not run.
invoked = [s for s in sorted(LY.RESTRICTED)
           if re.search(r"^\s*(python|\"\$CZIPY\")\s+" + re.escape(s),
                        src, re.M)]
print(f"     restricted: {sorted(LY.RESTRICTED)}")
print(f"     of those, invoked by run_all.sh: {invoked}")

chk("at least one restricted stage is actually batched", bool(invoked), True)

ungated = [s for s in invoked if f"layout_applies {s}" not in src]
chk("no restricted stage runs without asking first", ungated, [])

chk("the gate is called once per batched restricted stage",
    src.count("layout_applies ") , len(invoked))

print()
print("--- a skipped stage says so, rather than passing in silence ---")
chk("the else branch prints a SKIP naming the layout",
    bool(re.search(r"SKIP.*%s.*\\n'.*\"\$LAYOUT\"", src)), True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
