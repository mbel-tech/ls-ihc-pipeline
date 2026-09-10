"""No stage offers a fixed list of markers, and none defaults to one.

A stage whose --marker choices are a literal cannot be pointed at a study with
different markers: argparse rejects the value before any code runs, so the
failure is a usage error about an unrelated fluorophore.

That was the whole of this guard, and it was not enough. It matched on the text
`choices=`, so a stage that declared NO choices at all was invisible to it -
and two did. `01g_saturation_map.py` and `04b_atlas_match.py` each declared
`--marker` with a bare string default and no choices, which is the one shape
argparse cannot validate under any circumstances: it accepts any string, the
`marker_channel` filter matches nothing, and the stage runs to completion on an
empty set. 01g then wrote an empty `saturation_<marker>.csv`, which
`app/stages.py` declares as its output, so the app showed the stage as done.
Nothing raised, in either of them, ever.

So there are three checks here now, and the two new ones are read from the
SYNTAX TREE rather than from the text. A regex over lines cannot see an
argument whose keywords are spread over three of them, and both of the shapes
being looked for are about what a keyword is BOUND TO, which is a question
about the tree:

  1. a `choices=` list holding a bare fluorophore literal   (the original)
  2. a `--marker` whose `default=` is a string literal
  3. a `--marker` with no `choices=` at all

Check 2 is the one that would have caught the two offenders. Check 3 closes the
hole they came through, so a `--marker` that derives its default but forgets
its choices is caught too - argparse would still accept any string there.

`default=None` is not an offender: 05a_roi_geometry means "every marker" by it,
and that is a derived answer, not a fluorophore.

Run:  python tests/test_marker_choices.py
"""

import ast
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


STAGES = sorted(glob.glob(os.path.join(REPO, "scripts", "*.py")))


def where(path, node):
    return f"{os.path.basename(path)}:{node.lineno}"


# --- 1: a choices= list holding a bare fluorophore-looking literal ---------
LIT = re.compile(r"choices\s*=\s*[\[(][^\])]*[\"']AF\d+[\"']")
offenders = []
for path in STAGES:
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if LIT.search(line):
                offenders.append(f"{os.path.basename(path)}:{n}")

chk("no stage hardcodes its marker choices", offenders, [])
for o in offenders:
    print(f"     {o}")


# --- 2 and 3: what --marker is actually bound to ---------------------------
def marker_arguments(path):
    """Every `add_argument("--marker", ...)` call in one stage, from the tree.

    Matched on the flag, not on `dest`: the flag is what an operator types and
    what `app/stages.py` puts in an argv list. Any `.add_argument(...)` counts,
    whatever the parser object is called - stages build parsers in `main()`, in
    `build_parser()` and in subparser groups.
    """
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "add_argument"):
            continue
        flags = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if "--marker" in flags:
            yield node


def keyword(node, name):
    """The value node bound to one keyword, or None if it is not given."""
    return next((k.value for k in node.keywords if k.arg == name), None)


literal_defaults, no_choices, unparsed, seen = [], [], [], 0
for path in STAGES:
    try:
        nodes = list(marker_arguments(path))
    except SyntaxError as exc:
        # A stage that will not parse cannot be checked, and silently checking
        # nothing is how a guard stops guarding.
        unparsed.append(f"{os.path.basename(path)}: {exc}")
        continue
    for node in nodes:
        seen += 1
        default = keyword(node, "default")
        if isinstance(default, ast.Constant) and isinstance(default.value, str):
            literal_defaults.append(f"{where(path, node)}  default={default.value!r}")
        if keyword(node, "choices") is None:
            no_choices.append(where(path, node))

chk("every stage parses", unparsed, [])
for o in unparsed:
    print(f"     {o}")

chk("no --marker defaults to a string literal", literal_defaults, [])
for o in literal_defaults:
    print(f"     {o}")

chk("no --marker is declared without choices", no_choices, [])
for o in no_choices:
    print(f"     {o}")

# A guard that finds nothing to look at passes for the wrong reason. If the
# walk stops matching - a stage builds its parser some other way, a rename -
# these lists go empty and both checks above go green over nothing.
chk("...and there were --marker arguments to check", seen > 0, True)
print(f"     {seen} --marker arguments across {len(STAGES)} stages")

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
