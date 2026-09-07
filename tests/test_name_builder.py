"""Generating a filename pattern from marked-up spans, without a window.

The builder's whole job is to produce a pattern the operator did not have to
write, that is no looser than the example it came from, and that is checked
against every file before it can be saved. The failure it exists to prevent is
a file the pattern misses: that file never reaches any stage, and nothing says
so.

Run:  python tests/test_name_builder.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "app"))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import naming_build as B                                    # noqa: E402
import ls_naming as NM                                      # noqa: E402

failures = []


def chk(name, got, want):
    ok = got == want
    shown = got if len(repr(got)) < 92 else f"<{type(got).__name__}, {len(got)}>"
    print(f"{'ok  ' if ok else 'FAIL'} {name:58} {shown!r}")
    if not ok:
        print(f"     want {want!r}")
        failures.append(name)


def spans(*triples):
    return [B.Span(a, b, n) for a, b, n in triples]


# --------------------------------------------------------------------------
print("--- the shape comes from the characters, never from typed text ---")

chk("digits", B.infer_body("105"), r"\d+")
chk("letters", B.infer_body("ab"), r"[A-Za-z]+")
chk("letters then digits", B.infer_body("LS105"), r"[A-Za-z]+\d+")
chk("anything else is the literal set present",
    B.infer_body("a-b"), "[\\-ab]+")
chk("an empty run has no body", B.infer_body(""), "")

# --------------------------------------------------------------------------
print()
print("--- the LS example, marked up as the operator would ---")

EXAMPLE = "LS105_10a.czi"
#            0123456789
built, warns = B.spans_to_pattern(
    EXAMPLE, spans((0, 5, "subject"), (6, 8, "slide"), (8, 9, "replicate")))
chk("no ambiguity to warn about", warns, [])
chk("the pattern reads as the grammar it replaces", built,
    r"^(?P<subject>[A-Za-z]+\d+)_(?P<slide>\d+)(?P<replicate>[A-Za-z]+)\.czi$")
# slide and replicate touch here, but digits followed by letters have exactly
# one split, so pinning would be wrong.

m = re.match(built, EXAMPLE)
chk("it matches the example it came from",
    (m.group("subject"), m.group("slide"), m.group("replicate")),
    ("LS105", "10", "a"))
chk("the unmarked text is escaped, not treated as syntax",
    re.match(built, "LS105X10a.czi"), None)

# --------------------------------------------------------------------------
print()
print("--- a split with no defined answer is pinned, and said so ---")

# Two letter runs with nothing between them: the engine would pick a split
# and whichever it picked would not be a decision anyone made.
built2, warns2 = B.spans_to_pattern(
    "ABCD.czi", spans((0, 2, "subject"), (2, 4, "replicate")))
chk("the adjacency is reported", len(warns2), 1)
chk("...in words the operator can act on",
    "nothing separates it from replicate" in warns2[0], True)
chk("...and the left span is pinned to its width here",
    r"{2}" in built2, True)
m2 = re.match(built2, "ABCD.czi")
chk("the pinned pattern still splits the example correctly",
    (m2.group("subject"), m2.group("replicate")), ("AB", "CD"))
chk("...and it is not merely the greedy answer",
    re.match(r"^(?P<subject>[A-Za-z]+)(?P<replicate>[A-Za-z]+)$",
             "ABCD").group("subject"), "ABC")

built3, warns3 = B.spans_to_pattern(
    "AB_12.czi", spans((0, 2, "subject"), (3, 5, "slide")))
chk("a separator between spans needs no pinning", warns3, [])

# --------------------------------------------------------------------------
print()
print("--- what cannot be built at all ---")

for bad, why in (
        ([(0, 5, "slide")], "no subject"),
        ([(0, 5, "subject"), (3, 8, "slide")], "overlapping spans")):
    try:
        B.spans_to_pattern(EXAMPLE, spans(*bad))
        chk(f"{why} is refused", False, True)
    except ValueError:
        chk(f"{why} is refused", True, True)

# --------------------------------------------------------------------------
print()
print("--- the preview is the whole point ---")

NAMES = ["LS105_10a.czi", "LS105_1b.czi", "LS22_3a.czi", "notes.txt",
         "LS45_8b copy.czi"]
res = B.preview(NAMES, built)
chk("it counts both sides", (res["matched"], res["failed"]), (3, 2))
chk("failures come first, so they are what you see",
    [r["file"] for r in res["rows"]][:2],
    ["LS45_8b copy.czi", "notes.txt"])
chk("the summary says it plainly", B.summary(res),
    "3 of 5 matched — 2 did not")

ok, why = B.can_save(res)
chk("a pattern that misses files cannot be saved by accident", ok, False)
chk("...and the reason explains the consequence",
    "never reaches any stage" in why, True)
ok, _ = B.can_save(res, accept_failures=True)
chk("...but can be saved deliberately", ok, True)

clean = B.preview(NAMES[:3], built)
chk("a pattern that matches everything saves", B.can_save(clean)[0], True)
chk("...and says so", B.summary(clean), "all 3 filenames matched")

# --------------------------------------------------------------------------
print()
print("--- the problems that must be fixed, not merely accepted ---")

res = B.preview(["LS105_10a.czi"], r"^(?P<other>.+)\.czi$")
chk("a pattern with no subject group is a problem", len(res["problems"]), 1)
chk("...and says why subject matters", "joins on" in res["problems"][0], True)

res = B.preview(["A_B_1.czi"], r"^(?P<subject>[A-Za-z_]+)_(?P<slide>\d+)\.czi$")
chk("a subject with an underscore is a problem",
    any("underscore" in p for p in res["problems"]), True)
chk("...and that file is not counted as matched", res["matched"], 0)

# Two files reading as one section would have each overwriting the other.
res = B.preview(["LS1_2a.czi", "LS1_2a_rescan.czi"],
                r"^(?P<subject>[A-Za-z]+\d+)_(?P<slide>\d+)(?P<replicate>[a-z]).*\.czi$")
chk("two files reading as the same section is a problem",
    any("same section" in p for p in res["problems"]), True)
chk("...and both files are named", len(res["clashes"]), 1)

res = B.preview(["LS105_10a.czi"], r"^(?P<subject>ZZ\d+)\.czi$")
chk("a pattern matching nothing is a problem",
    any("matches none" in p for p in res["problems"]), True)

res = B.preview(["LS105_10a.czi"], r"^(?P<subject>[\.czi$")
chk("an uncompilable pattern is a problem, not a crash",
    any("not valid" in p for p in res["problems"]), True)

# --------------------------------------------------------------------------
print()
print("--- extra groups ride along as columns ---")

built4, _ = B.spans_to_pattern(
    "AB12_C_3.czi", spans((0, 4, "subject"), (5, 6, "batch"), (7, 8, "slide")))
res = B.preview(["AB12_C_3.czi"], built4)
chk("a group the pipeline does not know is carried",
    res["rows"][0]["extras"], {"batch": "C"})

# --------------------------------------------------------------------------
print()
print("--- the built pattern against the whole real corpus ---")

SRC = r"D:\SLIDES HE DEC 2025 LS"
if not os.path.isdir(SRC):
    print("SKIP the slide drive is not mounted")
else:
    names = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".czi"))

    # A pattern built from a TYPICAL example does not cover the atypical files,
    # and three of these 222 carry a rescan or pass suffix. That is the case
    # the preview exists for: they are named, counted, and the pattern cannot
    # be saved as if nothing were wrong.
    res = B.preview(names, built)
    chk("most of the corpus reads with a pattern built from one name",
        res["matched"], len(names) - 3)
    chk("the odd ones out are named, not lost",
        sorted(r["file"] for r in res["rows"] if not r["ok"]),
        ["LS53_2b-_A568.czi", "LS53_5b-_A568.czi", "LS85_7b-.czi"])
    chk("...and it cannot be saved as if they did not exist",
        B.can_save(res)[0], False)
    chk("...though it can be, deliberately",
        B.can_save(res, accept_failures=True)[0], True)

    # The escape hatch is the point: the generated regex stays editable, and
    # the hand-widened one covers every file. This is the pattern now in the
    # LS study config.
    LS = (r"^(?P<subject>LS\d+)_(?P<slide>\d+)(?P<replicate>[a-z])"
          r"(?P<rescan>-?)(?P<pass>_[A-Za-z0-9]+)?\.czi$")
    full = B.preview(names, LS)
    chk(f"the edited pattern reads all {len(names)}",
        (full["matched"], full["failed"]), (len(names), 0))
    chk("...with nothing to fix", full["problems"], [])
    chk("...and saves", B.can_save(full)[0], True)

    # And what it yields is what the pipeline's own parser yields.
    pat = NM.compile_pattern({"pattern": LS})
    bad = [n for n in names if NM.parse_name(n, pat) is None]
    chk("every file parses with the pipeline's own reader", bad, [])
    subjects = {NM.parse_name(n, pat)["subject"] for n in names}
    chk("and gives the twelve animals", len(subjects), 12)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
