"""How much the scene fix moved this dataset's clipping numbers.

Not a stage, and not a test. The `scene=` fix changes real values on purpose -
a read that does not name its scene composites whichever neighbours overlap it,
and 2241 of 2572 scenes are involved in an overlap - so a test asserting the
numbers unchanged would defeat the fix. This measures the difference instead,
so it can be reviewed and quoted.

Two reads of the same rectangle per scene: one naming the scene, one not. The
second is the old behaviour reproduced exactly, not a model of it.

Reads only. Writes one CSV and prints a summary.

Run:  work/appenv/Scripts/python.exe docs/scene_fix_report.py [--limit N]
"""

import argparse
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import czi_read as CR                                       # noqa: E402
import ls_config as LC                                      # noqa: E402

CONFIG = LC.load()
OUT_ROOT = LC.require_path("out_root", CONFIG)
SOURCE_DIR = LC.require_path("source_dir", CONFIG)
MARKER_C = int(CONFIG.get("channels", {}).get("marker_index", 1))
MANIFEST = os.path.join(OUT_ROOT, "manifest", "manifest_scenes.csv")
FILES = os.path.join(OUT_ROOT, "manifest", "manifest_files.csv")
REPORT = os.path.join(OUT_ROOT, "qc", "scene_fix_report.csv")

COLUMNS = ["scene_uid", "animal", "file", "scene_index", "marker_channel",
           "clipped_without_scene", "clipped_with_scene", "ratio",
           "foreign_fraction"]


class Rect(object):
    """What czi_read.read_plane wants: .x .y .w .h."""

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)


def ceilings():
    """file -> clip ceiling, as the manifest records it.

    Per file, not a constant: 65535 is only right for the 16-bit files, and
    01_overviews.load_ceilings() explains why assuming it is not safe.
    """
    with open(FILES, newline="", encoding="utf-8") as fh:
        return {r["file"]: float(r.get("clip_ceiling") or 65535)
                for r in csv.DictReader(fh)}


def summarise(out, skipped):
    """Print the finding. Returns nothing; the CSV is the record."""
    moved = [r for r in out if r["foreign_fraction"] > 0]
    print("scenes measured          : %d" % len(out))
    for reason, n in sorted(skipped.items()):
        if n:
            print("scenes skipped (%s): %d" % (reason, n))
    if not out:
        return
    pct = 100.0 * len(moved) / len(out)
    print("scenes whose pixels moved: %d (%.1f%%)" % (len(moved), pct))
    if not moved:
        return

    # The audit predicted overstatement, and that is only half of it. Reading
    # a rectangle without naming its scene composites the overlap, and a
    # neighbour's tile can OVERWRITE the target scene's own clipped pixels as
    # easily as it can add foreign ones. So the error runs both ways and is
    # reported both ways; collapsing it to one direction would be reporting
    # the prediction rather than the measurement.
    over = [r for r in moved if r["ratio"] != "" and r["ratio"] > 1]
    under = [r for r in moved if r["ratio"] != "" and r["ratio"] < 1]
    same = [r for r in moved if r["ratio"] != "" and r["ratio"] == 1]
    # A scene that clipped ONLY because of a neighbour has no finite ratio.
    # Reported separately rather than dropped: it is overstatement without
    # bound, and a median over the rest alone would exclude the clearest cases.
    only_foreign = [r for r in moved
                    if r["ratio"] == "" and r["clipped_without_scene"] > 0]

    print("  clipped fraction was OVERstated : %d scenes (median %.2fx, "
          "max %.2fx)" % (len(over), float(np.median([r["ratio"] for r in over]))
                          if over else 0, max([r["ratio"] for r in over])
                          if over else 0))
    print("  clipped fraction was UNDERstated: %d scenes (median %.2fx, "
          "min %.2fx)" % (len(under),
                          float(np.median([r["ratio"] for r in under]))
                          if under else 0,
                          min([r["ratio"] for r in under]) if under else 0))
    print("  pixels moved, clipped fraction did not: %d scenes" % len(same))
    if only_foreign:
        print("  clipping was ENTIRELY a neighbour's: %d scenes" %
              len(only_foreign))

    tot_a = sum(r["clipped_without_scene"] for r in out)
    tot_b = sum(r["clipped_with_scene"] for r in out)
    print("dataset mean clipped fraction: %.5f -> %.5f (%.2fx)"
          % (tot_a / len(out), tot_b / len(out),
             (tot_a / tot_b) if tot_b else float("inf")))

    def show(title, key):
        print("\n%s:" % title)
        for r in sorted(moved, key=key)[:5]:
            print("  %s: %.1f%% foreign pixels, clipped %.4f -> %.4f"
                  % (r["scene_uid"], 100 * r["foreign_fraction"],
                     r["clipped_without_scene"], r["clipped_with_scene"]))

    # Most foreign pixels is not the same question as most changed number: a
    # scene can composite a neighbour heavily and clip nowhere. Both are shown
    # because it is the second that reaches the analysis set.
    show("most foreign pixels", lambda r: -r["foreign_fraction"])
    show("largest change in clipped fraction",
         lambda r: -abs(r["clipped_without_scene"] - r["clipped_with_scene"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many scenes (0 = all)")
    ap.add_argument("--zoom", type=float, default=0.125,
                    help="zoom to measure at; 0.125 is the overview scale")
    args = ap.parse_args()

    from pylibCZIrw import czi as pyczi

    with open(MANIFEST, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    ceiling_by = ceilings()

    by_file = {}
    for r in rows:
        by_file.setdefault(r["file"], []).append(r)

    out = []
    skipped = {"file missing": 0, "scene not in file": 0, "shape mismatch": 0}
    done = 0
    for fname, scenes in sorted(by_file.items()):
        path = os.path.join(SOURCE_DIR, fname)
        if not os.path.exists(path):
            skipped["file missing"] += len(scenes)
            continue
        ceiling = ceiling_by.get(fname, 65535)
        with pyczi.open_czi(path) as doc:
            rects = doc.scenes_bounding_rectangle
            for r in scenes:
                s = int(r["scene_index"])
                if s not in rects:
                    skipped["scene not in file"] += 1
                    continue
                b = rects[s]
                rect = Rect(b.x, b.y, b.w, b.h)
                with_scene = CR.read_plane(doc, rect, MARKER_C,
                                           scene=s, zoom=args.zoom)
                # The old behaviour, reproduced exactly: same rectangle, no
                # scene, so whatever overlaps it comes too.
                without = np.squeeze(doc.read(
                    roi=(rect.x, rect.y, rect.w, rect.h),
                    plane={"C": MARKER_C}, zoom=args.zoom))
                if without.ndim != 2 or without.shape != with_scene.shape:
                    skipped["shape mismatch"] += 1
                    continue
                a = float((without >= ceiling).mean())
                c = float((with_scene >= ceiling).mean())
                out.append({
                    "scene_uid": r["scene_uid"], "animal": r["animal"],
                    "file": fname, "scene_index": s,
                    "marker_channel": r.get("marker_channel", ""),
                    "clipped_without_scene": round(a, 6),
                    "clipped_with_scene": round(c, 6),
                    "ratio": round(a / c, 3) if c else "",
                    "foreign_fraction": round(
                        float((without != with_scene).mean()), 6),
                })
                done += 1
                if args.limit and done >= args.limit:
                    break
        if args.limit and done >= args.limit:
            break

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out)

    summarise(out, skipped)
    print("\nwritten to %s" % REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
