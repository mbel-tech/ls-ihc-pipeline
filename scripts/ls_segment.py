"""How a channel becomes objects.

Two backends, because two different things get counted.

`stardist` is what this pipeline has always used, and it is the right answer for
anything nucleus-shaped: it separates touching nuclei, which a threshold cannot.
05c's docstring records why watershed was rejected for that job.

`threshold` is for everything else - fibre staining, processes, plaques. It
finds stained REGIONS and does not pretend they are cells. Connected components
cannot split what is connected, so two touching objects are one object here;
that is a limitation of the method and it is the honest count for the things
this backend is meant for.

The rule is the same one `06a` uses for positivity - median + k * 1.4826 * MAD -
so the pipeline has one definition of "above background" rather than two. It is
applied to a different sample, though: 06a measures the operator's curated
background discs, while this measures the frame being segmented, because 05c
runs before 06a and cannot read a file 06a has not written yet. In a
fluorescence frame most pixels are background, so the median estimates it.

1.4826 makes the MAD a consistent estimator of the standard deviation for
normally distributed data. The median and the MAD are used rather than the mean
and the SD because the objects themselves are in the sample: a bright object
drags a mean up and inflates an SD, and would raise the very cut that is
supposed to find it.

**THE MEDIAN IS BACKGROUND ONLY WHILE MOST OF THE FRAME IS.** Once signal
covers about half the frame the median lands INSIDE an object, the cut is
derived from that object's own intensity, and nothing clears it. Measured on a
300x300 frame, background 100+-10 against signal 1000+-100:

      signal      cut   px>cut  objects   true   below
        0.05    132.5     4553        1      1   0.004
        0.40    195.5    36000        1      1   0.007
        0.45    231.8    40500        1      1   0.011
        0.50   1625.8        0        0      1   0.500   <- it has failed
        0.80   1385.2        5        0      1   0.302

`below` is the statistic `background_check` returns, and it is the last column
because it is the only one that survives the cliff: `px>cut` collapses to
nothing there, which is exactly what an empty frame looks like.

The same cliff appears on fibre-like strands, which is exactly what this
backend exists for: 90 strands over 300 rows are 90 objects, 150 are zero. And
the cut is already drifting upward well before the cliff - 132.5 at 5%
coverage, 195.5 at 40% - so the counts are biased before they collapse.

None of that is FIXED here, and deliberately not: a different estimator - a low
percentile, say - would change every count this backend has ever produced, and
choosing one is a scientific decision rather than a bug fix. What is fixed is
the SILENCE. `background_check` measures whether the assumption held,
`threshold_labels` reports it to a caller that asks, and 05c writes the frames
that failed it to `qc/roi_background_assumption.csv` and says how many at the
end of the run. A zero that means "the background estimate failed here" is now
distinguishable from a zero that means "nothing was stained here"; it was not
before, and 05c's response to zero objects is to write no rows at all, so 06a
reported such an ROI at n = 0 and a density of 0.0.

Nothing here has been run against real microscopy. The live study is `paired`
with both markers on `segment: nuclear`, so it takes the stardist route that
already existed; the threshold backend is guaranteed only by
tests/test_ls_segment.py's synthetic fields.
"""

import numpy as np

BACKENDS = ("stardist", "threshold")

#: How much of a frame may lie BELOW its own background estimate before that
#: estimate stops being believable. Measured over synthetic fields of
#: background 100+-10 against signal 1000+-100, and over empty frames of
#: Gaussian, Poisson (lambda 3 to 200) and lognormal noise: a frame whose
#: median really is background puts under 0.6% of itself down there - 4.2% in
#: the worst case measured, a frame 49% covered, which is one step from the
#: cliff - while a frame whose median has moved into an object puts 30% to 50%
#: of itself down there. A tenth sits between the two with room on both sides.
#: It decides a WARNING and nothing else: no count, no threshold and no
#: published number depends on where exactly it is.
BACKGROUND_FAILED = 0.10

#: Frames smaller than this are not checked. The check estimates the noise from
#: the darkest quarter of the frame, and on 64 px that estimate is worth
#: nothing - an 8x8 frame of pure background flagged in one draw of 200. A real
#: ROI box at 0.65 um/px is millions of pixels; 05c's own floor is 8x8, so this
#: only declines to speak about the degenerate ones.
MIN_CHECK_PX = 1024


class SegmentError(Exception):
    """A backend could not be run, or does not exist."""


def _finite(a, what="the image"):
    """Refuse an array with a NaN or an infinity in it.

    `np.median` of an array holding one NaN is NaN, and `x > nan` is False for
    every x - so a frame with two obvious objects in it would be thresholded
    into an empty mask and counted as zero. Only a corrupted read gets here,
    and that is precisely why it is a refusal rather than a repair: nothing in
    the data says whether the missing pixel was background or the brightest
    thing in the frame, and a count published from the rest of it would be a
    guess wearing a number's clothes.
    """
    bad = int(np.count_nonzero(~np.isfinite(a)))
    if bad:
        raise SegmentError(
            f"{what} has {bad} non-finite pixel(s) of {a.size}. The median and "
            f"the MAD of such a frame are NaN, every comparison against the cut "
            f"is False, and it would be counted as empty rather than refused. "
            f"Fix the read - do not segment this frame.")


def mad(image):
    """Median absolute deviation. Not scaled - `cut_for` applies the 1.4826."""
    a = np.asarray(image, dtype=np.float64).ravel()
    if a.size == 0:
        return 0.0
    _finite(a)
    m = float(np.median(a))
    return float(np.median(np.abs(a - m)))


def cut_for(image, k=3.0):
    """The intensity above which a pixel counts as signal.

    Raises SegmentError on a frame with a non-finite pixel, through `mad`: the
    alternative is a NaN cut, which nothing clears, published as zero objects.
    """
    a = np.asarray(image, dtype=np.float64)
    if a.size == 0:
        return 0.0
    return float(np.median(a)) + float(k) * 1.4826 * mad(a)


def background_check(image, k=3.0):
    """Did this frame's median actually estimate its background?

    Returns a dict, always the same keys:

        cut               the intensity `cut_for` derived
        above_cut         the fraction of the frame above it
        below_background  the fraction of the frame far BELOW the median
        failed            whether that fraction reaches BACKGROUND_FAILED
        checked           False when the frame is too small or too flat to say

    `above_cut` is what this backend calls signal, and it reads as "how much of
    the frame is stained" only while the assumption holds. Once the median
    moves into an object the cut goes over the frame's own maximum and this
    falls to zero - which is the cliff, and looks exactly like an empty frame.

    `below_background` is what tells those two apart. The median is CLAIMED to
    be background, so almost nothing should lie far beneath it: noise is
    symmetric, and the same k that puts the cut above background mirrors below
    it. The scale for "far" is measured on the darkest quarter of the frame -
    background under any reading of the histogram - rather than on the whole
    frame's MAD, which is the very thing a second population inflates. The
    mirror is at 2k rather than k so that the check speaks only when the gap is
    unarguable; at k it flagged Poisson backgrounds.

    WHAT IT CANNOT SEE, and no threshold on this statistic could. A frame past
    about 90% coverage: with a tenth of the frame left as background the
    darkest quarter is mostly object, and the scale it hands back is the
    object's. A frame with no noise at all - a synthetic flat field, never a
    camera - gives that quarter a MAD of zero, so there is no scale to measure
    "far" in and the frame is reported unchecked rather than judged. And a
    frame that is ENTIRELY signal cannot be told from one that is entirely
    background by any statistic of the frame alone.
    """
    a = np.asarray(image, dtype=np.float64).ravel()
    out = {"cut": 0.0, "above_cut": 0.0, "below_background": 0.0,
           "failed": False, "checked": False}
    if a.size == 0:
        return out
    cut = cut_for(a, k=k)
    out["cut"] = cut
    out["above_cut"] = float(np.count_nonzero(a > cut)) / a.size
    if a.size < MIN_CHECK_PX:
        return out
    darkest = a[a <= np.percentile(a, 25)]
    scale = 1.4826 * mad(darkest)
    if scale <= 0:
        return out
    floor = float(np.median(a)) - 2.0 * float(k) * scale
    out["below_background"] = float(np.count_nonzero(a < floor)) / a.size
    out["checked"] = True
    out["failed"] = out["below_background"] >= BACKGROUND_FAILED
    return out


def threshold_labels(image, k=3.0, min_area_px=10, report=None):
    """Connected components above the cut, with the small ones dropped.

    `min_area_px` is not tidying: at k=3 over a large frame, thousands of
    single-pixel excursions clear the cut by chance, and each one would be
    counted as an object. The minimum is what makes the count mean "a stained
    region" rather than "a pixel that was noisy".

    Labelling is `skimage.measure.label` rather than `scipy.ndimage.label`
    because 05c - the one stage that calls this - already imports
    `skimage.measure`, and one imaging library for this job is enough. It
    returns the array alone, not a (labels, count) pair, so the count is
    labels.max().

    `report`, when a dict is passed, is UPDATED with `background_check`'s
    answer for this frame. Reported rather than printed: this runs inside a
    loop over thousands of ROIs, and a library printing from in there would
    produce thousands of lines nobody reads - and it is not this module's
    business to decide what a caller does about a frame whose background
    estimate failed. 05c records the ROI and counts it. Nothing is measured
    when no report is asked for, so the plain call costs what it always did.
    """
    from skimage.measure import label as connected_components

    a = np.asarray(image, dtype=np.float64)
    cut = cut_for(a, k=k)
    if report is not None:
        report.update(background_check(a, k=k))
    mask = a > cut
    labels = connected_components(mask).astype(np.int32)
    n = int(labels.max())
    if n == 0:
        return labels

    # Index 0 is the background's own count and must not be tested.
    areas = np.bincount(labels.ravel())
    too_small = np.flatnonzero(areas < int(min_area_px))
    too_small = too_small[too_small != 0]
    if too_small.size:
        labels[np.isin(labels, too_small)] = 0
        # Relabel so the ids are 1..n with no holes; downstream code takes
        # labels.max() as the object count, and the dropped object is under no
        # obligation to be the last one - drop the middle of three and the
        # survivors would otherwise be 1 and 3, reported as three objects.
        kept = np.unique(labels)
        kept = kept[kept != 0]
        remap = np.zeros(n + 1, dtype=np.int32)
        remap[kept] = np.arange(1, kept.size + 1, dtype=np.int32)
        labels = remap[labels]
    return labels.astype(np.int32)


def stardist_labels(image, model, n_tiles=None):
    """StarDist's instance segmentation, tiled.

    ALWAYS TILE. Untiled, StarDist takes 121 s on a 1.22 Mpx ROI; at
    n_tiles=(2,2) it takes 4.1 s and returns the identical 1177 nuclei. The
    cost is wildly non-linear in image size - a quarter of the pixels ran in
    0.7 s - so this is 30x on a typical ROI and the difference between a
    75-minute run and a 62-hour one. Nothing about the answer changes.

    Tiles of roughly 300k px, never fewer than 2x2. More tiles than that is
    slower again (5.1 s at 4x4, 11.1 s at 8x8): the per-tile overhead takes
    over. So the tiling is not a tuning knob.

    The model is passed in rather than loaded here so that one process loads it
    once - the weights are the expensive part.
    """
    from csbdeep.utils import normalize

    a = np.asarray(image)
    if n_tiles is None:
        nt = max(2, int(np.ceil(np.sqrt(a.size / 300_000))))
        n_tiles = (nt, nt)
    labels, _ = model.predict_instances(
        normalize(a, 1, 99.8), n_tiles=n_tiles,
        verbose=False, show_tile_progress=False)
    return labels


def segment(image, backend, model=None, k=3.0, min_area_px=10, report=None):
    """Dispatch to a backend by name.

    `report` is the threshold backend's diagnostic and is left untouched by
    every other one - stardist estimates no background, so a caller reading
    `report["failed"]` after a stardist call correctly finds nothing to say.
    """
    if backend == "threshold":
        return threshold_labels(image, k=k, min_area_px=min_area_px,
                                report=report)
    if backend == "stardist":
        if model is None:
            raise SegmentError(
                "the stardist backend needs a loaded model; 05c loads one per "
                "process so the weights are read once.")
        return stardist_labels(image, model)
    raise SegmentError(
        f"unknown segmentation backend {backend!r}. Known backends are "
        f"{', '.join(BACKENDS)}.")
