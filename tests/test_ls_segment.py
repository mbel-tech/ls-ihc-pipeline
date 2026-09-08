"""The segmentation backends, against synthetic fields with known objects.

Synthetic on purpose: the point of these is that the RULE is right - this many
objects, this threshold, this minimum area - not that it segments microscopy
well. Nothing here has met a real section, and the first study that uses
`segment: own` will find things these cannot.

Run:  python tests/test_ls_segment.py
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import ls_segment as SG                                     # noqa: E402

failures = []


def chk(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label.ljust(56) + " " + repr(got))
    if not ok:
        print("     want " + repr(want))
        failures.append(label)


def field(objects, shape=(200, 200), bg=100, noise=0):
    """A flat background with bright rectangles painted on it."""
    img = np.full(shape, bg, dtype=np.float64)
    if noise:
        img += np.random.default_rng(0).normal(0, noise, shape)
    for (y0, x0, h, w, v) in objects:
        img[y0:y0 + h, x0:x0 + w] = v
    return img


print("--- the threshold itself ---")

flat = field([])
chk("a flat field has a MAD of zero", SG.mad(flat), 0.0)
cut = SG.cut_for(flat, k=3.0)
chk("...so its cut is its median", cut, 100.0)

noisy = field([], noise=10)
chk("the cut sits above the background", SG.cut_for(noisy, k=3.0) > 100, True)

print()
print("--- objects found ---")

two = field([(10, 10, 20, 20, 5000), (100, 100, 20, 20, 5000)])
labels = SG.threshold_labels(two, k=3.0, min_area_px=10)
chk("two bright squares are two objects", int(labels.max()), 2)
chk("...and the background is label 0", int(labels[0, 0]), 0)

chk("an empty field finds nothing",
    int(SG.threshold_labels(flat, k=3.0, min_area_px=10).max()), 0)

print()
print("--- the minimum area is what stops noise being an object ---")

speck = field([(10, 10, 20, 20, 5000), (150, 150, 2, 2, 5000)])
chk("a 4 px speck is dropped at min_area_px=10",
    int(SG.threshold_labels(speck, k=3.0, min_area_px=10).max()), 1)
chk("...and kept at min_area_px=1",
    int(SG.threshold_labels(speck, k=3.0, min_area_px=1).max()), 2)

# The ids downstream code sees must be 1..n with no holes, and the object that
# gets dropped is not obliged to be the last one. Objects are labelled in
# raster order, so the speck in the middle here takes id 2 of 3; if the drop
# did not renumber, the survivors would be 1 and 3 and labels.max() would
# report three objects where there are two.
middle = field([(10, 10, 20, 20, 5000), (60, 60, 2, 2, 5000),
                (110, 110, 20, 20, 5000)])
mid = SG.threshold_labels(middle, k=3.0, min_area_px=10)
chk("dropping an object in the MIDDLE leaves two", int(mid.max()), 2)
chk("...and the ids are 1..n with no holes",
    sorted(int(v) for v in np.unique(mid)), [0, 1, 2])

print()
print("--- touching objects are ONE object, and that is the honest answer ---")

# Connected components cannot split what is connected. A threshold backend that
# claimed to separate touching objects would be inventing a boundary; the spec
# chose this backend for things that are not nucleus-shaped, where "one stained
# region" is the truthful count.
joined = field([(10, 10, 20, 40, 5000)])
chk("one wide region is one object",
    int(SG.threshold_labels(joined, k=3.0, min_area_px=10).max()), 1)

print()
print("--- the dispatch ---")

chk("threshold is a known backend", "threshold" in SG.BACKENDS, True)
chk("stardist is a known backend", "stardist" in SG.BACKENDS, True)
try:
    SG.segment(two, "nope", min_area_px=10)
    chk("an unknown backend is refused", False, True)
except SG.SegmentError as e:
    chk("an unknown backend is refused", "nope" in str(e), True)

chk("dispatch reaches the threshold backend",
    int(SG.segment(two, "threshold", min_area_px=10).max()), 2)

# The model is not loaded here - one process loads it once, in 05c - so asking
# for stardist without one is a refusal with a reason rather than a traceback
# from inside StarDist.
try:
    SG.segment(two, "stardist")
    chk("stardist without a model is refused", False, True)
except SG.SegmentError as e:
    chk("stardist without a model is refused", "model" in str(e), True)

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
