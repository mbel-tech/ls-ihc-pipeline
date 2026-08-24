"""Stage 4n - order the ROI curation queue so it can be stopped early.

`04l_roi_curator.py --marker AF568 --analysis-set` loads all 454 measurable pERK
sections in `(animal, section_order)` order. Worked through front to back that
means finishing LS105 entirely before LS120 is touched, so stopping half way
leaves five animals complete and six untouched - which supports no comparison at
all. The sections are the same either way; what changes is what a *prefix* of the
queue is worth.

This writes `roi_worklist.csv`, the same 454 sections in an order chosen so that
**any prefix is a usable dataset**: every animal advanced to roughly the same
fraction of its own series, and within each animal the sections spread across the
whole rostrocaudal range rather than marching along it.

Two orthogonal properties, both needed:

  * **Between animals** - each animal is advanced in proportion to how many
    sections it has, so after any number of sections every animal sits at about
    the same fraction of its own series. Equal *counts* per animal would finish
    the small animals early and leave the large ones sparse; equal *fractions*
    keeps them comparable, which is what a matched-level comparison needs.

  * **Within an animal** - farthest-point ordering over `section_order`: take the
    two ends, then repeatedly whichever section is furthest from everything
    already taken. The first handful therefore span the brain instead of
    clustering at one end, and coverage refines evenly as you go.

Tiers come first, order second. A section's tier says whether it belongs in the
main job at all:

    core                 421   paired, from an animal that can carry an estimate
    unpaired_unchecked    30   no PCNA partner - and the only analysis-set rows
                               whose rotation was never checked against anything
    animal_underpowered    3   LS85, which contributes too few to estimate from

Nothing is deleted. The excluded tiers are written into the same file with their
reason, so restoring them is a filter change rather than a re-run, and so the
count they represent stays visible.

**`pair_confidence` is deliberately not used for ordering.** It describes how
well a pERK section matched its *PCNA partner*; ROI curation landmarks a pERK
section against an *atlas plate*, which the partner plays no part in. A low value
is worth knowing at unblinding and is carried through as a column, but it is not
a reason to curate a section later. For the same reason the censoring columns are
not used either: inside `analysis_set` they are near zero by construction
(max 0.011 in tissue), so they rank nothing.

Run:  python 04n_roi_worklist.py
      python 04n_roi_worklist.py --tier core
"""

import argparse
import csv
import json
import os
from collections import defaultdict

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
DATASET_CSV = os.path.join(REFORMAT_DIR, "perk_sections_dataset.csv")
INDEX_CSV = os.path.join(REFORMAT_DIR, "reformat_index_AF568.csv")
OUT_CSV = os.path.join(REFORMAT_DIR, "roi_worklist.csv")

# An animal with fewer than this many measurable sections cannot support a
# per-animal estimate, so its sections are held out of the main job rather than
# spending curation time on a number nothing can be concluded from. Only LS85
# (3) falls under it; the next smallest is LS138 at 16.
MIN_SECTIONS_PER_ANIMAL = 10


def farthest_point_order(values):
    """Indices of `values` ordered so any prefix spreads across their range.

    Both ends first, then repeatedly whichever point is furthest from every
    point already chosen. For serial sections that means the first few span the
    brain and later ones bisect the gaps, so stopping early still leaves the
    rostrocaudal range covered instead of one end of it.
    """
    n = len(values)
    if n <= 2:
        return list(range(n))
    remaining = set(range(n))
    lo = min(remaining, key=lambda i: values[i])
    hi = max(remaining, key=lambda i: values[i])
    order = [lo, hi]
    remaining -= {lo, hi}
    while remaining:
        nxt = max(remaining, key=lambda i: min(abs(values[i] - values[j]) for j in order))
        order.append(nxt)
        remaining.discard(nxt)
    return order


def interleave_proportional(groups):
    """Merge per-animal queues so each advances at the same fraction of itself.

    Largest-remainder: at each step take from whichever animal has fallen
    furthest behind the fraction of its own list it should have consumed. An
    animal with 70 sections is therefore drawn from more often than one with 16,
    and both finish at the same time rather than the small one finishing first.
    """
    queues = {k: list(v) for k, v in groups.items() if v}
    taken = {k: 0 for k in queues}
    totals = {k: len(v) for k, v in queues.items()}
    out = []
    while queues:
        # the animal whose consumed fraction is currently smallest
        k = min(queues, key=lambda k: (taken[k] / totals[k], k))
        out.append(queues[k].pop(0))
        taken[k] += 1
        if not queues[k]:
            del queues[k]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default=None,
                    help="only write this tier (core / unpaired_unchecked / animal_underpowered)")
    args = ap.parse_args()

    with open(DATASET_CSV, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["status"] == "analysis_set"]

    # Every uid must have a reformatted image or the curator cannot show it.
    with open(INDEX_CSV, newline="", encoding="utf-8") as fh:
        have_image = {r["id"] for r in csv.DictReader(fh) if r["kind"] == "section"}
    missing = [r["scene_uid"] for r in rows if r["scene_uid"] not in have_image]
    if missing:
        raise SystemExit(f"{len(missing)} analysis-set sections have no AF568 image: {missing[:5]}")

    per_animal_total = defaultdict(int)
    for r in rows:
        per_animal_total[r["animal"]] += 1

    def tier_of(r):
        if per_animal_total[r["animal"]] < MIN_SECTIONS_PER_ANIMAL:
            return "animal_underpowered"
        if r["paired"] == "0":
            return "unpaired_unchecked"
        return "core"

    reason = {
        "core": "",
        "unpaired_unchecked": "no PCNA partner; rotation never checked against anything",
        "animal_underpowered": f"animal has <{MIN_SECTIONS_PER_ANIMAL} measurable sections",
    }

    # order within each tier independently, so a tier is self-contained
    ordered = []
    for tier in ("core", "unpaired_unchecked", "animal_underpowered"):
        tier_rows = [r for r in rows if tier_of(r) == tier]
        by_animal = defaultdict(list)
        for r in tier_rows:
            by_animal[r["animal"]].append(r)
        queues = {}
        for animal, rs in by_animal.items():
            orders = [int(r["section_order"]) for r in rs]
            queues[animal] = [rs[i] for i in farthest_point_order(orders)]
        ordered.extend((tier, r) for r in interleave_proportional(queues))

    def num(r, k):
        v = r.get(k, "").strip()
        return v if v not in ("", "nan") else ""

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["rank", "tier", "tier_reason", "scene_uid", "animal", "section_order",
                    "rotation_unchecked", "pair_confidence", "pair_align_iou",
                    "pcna_focus_score", "pcna_n_pieces", "pcna_largest_piece_mm2"])
        n = 0
        for tier, r in ordered:
            if args.tier and tier != args.tier:
                continue
            n += 1
            w.writerow([n, tier, reason[tier], r["scene_uid"], r["animal"], r["section_order"],
                        1 if r["paired"] == "0" else 0,
                        r["pair_confidence"], num(r, "pair_align_iou"),
                        num(r, "pcna_focus_score"), num(r, "pcna_n_pieces"),
                        num(r, "pcna_largest_piece_mm2")])

    counts = defaultdict(int)
    for tier, _ in ordered:
        counts[tier] += 1
    print(f"wrote {OUT_CSV}")
    for tier in ("core", "unpaired_unchecked", "animal_underpowered"):
        if counts[tier]:
            note = f"  - {reason[tier]}" if reason[tier] else ""
            print(f"  {tier:22} {counts[tier]:4}{note}")
    print(f"  {'total':22} {sum(counts.values()):4}")


if __name__ == "__main__":
    main()
