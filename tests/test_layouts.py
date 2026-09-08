"""Which stages apply to which acquisition layout.

02_pair_passes pairs two physical scans of one section; 04i carries one pass's
curation onto the other. A multiplex study has one scan, so both have nothing
to do - not "run and produce nothing", which is how a stage that silently
returns [] gets mistaken for a stage that ran.
"""

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_layouts as LY                                     # noqa: E402
import ls_channels as CH                                    # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


chk("02_pair_passes is paired-only",
    LY.layouts_for("02_pair_passes.py"), ("paired",))
chk("04i_propagate_to_perk is paired-only",
    LY.layouts_for("04i_propagate_to_perk.py"), ("paired",))
chk("an ordinary stage applies to both",
    LY.layouts_for("05c_detect_rois.py"), CH.LAYOUTS)
chk("a stage nobody classified still applies to both",
    LY.layouts_for("99_not_a_stage.py"), CH.LAYOUTS)

chk("a paired study runs the paired-only stage",
    LY.applies("02_pair_passes.py", "paired"), True)
chk("a multiplex study does not",
    LY.applies("02_pair_passes.py", "multiplex"), False)
chk("a multiplex study skips exactly those two",
    LY.skipped("multiplex"),
    ["02_pair_passes.py", "04i_propagate_to_perk.py"])
chk("a paired study skips nothing", LY.skipped("paired"), [])

print()
print("--- every numbered script applies to at least one layout ---")

orphans = []
for path in sorted(glob.glob(os.path.join(REPO, "scripts", "*.py"))):
    name = os.path.basename(path)
    if not re.match(r"^\d", name):
        continue
    if not LY.layouts_for(name):
        orphans.append(name)

chk("no numbered script applies to no layout", orphans, [])
for o in orphans:
    print(f"     {o}")

print()
print("--- the restricted stages are real files, not typos ---")
missing = [s for s in sorted(LY.RESTRICTED)
           if not os.path.exists(os.path.join(REPO, "scripts", s))]
chk("every restricted name is a script that exists", missing, [])

print()
print("--- the exceptions are named, and only the named ones ---")
chk("exactly two stages are layout-restricted",
    sorted(LY.RESTRICTED), ["02_pair_passes.py", "04i_propagate_to_perk.py"])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
