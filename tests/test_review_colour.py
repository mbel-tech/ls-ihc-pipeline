"""The Review pane draws a marker in the colour the study gave it.

Two things used to decide that, and they disagreed. `04o_section_rgb` built
the section composites from `ls_channels`, positionally: first declared marker
red, second green. The curator's Review pane picked an SVG filter from
`const perk = p.marker === "AF568"` - so for any study whose first marker is
not called AF568, `perk` was false for every marker and the pane drew all of
them green, while the composites in the same grid drew the first in red. The
operator was shown one section in two colour schemes with nothing on the page
saying which was right.

This is the oracle for the fix. It is Python rather than JS deliberately: the
JS suites run against a page built from the LIVE study, where "first marker" and
"AF568" are the same marker, so nothing observable there can tell a correct
implementation from the hardcoded one. A study with the colours SWAPPED can,
and needs only two markers to do it.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from _fixture import temp_study, load_stage                 # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(62) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


def expected(colour, nuclear, lift):
    """What a filter over (m, m, d) has to be, restated from the definition of
    feColorMatrix rather than by calling the function under test.

    A 4x5 matrix, row-major, each row a linear combination of input
    (R, G, B, A, 1) producing one output channel.

    Input R is the marker plane in every source this pane loads: the overview
    composite is `np.dstack([m8, m8, d8])` (01_overviews.py:358), so R and G
    are literally the same array, and `_MARK.png` is greyscale so R=G=B there.
    That is why the coefficient on input G is always 0 - one source column for
    the marker, chosen once, rather than a different one per marker.

    Input B is the counterstain in `_RGB.png` and the marker AGAIN in
    `_MARK.png` - which is why the marker-only variant must never read input B,
    and why there is a PAIR of filters per channel rather than one filter with
    a toggle (see the page's own note beside the definitions).
    """
    return [colour[0], 0, lift * nuclear[0], 0, 0,
            colour[1], 0, lift * nuclear[1], 0, 0,
            colour[2], 0, lift * nuclear[2], 0, 0,
            0, 0, 0, 1, 0]


def numbers(values):
    """A `values` attribute back as 20 numbers, whatever the spacing."""
    return [float(x) for x in values.split()]


def build(mod):
    """(filters, {id: values}) for a stage module under the current study."""
    filters = mod.review_filters(mod.MARKERS, mod.MARKER_COLOURS,
                                 mod.NUCLEAR_COLOUR)
    return filters, {d["id"]: d["values"] for d in filters["defs"]}


LS_MARKERS = {"layout": "paired", "markers": ["AF568", "AF488"]}

print("--- THE ORACLE: a study whose colours are the other way round ---")
#
# AF568 is declared FIRST, so the positional default would make it red, and
# the page's old rule made it red too - `p.marker === "AF568"` picked
# revPerkDapi. Here the config says green. Only an implementation that reads
# the config can tell the two apart, and this is the cheapest study that asks.
with temp_study(acquisition=LS_MARKERS,
                display={"colours": {"AF568": "green", "AF488": "red"}}):
    mod = load_stage("04l_roi_curator.py")
    F, vals = build(mod)
    lift = mod.DAPI_LIFT

    for marker, colour in (("AF568", (0, 1, 0)), ("AF488", (1, 0, 0))):
        ids = F["byMarker"][marker]
        chk(f"{marker} + DAPI is drawn in the colour the CONFIG gives it",
            numbers(vals[ids["dapi"]]), expected(colour, (0, 0, 1), lift))
        chk(f"{marker} alone reads no counterstain at all",
            numbers(vals[ids["only"]]), expected(colour, (0, 0, 0), lift))

print()
print("--- the LS default: nothing declared, nothing moves ---")
with temp_study(acquisition=LS_MARKERS):
    mod = load_stage("04l_roi_curator.py")
    rgb = load_stage("04o_section_rgb.py")
    F, vals = build(mod)
    first, second = mod.MARKERS

    # The four matrices that were written out by hand in the page's <defs>.
    #
    # The first marker's pair comes back character for character. The second
    # marker's does NOT, and deliberately: `revPcnaDapi` was
    # "0 0 0 0 0  0 1 0 0 0  0 0 4 0 0  0 0 0 1 0" - it took the marker from
    # input G, where the first marker's took it from input R. Both are the same
    # picture, exactly, because 01_overviews writes `np.dstack([m8, m8, d8])`
    # and `_MARK.png` is greyscale - but "which input column is the marker"
    # cannot be per-marker once a colour can be magenta, because then output B
    # needs the marker and input B is the counterstain. One column, chosen
    # once: input R. The bytes on screen are unchanged; the string is not.
    chk("the first marker + DAPI is the old revPerkDapi, character for character",
        vals[F["byMarker"][first]["dapi"]],
        "1 0 0 0 0  0 0 0 0 0  0 0 4 0 0  0 0 0 1 0")
    chk("...and alone, the old revPerkOnly",
        vals[F["byMarker"][first]["only"]],
        "1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0")
    chk("the second marker + DAPI is the old revPcnaDapi, one column moved",
        vals[F["byMarker"][second]["dapi"]],
        "0 0 0 0 0  1 0 0 0 0  0 0 4 0 0  0 0 0 1 0")
    chk("...and alone, the old revPcnaOnly, same column",
        vals[F["byMarker"][second]["only"]],
        "0 0 0 0 0  1 0 0 0 0  0 0 0 0 0  0 0 0 1 0")
    chk("DAPI alone is unchanged", vals[F["dapiOnly"]],
        "0 0 0 0 0  0 0 0 0 0  0 0 4 0 0  0 0 0 1 0")
    chk("both channels off is unchanged", vals[F["blank"]],
        "0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0")
    chk("the luminance-to-alpha stencil is unchanged", vals[F["lumAlpha"]],
        "1 0 0 0 0  1 0 0 0 0  1 0 0 0 0  1 0 0 0 0")

    print()
    # THE POINT OF THE WHOLE CHANGE, asserted rather than argued: the vector
    # the pane tints with is the vector 04o composites with, marker by marker.
    # This cannot be written against the pre-change code at all - 04l had no
    # colour concept to compare.
    chk("the pane and the composite read the same colour map",
        mod.MARKER_COLOURS, rgb.MARKER_COLOURS)
    chk("...and the same counterstain colour",
        mod.NUCLEAR_COLOUR, rgb.NUCLEAR_COLOUR)
    for m in mod.MARKERS:
        row = numbers(vals[F["byMarker"][m]["dapi"]])
        chk(f"{m}: the filter's marker coefficients ARE 04o's colour",
            (row[0], row[5], row[10]), tuple(rgb.MARKER_COLOURS[m]))

    print()
    # Structural rules, stated once here rather than restated per marker.
    for entry in F["defs"]:
        got = numbers(entry["values"])
        chk(f"{entry['id']}: input G is never read", got[1::5][:3], [0, 0, 0])
    for m in mod.MARKERS:
        got = numbers(vals[F["byMarker"][m]["only"]])
        chk(f"{m}: the marker-only filter never reads input B",
            got[2::5][:3], [0, 0, 0])

print()
print("--- three markers, one hex colour, one with none ---")
with temp_study(acquisition={"layout": "paired", "markers": ["A", "B", "C"]},
                display={"colours": {"A": "#ff00ff"}}):
    mod = load_stage("04l_roi_curator.py")
    F, vals = build(mod)
    lift = mod.DAPI_LIFT

    chk("only the markers with a colour get a filter pair",
        sorted(F["byMarker"]), ["A", "B"])
    chk("the hex colour is what A is drawn in",
        numbers(vals[F["byMarker"]["A"]["dapi"]]),
        expected((1, 0, 1), (0, 0, 1), lift))
    chk("...and B keeps the positional green",
        numbers(vals[F["byMarker"]["B"]["dapi"]]),
        expected((0, 1, 0), (0, 0, 1), lift))

    # The page's own resolution rule: `FILTERS.byMarker[p.marker] ||
    # FALLBACK`. C has no colour, so it must land on the fallback - grey, which
    # says "no colour set" - and NOT on another marker's filter, which is the
    # bug this replaced.
    resolved = F["byMarker"].get("C") or F["fallback"]
    chk("an uncoloured marker resolves to the fallback", resolved, F["fallback"])
    chk("...which is not any real marker's pair",
        resolved in list(F["byMarker"].values()), False)
    chk("...and is grey, not a colour another marker is wearing",
        numbers(vals[F["fallback"]["dapi"]]),
        expected((.5, .5, .5), (0, 0, 1), lift))

    pairs = [(v["dapi"], v["only"]) for v in F["byMarker"].values()]
    pairs.append((F["fallback"]["dapi"], F["fallback"]["only"]))
    chk("three distinct filter pairs, no id reused", len(set(pairs)), 3)
    chk("every id the page can ask for is defined",
        sorted({i for p in pairs for i in p} - set(vals)), [])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
