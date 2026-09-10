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
print("--- paired is not 'paired with these two fluorophore names' ---")

# 02 is reachable for ANY paired study - that is what layouts_for() says above.
# It computed the study's markers at :220 and then threw them away at :223:
#
#     markers = sorted({r["marker_channel"] for r in rows})
#     if len(markers) != 2: print("!! expected two marker channels")
#     marker_a, marker_b = "AF568", "AF488"
#
# so `chosen.get((animal, slide, "AF568"))` came back [] for every slide, the
# `if not a_rows or not b_rows` branch fired, `for r in (a_rows or b_rows)`
# iterated an empty list, nothing was appended, and _write printed "(nothing to
# write for pairs.csv)". The len() != 2 warning did NOT fire - there really are
# two markers - so that one line was the only signal that stage 2 of the
# pipeline had produced no output at all.

import csv                                                   # noqa: E402

if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _fixture import temp_study, load_stage                  # noqa: E402

SCENE_COLS = ["animal", "slide", "variant", "file", "scene_uid", "scene_index",
              "slide_serial", "section_order", "marker_channel",
              "center_x_um", "center_y_um"]

# One animal, one slide, imaged once per marker. Sections 8 mm apart against a
# 100 um reload displacement is the easy case on purpose: what is under test is
# whether the two passes are LOOKED UP at all, not the matching. The last
# section of each pass has no partner in the other, so both unmatched statuses
# are exercised as well as `matched`.
YS_A = [0.0, 8000.0, 16000.0, 32000.0]
YS_B = [0.0, 8000.0, 16000.0, 24000.0]
RELOAD_UM = 100.0


def _manifest(path, markers):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = []
    for k, marker in enumerate(markers):
        letter = "ab"[k] if k < 2 else "c"
        ys = (YS_A, YS_B)[k] if k < 2 else YS_B
        off = k * RELOAD_UM
        for i, y in enumerate(ys):
            rows.append({
                "animal": "AB12", "slide": 1, "variant": letter,
                "file": f"AB12_1{letter}.czi",
                "scene_uid": f"AB12_1{letter}-s{i}", "scene_index": i,
                "slide_serial": i + 1, "section_order": i + 1,
                "marker_channel": marker,
                "center_x_um": off, "center_y_um": y + off,
            })
    with open(path, "w", newline="\n", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SCENE_COLS)
        w.writeheader()
        w.writerows(rows)


def _run_02(markers, tag):
    """02.main() under a paired study of these markers. Returns (header, rows)."""
    with temp_study(acquisition={"layout": "paired",
                                 "markers": list(markers)}) as _st:
        P2 = load_stage("02_pair_passes.py", name="lsstage_02_" + tag)
        _manifest(os.path.join(P2.MANIFEST_DIR, "manifest_scenes.csv"), markers)
        P2.main()
        path = os.path.join(P2.OUT_ROOT, "pairs.csv")
        if not os.path.exists(path):
            return [], []
        with open(path, newline="", encoding="utf-8") as fh:
            rdr = csv.DictReader(fh)
            rows = list(rdr)
            return list(rdr.fieldnames or []), rows


mk_header, mk_rows = _run_02(["Mk1", "Mk2"], "mk")

chk("a paired study of Mk1/Mk2 gets a pairs.csv with rows in it",
    len(mk_rows), 5)
chk("...three of them matched pairs",
    sum(1 for r in mk_rows if r["status"] == "matched"), 3)
chk("...and its columns carry the markers, not two antibodies",
    mk_header,
    ["section_uid", "animal", "slide", "slide_serial", "status",
     "mk1_file", "mk1_scene", "mk1_scene_uid",
     "mk2_file", "mk2_scene", "mk2_scene_uid",
     "match_distance_um", "center_x_um", "center_y_um"])
chk("...and so do the statuses",
    sorted({r["status"] for r in mk_rows}),
    ["matched", "unmatched_Mk1", "unmatched_Mk2"])

print()
print("--- and the LS study's header does not move ---")

# THE WHOLE REASON deriving these from slug() is safe. `slug("AF568")` is
# "af568", which is the literal 02 has always written, so the live pairs.csv
# header comes back character for character and no fallback is needed. If
# slug() ever changed, this is the line that says so - before the operator's
# 1,379-row pairs.csv stopped joining to anything downstream.
LIVE_HEADER = ["section_uid", "animal", "slide", "slide_serial", "status",
               "af568_file", "af568_scene", "af568_scene_uid",
               "af488_file", "af488_scene", "af488_scene_uid",
               "match_distance_um", "center_x_um", "center_y_um"]

ls_header, ls_rows = _run_02(["AF568", "AF488"], "ls")
chk("the generated header is the live file's, exactly", ls_header, LIVE_HEADER)
chk("...and the statuses keep the marker name verbatim",
    sorted({r["status"] for r in ls_rows}),
    ["matched", "unmatched_AF488", "unmatched_AF568"])

print()
print("--- a paired study 02 cannot pair is a stop, not a warning ---")

# 02 pairs TWO passes onto one physical section. A one- or three-marker paired
# study has no meaning for it, and the old code printed a warning and carried
# on - into a silently empty pairs.csv, which is indistinguishable from a study
# where nothing paired.


def _refuses(markers):
    with temp_study(acquisition={"layout": "paired",
                                 "markers": list(markers)}) as _st:
        P2 = load_stage("02_pair_passes.py", name="lsstage_02_n")
        _manifest(os.path.join(P2.MANIFEST_DIR, "manifest_scenes.csv"), markers)
        try:
            P2.main()
        except SystemExit as exc:
            return "two passes" in str(exc)
        return False


chk("three declared markers is refused", _refuses(["A", "B", "C"]), True)
chk("one declared marker is refused", _refuses(["A"]), True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
