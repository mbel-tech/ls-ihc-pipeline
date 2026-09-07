"""--survey and --preview are read-only modes.

Run:  python tests/test_survey_preview.py
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


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


F = load("f", "04f_exclusion_candidates.py")
chk("a normal run writes the candidates", os.path.basename(F.output_path(False)), "exclusion_candidates.csv")
chk("a survey writes its own file", F.output_path(True).replace("\\", "/").endswith("qc/exclusion/survey.csv"), True)
chk("...and not the candidates", F.output_path(True) == F.output_path(False), False)

G = load("g", "04g_artifact_mask.py")
chk("no preview: process everything, write masks", G.run_plan(0, 0), (True, True))
chk("preview 3 with 2 collected: keep going, no masks", G.run_plan(3, 2), (True, False))
chk("preview 3 with 3 collected: stop", G.run_plan(3, 3), (False, False))
with open(os.path.join(SCRIPTS, "04g_artifact_mask.py"), encoding="utf-8") as fh:
    src = fh.read()
chk("the mask write is gated on write_masks", "if write_masks:\n            with IO.atomic_save(" in src, True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
