"""Which colour each marker is drawn in, and that the bytes did not move.

The default is positional - first marker red, second green, nuclear blue -
because that is what this pipeline has always produced and the curator's eye is
trained on it. `display.composite` says which markers are shown and in what
order; `display.colours` says what colour each one is.

The last block is the one that matters most. `04o.composite()` replaced a
direct plane assignment, and the constants probe cannot see pixels - so this is
the only thing standing between a colour model and 130 curated sections whose
landmarks were placed on the old bytes.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import numpy as np                                          # noqa: E402

# A study of our own before any stage is imported: 04o reads config at import,
# and config.example.json is multiplex, so the paired layout has to be asked
# for explicitly. The ls_channels checks below pass their own dicts and do not
# depend on it.
from _fixture import use_temp_study, load_stage             # noqa: E402

STUDY = use_temp_study(acquisition={"layout": "paired",
                                    "markers": ["AF568", "AF488"]})

import ls_channels as CH                                    # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(56) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


LS = {"acquisition": {"layout": "paired", "markers": ["AF568", "AF488"]}}

print("--- the default is positional, and is what LS already gets ---")
chk("first marker red, second green", CH.marker_colours(LS),
    {"AF568": (1, 0, 0), "AF488": (0, 1, 0)})

ONE = {"acquisition": {"layout": "paired", "markers": ["pERK"]}}
chk("one marker takes red only", CH.marker_colours(ONE), {"pERK": (1, 0, 0)})

THREE = {"acquisition": {"layout": "paired", "markers": ["A", "B", "C"]}}
chk("a third marker gets no colour by default",
    CH.marker_colours(THREE), {"A": (1, 0, 0), "B": (0, 1, 0)})

chk("no markers gives no colours",
    CH.marker_colours({"acquisition": {"layout": "paired", "markers": []}}), {})

chk("the nuclear channel is blue unless told otherwise",
    CH.nuclear_colour(LS), (0, 0, 1))
chk("...and named, not positional",
    CH.nuclear_colour({"acquisition": {"layout": "paired", "markers": ["A"]},
                       "display": {"nuclear_colour": "grey"}}), (.5, .5, .5))

print()
print("--- display.composite says WHICH markers, in order ---")
OVER = {"acquisition": {"layout": "paired", "markers": ["A", "B", "C"]},
        "display": {"composite": ["C", "A"]}}
chk("named markers take red and green in that order",
    CH.marker_colours(OVER), {"C": (1, 0, 0), "A": (0, 1, 0)})
chk("...and that is the order the colour default reads",
    CH.composite_order(OVER), ["C", "A"])
chk("no display.composite means the declared order",
    CH.composite_order(LS), ["AF568", "AF488"])

BAD = {"acquisition": {"layout": "paired", "markers": ["A", "B"]},
       "display": {"composite": ["A", "nope"]}}
try:
    CH.marker_colours(BAD)
    chk("an undeclared marker in display.composite is refused", False, True)
except CH.ChannelError as e:
    chk("an undeclared marker in display.composite is refused",
        "nope" in str(e), True)

for junk in ("A", 5, {"A": 0}):
    got = None
    try:
        CH.marker_colours({"acquisition": {"layout": "paired",
                                           "markers": ["A", "B"]},
                           "display": {"composite": junk}})
        got = "returned"
    except CH.ChannelError:
        got = "refused"
    except Exception as e:
        got = "CRASHED " + type(e).__name__
    chk(f"display.composite as {type(junk).__name__} is judged, not crashed on",
        got, "refused")

print()
print("--- display.colours says WHAT COLOUR, and overrides the position ---")
SWAP = {"acquisition": {"layout": "paired", "markers": ["AF568", "AF488"]},
        "display": {"colours": {"AF568": "green", "AF488": "red"}}}
chk("a declared colour beats the positional default",
    CH.marker_colours(SWAP), {"AF568": (0, 1, 0), "AF488": (1, 0, 0)})

HEX = {"acquisition": {"layout": "paired", "markers": ["A", "B", "C"]},
       "display": {"colours": {"A": "#ff00ff"}}}
chk("hex is accepted and normalised to 0-1",
    CH.marker_colours(HEX)["A"], (1.0, 0.0, 1.0))
chk("...while the others keep the positional default",
    CH.marker_colours(HEX)["B"], (0, 1, 0))
chk("...and the third marker is still uncoloured",
    "C" in CH.marker_colours(HEX), False)

chk("a named colour parses", CH.parse_colour("magenta"), (1, 0, 1))
chk("...case-insensitively", CH.parse_colour("MAGENTA"), (1, 0, 1))
for junk in ("mauve", "#ff00f", "#gggggg", "", 7, None, ["red"]):
    got = None
    try:
        CH.parse_colour(junk)
        got = "returned"
    except CH.ChannelError:
        got = "refused"
    except Exception as e:
        got = "CRASHED " + type(e).__name__
    chk(f"parse_colour({junk!r}) is judged, not crashed on", got, "refused")

print()
print("--- validate_display: reported, one line each, not raised ---")
errs, warns = CH.validate_display(LS)
chk("the live study has nothing to report", (errs, warns), ([], []))

errs, warns = CH.validate_display(
    {"acquisition": {"layout": "paired", "markers": ["A", "B"]},
     "display": {"colours": {"C": "red"}}})
chk("a colour for a marker this study does not measure is an ERROR",
    len(errs), 1)
chk("...and it names the marker", "C" in errs[0], True)

errs, warns = CH.validate_display(
    {"acquisition": {"layout": "paired", "markers": ["A", "B", "C"]}})
chk("a marker with no colour is a WARNING, not an error", errs, [])
chk("...naming the marker that will not be drawn",
    len(warns) == 1 and "C" in warns[0], True)

errs, _ = CH.validate_display(
    {"acquisition": {"layout": "paired", "markers": ["A"]},
     "display": {"colours": {"A": "mauve"}}})
chk("an unknown colour name is an error", len(errs), 1)

errs, _ = CH.validate_display(
    {"acquisition": {"layout": "paired", "markers": ["A"]},
     "display": {"colours": "red"}})
chk("display.colours as a string is judged, not crashed on", len(errs), 1)

errs, _ = CH.validate_display(
    {"acquisition": {"layout": "paired", "markers": ["A"]},
     "display": {"nuclear_colour": "puce"}})
chk("an unknown nuclear colour is an error", len(errs), 1)

print()
print("--- THE BIT-IDENTITY GUARANTEE ---")
#
# 130 curated sections carry landmark coordinates placed on the composites
# already on disk. `composite()` replaced `rgb[..., plane] = comp;
# rgb[..., 2] = img`, and the constants probe does not see pixels - so nothing
# else in this repo would notice if the new arithmetic moved a byte.
#
# Pinned with np.array_equal against the assignment it replaces, for both live
# markers, and with the colour taken from marker_colours rather than written
# here - so the tie between "AF568 is red" and "AF568 lands in plane 0" is
# asserted rather than restated.
RGB = load_stage("04o_section_rgb.py")

rng = np.random.default_rng(20260910)
dapi = rng.integers(0, 256, (23, 19), dtype=np.uint8)
mark = rng.integers(0, 256, (23, 19), dtype=np.uint8)
colours = CH.marker_colours(LS)

for marker, plane in (("AF568", 0), ("AF488", 1)):
    old = np.zeros(dapi.shape + (3,), np.uint8)
    old[..., plane] = mark
    old[..., 2] = dapi
    new = RGB.composite(mark, dapi, colours[marker])
    chk(f"{marker} composites to the exact bytes plane {plane} did",
        np.array_equal(old, new), True)
    chk(f"...and stays uint8 for {marker}", new.dtype == np.uint8, True)

# A marker that shares the blue plane with the counterstain: max, not sum, so
# neither is clipped and the two stay distinguishable.
mag = RGB.composite(mark, dapi, (1., 0., 1.))
chk("a magenta marker keeps the brighter of marker and counterstain in blue",
    np.array_equal(mag[..., 2], np.maximum(mark, dapi)), True)
chk("...and never saturates where sum would",
    int(mag[..., 2].max()) <= 255 and
    np.array_equal(mag[..., 0], mark), True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
