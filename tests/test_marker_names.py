"""The marker list, which is layout-aware.

Under multiplex the channel table already says what the markers are. Under
paired there is no channel table - each scan carries the nuclear channel plus
one marker - so the study declares the list. Two sources for one fact is how
they drift, so each layout has exactly one.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_channels as CH                                    # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


print("--- multiplex: the channel table is the list ---")

MULTI = {"acquisition": {"layout": "multiplex", "channels": [
    {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
    {"name": "pERK", "role": "marker", "czi_name": "AF568", "index": 1},
    {"name": "PCNA", "role": "marker", "czi_name": "AF488", "index": 2}]}}

chk("markers come from the table, in declared order",
    CH.marker_names(MULTI), ["pERK", "PCNA"])
chk("the nuclear channel is not a marker",
    "DAPI" in CH.marker_names(MULTI), False)

print()
print("--- paired: the study declares the list ---")

PAIRED = {"acquisition": {"layout": "paired",
                          "markers": ["AF568", "AF488"]}}

chk("markers come from acquisition.markers",
    CH.marker_names(PAIRED), ["AF568", "AF488"])
chk("declared order is preserved",
    CH.marker_names({"acquisition": {"layout": "paired",
                                     "markers": ["AF488", "AF568"]}}),
    ["AF488", "AF568"])

print()
print("--- the two sources may not both be used ---")

errors, _ = CH.validate({"layout": "multiplex", "markers": ["X"], "channels": [
    {"name": "DAPI", "role": "nuclear", "index": 0},
    {"name": "pERK", "role": "marker", "index": 1}]}, "multiplex")
chk("multiplex declaring acquisition.markers is an error",
    any("markers" in e for e in errors), True)

# Not an error: every stage validates config at import, so a paired study
# whose operator has not named their markers yet has to stay loadable. The
# stage that needs the names fails instead, in require().
errs, warns = CH.validate({"layout": "paired", "markers": []}, "paired")
chk("paired with no markers is a warning, not an error", errs, [])
chk("...and the warning names the key",
    any("acquisition.markers" in w for w in warns), True)
try:
    CH.require({"layout": "paired", "markers": []}, "paired")
    chk("require() refuses a paired study with no markers", False, True)
except SystemExit as exc:
    chk("require() refuses a paired study with no markers",
        "acquisition.markers" in str(exc), True)
chk("...but require() is happy once they are named",
    CH.require({"layout": "paired", "markers": ["AF568"]}, "paired"), [])

errs, _ = CH.validate({"layout": "paired", "markers": ["A", "A"]}, "paired")
chk("a duplicate marker name is an error",
    any("twice" in e or "duplicate" in e for e in errs), True)

print()
print("--- a marker name becomes a directory, so it is judged as one ---")

# The whole NAME_RE rule was deleted by a reviewer and all three suites still
# passed, while the mutant accepted markers = ["../../AF568"]. These are what
# was missing.
for bad_name in ("..", "AF/568", "AF\\568", "", " AF568", "con:", "a" * 200):
    e, _ = CH.validate({"layout": "paired", "markers": [bad_name]}, "paired")
    chk(f"marker name {bad_name!r:12} is refused",
        any("not usable in a file path" in x for x in e), True)

for ok_name in ("AF568", "AF 568", "Marker_1", "p-ERK", "CD3.1", "AF568+"):
    e, _ = CH.validate({"layout": "paired", "markers": [ok_name]}, "paired")
    chk(f"marker name {ok_name!r:12} is accepted", e, [])

print()
print("--- an entry that is not a name at all ---")

# Every one of these used to pass with ZERO errors or crash the validator:
# the identity check compared raw values while the rule and the output path
# were built from str(m), so ["1", 1] was two markers writing to one file.
for bad in ([{"name": "AF568"}], [["AF568"]], ["AF568", None], [1, 2],
            [True, "AF488"], [3.5]):
    try:
        e, _ = CH.validate({"layout": "paired", "markers": bad}, "paired")
        chk(f"{str(bad):24} is reported, not raised on", len(e) >= 1, True)
    except Exception as exc:                                # noqa: BLE001
        chk(f"{str(bad):24} is reported, not raised on",
            f"raised {type(exc).__name__}", True)

e, _ = CH.validate({"layout": "paired", "markers": ["1", 1]}, "paired")
chk("['1', 1] is refused - both would build the same output path",
    len(e) >= 1, True)
chk("...and it says what the offending entry is",
    any("int" in x for x in e), True)

# Three separate faults, three messages: fixing a config one error per
# attempt is what accumulating exists to prevent.
e, _ = CH.validate(
    {"layout": "paired", "markers": [{"n": 1}, "AF/568", "A", "A"]}, "paired")
chk("three unrelated marker faults are all reported", len(e), 3)

errs, _ = CH.validate({"layout": "paired", "markers": "AF568"}, "paired")
chk("a string instead of a list is judged, not crashed on",
    any("markers" in e for e in errs), True)

errs, _ = CH.validate({"layout": "paired", "markers": ["AF568"],
                       "channels": [{"name": "DAPI", "role": "nuclear",
                                     "index": 0}]}, "paired")
chk("paired declaring a channel table is an error",
    any("channel" in e.lower() for e in errs), True)

print()
print("--- the rules fire through ls_config, not just in isolation ---")

# The unit checks above passed while this was dead code: ls_config called
# ls_channels.validate with the channels LIST, so nothing ever reached the
# marker rules. A config-level check is the one that would have caught it.
import ls_config as LC                                      # noqa: E402

BASE = {"schema_version": 1, "study": {"name": "t"},
        "source_dir": ".", "out_root": ".", "atlas_pdf": ".",
        "pixel_size_um": 0.65, "overview_target_um_per_px": 4.0,
        "section_thickness_um": 12.0}


def cfg_errors(acq):
    full = dict(BASE)
    full["acquisition"] = acq
    errs, _ = LC.validate(full, "<test>")
    return [e for e in errs if "marker" in e.lower()]


def cfg_warnings(acq):
    full = dict(BASE)
    full["acquisition"] = acq
    _, warns = LC.validate(full, "<test>")
    return [w for w in warns if "marker" in w.lower()]


chk("a paired study with no markers warns through ls_config",
    bool(cfg_warnings({"layout": "paired"})), True)
chk("...and does not stop the config loading",
    cfg_errors({"layout": "paired"}), [])
chk("a marker entry that is not a name is rejected by ls_config",
    bool(cfg_errors({"layout": "paired", "markers": [{"name": "AF568"}]})),
    True)
chk("markers as a string is rejected by ls_config",
    bool(cfg_errors({"layout": "paired", "markers": "AF568"})), True)
chk("a duplicate marker is rejected by ls_config",
    bool(cfg_errors({"layout": "paired", "markers": ["A", "A"]})), True)
chk("a well-formed paired study passes",
    cfg_errors({"layout": "paired", "markers": ["AF568", "AF488"]}), [])
chk("a well-formed multiplex study passes",
    cfg_errors({"layout": "multiplex", "channels": [
        {"name": "DAPI", "role": "nuclear", "index": 0},
        {"name": "M1", "role": "marker", "index": 1}]}), [])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
