"""Choose a spread of sections for building the tile-correction field.

The field is the median of many folded tile cells, so what matters is that the
tissue falls at unrelated positions relative to the tile grid across the sample.
Sections from one animal, or all from the same rostro-caudal level, share
anatomy and would leave that anatomy baked into the "correction".

So: spread across every animal, both markers, and the full length of each
series, preferring sections with plenty of tissue.

Run:  python 01b_pick_sections.py            # ~72 sections
      python 01b_pick_sections.py --n 120
"""

import sys
import argparse
import csv
import json
import os
import random
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_naming as NM  # noqa: E402

SOURCE_DIR = CONFIG["source_dir"]
OUT_ROOT = CONFIG["out_root"]
OUT_CSV = os.path.join(OUT_ROOT, "qc", "tilefield_sample.csv")
SEED = 20260811


def pick_files(files, n_files):
    """`n_files` of `files`, evenly spread. Sampling at the CENTRE of each
    stride, so one file from a series is its middle slide - not the first,
    which is what `int(i * stride)` always returned for i = 0 and left every
    animal's tile-field sample on its most rostral slide."""
    stride = len(files) / n_files
    return [files[min(int((i + 0.5) * stride), len(files) - 1)] for i in range(n_files)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=72)
    ap.add_argument("--scenes-per-file", type=int, default=4)
    args = ap.parse_args()

    with open(os.path.join(OUT_ROOT, "manifest", "manifest_scenes.csv"), newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    present = {}
    usable = []
    for r in rows:
        if r["file"] not in present:
            present[r["file"]] = os.path.exists(os.path.join(SOURCE_DIR, r["file"]))
        if present[r["file"]]:
            r["section_order"] = int(r["section_order"])
            usable.append(r)

    groups = defaultdict(list)
    for r in usable:
        groups[(r["animal"], r["marker_channel"])].append(r)
    print(f"{len(usable)} sections available across {len(groups)} animal x marker series")

    rng = random.Random(SEED)
    per_group = max(1, args.n // max(len(groups), 1))
    picked = []
    for key, group in sorted(groups.items()):
        group.sort(key=lambda r: r["section_order"])

        # Take several scenes from few files rather than one scene from many.
        # Opening a CZI costs ~60 s of reader initialisation against ~1 s to
        # read a scene out of one already open, so file count - not section
        # count - is what sets the runtime.
        by_file = defaultdict(list)
        for r in group:
            by_file[r["file"]].append(r)
        files = sorted(by_file)
        n_files = max(1, min(len(files), -(-per_group // args.scenes_per_file)))
        chosen_files = pick_files(files, n_files)

        for fname in chosen_files:
            scenes = sorted(by_file[fname], key=lambda r: r["section_order"])
            step = len(scenes) / args.scenes_per_file
            for i in range(min(args.scenes_per_file, len(scenes))):
                idx = int(i * step + rng.random() * step)
                picked.append(scenes[min(idx, len(scenes) - 1)])

    seen = set()
    unique = []
    for r in picked:
        if r["scene_uid"] not in seen:
            seen.add(r["scene_uid"])
            unique.append(r)

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "scene", "scene_uid", "animal", "marker_channel"])
        for r in sorted(unique, key=lambda r: (r["file"], int(r["scene_index"]))):
            writer.writerow([r["file"], r["scene_index"], r["scene_uid"], r["animal"], r["marker_channel"]])

    by_marker = defaultdict(int)
    by_animal = defaultdict(int)
    for r in unique:
        by_marker[r["marker_channel"]] += 1
        by_animal[r["animal"]] += 1
    print(f"picked {len(unique)} sections from {len({r['file'] for r in unique})} files")
    print(f"  per marker: {dict(by_marker)}")
    print(f"  per animal: {dict(sorted(by_animal.items(), key=lambda kv: NM.natural_key(kv[0])))}")
    print(f"wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
