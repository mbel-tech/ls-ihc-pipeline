"""Centroid-in-mask, both ways, and who is allowed to ask.

The asymmetric case is the point: a small object's centroid can fall inside a
large one while the large one's centroid falls outside the small one. Overlap
fractions are not comparable when the objects came from different segmentations
- one a nuclear mask, one a threshold region - so containment is what gets
reported, in both directions, with the direction named.

SYNTHETIC. No study is `multiplex`, so no study computes co-localisation at
all; these are label arrays drawn by hand. What they guarantee is the rule, not
that it finds biology. The end-to-end half - that a multiplex run writes the
join table and the live paired study writes NO file - is driven through 05c's
real loop in tests/test_detect_backends.py, which has the fake reader.

Run:  python tests/test_colocalisation.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_coloc as CO                                        # noqa: E402
from _fixture import temp_study, load_stage                  # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(58) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


def labelled(boxes, shape=(100, 100)):
    """An int label image: boxes is [(label, y0, x0, h, w), ...]."""
    a = np.zeros(shape, dtype=np.int32)
    for (lab, y0, x0, h, w) in boxes:
        a[y0:y0 + h, x0:x0 + w] = lab
    return a


print("--- the symmetric case ---")

# Two squares sitting exactly on each other: each centroid is in the other.
same_a = labelled([(1, 10, 10, 20, 20)])
same_b = labelled([(1, 10, 10, 20, 20)])
pairs = CO.pairs(same_a, same_b)
chk("one pair found", len(pairs), 1)
chk("A's centroid is in B", pairs[0]["a_centroid_in_b"], True)
chk("B's centroid is in A", pairs[0]["b_centroid_in_a"], True)

print()
print("--- the asymmetric case, which is why both are reported ---")

# A big region and a small one near its edge but inside it.
big = labelled([(1, 10, 10, 40, 40)])
small = labelled([(1, 12, 12, 4, 4)])
p = CO.pairs(small, big)[0]
chk("the small object's centroid is inside the big one",
    p["a_centroid_in_b"], True)
chk("...but the big one's centroid is NOT inside the small one",
    p["b_centroid_in_a"], False)

print()
print("--- no relation at all ---")

far_a = labelled([(1, 5, 5, 6, 6)])
far_b = labelled([(1, 80, 80, 6, 6)])
chk("objects that do not touch produce no pair",
    CO.pairs(far_a, far_b), [])

print()
print("--- every object is considered, not just the first ---")

many_a = labelled([(1, 10, 10, 8, 8), (2, 40, 40, 8, 8)])
many_b = labelled([(1, 10, 10, 8, 8), (2, 40, 40, 8, 8)])
got = CO.pairs(many_a, many_b)
chk("two overlapping objects give two pairs", len(got), 2)
chk("...and the labels are carried through, not renumbered",
    sorted((r["object_a"], r["object_b"]) for r in got), [(1, 1), (2, 2)])

print()
print("--- an empty side ---")

chk("nothing segmented on one side gives no pairs",
    CO.pairs(many_a, np.zeros((100, 100), dtype=np.int32)), [])
chk("...either side", CO.pairs(np.zeros((100, 100), dtype=np.int32), many_b),
    [])

print()
print("--- a centroid can land off its own object, and that is fine ---")

# A C-shape's centroid falls in the notch, on background. It is still a real
# object of A; it simply relates to nothing, and must not raise.
c_shape = labelled([(1, 10, 10, 20, 4), (1, 10, 10, 4, 20),
                    (1, 26, 10, 4, 20)])
chk("a centroid on background relates to nothing",
    CO.pairs(c_shape, labelled([(1, 40, 40, 6, 6)])), [])

print()
print()
print("=== and who is allowed to ask, per study ===")

MULTIPLEX = {"layout": "multiplex", "channels": [
    {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
    {"name": "pERK", "role": "marker", "czi_name": "AF568", "index": 1,
     "segment": "nuclear"},
    {"name": "GFAP", "role": "marker", "czi_name": "AF647", "index": 2,
     "segment": "own", "backend": "threshold", "nucleus_shaped": False}]}

TWO_NUCLEAR = {"layout": "multiplex", "channels": [
    {"name": "DAPI", "role": "nuclear", "czi_name": "DAPI", "index": 0},
    {"name": "pERK", "role": "marker", "czi_name": "AF568", "index": 1,
     "segment": "nuclear"},
    {"name": "PCNA", "role": "marker", "czi_name": "AF488", "index": 2,
     "segment": "nuclear"}]}

#: The live study: two markers, no channel table, separate physical scans.
PAIRED = {"layout": "paired", "markers": ["AF568", "AF488"], "channels": []}

print()
print("--- markers whose objects are distinct ---")

with temp_study(acquisition=MULTIPLEX) as study:
    D5 = load_stage("05c_detect_rois.py")
    chk("a nuclear-segmented and an own-segmented marker relate",
        D5.coloc_applies("pERK", "GFAP"), True)
    chk("...in either order", D5.coloc_applies("GFAP", "pERK"), True)
    chk("a marker never relates to itself",
        D5.coloc_applies("pERK", "pERK"), False)
    # The pair is computed ONCE, in the run of whichever marker is declared
    # first. 05c measures ONE marker per run, so both runs would otherwise
    # write the same relation, mirrored.
    chk("the first-declared marker's run owns the pair",
        D5.coloc_partners("pERK"), ["GFAP"])
    chk("...and the second's run has nothing to do",
        D5.coloc_partners("GFAP"), [])

print()
print("--- markers that SHARE their objects ---")

with temp_study(acquisition=TWO_NUCLEAR) as study:
    D5 = load_stage("05c_detect_rois.py")
    # Both are measured inside the same nuclear masks, so every object
    # contains itself and the table would be a diagonal.
    chk("two nuclear-segmented markers do not relate",
        D5.coloc_applies("pERK", "PCNA"), False)
    chk("...so neither run has a partner", D5.coloc_partners("pERK"), [])

print()
print("--- the live study, which is paired ---")

with temp_study(acquisition=PAIRED) as study:
    D5 = load_stage("05c_detect_rois.py")
    # Separate physical scans of DIFFERENT sections. The objects are not in
    # one coordinate frame, so relating them would be meaningless rather than
    # merely empty - which is why no file is written at all.
    chk("the layout is the live one", D5.LAYOUT, "paired")
    chk("paired markers do not relate",
        D5.coloc_applies("AF568", "AF488"), False)
    chk("...so no run has a partner", D5.coloc_partners("AF568"), [])
    chk("...nor the other one", D5.coloc_partners("AF488"), [])

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
