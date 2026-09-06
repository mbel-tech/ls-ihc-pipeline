"""Stage 0c - decide which fluorophore carries pERK and which carries PCNA.

The CZI records fluorophores, not antibodies, so nothing in the metadata says
which is which. The two markers have very different spatial signatures though:

  PCNA  proliferating cells sit in the periventricular germinal zones, so
        positive nuclei hug the ventricular surface and cluster tightly.
  pERK  activity is distributed through the parenchyma, so positive cells are
        dispersed and much closer to spatially random.

Two scale-free statistics separate them without needing either marker named in
advance:

  clustering index   mean nearest-neighbour distance between detected objects,
                     divided by the value expected for the same number of
                     objects scattered at random over the same tissue area.
                     Below 1 = clustered, near 1 = random.

  edge affinity      median distance from a detected object to the nearest
                     tissue boundary, as a fraction of the tissue's own
                     half-width. Periventricular and outer-surface signal
                     scores low; parenchymal signal scores high.

Both are ratios, so neither depends on section size, tissue area, or how bright
the staining happens to be.

The call is written to config.json only after you confirm it against the
evidence figures - nothing downstream may use the names before that.

Run:  python 00c_channel_identity.py
      python 00c_channel_identity.py --accept    # write the call into config.json
"""

import argparse
import csv
import json
import os
import random
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from scipy import ndimage

# LS_CONFIG names the file explicitly; the file-relative path is the fallback.
# Frozen, the scripts sit inside _internal/ while config.json is beside the
# executable, so the fallback would point at a file that does not exist.
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
REPORT_DIR = os.path.join(OUT_ROOT, "qc", "channel_identity")

SECTIONS_PER_MARKER = 14
SEED = 20260811

# Detection on the 8-bit overviews is deliberately crude: this asks where the
# signal sits, not how much of it there is.
BLUR_SIGMA_PX = 1.2
MIN_OBJECT_PX = 3
TOP_PERCENTILE = 99.0


def load_sections():
    if not os.path.exists(QC_CSV):
        raise SystemExit(f"{QC_CSV} not found - run 01_overviews.groovy first.")
    with open(QC_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["tissue_fraction"] = float(r["tissue_fraction"] or 0)
    return [r for r in rows if r["tissue_fraction"] > 0.05]


def detect(marker_img, tissue):
    """Bright local maxima inside tissue - approximate positive objects."""
    data = ndimage.gaussian_filter(marker_img.astype(np.float32), BLUR_SIGMA_PX)
    inside = data[tissue]
    if inside.size < 100:
        return np.empty((0, 2)), None
    threshold = np.percentile(inside, TOP_PERCENTILE)
    blobs = (data > threshold) & tissue
    labels, n = ndimage.label(blobs)
    if n == 0:
        return np.empty((0, 2)), None
    sizes = ndimage.sum(blobs, labels, range(1, n + 1))
    keep = np.where(sizes >= MIN_OBJECT_PX)[0] + 1
    if not keep.size:
        return np.empty((0, 2)), None
    centres = ndimage.center_of_mass(blobs, labels, keep)
    return np.array(centres), labels


def clustering_index(points, tissue_area_px):
    """Mean NN distance over the value expected under complete randomness."""
    if len(points) < 8:
        return np.nan
    d = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)
    np.fill_diagonal(d, np.inf)
    observed = float(np.mean(d.min(axis=1)))
    expected = 0.5 * np.sqrt(tissue_area_px / len(points))
    return observed / expected if expected > 0 else np.nan


def edge_affinity(points, tissue):
    """Distance to the nearest tissue boundary, scaled by the tissue half-width."""
    if not len(points):
        return np.nan
    distance = ndimage.distance_transform_edt(tissue)
    scale = float(distance.max())
    if scale <= 0:
        return np.nan
    rows = np.clip(points[:, 0].astype(int), 0, tissue.shape[0] - 1)
    cols = np.clip(points[:, 1].astype(int), 0, tissue.shape[1] - 1)
    return float(np.median(distance[rows, cols]) / scale)


def analyse(row):
    base = os.path.join(OVERVIEW_DIR, row["animal"], row["marker_channel"], row["scene_uid"])
    mark_path, dapi_path = base + "_MARK.png", base + "_DAPI.png"
    if not (os.path.exists(mark_path) and os.path.exists(dapi_path)):
        return None

    marker = np.asarray(Image.open(mark_path).convert("L"))
    dapi = np.asarray(Image.open(dapi_path).convert("L"))

    tissue = ndimage.binary_fill_holes(
        ndimage.gaussian_filter(dapi.astype(np.float32), 3) > max(8, np.percentile(dapi, 60))
    )
    tissue = ndimage.binary_opening(tissue, np.ones((5, 5)))
    area = int(tissue.sum())
    if area < 5000:
        return None

    points, _ = detect(marker, tissue)
    if len(points) < 8:
        return None

    return {
        "scene_uid": row["scene_uid"],
        "animal": row["animal"],
        "marker_channel": row["marker_channel"],
        "n_objects": len(points),
        "clustering_index": clustering_index(points, area),
        "edge_affinity": edge_affinity(points, tissue),
        "_points": points,
        "_marker": marker,
        "_tissue": tissue,
    }


def figure(results, path):
    by_marker = defaultdict(list)
    for r in results:
        by_marker[r["marker_channel"]].append(r)

    markers = sorted(by_marker)
    fig, axes = plt.subplots(len(markers), 4, figsize=(16, 4.2 * len(markers)), squeeze=False)
    for row, marker in enumerate(markers):
        group = by_marker[marker]
        for col, r in enumerate(group[:3]):
            ax = axes[row][col]
            ax.imshow(r["_marker"], cmap="gray")
            ax.contour(r["_tissue"], levels=[0.5], colors="#3080ff", linewidths=0.6)
            ax.scatter(r["_points"][:, 1], r["_points"][:, 0], s=5, c="#ff3020", alpha=0.7)
            ax.set_title(f"{marker}  {r['scene_uid']}\nCI {r['clustering_index']:.2f}  "
                         f"EA {r['edge_affinity']:.2f}", fontsize=9)
            ax.axis("off")

        ax = axes[row][3]
        ci = [r["clustering_index"] for r in group if np.isfinite(r["clustering_index"])]
        ea = [r["edge_affinity"] for r in group if np.isfinite(r["edge_affinity"])]
        ax.scatter(ci, ea, s=22, alpha=0.8)
        ax.axvline(1.0, color="#909090", ls="--", lw=0.8)
        ax.set_xlabel("clustering index (<1 = clustered)")
        ax.set_ylabel("edge affinity (low = periventricular)")
        ax.set_title(f"{marker}: median CI {np.median(ci):.2f}, EA {np.median(ea):.2f}", fontsize=10)

    fig.suptitle("Channel identity evidence - PCNA should be clustered and edge-hugging", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=105)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accept", action="store_true")
    args = ap.parse_args()
    os.makedirs(REPORT_DIR, exist_ok=True)

    rows = load_sections()
    by_marker = defaultdict(list)
    for r in rows:
        by_marker[r["marker_channel"]].append(r)

    rng = random.Random(SEED)
    results = []
    for marker, group in sorted(by_marker.items()):
        rng.shuffle(group)
        taken = 0
        for r in group:
            if taken >= SECTIONS_PER_MARKER:
                break
            res = analyse(r)
            if res:
                results.append(res)
                taken += 1
        print(f"  {marker}: analysed {taken} sections")

    if not results:
        raise SystemExit("no sections could be analysed")

    stats = defaultdict(lambda: {"ci": [], "ea": []})
    for r in results:
        if np.isfinite(r["clustering_index"]):
            stats[r["marker_channel"]]["ci"].append(r["clustering_index"])
        if np.isfinite(r["edge_affinity"]):
            stats[r["marker_channel"]]["ea"].append(r["edge_affinity"])

    summary = {}
    for marker, s in stats.items():
        summary[marker] = {
            "clustering_index": float(np.median(s["ci"])) if s["ci"] else float("nan"),
            "edge_affinity": float(np.median(s["ea"])) if s["ea"] else float("nan"),
            "n_sections": len(s["ci"]),
        }

    fig_path = os.path.join(REPORT_DIR, "channel_identity.png")
    figure(results, fig_path)

    with open(os.path.join(REPORT_DIR, "channel_identity.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["scene_uid", "animal", "marker_channel", "n_objects",
                    "clustering_index", "edge_affinity"])
        for r in results:
            w.writerow([r["scene_uid"], r["animal"], r["marker_channel"], r["n_objects"],
                        round(r["clustering_index"], 4), round(r["edge_affinity"], 4)])

    print()
    print("=" * 72)
    for marker, s in sorted(summary.items()):
        print(f"  {marker}: clustering {s['clustering_index']:.3f}  "
              f"edge affinity {s['edge_affinity']:.3f}  (n={s['n_sections']})")

    call = None
    if len(summary) == 2:
        a, b = sorted(summary)
        # PCNA is the more clustered and more edge-hugging of the two; both
        # statistics must agree or the call is not made.
        clustered = a if summary[a]["clustering_index"] < summary[b]["clustering_index"] else b
        edgy = a if summary[a]["edge_affinity"] < summary[b]["edge_affinity"] else b
        if clustered == edgy:
            other = b if clustered == a else a
            call = {clustered: "PCNA", other: "pERK"}
            print(f"\n  CALL: {clustered} = PCNA (clustered, periventricular), {other} = pERK")
        else:
            print(f"\n  NO CALL: the two statistics disagree "
                  f"(clustered={clustered}, edge-hugging={edgy}).")
            print("  Look at the figure and set marker_identity in config.json by hand.")

    print(f"\n  evidence: {fig_path}")
    print("=" * 72)

    if call and args.accept:
        CONFIG["marker_identity"].update(call)
        CONFIG["marker_identity"]["_confirmed"] = "00c_channel_identity.py --accept"
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(CONFIG, fh, indent=2)
        print("  written into config.json")
    elif call:
        print("  re-run with --accept once the figure agrees.")


if __name__ == "__main__":
    main()
