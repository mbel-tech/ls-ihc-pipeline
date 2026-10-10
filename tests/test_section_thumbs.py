"""`04o --thumbs` - the 256px colour thumbnails the review grid draws.

The grid draws a few hundred cells at 78px. It has now made the same mistake
twice: first with the 1632x1862 overviews, which left most cells blank behind
`loading="lazy"`, then with the 768px composites at 448 KB, which put 56.6 MB
of picture behind one animal. What can go wrong here is quiet:

  * a thumbnail rebuilt from the overviews instead of downscaled from the
    composite would put a second render path between the grid and the frame the
    landmarks were placed in - the picture would look right and be a different
    image;
  * a thumbnail written at the composite's size saves nothing while looking
    like it worked;
  * NEAREST or BILINEAR on a 3:1 reduction of a sparse fluorescent signal drops
    isolated positive nuclei, which is the thing the grid is scanned for;
  * losing a channel gives a grid that is plausibly grey next to a colour
    detail pane;
  * overwriting on every run turns a top-up into a full rebuild of 1,506 files.

Run:  python tests/test_section_thumbs.py
"""

import importlib.util
import os
import shutil
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

# This suite imports stage modules, which read config at import. Without a
# config of its own it would fall through to the operator's live study and
# then pass or fail on their data. See tests/_fixture.py.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _fixture import use_temp_study  # noqa: E402

STUDY = use_temp_study()

_spec = importlib.util.spec_from_file_location(
    "o4", os.path.join(SCRIPTS, "04o_section_rgb.py"))
O = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(O)

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(56) + " %r" % (got,)
          + ("" if ok else "   want %r" % (want,)))


def truthy(label, got):
    global fails
    if not got:
        fails += 1
    print(("ok   " if got else "FAIL ") + label.ljust(56) + " %r" % (got,))


def composite(path, size=768):
    """A composite with a KNOWN sparse signal: a bright single-pixel dot in the
    marker plane, on a dim DAPI field. The dot is what a downscale destroys."""
    a = np.zeros((size, size, 3), np.uint8)
    a[..., 2] = 40                       # DAPI, blue, everywhere
    a[size // 2, size // 2, 0] = 255     # one isolated marker pixel, red
    a[100:140, 100:140, 0] = 200         # and a small blob
    Image.fromarray(a).save(path)


def main():
    tmp = tempfile.mkdtemp(prefix="lsthumb_")
    try:
        rgb = os.path.join(tmp, "sections_rgb")
        os.makedirs(rgb)
        for i in range(3):
            composite(os.path.join(rgb, "U%d.png" % i))
        # something that is not a PNG must not be picked up
        open(os.path.join(rgb, "notes.txt"), "w").close()

        made, existing, failed = O.write_thumbs(rgb)
        out = rgb + "_thumb"

        chk("it writes one thumbnail per composite", made, 3)
        chk("...and nothing was already there", existing, 0)
        chk("...and none failed", failed, 0)
        chk("the directory is the composite's plus _thumb",
            os.path.basename(out), "sections_rgb_thumb")
        chk("a non-PNG in the source is ignored",
            os.path.exists(os.path.join(out, "notes.txt")), False)
        chk("names carry over unchanged",
            sorted(os.listdir(out)), ["U0.png", "U1.png", "U2.png"])

        with Image.open(os.path.join(out, "U0.png")) as im:
            chk("the size is the canonical grid, not the composite's",
                im.size, (256, 256))
            a = np.asarray(im.convert("RGB"))

        # Colour, not a greyscale that merely looks fine in a dark grid.
        truthy("the marker plane survives", a[..., 0].max() > 0)
        truthy("the DAPI plane survives", a[..., 2].max() > 0)
        truthy("the planes differ, so it is genuinely colour",
               (a[..., 0] != a[..., 2]).any())
        chk("the unused plane stays empty", int(a[..., 1].max()), 0)

        # The blob must still be there. A 3:1 reduction of a 40px blob is ~13px;
        # if the marker plane came back empty the grid would show DAPI only.
        truthy("the marker blob is still visible after the reduction",
               a[30:50, 30:50, 0].max() > 100)

        # LANCZOS keeps a trace of the single isolated pixel; NEAREST would have
        # a 1-in-9 chance of sampling it and BILINEAR would smear it to nothing.
        truthy("the isolated marker pixel leaves a trace",
               a[126:130, 126:130, 0].max() > 0)

        # ---- a second run is a top-up, not a rebuild ------------------------
        made2, existing2, _ = O.write_thumbs(rgb)
        chk("a second run rebuilds nothing", made2, 0)
        chk("...and reports what it left alone", existing2, 3)

        made3, _, _ = O.write_thumbs(rgb, force=True)
        chk("--force rebuilds them", made3, 3)

        # ---- a new composite is picked up without touching the rest ---------
        composite(os.path.join(rgb, "U3.png"))
        made4, existing4, _ = O.write_thumbs(rgb)
        chk("a new composite is topped up", made4, 1)
        chk("...at the cost of only that one", existing4, 3)

        # ---- an unreadable file is counted, not fatal -----------------------
        with open(os.path.join(rgb, "broken.png"), "w", encoding="utf-8") as fh:
            fh.write("not a png")
        _m, _e, failed5 = O.write_thumbs(rgb)
        chk("an unreadable composite is reported rather than raising", failed5, 1)

        # ---- the size is a parameter, and it is honoured --------------------
        alt = os.path.join(tmp, "alt_rgb")
        os.makedirs(alt)
        composite(os.path.join(alt, "V.png"))
        O.write_thumbs(alt, size=128)
        with Image.open(os.path.join(alt + "_thumb", "V.png")) as im:
            chk("an explicit size is used", im.size, (128, 128))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("ALL PASS" if not fails else "%d FAILED" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
