"""Stage 0c - which fluorophore carries the clustered marker and which the
dispersed one.

The CZI records fluorophores, not antibodies, so nothing in the metadata says
which is which. Two markers of the kind this pipeline was built for have very
different spatial signatures though - the LS study's pair as the worked example:

  PCNA  proliferating cells sit in the periventricular germinal zones, so
        positive nuclei hug the ventricular surface and cluster tightly.
  pERK  activity is distributed through the parenchyma, so positive cells are
        dispersed and much closer to spatially random.

Those two names are an EXAMPLE and appear nowhere in the code. What this stage
measures is the pattern; what the channels are called comes from the study's
own `marker_identity` block, and where the study has not said, no name is
offered. See `make_call`.

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

import sys
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

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_channels as CH  # noqa: E402

MARKERS = list(CH.marker_names(CONFIG))

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

    # No antibody name in the caption: the figure is the evidence for a
    # PATTERN, and which antibody is expected to show it is the study's
    # statement, not this file's. See make_call.
    fig.suptitle("Channel identity evidence - the proliferation marker should be "
                 "clustered and edge-hugging", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=105)
    plt.close(fig)


def declared_names(cfg=None):
    """{fluorophore: antibody name} for the markers this study declares.

    The study's own record, from `marker_identity`. Only entries whose key is a
    declared marker and whose value is a plain non-empty string: that block also
    carries `_note`-style commentary and a `DAPI` sub-object of excitation and
    emission wavelengths, and neither is an antibody name.
    """
    cfg = CONFIG if cfg is None else cfg
    block = (cfg or {}).get("marker_identity")
    if not isinstance(block, dict):
        return {}
    out = {}
    for marker in MARKERS:
        value = block.get(marker)
        if isinstance(value, str) and value.strip():
            out[marker] = value.strip()
    return out


def pattern(summary):
    """(clustered, dispersed), or None when the evidence does not decide.

    This is everything the measurement can say on its own, and it is all this
    stage knows without being told something: two scale-free statistics, and
    which of exactly two channels sits low on both. They must agree - one
    channel clustered and the OTHER edge-hugging is not a signature, it is a
    reason to look at the figure.
    """
    if len(summary) != 2:
        return None
    a, b = sorted(summary)
    clustered = a if summary[a]["clustering_index"] < summary[b]["clustering_index"] else b
    edgy = a if summary[a]["edge_affinity"] < summary[b]["edge_affinity"] else b
    if clustered != edgy:
        return None
    return clustered, (b if clustered == a else a)


def make_call(summary, declared):
    """(identity record to write, what to print). `None` when it cannot be made.

    THIS USED TO INVENT THE NAMES. It was `call = {clustered: "PCNA", other:
    "pERK"}`, and with `--accept` those two literals went into the operator's
    `config.json`. For a study measuring neither antibody that is a false
    record - and one the operator is then asked to CONFIRM, which is worse than
    a wrong default, because the stage presents it as evidence-backed.

    What the measurement establishes is a PATTERN, not a name: this channel is
    the clustered, edge-hugging one. Turning a pattern into an antibody name
    needs someone to say which of this study's antibodies is expected to look
    like that, and nothing in the config says so - `marker_identity` records the
    conclusion, not the expectation. So the names come from the study where it
    has declared them, and where it has not, no name is offered at all: the
    pattern is printed and the operator writes the block by hand. Refusing is
    the honest half of "derive from the study"; there is no third source.

    The consequence, stated plainly: for a study that HAS declared its
    identities this is a re-confirmation, and the evidence is put beside the
    declaration for the operator to judge rather than checked automatically.
    Automatic checking would need the expectation, which is the thing that is
    missing. `ls_config` records that `marker_identity` is read by no stage
    today, so what was at stake was a wrong written record rather than a wrong
    number - but it is the only written record of the assignment, and every
    biological name downstream is meant to come from it.
    """
    found = pattern(summary)
    if found is None:
        if len(summary) != 2:
            return None, ["NO CALL: this study does not have exactly two "
                          f"measured channels ({len(summary)} here)."]
        a, b = sorted(summary)
        clustered = a if summary[a]["clustering_index"] < summary[b]["clustering_index"] else b
        edgy = a if summary[a]["edge_affinity"] < summary[b]["edge_affinity"] else b
        return None, [f"NO CALL: the two statistics disagree "
                      f"(clustered={clustered}, edge-hugging={edgy}).",
                      "Look at the figure and set marker_identity in "
                      "config.json by hand."]

    clustered, dispersed = found
    lines = [f"PATTERN: {clustered} is the clustered, edge-hugging channel; "
             f"{dispersed} is the dispersed one."]
    missing = [m for m in (clustered, dispersed) if m not in declared]
    if missing:
        lines.append("NO CALL: this study has not declared what "
                     + " and ".join(missing) + " measure, and this stage will "
                     "not invent a name for them.")
        lines.append("Put the antibody names into marker_identity in "
                     "config.json - the pattern above is the evidence for "
                     "which is which - and re-run to confirm them.")
        return None, lines

    lines.append(f"CALL: {clustered} = {declared[clustered]} (clustered, "
                 f"periventricular), {dispersed} = {declared[dispersed]}")
    lines.append("These are the names the STUDY declares. Check them against "
                 "the figure: the clustered, edge-hugging channel is the one "
                 "whose positive cells sit at the ventricular surface.")
    return dict(declared), lines


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

    # The proliferation marker is the more clustered and more edge-hugging of
    # the two; both statistics must agree or no call is made. What the channels
    # are CALLED comes from the study, never from this file - see make_call.
    call, lines = make_call(summary, declared_names())
    print()
    for line in lines:
        print("  " + line)

    print(f"\n  evidence: {fig_path}")
    print("=" * 72)

    if call and args.accept:
        CONFIG.setdefault("marker_identity", {}).update(call)
        CONFIG["marker_identity"]["_confirmed"] = "00c_channel_identity.py --accept"
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(CONFIG, fh, indent=2)
        print("  written into config.json")
    elif call:
        print("  re-run with --accept once the figure agrees.")


if __name__ == "__main__":
    main()
