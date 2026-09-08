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

errs, _ = CH.validate({"layout": "paired", "markers": []}, "paired")
chk("paired with no markers is an error",
    any("markers" in e for e in errs), True)

errs, _ = CH.validate({"layout": "paired", "markers": ["A", "A"]}, "paired")
chk("a duplicate marker name is an error",
    any("twice" in e or "duplicate" in e for e in errs), True)

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


chk("a paired study with no markers is rejected by ls_config",
    bool(cfg_errors({"layout": "paired"})), True)
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
