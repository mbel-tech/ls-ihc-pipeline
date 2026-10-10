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
    unpaired_unchecked    30   no partner in the geometry-source pass - and the
                               only analysis-set rows whose rotation was never
                               checked against anything
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

import sys
import argparse
import csv
import importlib.util
import json
import os
from collections import defaultdict

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_channels as CH  # noqa: E402
import ls_paths as LP  # noqa: E402

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")

# The queue is over the MEASURED pass - the one 04m's table has a row per - so
# the marker is the one that is not the geometry source. Asked of ls_paths
# rather than derived as MARKERS[0]: the geometry source is the SECOND declared
# marker, and every copy of that rule this repo wrote by hand came out inverted.
MARKERS = list(CH.marker_names(CONFIG))
LAYOUT = (CONFIG.get("acquisition") or {}).get("layout", CH.LAYOUT_MULTIPLEX)
NAMES = LP.for_config(CONFIG)
PARTNER = LP.geometry_source(MARKERS, LAYOUT)
MARKER = next((m for m in MARKERS if m != PARTNER), PARTNER)


def dataset_csv():
    """04m's table. `read()`, so the operator's `perk_sections_dataset.csv` is
    still found after 04m started writing `sections_dataset_<marker>.csv`."""
    return NAMES.read("sections_dataset", MARKER)


def index_csv():
    return NAMES.read("index", MARKER)


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
    ap.add_argument("--min-sections", type=int, default=MIN_SECTIONS_PER_ANIMAL,
                    metavar="N",
                    help="animals with fewer than N measurable sections are held out "
                         f"of core (default {MIN_SECTIONS_PER_ANIMAL}). Pass 0 to keep "
                         "every animal, which puts its sections in the main queue "
                         "interleaved rather than appended at the end")
    args = ap.parse_args()
    min_sections = args.min_sections

    dataset = dataset_csv()
    with open(dataset, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        fields = list(rd.fieldnames or [])
        rows = [r for r in rd if r["status"] == "analysis_set"]

    # THE PARTNER COLUMNS, RESOLVED ONCE AGAINST THE HEADER - not per row, and
    # never with `.get()`. `num(r, k)` below used to do exactly that, so the day
    # 04m renamed `pcna_focus_score` this stage would have written a worklist
    # with the right number of rows, the right columns and an empty string in
    # every partner cell - a blank that is indistinguishable from a section
    # whose partner genuinely had no score. `pick_column` refuses instead, with
    # both spellings in the message.
    what = os.path.basename(dataset)
    col_uid = IO.pick_column(fields, "partner_scene_uid", "pcna_scene_uid",
                             what=what)
    col_focus = IO.pick_column(fields, "partner_focus_score",
                               "pcna_focus_score", what=what)
    col_pieces = IO.pick_column(fields, "partner_n_pieces", "pcna_n_pieces",
                                what=what)
    col_largest = IO.pick_column(fields, "partner_largest_piece_mm2",
                                 "pcna_largest_piece_mm2", what=what)

    # Every uid must have a reformatted image or the curator cannot show it.
    with open(index_csv(), newline="", encoding="utf-8") as fh:
        have_image = {r["id"] for r in csv.DictReader(fh) if r["kind"] == "section"}
    missing = [r["scene_uid"] for r in rows if r["scene_uid"] not in have_image]
    if missing:
        raise SystemExit(f"{len(missing)} analysis-set sections have no "
                         f"{MARKER} image: {missing[:5]}")

    per_animal_total = defaultdict(int)
    for r in rows:
        per_animal_total[r["animal"]] += 1

    def tier_of(r):
        if per_animal_total[r["animal"]] < min_sections:
            return "animal_underpowered"
        if r["paired"] == "0":
            return "unpaired_unchecked"
        return "core"

    reason = {
        "core": "",
        "unpaired_unchecked": "no partner in the geometry-source pass; "
                              "rotation never checked against anything",
        "animal_underpowered": f"animal has <{min_sections} measurable sections",
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
        # `k` is a column name that came out of pick_column above, so it is
        # present in the header. The blank this can still return is a blank
        # CELL, which is a real answer; a missing column is no longer one of
        # the ways to reach it.
        v = r.get(k, "").strip()
        return v if v not in ("", "nan") else ""

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["rank", "tier", "tier_reason", "scene_uid",
                    "partner_scene_uid", "animal", "section_order",
                    "rotation_unchecked", "pair_confidence", "pair_align_iou",
                    "partner_focus_score", "partner_n_pieces",
                    "partner_largest_piece_mm2"])
        n = 0
        for tier, r in ordered:
            if args.tier and tier != args.tier:
                continue
            n += 1
            w.writerow([n, tier, reason[tier], r["scene_uid"], r[col_uid],
                        r["animal"], r["section_order"],
                        1 if r["paired"] == "0" else 0,
                        r["pair_confidence"], num(r, "pair_align_iou"),
                        num(r, col_focus), num(r, col_pieces),
                        num(r, col_largest)])

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
