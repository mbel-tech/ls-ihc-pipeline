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
# The other direction of the same default, and the one a study with no
# counterstain depends on: with no nuclear channel to segment on, a marker
# segments itself. That is what lets such a study declare nothing about
# segmentation and still be read correctly.
chk("segment defaults to own when there is no nuclear channel",
    [c.segment for c in CH.markers(CH.parse(
        [{"name": "X", "role": "marker", "index": 0}]))], ["own"])

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

# Two planes under one name is not something to pick between silently.
try:
    CH.resolve(CH.parse([{"name": "N", "role": "nuclear",
                          "czi_name": "DAPI", "index": 0}]),
               ["DAPI", "DAPI"])
    chk("two planes with the same name raises", False, True)
except CH.ChannelError as exc:
    chk("two planes with the same name raises", True, True)
    chk("...and says which planes they are", "planes 0, 1" in str(exc), True)

print()
print("--- what a study may not declare ---")


def block_of(table, layout, markers=None):
    """The `acquisition` block a study with this channel table would have.

    validate() judges the block, not the bare table: the `acquisition.markers`
    rules read a key a list cannot carry, and the version that accepted either
    shape skipped those rules on the list - which is how they came to be
    checked by nothing in the real path. A paired study must name its markers,
    so these helpers take them alongside the table.
    """
    block = {"layout": layout, "channels": table}
    if markers is not None:
        block["markers"] = markers
    return block


def errs(table, layout="multiplex", markers=None):
    return CH.validate(block_of(table, layout, markers), layout)[0]


def warns(table, layout="multiplex", markers=None):
    return CH.validate(block_of(table, layout, markers), layout)[1]


chk("a valid table has nothing to say", errs(BLOCK), [])
chk("two channels cannot share a name",
    len(errs([BLOCK[0], dict(BLOCK[1], name="DAPI")])), 1)
chk("...and says which name",
    "both called" in errs([BLOCK[0], dict(BLOCK[1], name="DAPI")])[0], True)
# Each of these declares an otherwise-valid table, so the count below is the
# fault under test and not an echo of it: a block with no valid marker would
# also report "nothing to measure", which is true but is a second fault.
chk("a name has to be usable as a folder",
    len(errs([dict(BLOCK[0], name="a/b"), BLOCK[1]])), 1)
chk("there is at most one nuclear channel",
    len(errs([BLOCK[0], BLOCK[1], dict(BLOCK[2], role="nuclear")])), 1)
chk("...and says how many there are",
    "marked nuclear" in errs([BLOCK[0], BLOCK[1],
                              dict(BLOCK[2], role="nuclear")])[0], True)
chk("something has to be a marker",
    len(errs([BLOCK[0]])), 1)
chk("...and says there is nothing to measure",
    "nothing to measure" in errs([BLOCK[0]])[0], True)
chk("an unknown role is refused",
    len(errs([BLOCK[0], BLOCK[1], dict(BLOCK[2], role="whatever")])), 1)
chk("...and lists the roles there are",
    "registration" in errs([BLOCK[0], BLOCK[1],
                            dict(BLOCK[2], role="whatever")])[0], True)

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

seg = errs([BLOCK[0], dict(BLOCK[1], segment="sideways")])
chk("an unknown segment is refused", len(seg), 1)
chk("...and lists the segments there are", "own" in seg[0], True)

back = errs([BLOCK[0], dict(BLOCK[1], segment="own", backend="magic")])
chk("an unknown backend is refused", len(back), 1)
chk("...and lists the backends there are", "threshold" in back[0], True)

chk("segment: nuclear needs a nuclear channel to segment",
    len(errs([dict(BLOCK[1], segment="nuclear")])), 1)
chk("...but own-channel markers alone are fine",
    errs([dict(BLOCK[1], segment="own", backend="stardist",
               nucleus_shaped=True)]), [])
# ...including when the table says nothing about segmentation at all. A study
# with no counterstain is a supported study, not a half-declared one, and
# parse's default above is what makes its markers segment themselves.
chk("a study may declare no nuclear channel at all",
    errs([{"name": "GFAP", "role": "marker", "index": 0}]), [])

chk("the paired layout declares no channels",
    len(errs(BLOCK, layout="paired", markers=["AF568"])), 1)
chk("...and no table, with the markers named, is what it wants",
    errs([], layout="paired", markers=["AF568"]), [])
# The markers are not optional under paired: with no channel table, that list
# is the only record of what the study measures. It warns rather than errors
# for the same reason the empty multiplex table does - every stage validates
# at import - and require() is where it is fatal.
chk("...and an empty table with no markers named is a warning",
    errs([], layout="paired"), [])
chk("...which names the key that is missing",
    any("acquisition.markers" in w for w in warns([], layout="paired")), True)
# A multiplex study with no channels yet is a warning, not an error - see the
# "not yet declared" section below. Kept split rather than folded into that
# section since it belongs next to the paired-layout comparison it explains.
chk("multiplex with no channels at all is not an error",
    errs([], layout="multiplex"), [])
chk("...but it is a warning", len(warns([], layout="multiplex")), 1)

print()
print("--- a table that cannot be read is reported, not raised on ---")
chk("a string where a list belongs", len(errs("DAPI,AF568")), 1)
chk("...and it says what it got", "not a str" in errs("DAPI,AF568")[0], True)
chk("an entry that is not a block", len(errs([["not", "a", "dict"]])), 1)
chk("a number", len(errs(42)), 1)

# The block itself gets the same treatment as the table inside it - including
# the old mistake of handing over the channels list, which is now a fault
# with a message rather than a silent half-validation.
for bad_block in ("acquisition", 42, [{"name": "DAPI"}]):
    got = CH.validate(bad_block, "multiplex")[0]
    chk(f"an acquisition block that is a {type(bad_block).__name__}",
        len(got) == 1 and "acquisition" in got[0], True)

print()
print("--- a channel with no way to be found ---")
chk("no czi_name and no index is refused",
    len(errs([{"name": "D", "role": "nuclear"},
              {"name": "A", "role": "marker", "index": 1}])), 1)
chk("...and says what to give it",
    "no way to find it" in errs([{"name": "D", "role": "nuclear"},
                                 {"name": "A", "role": "marker",
                                  "index": 1}])[0], True)
chk("two channels claiming one czi_name is refused",
    len(errs([dict(BLOCK[0], czi_name="AF568"), BLOCK[1]])), 1)

print()
print("--- not yet declared is a warning, not a failure ---")
chk("multiplex with no channels warns", len(warns([])), 1)
chk("...and is not an error", errs([]), [])

print()
print("--- two channels cannot land on one plane ---")
two = CH.parse([{"name": "A", "role": "marker", "index": 1},
                {"name": "B", "role": "marker", "index": 1}])
try:
    CH.resolve(two, ["DAPI", "AF568"])
    chk("two channels on one plane raises", False, True)
except CH.ChannelError as exc:
    chk("two channels on one plane raises", True, True)
    chk("...and names both", "'A'" in str(exc) and "'B'" in str(exc), True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
