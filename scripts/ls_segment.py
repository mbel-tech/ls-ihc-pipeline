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

Nothing here has been run against real microscopy. The live study is `paired`
with both markers on `segment: nuclear`, so it takes the stardist route that
already existed; the threshold backend is guaranteed only by
tests/test_ls_segment.py's synthetic fields.
"""

import numpy as np

BACKENDS = ("stardist", "threshold")


class SegmentError(Exception):
    """A backend could not be run, or does not exist."""


def mad(image):
    """Median absolute deviation. Not scaled - `cut_for` applies the 1.4826."""
    a = np.asarray(image, dtype=np.float64).ravel()
    if a.size == 0:
        return 0.0
    m = float(np.median(a))
    return float(np.median(np.abs(a - m)))


def cut_for(image, k=3.0):
    """The intensity above which a pixel counts as signal."""
    a = np.asarray(image, dtype=np.float64)
    if a.size == 0:
        return 0.0
    return float(np.median(a)) + float(k) * 1.4826 * mad(a)


def threshold_labels(image, k=3.0, min_area_px=10):
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
    """
    from skimage.measure import label as connected_components

    a = np.asarray(image, dtype=np.float64)
    mask = a > cut_for(a, k=k)
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


def segment(image, backend, model=None, k=3.0, min_area_px=10):
    """Dispatch to a backend by name."""
    if backend == "threshold":
        return threshold_labels(image, k=k, min_area_px=min_area_px)
    if backend == "stardist":
        if model is None:
            raise SegmentError(
                "the stardist backend needs a loaded model; 05c loads one per "
                "process so the weights are read once.")
        return stardist_labels(image, model)
    raise SegmentError(
        f"unknown segmentation backend {backend!r}. Known backends are "
        f"{', '.join(BACKENDS)}.")
