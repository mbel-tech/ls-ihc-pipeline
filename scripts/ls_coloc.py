"""Relating objects of one marker to objects of another.

**A is co-localised with B when A's centroid falls inside B's mask.**

Not an overlap fraction. Objects from different markers are not the same
shapes - one may have come from a nuclear mask and another from a threshold
region on its own channel - so an overlap fraction is not comparable between
pairs, and a fraction needs a cutoff, which would be a second uncalibrated
parameter in a pipeline that already carries one in the detection threshold.

Containment is asymmetric: a small object's centroid can sit inside a large one
while the large one's centroid sits outside the small one. So BOTH directions
are computed and both are recorded, and the reader is told which is which
rather than being handed one number called "co-localisation".

A centroid is not obliged to lie on its own object - a C-shaped region's falls
in the notch - so an object can relate to nothing, or to something it barely
touches. That is a property of the rule, not a bug in it, and it is why the
containment is reported per object pair rather than summed into a rate here.

Label ids are carried through untouched: they are what `roi_nuclei.csv` records
as `nucleus_id`, so a row of the join table points at two rows of the
measurement table by (scene_uid, roi_index, marker, nucleus_id). Renumbering
them would break that join silently.

Centroids come from `skimage.measure.regionprops`, which is what 05c - the only
caller - already uses to measure every object. scipy's center_of_mass would
compute the same numbers while pulling a second imaging library into a module
that needs one function from it.

Nothing here has been run on real data: no study is `multiplex`, and
co-localisation is not computed under any other layout. See
tests/test_colocalisation.py.
"""

import numpy as np


def centroids(labels):
    """{label: (row, col)} for every object in an int label image."""
    from skimage.measure import regionprops

    a = np.asarray(labels)
    if a.size == 0 or int(a.max()) == 0:
        return {}
    return {int(p.label): (float(p.centroid[0]), float(p.centroid[1]))
            for p in regionprops(a)}


def _label_at(labels, point):
    """The object id under a centroid, or 0 for background / off-image."""
    r, c = int(round(point[0])), int(round(point[1]))
    if r < 0 or c < 0 or r >= labels.shape[0] or c >= labels.shape[1]:
        return 0
    return int(labels[r, c])


def pairs(labels_a, labels_b):
    """Every related (a, b) pair, with both directions recorded.

    A pair is emitted when EITHER direction holds, so a relation is never
    dropped for being one-way - which is the whole reason both are computed.
    """
    a_cen = centroids(labels_a)
    b_cen = centroids(labels_b)
    if not a_cen or not b_cen:
        return []

    labels_a = np.asarray(labels_a)
    labels_b = np.asarray(labels_b)

    found = {}
    for a_id, point in a_cen.items():
        b_id = _label_at(labels_b, point)
        if b_id:
            found[(a_id, b_id)] = {"object_a": a_id, "object_b": b_id,
                                   "a_centroid_in_b": True,
                                   "b_centroid_in_a": False}
    for b_id, point in b_cen.items():
        a_id = _label_at(labels_a, point)
        if a_id:
            row = found.get((a_id, b_id))
            if row is None:
                found[(a_id, b_id)] = {"object_a": a_id, "object_b": b_id,
                                       "a_centroid_in_b": False,
                                       "b_centroid_in_a": True}
            else:
                row["b_centroid_in_a"] = True
    return [found[k] for k in sorted(found)]
