"""The channel table: what a study says its CZI channels are, and what each is for.

Reading the wrong plane produces a plausible number rather than an error, so
resolution is the part that must never guess. A declared channel resolves by
the CZI's own channel name first - which survives channels being acquired in a
different order - and by index only as a fallback. When neither works it says
what it wanted and what the file actually has.

Run:  python tests/test_ls_channels.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_channels as CH                                    # noqa: E402

failures = []


def chk(name, got, want):
    ok = got == want
    shown = got if len(repr(got)) < 90 else f"<{type(got).__name__}>"
    print(f"{'ok  ' if ok else 'FAIL'} {name:60} {shown!r}")
    if not ok:
        print(f"     want {want!r}")
        failures.append(name)


BLOCK = [
    {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
    {"name": "pERK", "role": "marker", "czi_name": "AF568", "index": 1,
     "segment": "nuclear"},
    {"name": "GFAP", "role": "marker", "czi_name": "AF647", "index": 2,
     "segment": "own", "backend": "threshold", "nucleus_shaped": False},
]

print("--- parsing ---")
chans = CH.parse(BLOCK)
chk("every declared channel is parsed", [c.name for c in chans],
    ["DAPI", "pERK", "GFAP"])
chk("the nuclear channel is findable", CH.nuclear(chans).name, "DAPI")
chk("markers are the ones to measure", [c.name for c in CH.markers(chans)],
    ["pERK", "GFAP"])
chk("segment defaults to nuclear when a nuclear channel exists",
    CH.parse([BLOCK[0], {"name": "X", "role": "marker", "index": 1}])[1].segment,
    "nuclear")
chk("a marker on its own channel defaults to stardist",
    CH.parse([{"name": "X", "role": "marker", "index": 0,
               "segment": "own"}])[0].backend, "stardist")

print()
print("--- resolving a declared channel to a plane in one file ---")
chk("by CZI channel name, whatever the order",
    CH.resolve(chans, ["AF647", "DAPI", "AF568"]),
    {"DAPI": 1, "pERK": 2, "GFAP": 0})
chk("by index when the file names nothing",
    CH.resolve(chans, [None, None, None]),
    {"DAPI": 0, "pERK": 1, "GFAP": 2})
chk("by index when the name is not among them",
    CH.resolve(CH.parse([{"name": "M", "role": "marker",
                          "czi_name": "AF488", "index": 1}]),
               ["DAPI", "AF568"]),
    {"M": 1})

try:
    CH.resolve(chans, ["DAPI"])
    chk("a channel that resolves to nothing raises", False, True)
except CH.ChannelError as exc:
    chk("a channel that resolves to nothing raises", True, True)
    chk("...and names the channel it wanted", "pERK" in str(exc), True)
    chk("...and what the file actually has", "DAPI" in str(exc), True)

print()
print("--- what a study may not declare ---")


def errs(block, layout="multiplex"):
    return CH.validate(block, layout)


chk("a valid table has nothing to say", errs(BLOCK), [])
chk("two channels cannot share a name",
    len(errs([BLOCK[0], dict(BLOCK[1], name="DAPI")])), 1)
# Each of these declares an otherwise-valid table, so the count below is the
# fault under test and not an echo of it: a block with no valid marker would
# also report "nothing to measure", which is true but is a second fault.
chk("a name has to be usable as a folder",
    len(errs([dict(BLOCK[0], name="a/b"), BLOCK[1]])), 1)
chk("there is at most one nuclear channel",
    len(errs([BLOCK[0], BLOCK[1], dict(BLOCK[2], role="nuclear")])), 1)
chk("something has to be a marker",
    len(errs([BLOCK[0]])), 1)
chk("an unknown role is refused",
    len(errs([BLOCK[0], BLOCK[1], dict(BLOCK[2], role="whatever")])), 1)

# Independent faults are reported together. Returning only the first would
# mean fixing a config one error per attempt.
chk("two unrelated faults are both reported",
    len(errs([dict(BLOCK[0], name="a/b")])), 2)

# The contradiction the spec names: StarDist is a nucleus detector, so asking
# for it on something declared not nucleus-shaped would under-detect silently.
bad = errs([BLOCK[0], dict(BLOCK[1], segment="own", backend="stardist",
                           nucleus_shaped=False)])
chk("stardist on a non-nuclear marker is refused", len(bad), 1)
chk("...and says why", "nucleus" in bad[0].lower(), True)

chk("segment: nuclear needs a nuclear channel to segment",
    len(errs([dict(BLOCK[1], segment="nuclear")])), 1)
chk("...but own-channel markers alone are fine",
    errs([dict(BLOCK[1], segment="own", backend="stardist",
               nucleus_shaped=True)]), [])

chk("the paired layout declares no channels",
    len(errs(BLOCK, layout="paired")), 1)
chk("...and an empty table is what it wants", errs([], layout="paired"), [])
chk("multiplex with no channels at all is refused",
    len(errs([], layout="multiplex")), 1)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
