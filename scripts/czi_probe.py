import time, sys
import numpy as np
from pylibCZIrw import czi as pyczi

PATH = r"D:\SLIDES HE DEC 2025 LS\LS45_5a.czi"
t0 = time.time()
with pyczi.open_czi(PATH) as czi:
    t_open = time.time() - t0
    print(f"open: {t_open:.2f} s")

    bb = czi.total_bounding_box
    print("total_bounding_box:", {k: v for k, v in list(bb.items())[:8]})
    print("pixel_types:", czi.pixel_types)

    scenes = czi.scenes_bounding_rectangle
    print(f"scenes: {len(scenes)}")
    for i in sorted(scenes)[:3]:
        print("   scene", i, scenes[i])

    s0 = scenes[0]
    for zoom in (0.125, 0.25):
        t = time.time()
        img = czi.read(roi=(s0.x, s0.y, s0.w, s0.h), plane={"C": 0}, zoom=zoom)
        dt = time.time() - t
        um = 0.65 / zoom
        print(f"  scene0 C0 zoom={zoom}: {img.shape} {img.dtype} "
              f"min={img.min()} max={img.max()} in {dt:.2f}s  ({um:.2f} um/px)")

    # both channels, all scenes, at overview resolution - the Stage 1 workload
    t = time.time()
    n = 0
    for i in sorted(scenes):
        r = scenes[i]
        for c in (0, 1):
            czi.read(roi=(r.x, r.y, r.w, r.h), plane={"C": c}, zoom=0.125)
            n += 1
    dt = time.time() - t
    print(f"\nall {len(scenes)} scenes x 2 channels at 5.2 um/px: {dt:.1f}s "
          f"({dt/len(scenes):.2f}s per section)")
