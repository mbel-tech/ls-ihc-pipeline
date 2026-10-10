"""The segmentation backends, against synthetic fields with known objects.

Synthetic on purpose: the point of these is that the RULE is right - this many
objects, this threshold, this minimum area - not that it segments microscopy
well. Nothing here has met a real section, and the first study that uses
`segment: own` will find things these cannot.

The last two sections are about what the backend does when it CANNOT answer.
Its cut comes from the frame's own median, which is background only while most
of the frame is background; past that the median lands inside an object and the
count collapses to zero. A zero that means "the estimate failed" is driven here
beside a zero that means "the frame was empty", because those two are the same
number and 05c writes no rows for either.

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
print("--- the assumption the whole backend rests on, and when it fails ---")

# The cut is derived from the frame's own median, which is background only
# while most of the frame is. These three frames are the argument: one this
# backend handles, the same staining covering half the frame, and an empty
# one. The second and the third BOTH report zero objects, and until the check
# existed there was nothing at all to tell those two zeros apart - 05c writes
# no rows for either, so 06a published n = 0 and a density of 0.0 for both.


def strands(n, shape=(300, 300), seed=0):
    """`n` bright rows on a noisy background - fibre staining, roughly.

    Noisy on purpose, and not a flat synthetic field: the check measures how
    far below the median the frame's floor sits IN UNITS OF ITS OWN NOISE, and
    a field with no noise gives it no unit to measure in. A camera frame
    always has some; `field()` above does not, which is why it is not used
    here.
    """
    rng = np.random.default_rng(seed)
    a = rng.normal(100, 10, shape)
    for i in range(n):
        a[int(i * shape[0] / n), :] = rng.normal(1000, 100, shape[1])
    return a


def empty_frame(shape=(300, 300), seed=1):
    """Background and nothing else - the honest zero."""
    return np.random.default_rng(seed).normal(100, 10, shape)


ok_rep, failed_rep, empty_rep = {}, {}, {}
ok_lab = SG.threshold_labels(strands(90), k=3.0, min_area_px=10, report=ok_rep)
failed_lab = SG.threshold_labels(strands(150), k=3.0, min_area_px=10,
                                 report=failed_rep)
empty_lab = SG.threshold_labels(empty_frame(), k=3.0, min_area_px=10,
                                report=empty_rep)

chk("90 strands over 300 rows are 90 objects", int(ok_lab.max()), 90)
chk("...on a frame whose background estimate held", ok_rep["failed"], False)
chk("150 strands - half the frame - are reported as NONE",
    int(failed_lab.max()), 0)
chk("...and that zero says the background estimate FAILED",
    failed_rep["failed"], True)
chk("an empty frame is zero objects too", int(empty_lab.max()), 0)
chk("...and its zero says the frame was empty", empty_rep["failed"], False)

# The numbers behind the flag. `below_background` is what separates the two
# zeros; `above_cut` cannot, because the cut climbs over the whole frame.
chk("half the failed frame lies below its own 'background'",
    round(failed_rep["below_background"], 2), 0.5)
chk("...while an empty frame puts under 1% down there",
    empty_rep["below_background"] < 0.01, True)
chk("nothing at all is above the cut on the failed frame",
    failed_rep["above_cut"], 0.0)
chk("...which is what an empty frame looks like too",
    empty_rep["above_cut"] < 0.01, True)
chk("both frames were actually checked",
    (failed_rep["checked"], empty_rep["checked"]), (True, True))

# It declines to speak rather than guess. Two frames it cannot judge, neither
# of them flagged: a frame too small for the darkest quarter to estimate noise
# from, and one with no noise in it at all.
tiny = {}
SG.threshold_labels(empty_frame(shape=(20, 24), seed=2), min_area_px=10,
                    report=tiny)
chk("a frame too small to estimate noise from is not judged",
    (tiny["checked"], tiny["failed"]), (False, False))
noiseless = {}
SG.threshold_labels(field([(10, 10, 20, 20, 5000)]), min_area_px=10,
                    report=noiseless)
chk("...nor is a synthetic field with no noise to measure",
    (noiseless["checked"], noiseless["failed"]), (False, False))

# The dispatch carries the report, since 05c calls segment() and not the
# backend directly.
dispatched = {}
chk("segment() reaches the threshold backend with a report",
    int(SG.segment(strands(150), "threshold", min_area_px=10,
                   report=dispatched).max()), 0)
chk("...and the backend filled it in", dispatched["failed"], True)
untouched = {}
try:
    SG.segment(two, "stardist", report=untouched)
except SG.SegmentError:
    pass
chk("a backend that estimates no background reports none", untouched, {})

# And the plain call is unchanged: no report asked for, nothing measured.
chk("a call with no report still returns labels",
    int(SG.threshold_labels(strands(90), min_area_px=10).max()), 90)

print()
print("--- a corrupted read is refused, not counted as zero ---")

# One NaN makes the median NaN, `x > nan` is False for every x, and the mask
# is empty - so a frame with two obvious squares in it would be counted as
# zero objects. Only a bad read produces one, and zero is precisely what such
# a read must not be published as.
two_squares = [(10, 10, 20, 20, 5000), (100, 100, 20, 20, 5000)]
nan_frame = field(two_squares)
nan_frame[0, 0] = np.nan
chk("the frame really does have two objects in it",
    int(SG.threshold_labels(field(two_squares), min_area_px=10).max()), 2)
chk("...and a NaN cut would have called it empty",
    int((nan_frame > np.nan).sum()), 0)
for name, call in (
        ("mad", lambda: SG.mad(nan_frame)),
        ("cut_for", lambda: SG.cut_for(nan_frame)),
        ("threshold_labels",
         lambda: SG.threshold_labels(nan_frame, min_area_px=10)),
        ("segment", lambda: SG.segment(nan_frame, "threshold",
                                       min_area_px=10))):
    try:
        call()
        got = "not refused"
    except SG.SegmentError as exc:
        got = "refused" if "non-finite" in str(exc) else "refused, wrong reason"
    chk(f"{name} refuses it", got, "refused")

inf_frame = field(two_squares)
inf_frame[5, 5] = np.inf
try:
    SG.cut_for(inf_frame)
    got = "not refused"
except SG.SegmentError:
    got = "refused"
chk("an infinity is refused the same way", got, "refused")

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
