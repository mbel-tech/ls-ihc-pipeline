"""The one place this pipeline reads pixels out of a CZI.

It exists because of two findings in docs/czi-reading-audit.md.

**Finding 1, confirmed and widespread.** `scene=` was passed nowhere. 219 of
the 222 files have at least one overlapping pair of scene rectangles, and 2241
of 2572 scenes are involved in an overlap, so reading a scene's rectangle
without naming the scene composites whichever neighbours overlap it - up to
20.6% foreign pixels, and clipped fractions overstated by up to 2.6x. `scene`
is a required argument here, not a defaulted one: a default of None would
restore exactly the behaviour this module exists to end.

**Finding 8.** `np.squeeze` was assuming the plane is grayscale. A channel with
an RGB pixel type squeezes to 3-D, and every downstream shape comparison would
then be comparing the wrong thing. The result is checked, and says which scene
and channel when it is not what was expected.

Which plane a named channel IS lives in `ls_channels`; this module takes an
index and does not know what it means.
"""

import numpy as np


class ReadError(Exception):
    """A read returned something that is not a single 2-D plane."""


def read_plane(doc, rect, channel, *, scene, zoom=1.0):
    """One scene, one channel, at one zoom, as a 2-D array.

    `scene` is keyword-only and has no default, so a caller that has not
    thought about it fails at the call rather than reading the wrong pixels.
    """
    arr = doc.read(roi=(rect.x, rect.y, rect.w, rect.h),
                   plane={"C": int(channel)}, scene=int(scene), zoom=float(zoom))
    out = np.squeeze(arr)
    if out.ndim != 2:
        raise ReadError(
            f"reading channel {channel} of scene {scene} gave a "
            f"{out.ndim}-D array of shape {out.shape}, not a single plane. A "
            f"channel with an RGB pixel type does this; every shape check "
            f"downstream assumes 2-D.")
    return out


def read_planes(doc, rect, planes, *, scene, zoom=1.0):
    """{name: 2-D array} for several channels of the SAME scene.

    Named channels rather than a list, so a caller cannot mix up which array
    it got - which is the mistake `dapi, mark = read(0), read(1)` invites.
    """
    if not planes:
        raise ReadError("read_planes was asked for no channels.")
    return {name: read_plane(doc, rect, index, scene=scene, zoom=zoom)
            for name, index in planes.items()}
