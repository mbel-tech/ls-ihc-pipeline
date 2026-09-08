"""Which marker lands in which RGB plane.

The default is positional - first marker red, second green, nuclear blue -
because that is what this pipeline has always produced and the curator's eye is
trained on it. display.composite overrides it by name.
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
    print(("ok   " if ok else "FAIL ") + label.ljust(56) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


LS = {"acquisition": {"layout": "paired", "markers": ["AF568", "AF488"]}}

print("--- the default is positional, and is what LS already gets ---")
chk("first marker is red", CH.marker_planes(LS), {"AF568": 0, "AF488": 1})

ONE = {"acquisition": {"layout": "paired", "markers": ["pERK"]}}
chk("one marker takes red only", CH.marker_planes(ONE), {"pERK": 0})

THREE = {"acquisition": {"layout": "paired", "markers": ["A", "B", "C"]}}
chk("a third marker gets no plane by default",
    CH.marker_planes(THREE), {"A": 0, "B": 1})

chk("no markers gives no planes",
    CH.marker_planes({"acquisition": {"layout": "paired", "markers": []}}), {})

print()
print("--- display.composite overrides by name ---")
OVER = {"acquisition": {"layout": "paired", "markers": ["A", "B", "C"]},
        "display": {"composite": ["C", "A"]}}
chk("named markers take red and green in order",
    CH.marker_planes(OVER), {"C": 0, "A": 1})

BAD = {"acquisition": {"layout": "paired", "markers": ["A", "B"]},
       "display": {"composite": ["A", "nope"]}}
try:
    CH.marker_planes(BAD)
    chk("an undeclared marker in display.composite is refused", False, True)
except CH.ChannelError as e:
    chk("an undeclared marker in display.composite is refused",
        "nope" in str(e), True)

for junk in ("A", 5, {"A": 0}):
    got = None
    try:
        CH.marker_planes({"acquisition": {"layout": "paired",
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
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
