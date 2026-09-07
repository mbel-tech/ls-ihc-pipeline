"""Stage 4l - assign a plate, place landmarks, warp the atlas regions onto the section.

This is SHARCQ's workflow (Lauridsen et al. 2022, eNeuro), rebuilt for the salmon
atlas. SHARCQ cannot be used directly - MATLAB, and bound to the Allen or
Franklin-Paxinos 3D atlas - but its shape is the right one, and the important
thing about it is what it does **not** automate: its user "must scroll to the
correct AP coordinate and DV/ML tilt" by eye, then clicks numbered corresponding
points between the slice and the atlas. What it automates is the landmark
registration, the warping, and the per-region counting.

That matters here because automatic level assignment has now been measured to
fail twice on this data, for a reason in the data rather than in the algorithm:

  * `04c`, silhouette IoU: correlation between serial order and best-matching
    plate is -0.05, 0.00, 0.17, -0.04;
  * giRAff's method, registered-intensity cross-correlation: -0.18 to +0.09 in
    both polarities.

See REFERENCES.md. The published tool for this exact task picks the plate by
hand, so this does too.

Interaction
-----------

  **Scrub the plate slider** until the plate matches the section, then **click
  matching points** - once on the section, once on the plate, alternating. Three
  pairs are the minimum for an affine; more improves it.

  **Press `Rotate`, then drag left or right on the section to tilt it.** Rotation
  is a mode rather than a gesture, so dragging can never be mistaken for placing
  a landmark - while it is on, clicks on the section are inert. Hold shift for
  fine control. **The tilt saves itself the moment the mouse is released** and is
  kept with that section, so leaving it and coming back shows it exactly as it was
  left. `Restore original tilt` (or `r`) puts the section back the way
  `04a_reformat` produced it, which is exactly rot = 0. The rotation is a
  **viewing aid and nothing else** - every stored coordinate stays in the
  unrotated reformatted frame, so the transform, the residuals and all three
  exports are identical whether the section was turned or not. The angle is
  carried in `roi_plates.csv` as `view_rotation_deg` for provenance only.

  **`Exclude` rejects the section**, and is a different statement from `No ROI
  here`: no-ROI says the section is fine and has nothing to measure at this
  level, exclude says the section should not be used. Landmarks already placed
  are kept in the exports; the exclusion is a flag to filter on, not a deletion.

  **Work is saved as you go**, to the browser's local storage, on every single
  change - not on a timer. On top of that a rolling snapshot is written once a
  minute under a second key, and `saved HH:MM:SS` in the header reports it. The
  snapshot exists for the one failure the per-change save cannot cover: it
  overwrites the single record every time, so a state that goes wrong has no
  earlier version to go back to. `roiRestoreBackup()` in the console rolls back
  to it - console rather than a button, because it replaces the live state
  wholesale. None of this is a substitute for `Export`, which is what produces
  the actual files.

  **`Shotgun` writes the deck.** Every favourite that has a plate, one slide per
  plate per marker, split down the middle by treatment, DAPI stripped, downloaded
  as a `.pptx`. It is the only button here that reads the group key, and the only
  one that produces a figure rather than a record - see the Shotgun section at the
  foot of the page script for why that is a declared exception to blinding. With
  no `groups` block in `config.json` it is disabled and says so.

  **`By region` writes the same deck cut the other way** - one slide per atlas
  REGION rather than per plate. A section appears on every region it carries an
  ROI for, so it appears more than once, and a favourite carrying no seeded ROI
  does not appear at all: the grouping comes from the seeds the ROIs answer,
  which is the same thing `roi_regions.csv` reports. Use it to compare one region
  across animals; use `Shotgun` to compare one level.

  **`f` marks a section favourite** - the subset worth carrying into actual
  quantification. It is orthogonal to the plate assignment, because a section can
  be worth quantifying before anyone has landmarked it, so it sets no other flag
  and is reported on its own. "favourites only" narrows the strip to that subset.

  **The plate and the section step independently.** The up/down arrows move
  through sections and leave the plate where it is; left/right moves the plate.
  Consecutive sections are at neighbouring levels, so the plate rarely needs to
  move more than a notch. Arrows move, letters act: `a` assign, `f` favourite,
  `x` exclude, `z` undo a point, `r` restore the original tilt. `x` was
  previously "next section", paired with `z`; the arrows do that now.
  Returning to a section that was already assigned or landmarked does show its
  own plate again, because that is a recorded decision rather than a position.

  **Nothing is warped onto the section.** Warping every seed through the fit and
  drawing them was tried and removed: ten placed ROIs produced thirty on screen
  and twenty-seven in the export, and the seventeen nobody had touched were
  extrapolation that looked like measurement. The check the overlay used to
  provide is now the residual per landmark, shown for each one so a mis-clicked
  pair is visible as a large error rather than quietly degrading the fit.

Regions, drawn rather than sampled
----------------------------------

  A region carries several seeds per lobe - Dl 142 over its plates, Dm 114 - and
  placing a small disc on each measures those discs, not the region. **`Region`
  mode draws the region itself.** Click its shape on the plate to say which one
  you are drawing, then click out the outline on the section, corner by corner;
  the first vertex, Enter or a double-click closes it.

  The plate shows each region as a HULL of its own seeds, one per lobe, so there
  is a shape to answer rather than a scatter of dots to infer one from. The hulls
  are convex and computed in `region_hulls` below - splitting a region's seeds
  before hulling them is the load-bearing part, because these regions are
  bilateral and a hull over both lobes spans the midline gap, which is the same
  failure `04f_exclusion_candidates.py` records for section solidity.

  **A polygon claims the seeds it encloses.** Their pairs stay landmarks - the
  fit wants every one of them, and nothing about placing them changed - but they
  stop being ROIs of their own, because the region drawn over them already
  measures that tissue. Exporting both would count the same nuclei twice.

Scope, deliberately bounded
---------------------------

**Vd, Vv and POA are not separable here.** A telencephalic section is
recognisable as telencephalon, but how far rostral or caudal it sits is not
readable from the section itself, and those three ventral regions occupy
overlapping positions across that range (Vd/Vv on plate_011-015, POA on
plate_020-025). A seed landing on one of them is evidence of "one of these
three", not of that region specifically, so the overlay and the summary show the
group and `roi_regions.csv` carries `region_ambiguous` and `ambiguity_group`
(and `region_uncertain_in_atlas`, for the eight seeds the atlas itself marks "??")
beside the atlas's own label. The label itself is never overwritten - pooling
them stays the reader's decision.

**31 of the 64 plates carry region seeds** - 362 seeds over 13 regions:
telencephalon and POA on plate_009 to plate_025 (Dl 142, Dm 114, Vv 16, POA 16,
Vd 10, Vl 10, Vs 4, Vc 4), the tuberal set on plate_038 to plate_044 (Nucleus
Anterior tuberal 10, Nucleus Lateral tuberal 10, Nucleus Posterior Tuberal 8,
Migrated posterior tuberal nucleus 4), then Rm on plate_051 to plate_057 (14).
A section assigned to any other plate has no regions to receive, so the tool
marks those plates and there is no reason to place landmarks on such a section.

The tuberal four arrived with the 2026-09 atlas, which also dropped the label
"Posterior tuberculum" that used to sit on those levels. Names are carried
exactly as the atlas writes them, long ones included - the curator groups and
orders by them, it does not parse them.

Affine below six points, thin-plate spline above
------------------------------------------------

Three or more pairs determine an **affine** by least squares. From **six** pairs
the tool switches to a **thin-plate spline**, and the header says which is live.

The gate is the whole argument. A TPS interpolates its landmarks *exactly*, so
its residual is zero by construction and tells you nothing; with 3-4 points it
would fit them perfectly and invent deformation everywhere else from almost no
evidence. From six well-spread points the interpolation is constrained by enough
real correspondences to be worth having - and an affine genuinely cannot follow
the local distortion that sectioning and mounting put into a slice, which is why
BigWarp and VisuAlign both use a TPS for exactly this task.

So: read the residual while it is an affine, and read the **overlay** once it is a
spline. `04e_register_elastix.py` remains available for an automatic B-spline
refinement once a plate assignment is trusted.

**The plate is shown in its ORIGINAL form, not reformatted.** The seeds are
recorded as fractions of the original plate, so using the original avoids
carrying them through the reformat's rotate-crop-pad-resize chain - a transform
that `04e` notes is not invertible from the index alone.

Three outputs, because there are three separable decisions
----------------------------------------------------------

`roi_plates.csv`     one row per section the operator has *touched*, with its
                     plate and a `status` of `registered` (3+ landmarks),
                     `plate_only` (plate chosen, not landmarked), `no_roi`
                     (deliberately marked as having nothing to measure) or
                     `excluded`.
`roi_landmarks.csv`  every landmark pair, with its residual - blank where there
                     is no fit to measure one against.
`roi_regions.csv`    one row per ROI actually placed, in the section's
                     reformatted frame, with the radius it was placed at.
                     Nothing here is positioned by the transform. `roi_kind`
                     separates the real ROIs from the background discs, which
                     carry identical columns because everything downstream
                     measures them identically.

**A plate assignment is a judgement in its own right.** An earlier version wrote
nothing for a section with fewer than three landmarks, which discarded exactly
the case where the operator had looked at a section and decided it was not worth
landmarking. `assigned` is set only by a real slider move or an explicit button -
never by merely selecting a section - so an untouched section still says
nothing.

Both channels live in ONE page. pERK and PCNA are separate physical sections cut
at different times and are curated independently - the channel selector next to
the sample selector switches between them, and every decision, count and export
row carries the channel it was made on. What they share is the tool and the atlas
plates, never a judgement: nothing about a pERK section reaches its PCNA partner.

The subset flags below are pERK subsets and say nothing about a PCNA section
(`--analysis-set` is defined by clipped-pixel censoring measured on the pERK
scans; `--worklist` is keyed on pERK uids). They therefore narrow the pERK side
only, and PCNA is offered on its own full set in the same page.

Run:  python 04l_roi_curator.py
      python 04l_roi_curator.py --rgb --worklist
      python 04l_roi_curator.py --animal LS45
"""

import sys
import argparse
import csv
import importlib.util
import json
import math
import os

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
import ls_config as LC  # noqa: E402
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402

OUT_ROOT = CONFIG["out_root"]
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
ANALYSIS_CSV = os.path.join(REFORMAT_DIR, "perk_analysis_set.csv")
PERK_MAP_CSV = os.path.join(REFORMAT_DIR, "perk_overrides.csv")
WORKLIST_CSV = os.path.join(REFORMAT_DIR, "roi_worklist.csv")

# Regions that cannot be told apart without knowing the rostrocaudal level.
# A telencephalic section is recognisable as telencephalon, but how far front or
# back it sits is not readable from the section itself - and these three ventral
# regions occupy overlapping positions across that range (Vd/Vv on plate_011 to
# plate_015, POA on plate_020 to plate_025). A seed landing on one of them is
# therefore evidence of "one of these three", not of that specific region.
#
# The atlas's own label is kept unchanged; the group is carried alongside it, so
# nothing is lost and pooling stays the reader's decision rather than being baked
# in here.
AMBIGUOUS_GROUPS = [("Vd", "Vv", "POA")]
REGION_GROUP = {r: "/".join(g) for g in AMBIGUOUS_GROUPS for r in g}
# The canonical reformatted frame every stored coordinate is expressed in. 04o may
# render the picture larger; the curator divides that back out on export.
SEC_GRID = 256

# COL_BAND / COL_SPAN group the seeds of a plate into the vertical strips the
# click-through order runs down; see the long note at their use in `main`. They
# live up here because the region hulls below reuse COL_SPAN, and a reader has
# to be able to see that the two thresholds are deliberately the same number
# rather than two guesses that happen to agree.
COL_BAND, COL_SPAN = 0.08, 0.12

# A region on one plate is not one blob, and hulling it as though it were is the
# mistake this constant exists to stop. These regions are BILATERAL: a hull over
# all of Dl's seeds spans the midline gap and draws a single band across the
# whole brain. `04f_exclusion_candidates.py` documents the identical failure for
# section solidity - "two bilaterally separated lobes ... its hull spans the
# midline gap" - and rejected the metric over it. So a region's seeds are SPLIT
# before they are hulled, and each part is hulled on its own.
#
# The split is a gap in x at COL_SPAN, reused rather than invented. That value is
# already tuned to sit between the two real scales: wide enough to hold a strip
# that drifts sideways as it descends (the left lateral arc on plate_013 runs
# x = 0.05 -> 0.13), narrow enough that a strip cannot chain across the midline
# and swallow its bilateral partner (plate_013's partners sit at 0.05 and 0.94).
# That is exactly the discrimination a lobe split needs.
#
# EVERY gap over the threshold cuts, not only the widest: nothing says a region
# has exactly two parts, and a midline structure like POA has one.
LOBE_GAP = COL_SPAN


def load_seeds(plate_dir=None):

    """Every plate's region seeds, numbered in the fixed click-through order.

    Factored out of `main` so the atlas region tracer (`04a5_atlas_regions.py`)
    reads them the same way the curator does. Seed 4 has to be the same seed in
    both tools and in every export, and a second copy of the ordering rule would
    be a second chance to disagree.
    """
    seeds = {}
    path = os.path.join(plate_dir or PLATE_DIR, "seeds.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        for s in csv.DictReader(fh):
            seeds.setdefault(s["plate_id"], []).append(
                # TWO different uncertainties, and they are not the same thing.
                # `amb` is ours: Vd/Vv/POA cannot be told apart without knowing
                # the section's rostrocaudal level, so the group is shown instead
                # of a name the data cannot support. `unk` is the ATLAS's own -
                # eight seeds are labelled "Rm (Raphe) ??" in the source, and
                # dropping that flag here made the tool report them as settled.
                {"region": s["region"], "amb": REGION_GROUP.get(s["region"], ""),
                 "unk": 1 if s.get("is_unknown") == "1" else 0,
                 "xf": float(s["x_frac"]), "yf": float(s["y_frac"]),
                 "hex": s.get("colour_hex") or "#4da3ff"})
    for lst in seeds.values():
        number_seeds(lst)
    return seeds


def number_seeds(lst):
    """Set `n` on one plate's seeds, in place, in the click-through order.

    A FIXED order, decided here rather than in the page, so that "seed 4" is the
    same seed in the tool, in every export and in a re-run. seeds.csv is in
    extraction order, which is arbitrary and puts bilateral partners far apart.
    Reading order - down the plate, left to right within a row - can be followed
    by eye.

    The rows have to be FOUND, not rounded to a grid. Seeds on one visual row sit
    at y values ~0.001 apart (0.2329, 0.2338, 0.2347 on plate_013) while real
    rows are ~0.02 apart, so any fixed rounding either splits a row or merges
    two. Splitting a row is the damaging one: the x tiebreak never fires, and the
    order zigzags across the midline - 0.39, 0.05, 0.60, 0.94 - which is exactly
    the thing a fixed order is supposed to stop. So rows are grown greedily by
    gap, at a threshold between the two scales.

    Left to right every row, not serpentine. Serpentine is 14% less travel and
    costs more than it saves: these regions are bilateral, and alternating the
    direction flips which hemisphere the next seed is in on every row. COLUMNS,
    top to bottom, starting from the left. Not rows: these seeds run in vertical
    strips - a lateral arc down each side and a medial strip either side of the
    midline - and reading across rows cut every strip into fragments, so
    consecutive numbers landed on opposite sides of the brain. Down a column the
    next number is the next seed in the same structure.

    COL_BAND has to be wide enough to hold a strip that drifts sideways as it
    descends: the left lateral arc on plate_013 runs x = 0.05, 0.04, 0.07, 0.13
    while y goes 0.23 -> 0.50. At 0.02 that arc fragments into four one-seed
    "columns" (74% of all columns were single); at 0.08 plate_013 resolves into
    the six strips actually present and 22% are single. COL_SPAN caps a column's
    total width as well as the step between neighbours, so a strip drifting
    steadily sideways cannot chain across the midline and swallow its bilateral
    partner. Both live at module level, because `region_hulls` splits a region's
    lobes at that same COL_SPAN.
    """
    if not lst:
        return lst
    lst.sort(key=lambda s: (s["xf"], s["yf"]))
    cols, cur = [], [lst[0]]
    for s in lst[1:]:
        if (s["xf"] - cur[-1]["xf"] > COL_BAND
                or s["xf"] - cur[0]["xf"] > COL_SPAN):
            cols.append(cur); cur = [s]
        else:
            cur.append(s)
    cols.append(cur)
    lst[:] = [s for col in cols for s in sorted(col, key=lambda s: s["yf"])]
    for i, s in enumerate(lst, 1):
        s["n"] = i
    return lst


def convex_hull(pts):

    """Monotone-chain hull of (x, y) pairs, no repeated closing point.

    Written out rather than imported. This runs wherever the page is generated
    and is emitted as page data, and pulling scipy in for eight points would be
    the only reason this stage needed it at all.

    CONVEX, not concave, and that is a limit of the data rather than a
    preference: a lobe of Dl carries a handful of seeds, and a concave hull over
    three points is noise dressed as anatomy.

    Fewer than three points is not an error - Vs and Vc carry four seeds in the
    entire atlas - so a part of one or two comes back as itself and the page
    draws a dot or a segment. Collinear points collapse to the two ends for the
    same reason.
    """
    p = sorted(set((float(a), float(b)) for a, b in pts))
    if len(p) < 3:
        return [list(q) for q in p]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for q in p:
        while len(lower) > 1 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper = []
    for q in reversed(p):
        while len(upper) > 1 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return [list(q) for q in lower[:-1] + upper[:-1]]


def region_hulls(sd):
    """One hull per (region, part) on a plate, built from that plate's own seeds.

    This is what the atlas pane draws a region as, instead of leaving the reader
    to infer the region's extent from a scatter of numbered dots. `sd` is the
    plate's seed list, already numbered by the click-through order.

    Vertices are FRACTIONS of the plate image, exactly as the seeds are, so the
    plate can keep being shown in its original unreformatted form and nothing
    here needs a transform.
    """
    by_region = {}
    for s in sd:
        by_region.setdefault(s["region"], []).append(s)
    out = []
    for region in sorted(by_region):
        grp = sorted(by_region[region], key=lambda s: s["xf"])
        parts, cur = [], [grp[0]]
        for s in grp[1:]:
            if s["xf"] - cur[-1]["xf"] > LOBE_GAP:
                parts.append(cur)
                cur = [s]
            else:
                cur.append(s)
        parts.append(cur)
        for i, part in enumerate(parts, 1):
            out.append({
                "region": region,
                # Both uncertainties belong to the seeds, so a hull inherits
                # them rather than inventing its own. `amb` is the same for
                # every seed of a region by construction. `unk` is true if ANY
                # seed under the hull is one the atlas marked "??" - a part
                # holding an uncertain seed is not a settled part.
                "amb": part[0]["amb"],
                "unk": 1 if any(s["unk"] for s in part) else 0,
                "hex": part[0]["hex"],
                "part": i, "n_parts": len(parts),
                "seeds": sorted(s["n"] for s in part),
                "v": [[round(x, 6), round(y, 6)] for x, y in
                      convex_hull([(s["xf"], s["yf"]) for s in part])],
            })
    # THE ROI NUMBER. An ROI is an area, and this is its identity on the plate:
    # one number per region per lobe, carried by every seed under it, so the
    # atlas reads "ROI 1, ROI 2, ROI 3" instead of "seed 1 ... seed 30".
    #
    # Ordered by the group's LOWEST seed, which makes the ROI order the same
    # traversal `number_seeds` already establishes - down each column, columns
    # left to right - rather than a second, alphabetical one nobody asked for.
    # On plate_013 that runs Dl-left, Dm-left, Vd, Vv, Vl, then across the
    # midline and back to Dl-right.
    #
    # The seeds keep their own `n`. Only the DISPLAYED number becomes the ROI's,
    # because `P.seeds[n-1]` is how three places resolve a number back to a seed
    # and the operator's store holds 268 sections whose pairs carry the old
    # per-seed numbers. Renumbering the seeds themselves would re-label every one
    # of them through a scheme with a third as many values, and nothing would
    # error.
    out.sort(key=lambda h: min(h["seeds"]))
    for i, h in enumerate(out, 1):
        h["roi"] = i
    return out


def tag_rois(sd, hulls):
    """Write each seed's ROI number onto it, from the hulls just computed.

    Separate from `region_hulls` on purpose. Having the hull builder quietly
    mutate the list it was handed would mean a caller that only wanted the hulls
    changed the seeds as a side effect, and a caller that wanted the numbers had
    to know to call it first. Here the dependency is one visible line.
    """
    roi_of = {n: h["roi"] for h in hulls for n in h["seeds"]}
    for s in sd:
        s["roi"] = roi_of.get(s["n"], 0)
    return sd


def marker_paths(marker):
    """Index and image directory for a marker, mirroring `04a_reformat`."""
    if marker == "AF568":
        return (os.path.join(REFORMAT_DIR, "reformat_index_AF568.csv"), "sections_AF568")
    return (os.path.join(REFORMAT_DIR, "reformat_index.csv"), "sections")


def analysis_uids(marker):
    """The pERK sections that survived clipped-pixel censoring - the 454.

    pERK only, and deliberately. The analysis set is defined by clipped-pixel
    censoring measured on the pERK scans, so it says nothing about a PCNA
    section; deriving a PCNA subset by following the pairing would make one
    channel's curation depend on the other's, and they are separate physical
    sections cut at different times. PCNA is curated on its own full set.
    """
    if marker != "AF568":
        raise SystemExit(
            "--analysis-set is a pERK subset (clipped-pixel censoring is measured on "
            "the pERK scans) and does not define a PCNA one.\n"
            "Run PCNA without it: python 04l_roi_curator.py --marker AF488")
    with open(ANALYSIS_CSV, newline="", encoding="utf-8") as fh:
        perk = {r["scene_uid"] for r in csv.DictReader(fh) if r["in_analysis_set"] == "1"}
    return perk, len(perk), 0
# Which plate set to use, from config. The two sets reuse the same plate_NNN
# names for different images, so this must not be hard-coded in two places.
PLATE_SET = CONFIG.get("atlas_plate_set", {}).get("dir", "plates")
PLATE_DIR = os.path.join(OUT_ROOT, "atlas", PLATE_SET)
CURATOR_HTML = os.path.join(REFORMAT_DIR, "roi_curator.html")
# Where exports are filed. Config so the app and this stage cannot disagree
# about it; one dated folder per export is created inside it.
EXPORT_DIR = LC.export_dir(CONFIG)
PROVENANCE_CSV = os.path.join(REFORMAT_DIR, "section_provenance.csv")

# The Review mode needs one row per SCANNED section - 2,572, against the ~1,242
# the rest of the page carries - so the fields are chosen and the rows are
# emitted as ARRAYS under a shared header rather than as objects. Per-object
# keys would repeat 22 field names 2,572 times and roughly double the page for
# nothing. A separate JSON fetched at load is not an option: `fetch()` is
# refused under file://, which is how this page is often opened.
PROV_FIELDS = [
    "scene_uid", "animal", "marker", "slide", "section_order", "czi_file",
    "scene_index", "status", "decision", "exclusion_class", "decision_reason",
    "proposed_excluded", "tissue_area_mm2", "focus_score", "largest_mm2",
    "n_artifact_objects", "artifact_pct_of_tissue", "in_analysis_set",
    "censored_fraction_in_tissue", "censor_reason",
    "has_overview", "has_section", "has_section_rgb", "has_section_thumb",
    "has_mask", "has_censor", "has_tissue",
    "n_rois", "n_nuclei",
]

# Columns whose values repeat across thousands of rows. "manually excluded:
# tissue too damaged to measure" alone appears 789 times, and there are 222
# distinct CZI files across 2,572 sections. Each of these becomes an index into
# a per-column list. Measured: 773 KB -> 393 KB, which on a page that was 378 KB
# is the difference between a nuisance and a problem.
PROV_POOLED = ("animal", "marker", "slide", "czi_file", "status", "decision",
               "exclusion_class", "decision_reason", "censor_reason")


def load_provenance():
    """`04p_section_provenance.py`'s table, compacted for embedding.

    `{"f": fields, "p": {field: [distinct values]}, "r": [[values]...]}` - rows
    are arrays under a shared header, and pooled columns carry an index into `p`
    instead of the string. Objects per row would repeat 24 field names 2,572
    times; see PROV_POOLED for the rest.

    **The three image paths are NOT carried.** They are a fixed function of the
    uid, animal and marker, and at ~110 bytes each over 2,572 rows they were
    275 KB - a third of the table - to say something the page can derive. What
    IS carried is whether each file exists, which is the part that cannot be
    derived. The naming rule therefore lives in two places, here and in
    `revSrc()`; it is one line in each and it is stated in both.

    Empty when 04p has not been run: the Review button then explains itself and
    the rest of the page is unaffected.
    """
    if not os.path.exists(PROVENANCE_CSV):
        return {"f": PROV_FIELDS, "p": {}, "r": []}
    with open(PROVENANCE_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    for r in rows:
        r["has_overview"] = 1 if r.get("overview_img") else 0
        r["has_section"] = 1 if r.get("section_img") else 0
        # Separate from has_section on purpose: all 2,572 have a greyscale
        # section image, only the 1,506 reformatted ones have a composite.
        r["has_section_rgb"] = 1 if r.get("section_rgb") else 0
        r["has_section_thumb"] = 1 if r.get("section_thumb") else 0
        r["has_mask"] = 1 if r.get("mask_img") else 0
        # WHETHER the file exists, never which marker. 04j was AF568-only while
        # it read the 8-bit _MARK.png; reading the raw data lifted that and both
        # channels have censor masks now, so a marker test is already wrong.
        r["has_censor"] = 1 if r.get("censor_img") else 0
        r["has_tissue"] = 1 if r.get("tissue_img") else 0

    pool, index = {}, {}
    for k in PROV_POOLED:
        vals = sorted({r.get(k, "") for r in rows})
        pool[k] = vals
        index[k] = {v: i for i, v in enumerate(vals)}
    out = []
    for r in rows:
        out.append([index[k][r.get(k, "")] if k in index else r.get(k, "")
                    for k in PROV_FIELDS])
    return {"f": PROV_FIELDS, "p": pool, "r": out}

# THE GROUP KEY, and the only place in this pipeline before 06b that reads one.
# It exists for the Shotgun deck and reaches nothing else - not a count, not a
# threshold, not a curation decision. `blinding._note` in config.json forbids
# reading a group label this early; this is the declared exception to it, and it
# is opt-in: with `groups` absent or empty the page ships with the button
# disabled and no key in it. Everything else the curator does is unchanged
# whether the key is there or not.
#
# Dropped entirely rather than passed through empty-valued: an animal listed
# with a blank treatment is an animal nobody has assigned yet, and guessing at
# it would put a made-up group on a figure.
_GROUPS_RAW = CONFIG.get("groups", {}) or {}
GROUPS = {
    "order": [g for g in _GROUPS_RAW.get("order", []) if g],
    "by_animal": {a: g for a, g in (_GROUPS_RAW.get("by_animal", {}) or {}).items()
                  if g and not a.startswith("_")},
}

PAGE = """<!doctype html>
<meta charset="utf-8"><title>ROI curator</title>
<style>
:root{--bg:#14161a;--fg:#e8e8ea;--dim:#9aa0a8;--line:#2a2f37;--accent:#4da3ff;
      --ok:#3fb950;--warn:#d29922;--done:#7c5cff}
*{box-sizing:border-box}
/* The whole tool is one screen. body is a flex column, the panes take what is
   left, and only the side card and the strip scroll - inside themselves. */
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;
     display:flex;flex-direction:column;overflow:hidden}
header{flex:0 0 auto;background:var(--bg);border-bottom:1px solid var(--line);
       padding:7px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}.grow{flex:1}
.row{color:var(--dim)}.row b{color:var(--fg)}
button,select{background:#1c2027;color:var(--fg);border:1px solid var(--line);border-radius:7px;
       padding:6px 10px;cursor:pointer;font:inherit}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#04121f;font-weight:600}
#panes{flex:1 1 auto;min-height:0;display:grid;grid-template-columns:1fr 1fr 250px;
       grid-template-rows:minmax(0,1fr);gap:10px;padding:10px}
.pane{position:relative;background:#0e1014;border:1px solid var(--line);border-radius:9px;
      overflow:hidden;min-width:0;min-height:0}

/* Step buttons on each pane. Absolute over the canvas so they cost no layout,
   dim until pointed at so they do not compete with the tissue, and skipped by
   the tab order because the keyboard already has the same moves on the arrows.
   z-index above the h2 so the left one is not swallowed by the title. */
.nav{position:absolute;top:50%;transform:translateY(-50%);z-index:4;
     width:34px;height:54px;border-radius:8px;border:1px solid var(--line);
     background:rgba(14,16,20,.55);color:var(--dim);font:600 20px system-ui;
     cursor:pointer;opacity:.45;transition:opacity .12s,border-color .12s,color .12s;
     display:flex;align-items:center;justify-content:center;padding:0}
.pane:hover .nav{opacity:.9}
.nav:hover{border-color:var(--accent);color:var(--accent);opacity:1}
.nav:disabled{opacity:.12;cursor:default;border-color:var(--line);color:var(--dim)}
.nav.l{left:6px} .nav.r{right:6px}
.pane h2{position:absolute;top:6px;left:8px;margin:0;font-size:11px;color:var(--dim);
         z-index:3;pointer-events:none;text-shadow:0 0 6px #000}
canvas{display:block;width:100%;height:100%;object-fit:contain;cursor:crosshair;
       user-select:none;-webkit-user-drag:none}
#cSec.rotmode{cursor:ew-resize}
#cSec.bgmode{cursor:crosshair;outline:3px solid #f778ba;outline-offset:-3px}
.btn-bg{border-color:#8b3d6b;color:#f778ba}
.btn-bg:hover{border-color:#f778ba;color:#f778ba}
.bg-on{border-color:#f778ba !important;background:#33132a;color:#ffb3d9 !important}
/* Region mode. Green rather than pink, and matching the armed hull's ring on
   the plate, so the two panes say the same thing about which mode is live. */
#cSec.regionmode{cursor:crosshair;outline:3px solid #3fb950;outline-offset:-3px}
.btn-region{border-color:#2d6a3e;color:#7ee787}
.btn-region:hover{border-color:#3fb950;color:#7ee787}
.reg-on{border-color:#3fb950 !important;background:#10261a;color:#7ee787 !important}
#cSec.rotating{cursor:ew-resize}
button[disabled]{opacity:.4;cursor:default}
button[disabled]:hover{border-color:var(--line)}
#side{display:flex;flex-direction:column;gap:9px;min-height:0;overflow-y:auto}
.card{border:1px solid var(--line);border-radius:9px;padding:9px;background:#0e1014}
.card h3{font-size:11px;margin:0 0 5px;color:var(--dim);font-weight:600;letter-spacing:.04em}
.kv{font-size:12px;color:var(--dim)}.kv b{color:var(--fg)}
input[type=range]{width:100%}
.unlab{color:var(--warn);font-size:11px}
.lab{color:var(--ok);font-size:11px}
#lmlist{font:11px ui-monospace,monospace;color:var(--dim);max-height:130px;overflow-y:auto}
#lmlist div{display:flex;justify-content:space-between}
#lmlist .bad{color:#ff6b5e}
#strip{flex:0 0 auto;display:flex;gap:4px;overflow-x:auto;overflow-y:hidden;
       padding:7px 14px;border-top:1px solid var(--line);background:#101318}
/* The strip is where the sections would have been, so it is where the reason
   they are not belongs. Sized like a cell so the bar does not collapse. */
#strip .empty{flex:1 1 auto;display:flex;align-items:center;min-height:74px;
              color:var(--warn);font-size:13px;padding:0 4px}
#strip .empty b{color:var(--fg)}
.cell{flex:0 0 auto;width:74px;border:2px solid var(--line);border-radius:6px;padding:2px;
      background:#0e1014;cursor:pointer;user-select:none}
.cell:hover{border-color:var(--accent)}
/* Three times the resting border. The strip is scanned at a glance while the
   eye is really on the section, and a 2px accent edge is not enough to find
   your place in sixty near-identical thumbnails - especially once done,
   plate-only and excluded are all colouring their borders too. box-sizing is
   border-box globally, so the cell keeps its 74px and the strip does not
   reflow as the selection moves. */
.cell.active{border-color:var(--accent);border-width:6px;
             box-shadow:0 0 0 2px rgba(77,163,255,.35)}
.cell.done{border-color:var(--done);background:#141026}
.cell.plateonly{border-color:var(--accent);background:#0d1520}
.cell.noroi{border-color:#3a3f47;opacity:.55}
.cell.fav{box-shadow:inset 0 0 0 2px #e3b341}
.fav-on{border-color:#e3b341 !important;color:#e3b341}
.mode-on{border-color:var(--accent) !important;color:var(--accent)}
/* Resting colour by function, so the toolbar reads at a glance without text:
   plate assignment, the rotation-tool group, the two per-section decisions
   (each already escalates to a brighter/filled state on toggle - fav-on and
   the inline no-roi green above - so this is deliberately the dimmer resting
   shade of the same hue, not a competing colour), and point editing. Export
   stays .primary: solid fill is its own category, the single confirming action. */
.btn-plate{border-color:#3d6d99;color:#7fb8f0}
.btn-plate:hover{border-color:var(--accent);color:var(--accent)}
.btn-rot{border-color:#6e4d99;color:#bc8cff}
.btn-rot:hover{border-color:#bc8cff;color:#bc8cff}
.btn-fav{border-color:#8a7326;color:#e3b341}
.btn-fav:hover{border-color:#e3b341;color:#e3b341}
.btn-excl{border-color:#8a5a2e;color:#f0883e}
.btn-excl:hover{border-color:#f0883e;color:#f0883e}
.btn-kill{border-color:#8a2f36;color:#f85149}
.btn-kill:hover{border-color:#f85149;color:#f85149}
.kill-on{border-color:#f85149 !important;background:#3d1417;color:#ff9d96 !important}
/* Anchored to the window rather than the pane: it is a decision about the pair,
   not about the picture underneath it, and it must stay put when the section
   pane resizes between a 3-column and a 4-column layout. */
.cell.excl{border-color:#f85149;opacity:.5}
.cell.excl img{filter:grayscale(1)}
/* Reinstated in Review mode: curatable now, but NOT in the index until 04a runs
   again, so it must not look like an ordinary section that was always there. */
.cell.reinstated{border-color:#3fb950;border-style:dashed;opacity:1}
.cell.reinstated img{filter:none}
/* The seeds are drawn in the atlas's own colours on both panes, so the key has
   to use those same colours - reading it off the seed rather than a table here
   is what keeps the two from ever disagreeing. */
#regKey{margin-top:7px;display:flex;flex-direction:column;gap:3px}
#regKey div{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--dim)}
#regKey i{width:11px;height:11px;border-radius:50%;border:1px solid #000;
          flex:0 0 auto;display:inline-block}
#regKey b{color:var(--fg);font-weight:600}
.btn-guide{border-color:#2ea043;color:#3fb950}
.btn-guide:hover{border-color:#3fb950;color:#3fb950}
.guide-on{border-color:#3fb950 !important;background:#0f2e18;color:#7ee787 !important}
.btn-edit{border-color:#2c7a82;color:#39c5cf}
.btn-edit:hover{border-color:#39c5cf;color:#39c5cf}
/* Its own colour because it is the only button that writes a DELIVERABLE rather
   than recording a decision - and the only one that reads the group key. */
.btn-shot{border-color:#7a5c2e;color:#e8a33d}
.btn-shot:hover{border-color:#e8a33d;color:#e8a33d}
/* Disabled, but never FAINT. This button spends most of its life disabled -
   a page opened from disk cannot build a deck at all, which is the normal way
   this file gets opened - and under the global button[disabled]{opacity:.4} it
   went grey at 40% on a dark header and read as absent rather than
   unavailable. It was reported as "not visible" twice, and both times it was
   there. It keeps its amber now, one step down, and says why beside itself. */
.btn-shot:disabled{opacity:1;border-color:#6b5326;color:#c98f31;background:#1a1610;
                   cursor:not-allowed}
.btn-shot:disabled:hover{border-color:#6b5326;color:#c98f31}
label.chk{color:var(--dim);font-size:12px;display:flex;align-items:center;gap:4px;cursor:pointer}
/* The header wraps, and with a dozen counters between them the buttons used to
   break across lines in whatever order the width happened to allow. Filters and
   actions are each one flex box now, so they wrap as a UNIT: what narrows the
   view sits by the sample selector, what acts on a section sits by Export. */
.filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap;
         padding:3px 8px;border:1px solid var(--line);border-radius:8px;background:#12151a}
.actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-left:auto}
/* The two buttons that write a FILE, bound together so they cannot be split.
   `.actions` wraps, and Shotgun was last in it: at 1280 CSS px - which is what a
   1920 screen gives at the 150% scaling Windows commonly ships with - it broke
   onto a new row on its own and landed at the far LEFT, a lone amber button
   with nothing near it and no longer beside the Export it belongs with. It was
   on screen and might as well not have been.

   nowrap keeps the pair on one line; the pair still wraps as a unit, which is
   the same rule .filters and .actions already follow. */
.deliver{display:flex;gap:6px;align-items:center;flex-wrap:nowrap}
/* The export target, beside the button that changes it. Truncated rather than
   wrapped: this row must stay one line, and a long path is not worth the
   header growing a second one. */
.expdir{font-size:11px;opacity:.75;max-width:150px;overflow:hidden;
        text-overflow:ellipsis;white-space:nowrap}
#expStat{font-size:11px;opacity:.75}
.cell img{width:100%;aspect-ratio:1;object-fit:contain;display:block;border-radius:3px}
.cap{font-size:9px;color:var(--dim);text-align:center;line-height:1.15;margin-top:1px}
footer{flex:0 0 auto;background:var(--bg);border-top:1px solid var(--line);
       padding:6px 14px;font-size:12px;color:var(--dim)}
kbd{display:inline-block;padding:1px 5px;border:1px solid var(--line);border-radius:4px;
    background:#1c2027;font:600 11px ui-monospace,monospace}

/* ---- Review mode ------------------------------------------------------- */
/* The cell vocabulary is 04d_rotation_curator's, deliberately unchanged: a
   DASHED amber border is a proposal the program made, a SOLID red one is a
   decision a person made. The operator already reads those two borders that
   way, and inventing a second language for the same distinction would be the
   worse choice even though this is a different page. */
#review{flex:1 1 auto;display:none;min-height:0;overflow:hidden}
#review.on{display:flex}
#revGrid{flex:1 1 auto;overflow:auto;padding:8px 10px}
#revSide{flex:0 0 380px;border-left:1px solid var(--line);overflow:auto;padding:10px}
.revGroup{margin-bottom:14px}
.revGroup h4{margin:0 0 5px;font:600 11px ui-monospace,monospace;color:var(--dim);
             letter-spacing:.06em;position:sticky;top:0;background:var(--bg);padding:3px 0;z-index:1}
.revCells{display:grid;grid-template-columns:repeat(auto-fill,minmax(78px,1fr));gap:5px}
.rc{position:relative;border:2px solid var(--line);border-radius:4px;overflow:hidden;
    cursor:pointer;background:#0f1216}
.rc img{width:100%;aspect-ratio:1;object-fit:contain;display:block}
.rc .n{position:absolute;left:2px;top:1px;font:600 9px ui-monospace,monospace;
       color:#c9d1d9;text-shadow:0 0 3px #000}
.rc.sel{border-color:#7c5cff;box-shadow:0 0 0 2px rgba(124,92,255,.35)}
.rc.excluded{border-color:#c0392b;background:#1c1010}
.rc.excluded img{opacity:.32;filter:grayscale(1)}
.rc.proposed{border-style:dashed;border-color:var(--warn)}
.rc.measured{border-color:#3fb950}
.rc.censored{border-color:#e3b341}
.rc .flag{position:absolute;right:2px;bottom:1px;font:700 8px ui-monospace,monospace;
          padding:0 3px;border-radius:2px}
.rc .flag.rs{background:#1f6feb;color:#fff}
.rc .flag.dr{background:#c0392b;color:#fff}
.rc .flag.um{background:#8957e5;color:#fff}
#revImg{width:100%;border:1px solid var(--line);border-radius:4px;background:#000;
        display:block;aspect-ratio:1;object-fit:contain}
#revImgWrap{position:relative}
/* THE OVERLAYS ARE DRAWN, NOT BLENDED.
   The first version stacked the mask PNGs with mix-blend-mode. `screen` is
   invisible over bright tissue - and artifacts are BY DEFINITION the brightest
   pixels in the section, so it failed exactly where it was needed. `multiply`
   has the mirrored problem on dark background. No blend mode reads on both.
   So the two masks are now image SOURCES only, kept in the DOM so the browser
   loads and caches them, and a canvas composites them at a fixed opacity.
   Still no getImageData anywhere - that taints on a file:// page. */
#revMask,#revCensor,#revTissue{display:none}
#revOv{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
/* FULLSCREEN. The pane is ~320px wide and the overview is 1174x1632, so the
   detail image is shown at about a fifth of its resolution - fine for "which
   section is this", useless for "is that debris or tissue". The card goes
   fullscreen rather than the image alone so the channel and mask toggles come
   with it; looking closely is exactly when switching layers matters.

   aspect-ratio is dropped here: square is right for a side panel, and wrong
   for a screen. The canvas follows the image because it is inset:0 on the same
   wrapper, but its BACKING STORE is sized in drawRevOverlays from clientWidth,
   so entering and leaving fullscreen has to redraw - see revFull(). */
/* TWO MECHANISMS, ONE LOOK. The Fullscreen API is the nicer one - it hides the
   browser chrome too - but it is refused often enough to be useless on its own:
   a permissions-policy on an embedding viewer, or a page opened from file://,
   and requestFullscreen resolves having done nothing. So the class is what
   actually does the work and native fullscreen is a bonus layered on top. Both
   selectors carry the same rules so the two cannot drift. */
#revImgCard:fullscreen,#revImgCard.imgmax{background:#000;padding:10px;
        display:flex;flex-direction:column;gap:6px;box-sizing:border-box}
#revImgCard.imgmax{position:fixed;inset:0;z-index:9999;margin:0;border-radius:0;
        overflow:auto}
#revImgCard:fullscreen #revImgWrap,#revImgCard.imgmax #revImgWrap{
        flex:1 1 auto;min-height:0;display:flex}
#revImgCard:fullscreen #revImg,#revImgCard.imgmax #revImg{
        height:100%;width:100%;aspect-ratio:auto;border:0;object-fit:contain}
#revImgCard:fullscreen .deliver,#revImgCard.imgmax .deliver{
        flex:0 0 auto;justify-content:center}
#revFullBtn{margin-left:auto}
/* Stepping and reinstating live in other cards, which do not come along when
   the image card is maximised - so they are repeated here and shown only then.
   Hidden in the windowed layout on purpose: the same two controls a few
   centimetres apart is a worse page, not a more capable one. */
.fsonly{display:none}
#revImgCard:fullscreen .fsonly,#revImgCard.imgmax .fsonly{display:inline-flex;
        align-items:center;gap:6px}
#revImgCard:fullscreen #revFsPos,#revImgCard.imgmax #revFsPos{
        color:var(--dim);font:11px ui-monospace,monospace;min-width:74px;
        text-align:center}
.revChain{font:11px ui-monospace,monospace;line-height:1.5}
.revChain .st{display:flex;gap:6px;padding:3px 0;border-bottom:1px solid #1b1f26}
.revChain .st b{flex:0 0 96px;color:var(--dim);font-weight:600}
.revChain .st span{flex:1 1 auto;color:#c9d1d9;word-break:break-word}
.revChain .st.no b,.revChain .st.no span{color:#5b6270}
.revWhy{width:100%;box-sizing:border-box;margin:6px 0;padding:5px;border-radius:4px;
        border:1px solid var(--line);background:#0f1216;color:#e6e6e6;font:11px ui-monospace,monospace}
</style>
<header>
  <h1>ROI curator</h1>
  <span class="row" id="scope" style="color:#7c5cff"></span>
  <span class="filters">
    <select id="animal" onchange="render(); this.blur()"></select>
    <select id="marker" onchange="onMarker(); this.blur()"></select>
    <label class="chk"><input type="checkbox" id="favOnly" onchange="render(); this.blur()">favourites only</label>
    <label class="chk"><input type="checkbox" id="hideExcl" onchange="render(); this.blur()">hide excluded</label>
    <span class="row" style="margin-left:6px">bg disc <b id="roiSizeVal"></b> px</span>
    <input type="range" id="roiSize" min="2" max="60" step="1"
           title="Default radius for a background disc - the only thing still placed as a circle. Dragging as you place one still overrides it."
           oninput="onRoiSize(this.value)" onchange="this.blur()"
           style="width:90px;vertical-align:middle">
  </span>
  <span class="row"><b id="nsec"></b> shown</span>
  <span class="row" style="color:#7c5cff"><b id="ndone"></b> registered</span>
  <span class="row" style="color:#4da3ff"><b id="nassign"></b> plate only</span>
  <span class="row" style="color:#9aa0a8"><b id="nnoroi"></b> no ROI</span>
  <span class="row" style="color:#e3b341"><b id="nfav"></b> favourite</span>
  <span class="row" style="color:#f85149"><b id="nexcl"></b> excluded</span>
  <span class="row" id="savedAt" style="color:#3fb950"></span>
  <span class="row" id="seedOffer" style="display:none"></span>
  <span class="row" id="shotStat" style="color:#e8a33d"></span>
  <span class="row"><b id="npair"></b> pairs on this section</span>
  <span class="row" id="fit"></span>
  <span class="actions">
  <button class="btn-plate" onclick="markAssigned()">Assign plate</button>
  <button id="rotBtn" class="btn-rot" onclick="toggleRotMode()">Rotate</button>
  <button id="rotReset" class="btn-rot" onclick="restoreTilt()">Restore original tilt</button>
  <button id="favBtn" class="btn-fav" onclick="toggleFav()">Favourite</button>
  <button id="noroiBtn" class="btn-excl" onclick="toggleNoRoi()">No ROI here</button>
  <button id="exclBtn" class="btn-kill" onclick="toggleExcl()">Exclude</button>
  <button id="dapiBtn" class="btn-plate" onclick="toggleDapi()">DAPI</button>
  <button id="bgBtn" class="btn-bg" onclick="toggleBgMode()">Background</button>
  <button id="hullBtn" class="btn-region" onclick="toggleHulls()">Hulls</button>
  <button id="undoPolyBtn" class="btn-edit" onclick="undoPoly()">Undo region</button>
  <button id="guideBtn" class="btn-guide" onclick="toggleGuided()">Guided</button>
  <button id="skipBtn" class="btn-guide" onclick="skipRoi()">Skip ROI</button>
  <button class="btn-edit" onclick="undoPt()">Undo point</button>
  <button id="undoBtn" class="btn-rot" onclick="undoLast()" disabled
          title="Nothing to undo (u)">Undo</button>
  <button class="btn-edit" onclick="clearPts()"
          title="take back everything placed on this section - landmarks, an unfinished outline and the regions. u puts it back">Clear section</button>
  <span class="deliver">
    <button id="revBtn" class="btn-guide" onclick="toggleReview()">Review</button>
    <button id="expDirBtn" class="btn-edit" onclick="chooseExportDir()"
            title="pick the folder exports are written into">Folder...</button>
    <span id="expDirLbl" class="expdir"></span>
    <button class="primary" onclick="exportCsv()">Export</button>
    <button id="shotBtn" class="btn-shot" onclick="shotgun()">Shotgun</button>
    <button id="shotRegBtn" class="btn-shot" onclick="shotgun('region')">By region</button>
    <span id="expStat"></span>
  </span>
  </span>
</header>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
  <!-- LUMINANCE -> ALPHA. Canvas compositing reads alpha, and a greyscale mask
       PNG is opaque everywhere, so `source-in` kept the fill across the whole
       rectangle rather than only where the mask was set. This matrix copies the
       red channel into RGB and into A, which makes the stencil's alpha mean what
       its brightness means. sRGB so the values are not linearised first. -->
  <filter id="revLumAlpha" color-interpolation-filters="sRGB">
    <feColorMatrix type="matrix" values="1 0 0 0 0  1 0 0 0 0  1 0 0 0 0  1 0 0 0 0"/>
  </filter>

  <!-- THE OVERVIEW PUTS THE MARKER IN BOTH RED AND GREEN, so every section
       renders yellow whichever channel it is - and the section composites next
       to it are red for pERK and green for PCNA. Same section, two colour
       schemes, and the one that looks like a third marker is the overview.

       The duplication is what makes this exact rather than a tint: R and G hold
       the identical marker image (measured: means equal to 2dp), so dropping
       one loses nothing and leaves the marker in its own colour. Blue is DAPI
       and is untouched by the choice.

       DAPI is then lifted 4x. It is not a contrast preference: in tissue the
       marker runs 4.0-4.6x brighter than DAPI across 24 sampled sections, so
       at native scale the counterstain is swamped by the thing sitting on top
       of it and the section reads as marker-only. The pipeline measures the
       raw data; this is the viewing pane.

       Marker-only (_MARK.png) is greyscale, so R=G=B there and the same matrix
       gives the marker its colour with no blue to lift - hence a pair per
       channel rather than one filter with a toggle. -->
  <filter id="revPerkDapi" color-interpolation-filters="sRGB">
    <feColorMatrix type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 4 0 0  0 0 0 1 0"/>
  </filter>
  <filter id="revPerkOnly" color-interpolation-filters="sRGB">
    <feColorMatrix type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0"/>
  </filter>
  <filter id="revPcnaDapi" color-interpolation-filters="sRGB">
    <feColorMatrix type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 4 0 0  0 0 0 1 0"/>
  </filter>
  <filter id="revPcnaOnly" color-interpolation-filters="sRGB">
    <feColorMatrix type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0"/>
  </filter>
  <!-- DAPI alone. _DAPI.png is greyscale, so R=G=B and only the blue row does
       anything. Still lifted 4x: the point of a toggle is to compare, and a
       channel that changed brightness depending on what was next to it would
       make that comparison a guess. -->
  <filter id="revDapiOnly" color-interpolation-filters="sRGB">
    <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 4 0 0  0 0 0 1 0"/>
  </filter>
  <!-- Both channels off. The image still LOADS - blanked rather than removed -
       because the overlay canvas takes its size from the base image, so a
       missing one would take the artifact and censor layers down with it. This
       way the masks can be read on their own against black. -->
  <filter id="revBlank" color-interpolation-filters="sRGB">
    <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0"/>
  </filter>
</defs></svg>
<div id="review">
  <div id="revGrid"></div>
  <div id="revSide">
    <div class="card"><h3 id="revTitle">SECTION REVIEW</h3>
      <div class="kv" id="revHint">pick a section on the left</div>
      <div class="deliver" style="margin-top:5px">
        <button class="btn-edit" onclick="revStep(-1)" title="Previous section (up arrow)">&lsaquo;</button>
        <span class="kv" id="revPos" style="flex:1 1 auto;text-align:center">-</span>
        <button class="btn-edit" onclick="revStep(1)" title="Next section (down arrow)">&rsaquo;</button>
      </div>
      <select id="revFilter" onchange="revRender(); this.blur()" style="width:100%;margin-top:5px">
        <option value="all">every scanned section</option>
        <option value="excluded">excluded only - what the pipeline threw out</option>
        <option value="analysis">in the analysis only</option>
        <option value="measured">measured only</option>
        <option value="masked">has an artifact mask</option>
      </select></div>
    <div class="card" id="revImgCard"><h3 id="revImgH">IMAGE</h3>
      <div id="revImgWrap" ondblclick="revFull()" title="double-click for fullscreen">
        <img id="revImg" alt=""><img id="revMask" alt="">
        <img id="revCensor" alt=""><img id="revTissue" alt="">
        <canvas id="revOv"></canvas></div>
      <div class="kv" id="revImgNote" style="margin-top:4px"></div>
      <div class="deliver" style="flex-wrap:wrap;margin-top:4px">
        <button id="revDapiBtn" class="btn-plate" onclick="revLayer('dapi')">DAPI</button>
        <button id="revMarkBtn" class="btn-fav" onclick="revLayer('mark')">Marker</button>
        <button id="revArtBtn" class="btn-rot" onclick="revLayer('art')">Artifacts</button>
        <button id="revCenBtn" class="btn-kill" onclick="revLayer('cen')">Censored</button>
        <button id="revApplyBtn" class="btn-excl" onclick="revLayer('apply')">Apply mask</button>
        <span class="fsonly">
          <button class="btn-edit" onclick="revStep(-1)"
                  title="Previous section (up arrow)">&lsaquo;</button>
          <span id="revFsPos">-</span>
          <button class="btn-edit" onclick="revStep(1)"
                  title="Next section (down arrow)">&rsaquo;</button>
          <button id="revFsRestore" class="btn-plate" onclick="revAct('restore')"
                  title="Put this section back into the pipeline">Reinstate</button>
        </span>
        <button id="revFullBtn" class="btn-edit" onclick="revFull()"
                title="Fullscreen (f) - double-clicking the image does it too">&#9974; Full</button>
      </div>
      <label class="chk" style="margin-top:5px;display:block">
        <input type="checkbox" id="revPenChk" checked onchange="revImg()">
        hide the PAP pen ring - show only censoring inside the tissue</label></div>
    <div class="card"><h3>WHAT EACH STAGE DECIDED</h3>
      <div class="revChain" id="revChain"></div></div>
    <div class="card"><h3>YOUR DECISION</h3>
      <textarea class="revWhy" id="revWhy" rows="2"
                placeholder="why - recorded with the decision"></textarea>
      <div class="deliver" style="flex-wrap:wrap">
        <button id="revRestore" class="btn-plate" onclick="revAct('restore')">Reinstate</button>
        <button id="revDrop" class="btn-kill" onclick="revAct('drop')">Drop</button>
        <button id="revUnmask" class="btn-rot" onclick="revAct('unmask')">Reject mask</button>
        <button class="btn-edit" onclick="revAct('')">Clear</button>
      </div>
      <div class="kv" id="revState" style="margin-top:5px"></div></div>
    <div class="card"><h3>EXPORT</h3>
      <div class="kv" id="revCount">-</div>
      <button class="primary" onclick="exportReview()" style="margin-top:5px">
        Export review decisions</button></div>
  </div>
</div>
<div id="panes">
  <div class="pane"><h2 id="secTitle">SECTION - click to place a point</h2>
    <canvas id="cSec" tabindex="0" onmousedown="secDown(event)"
            ondblclick="if(draft) commitPoly()"></canvas>
    <button class="nav l" id="secPrev" tabindex="-1" title="Previous section (up arrow)"
            onclick="stepSection(-1)">&lsaquo;</button>
    <button class="nav r" id="secNext" tabindex="-1" title="Next section (down arrow)"
            onclick="stepSection(1)">&rsaquo;</button></div>
  <div class="pane"><h2 id="plTitle">ATLAS PLATE - click the matching point</h2>
    <canvas id="cPl" tabindex="0" onclick="clickPl(event)"></canvas>
    <button class="nav l" id="plPrev" tabindex="-1" title="Previous plate (left arrow)"
            onclick="stepPlate(-1)">&lsaquo;</button>
    <button class="nav r" id="plNext" tabindex="-1" title="Next plate (right arrow)"
            onclick="stepPlate(1)">&rsaquo;</button></div>
  <div id="side">
    <div class="card"><h3>SECTION</h3><div class="kv" id="secInfo">-</div>
      <div class="kv" id="rotInfo"></div></div>
    <div class="card"><h3>PLATE</h3>
      <input type="range" id="slider" min="0" max="0" value="0" oninput="onSlideUser(this.value)" onchange="this.blur()">
      <div class="kv"><b id="plName">-</b></div>
      <div id="plLab"></div>
    </div>
    <div class="card"><h3>LANDMARKS</h3>
      <div class="kv" id="lmHint">click section, then plate</div>
      <div id="lmlist"></div>
    </div>
    <div class="card"><h3>ROIs PLACED</h3>
      <div class="kv" id="regInfo">needs 3 pairs</div>
      <div id="regKey"></div></div>
  </div>
</div>
<div id="strip"></div>
<footer>
  <kbd>g</kbd> guided: the plate's ROIs one at a time - <kbd>click</kbd> each
  corner of the region on the section, then <kbd>Enter</kbd>, a double-click or
  the first corner to close it &middot;
  <kbd>z</kbd> drops a corner &middot;
  <kbd>s</kbd> skip an ROI that is not on this section &middot;
  once closed a region stays live: <kbd>drag</kbd> a corner to move it, click an
  edge to add one, <kbd>Delete</kbd> removes the one under the cursor - any time
  you are not part-way through drawing another &middot;
  <kbd>h</kbd> hides the shapes on the plate &middot;
  with guided OFF, <kbd>click</kbd> section then plate to add a landmark pair &middot;
  <kbd>&larr;</kbd><kbd>&rarr;</kbd> plate &middot;
  <kbd>&uarr;</kbd>/<kbd>&darr;</kbd> previous / next section (the plate stays put,
  or use the arrows on the panes) &middot;
  <kbd>a</kbd> assign plate &middot;
  <kbd>Rotate</kbd> then drag the section left/right (<kbd>shift</kbd> fine) - kept on release,
  <kbd>r</kbd> restores the original &middot;
  <kbd>f</kbd> favourite &middot; <kbd>x</kbd> exclude this section &middot;
  <kbd>d</kbd> background disc: mark tissue with NO signal, 2-3 per section - it is
  measured by the same detector, so it reports the false-positive rate here. It is
  the only thing still placed as a circle, and it does not move the ROI cursor &middot;
  <kbd>Review</kbd> every scanned section and what each stage decided about it -
  reinstate one the pipeline excluded, or reject its artifact mask. There,
  <kbd>&uarr;</kbd>/<kbd>&darr;</kbd> step one section at a time through whatever
  the filter shows (including the excluded ones), and the layers are independent:
  <kbd>d</kbd> DAPI on/off, <kbd>k</kbd> the marker on/off, <kbd>v</kbd> artifacts
  in red, <kbd>c</kbd> censored pixels in cyan, <kbd>m</kbd> apply the mask to see
  what 04a removed, <kbd>f</kbd> fullscreen (or double-click the image) &middot;
  <kbd>[</kbd><kbd>]</kbd> background disc size (or drag as you place one) &middot;
  <kbd>u</kbd> undo the last thing, whatever it was (<kbd>z</kbd> stays
  corner-only) &middot;
  <span style="color:#7c5cff">purple</span> = registered &middot;
  <span style="color:#4da3ff">blue</span> = plate assigned only &middot;
  <span style="color:#e3b341">gold edge</span> = favourite &middot;
  <span style="color:#f778ba">pink</span> = background disc &middot;
  faded = marked no-ROI &middot; autosaves &middot;
  filters (sample, channel, favourites, excluded) are top left, actions top right
</footer>
<script>
const DATA = __DATA__;      // [{uid, animal, order, img}]
const PLATES = __PLATES__;  // [{id, img, w, h, labelled, seeds:[{region,xf,yf,hex}],
                           //   hulls:[{region,part,n_parts,hex,amb,unk,seeds,v:[[xf,yf]]}]}]
// A hull is what a REGION is on a plate, as opposed to where its seeds are:
// one per region per lobe, convex, hulled in Python so the lobe split is
// testable rather than a drawing decision. See `region_hulls` there.
// Which plate set these ids belong to. plate_012 exists in every set and is a
// DIFFERENT image in each, so every export carries this and a landmark file can
// never be silently matched against the wrong plates.
const PLATE_SET = __PLATESET__;
// The unblinding key, and the ONLY thing in this page that reads one. Empty
// unless config.json declares `groups`, which is what keeps the Shotgun button
// off by default. See the Shotgun section at the foot of this script.
const GROUPS = __GROUPS__;
// Which channel these sections are, and which subset of it. The two markers are
// separate physical sections curated independently, so the channel is recorded
// in every export rather than inferred later from the file name.
// Both channels are in one page. They are separate physical sections curated
// independently, so nothing is shared between them except the tool itself: each
// DATA row carries its own marker, its own subset and whether a composite exists
// for it, and every export writes the row's own marker rather than a page-wide
// one. Scene uids never collide (`_s01a_` is pERK, `_s01b_` is PCNA), which is
// what lets a single store hold both without keying on the channel.
const MARKERS = __MARKERS__;          // [{id, label, n, sub}]
const DEFAULT_MARKER = __MARKER__;
// The canonical reformatted grid (04a GRID). Display may be a multiple of it.
const SEC_GRID = __SECGRID__;
const KEY = "ls_roi_curator_v1";
// Curation as it stood when this page was generated. localStorage is partitioned
// per origin AND per browser profile, so a page opened from disk in one browser
// cannot see what the app - or the same file in another browser - recorded. That
// is not a bug to route around; it means a page handed to someone has to carry
// the state with it or arrive empty.
//
// Whatever this browser already holds wins. The seed only fills an empty store,
// so opening a stale copy of the page can never overwrite work in progress.
const SEED_STATE = __SEED__;
// WHAT COUNTS AS WORK. `st()` creates a record the moment a section is looked
// at, and the slider writes into it - so "the store has records" never meant
// "the operator decided something". These two predicates are the only rule:
// hasRoiWork is what exportCsv reports; hasDecision adds the two things kept
// but exported elsewhere (a tilt, a Review-mode verdict).
// A drawn region is work, and this is not only about the export: `decided()`
// filters the store on every load, so a section curated ENTIRELY with polygons
// and no landmarks would have been thrown away as an empty record the next time
// the page opened.
const hasRoiWork  = r => !!r && !!(r.assigned || r.fav || r.excl || r.noroi
                                   || (r.pairs && r.pairs.length)
                                   || (r.polys && r.polys.length));
const hasDecision = r => hasRoiWork(r) || !!(r && (r.rot || r.rev));
const decided = obj => Object.fromEntries(
  Object.entries(obj || {}).filter(([, v]) => hasDecision(v)));
// Whatever this browser already holds wins - but only what it holds that is a
// decision. A store of looked-at sections is an empty store.
function initState(raw, seed){
  try {
    if (raw) { const v = decided(JSON.parse(raw)); if (Object.keys(v).length) return v; }
  } catch (e) {}
  return decided(seed);
}
let S = initState(localStorage.getItem(KEY), SEED_STATE);
let active = null, pending = null;   // pending section point awaiting its plate partner
const el = id => document.getElementById(id);
// Only decisions reach disk. The in-memory record for a section being looked
// at stays (the plate it is on is needed while it is on screen); it is simply
// not persisted until something is decided about it.
const save = () => localStorage.setItem(KEY, JSON.stringify(decided(S)));
// AUTOSAVE.
//
// save() already runs on every change - all twelve mutation sites call it - so
// this is not what keeps the work; localStorage is written the moment a decision
// is made. What the timer adds is a **recovery point**: a rolling snapshot under
// a second key, so a state that gets corrupted or overwritten can be rolled back
// instead of being the only copy. That is the failure the per-change save cannot
// protect against, because it overwrites the one record every time.
//
// It also gives a visible "saved HH:MM:SS", so the tool says so rather than
// leaving it to be assumed.
const BACKUP_KEY = KEY + "_backup";
const AUTOSAVE_MS = 60000;
function autosave(){
  save();
  try {
    localStorage.setItem(BACKUP_KEY, JSON.stringify(
      {at: new Date().toISOString(), marker: el("marker").value, S}));
  } catch(e) {
    // Quota is the only realistic failure and it must not take the session with
    // it: the live save above has already happened, which is the copy that matters.
    console.warn("autosave backup skipped:", e && e.message);
  }
  const t = new Date().toTimeString().slice(0,8);
  const el2 = el("savedAt"); if(el2) el2.textContent = "saved " + t;
}
setInterval(autosave, AUTOSAVE_MS);
// Restoring is deliberately not a button: it overwrites the live state wholesale
// and should not sit one stray click away from a day's curation. Run
// `roiRestoreBackup()` in the console.
function roiRestoreBackup(){
  const raw = localStorage.getItem(BACKUP_KEY);
  if(!raw){ console.warn("no backup yet - one is written every minute"); return; }
  const b = JSON.parse(raw);
  const n = Object.keys(b.S || {}).length;
  if(!confirm(`Restore the snapshot from ${b.at} (${n} sections)?

`
            + `This REPLACES everything currently in the tool.`)) return;
  S = b.S; save(); render(); status();
  console.log("restored", n, "sections from", b.at);
}
// Leaving the page is exactly when an unsaved change would be lost, and hiding
// the tab is the usual prelude to it.
addEventListener("beforeunload", save);
document.addEventListener("visibilitychange", ()=>{ if(document.hidden) autosave(); });

const animals = [...new Set(DATA.map(d=>d.animal))].sort((a,b)=>+a.slice(2)-+b.slice(2));
el("animal").innerHTML = animals.map(a=>`<option>${a}</option>`).join("");
el("slider").max = PLATES.length-1;
el("marker").innerHTML =
  MARKERS.map(m=>`<option value="${m.id}">${m.label} - ${m.n}</option>`).join("")
  + (MARKERS.length>1 ? `<option value="both">both channels - ${DATA.length}</option>` : "");
el("marker").value = DEFAULT_MARKER;
// One listener per container instead of an onclick string per cell: the uid
// never has to survive being pasted into a JS string literal.
el("strip").addEventListener("click", e => {
  const c = e.target.closest && e.target.closest(".cell"); if(c) select(c.dataset.uid);
});
el("revGrid").addEventListener("click", e => {
  const c = e.target.closest && e.target.closest(".rc"); if(c) revPick(c.dataset.uid);
});
const D_BY = Object.fromEntries(DATA.map(d=>[d.uid,d]));
// Which channel is on screen. `both` is a real option - useful for reading
// progress across the pair - but the two are still independent sections; nothing
// about one section's decision reaches the other.
function scopeLabel(){
  const v=el("marker").value, m=MARKERS.find(x=>x.id===v);
  el("scope").innerHTML = m
    ? `<b>${m.label}</b>` + (m.sub==="all" ? "" : ` &middot; <b>${m.sub.replace(/_/g," ")}</b>`)
    : `<b>both channels</b>`;
}
function onMarker(){ pending=null; scopeLabel(); render(); }
const inScope = () => DATA.filter(d=>d.animal===el("animal").value
  && (el("marker").value==="both" || d.m===el("marker").value));
// The filters narrow the strip, so `rows` - which also drives the arrow keys and
// the counts - honours them. Hiding the excluded is a VIEW, not a deletion: the
// sections keep their flag, still appear in the excluded count, and are still
// written to roi_plates.csv with excluded=1.
const rows = () => inScope()
  .filter(d => !el("favOnly").checked || S[d.uid]?.fav)
  .filter(d => !el("hideExcl").checked || !isExcl(d.uid))
  .sort((a,b)=>a.order-b.order);
// `assigned` is set only by a real slider move or an explicit button, never by
// merely selecting a section - otherwise clicking through the strip would record
// a plate_001 assignment for everything it touched.
const st = uid => S[uid] || (S[uid] = {plate: 0, pairs: [], assigned: false,
                                       noroi: false, fav: false, rot: 0,
                                       excl: false});

const secImg = new Image();
secImg.onload = ()=>{ markerCache=null; drawSec(); };   // cache belongs to one section

// All 101 plates preloaded - 7.4 MB total, median 71 KB. Setting plImg.src on
// every slider step made each step wait on a disk read and a JPEG decode, which
// is what made scrubbing feel heavy. Held as decoded Image objects instead, so
// changing plate is just a canvas draw.
const PLIMG = PLATES.map(p => { const im = new Image(); im.src = p.img; return im; });
const plateImg = () => PLIMG[st(active).plate];

// ---- affine from >=3 correspondences, least squares ------------------------
// A thin-plate spline would fit the clicked points exactly and invent
// deformation between them that nothing measured. With 3-6 landmarks an affine
// is the honest transform, and it is the class SHARCQ uses from the same input.
function solve3(A, b){
  const M = A.map((r,i)=>[...r, b[i]]);
  for(let c=0;c<3;c++){
    let p=c; for(let r=c+1;r<3;r++) if(Math.abs(M[r][c])>Math.abs(M[p][c])) p=r;
    if(Math.abs(M[p][c])<1e-12) return null;
    [M[c],M[p]]=[M[p],M[c]];
    for(let r=0;r<3;r++){ if(r===c) continue;
      const f=M[r][c]/M[c][c]; for(let k=c;k<4;k++) M[r][k]-=f*M[c][k]; }
  }
  const out = [M[0][3]/M[0][0], M[1][3]/M[1][1], M[2][3]/M[2][2]];
  // A pivot can clear the test above and still leave a non-finite result on a
  // badly conditioned system. Returning null says "no fit", which every caller
  // already handles; returning an array of NaNs says "a fit", and is truthy, so
  // it would be treated as one - and reach mean_residual_px as the string NaN.
  //
  // The pivot floor above is deliberately left as it was. Making it relative to
  // the matrix looked like the tidier fix, but measured across the 23 seeded
  // plates it rejected the first-three-seed fit at 0.83 and 1.02 degrees off
  // collinear while accepting one at 1.07 - a threshold that does not track the
  // degeneracy it is supposed to catch. This guard only removes results that
  // are already not numbers.
  return out.every(Number.isFinite) ? out : null;
}
function affine(pairs){          // plate (px,py) -> section (sx,sy)
  if(pairs.length < 3) return null;
  const N=[[0,0,0],[0,0,0],[0,0,0]], bx=[0,0,0], by=[0,0,0];
  for(const [sx,sy,px,py] of pairs){
    const v=[px,py,1];
    for(let i=0;i<3;i++){ for(let j=0;j<3;j++) N[i][j]+=v[i]*v[j];
      bx[i]+=v[i]*sx; by[i]+=v[i]*sy; }
  }
  const a=solve3(N.map(r=>[...r]),bx), d=solve3(N.map(r=>[...r]),by);
  return (a&&d) ? {kind:"affine", a, d} : null;
}

// ---- thin-plate spline, used from TPS_MIN pairs upward ----------------------
// An affine cannot follow the local distortion that sectioning and mounting put
// into a slice; a TPS can, and it is what BigWarp and VisuAlign use for exactly
// this job. The reason it is gated rather than always on: a TPS interpolates the
// landmarks EXACTLY, so with 3-4 points it fits them perfectly and invents
// deformation everywhere else from almost no evidence. From six well-spread
// points the interpolation is constrained by enough real correspondences to be
// worth having.
const TPS_MIN = 6;
function solveN(A, b){                       // Gaussian elimination with pivoting
  const n=A.length, M=A.map((r,i)=>[...r,b[i]]);
  for(let c=0;c<n;c++){
    let p=c; for(let r=c+1;r<n;r++) if(Math.abs(M[r][c])>Math.abs(M[p][c])) p=r;
    if(Math.abs(M[p][c])<1e-10) return null;
    [M[c],M[p]]=[M[p],M[c]];
    for(let r=0;r<n;r++){ if(r===c) continue;
      const f=M[r][c]/M[c][c]; for(let k=c;k<=n;k++) M[r][k]-=f*M[c][k]; }
  }
  return M.map((r,i)=>r[n]/r[i]);
}
const U = r2 => r2 < 1e-12 ? 0 : r2 * Math.log(r2);   // r^2 log r^2, the 2-D TPS kernel
function tps(pairs){
  const n=pairs.length; if(n < TPS_MIN) return null;
  const P=pairs.map(p=>[p[2],p[3]]), S=pairs.map(p=>[p[0],p[1]]);
  const m=n+3, A=Array.from({length:m},()=>new Array(m).fill(0));
  for(let i=0;i<n;i++){
    for(let j=0;j<n;j++){
      const dx=P[i][0]-P[j][0], dy=P[i][1]-P[j][1];
      A[i][j]=U(dx*dx+dy*dy);
    }
    A[i][n]=1; A[i][n+1]=P[i][0]; A[i][n+2]=P[i][1];
    A[n][i]=1; A[n+1][i]=P[i][0]; A[n+2][i]=P[i][1];
  }
  const bx=new Array(m).fill(0), by=new Array(m).fill(0);
  for(let i=0;i<n;i++){ bx[i]=S[i][0]; by[i]=S[i][1]; }
  const wx=solveN(A.map(r=>[...r]),bx), wy=solveN(A.map(r=>[...r]),by);
  return (wx&&wy) ? {kind:"tps", P, wx, wy, n} : null;
}
function tpsApply(T,px,py){
  let X=T.wx[T.n]+T.wx[T.n+1]*px+T.wx[T.n+2]*py;
  let Y=T.wy[T.n]+T.wy[T.n+1]*px+T.wy[T.n+2]*py;
  for(let i=0;i<T.n;i++){
    const dx=px-T.P[i][0], dy=py-T.P[i][1], u=U(dx*dx+dy*dy);
    X+=T.wx[i]*u; Y+=T.wy[i]*u;
  }
  return [X,Y];
}

// The transform actually used: TPS once there are enough points, affine below.
function transform(pairs){
  // A background disc is a position on the SECTION with no counterpart on the
  // plate, so it must never enter the fit - its (0,0) plate coordinate would
  // drag the whole spline to the corner. Filtered here rather than at each call
  // site, so a new caller cannot forget: there is no way to ask for a transform
  // that includes them.
  const p = pairs.filter(q => q[6] !== "bg");
  return tps(p) || affine(p);
}
function apply(T,px,py){
  return T.kind==="tps" ? tpsApply(T,px,py)
                        : [T.a[0]*px+T.a[1]*py+T.a[2], T.d[0]*px+T.d[1]*py+T.d[2]];
}

// ---- drawing ---------------------------------------------------------------
function fit(c, img){ c.width=img.naturalWidth||600; c.height=img.naturalHeight||600; }
// ---- rotation, as a VIEWING aid only ---------------------------------------
// Every stored coordinate - landmarks, pending points, warped seeds - stays in
// the UNROTATED reformatted frame. Only the drawing and the click mapping know
// the angle. That is the whole point: the transform, the residuals and all
// three exports are byte-identical whether the operator rotated or not, so
// turning the section to see it better can never move a landmark.
//
// The canvas is the DIAGONAL of the image, not the image, so a rotated section
// never has its corners clipped.
function secGeom(){
  const w=secImg.naturalWidth||256, h=secImg.naturalHeight||256;
  const a=effRot()*Math.PI/180;
  return {w, h, D:Math.ceil(Math.hypot(w,h)), a, cos:Math.cos(a), sin:Math.sin(a)};
}
const img2can = (x,y,g) => { const dx=x-g.w/2, dy=y-g.h/2;
  return [g.D/2 + dx*g.cos - dy*g.sin, g.D/2 + dx*g.sin + dy*g.cos]; };
const can2img = (X,Y,g) => { const dx=X-g.D/2, dy=Y-g.D/2;
  return [g.w/2 + dx*g.cos + dy*g.sin, g.h/2 - dx*g.sin + dy*g.cos]; };

// DAPI is the blue channel of the composite, so it is already underneath the
// marker in the one image - showing it is the default and hiding it means
// removing blue, not drawing a second layer.
//
// Done by compositing, NOT by reading pixels. An earlier version split the
// channels with getImageData, which throws a SecurityError the moment the page
// is opened from disk: a file:// image taints the canvas, and the throw killed
// the whole onload handler, so the section never drew at all. Nothing here reads
// the bitmap back.
let dapiOn = true;
const hasRgb = uid => !!D_BY[uid]?.rgb;
function toggleDapi(){
  if(!hasRgb(active)) return;
  dapiOn = !dapiOn;
  dapiBtnState();
  drawSec();
}
// Whether a section HAS a DAPI channel to hide is a fact about that section -
// only sections 04o has built a composite for do - so the button reports the
// section on screen rather than a decision made once for the whole page.
function dapiBtnState(){
  const rgb = hasRgb(active), on = rgb && dapiOn;
  el("dapiBtn").disabled = !rgb;
  el("dapiBtn").classList.toggle("mode-on", on);
  el("dapiBtn").textContent = on ? "DAPI ✓" : "DAPI";
  el("dapiBtn").title = rgb ? ""
    : "no colour composite for this section - run 04o_section_rgb.py --all";
}

// The blue-stripped copy, built on a canvas exactly the size of the image.
//
// The multiply CANNOT be done on the visible canvas. That one is a square of
// side hypot(w,h) so the section can rotate inside it without clipping, which
// leaves transparent margins around the image - and canvas "multiply" over a
// transparent backdrop has nothing to multiply against, so it paints the source
// straight on. The margins came out solid yellow. Here every pixel is covered by
// the opaque image, so the blend does what it says, and the rotated edge keeps
// its antialiasing instead of picking up a yellow fringe.
//
// Rebuilt only when the section changes, not on every redraw. The cache belongs
// to the ON-SCREEN section, so it applies only when this is called with no
// argument; Shotgun passes each deck image in and gets an uncached copy, which
// is right - those are built once each and never redrawn.
let markerCache = null;
function markerOnly(img){
  const src = img || secImg;
  if(src === secImg && markerCache) return markerCache;
  const w=src.naturalWidth, h=src.naturalHeight;
  if(!w) return src;
  const c=document.createElement("canvas"); c.width=w; c.height=h;
  const x=c.getContext("2d");
  x.drawImage(src,0,0);
  x.globalCompositeOperation="multiply";
  x.fillStyle="#ffff00";          // keep red and green, zero blue
  x.fillRect(0,0,w,h);
  if(src === secImg) markerCache=c;
  return c;
}

function drawSec(){
  const c=el("cSec"), x=c.getContext("2d"); if(!secImg.naturalWidth) return;
  syncFrame(active);          // pairs drawn in the frame of the image on screen
  const g=secGeom();
  c.width=g.D; c.height=g.D;
  x.clearRect(0,0,g.D,g.D);
  x.save(); x.translate(g.D/2,g.D/2); x.rotate(g.a);
  // Hiding DAPI means drawing the blue-stripped copy instead - see markerOnly().
  x.drawImage((hasRgb(active) && !dapiOn) ? markerOnly() : secImg, -g.w/2, -g.h/2);
  x.restore();
  const s=st(active), T=transform(s.pairs), u=uiScale(c);
  // NP went with the region labels; mark() sizes its own badge from ns.
  const ns=numScale(PLATES[s.plate], c, u);
  // ROIs are the ones that were placed. Nothing is positioned by the transform.
  //
  // This used to warp every seed on the plate through the fit and draw them all,
  // so ten placed ROIs produced thirty on screen and twenty-seven in the export.
  // The seventeen nobody touched were extrapolation - a thin-plate spline is
  // exact at its own landmarks and speculative everywhere else, most of all past
  // the edge of them, which is precisely where the untouched seeds were. They
  // looked like measurements.
  //
  // NO REGION NAME IS DRAWN ON THE SECTION. There was one, next to every ROI,
  // and on a dense plate it turned the tissue into a wall of text sitting on
  // exactly the anatomy being judged. The number in mark()'s badge already says
  // which seed the ROI answers, the plate pane shows that number on the seed
  // itself, and the legend under the card maps number to region and colour. The
  // name added a third copy of something already said twice, over the image.
  // Two independent numberings. The index into s.pairs used to serve as the
  // free-mode label, but background discs are interleaved with landmarks, so an
  // index would number the landmarks 1,3,4 the moment one was placed between
  // them. Each kind counts its own.
  // ---- the ROIs drawn on this section ---------------------------------------
  //
  // SHADED in the region's own colour, the same colour the atlas draws it in -
  // reading it off the seed rather than a table is what keeps the two panes from
  // ever disagreeing. Region names were taken off this pane because on a dense
  // plate they became a wall of text over exactly the anatomy being judged; the
  // colour and the ROI number say the same thing without a character of it
  // landing on the tissue.
  //
  // Cased, like the shapes on the plate: Dl is pure yellow and the tissue under
  // it is pale.
  const Ppl = PLATES[s.plate];
  polysOf(s).forEach(pg => {
    const col = polyCol(Ppl, pg);
    x.beginPath();
    for(let i=0;i<pg.v.length;i+=2){
      const [X,Y]=img2can(pg.v[i],pg.v[i+1],g);
      i ? x.lineTo(X,Y) : x.moveTo(X,Y);
    }
    x.closePath();
    x.fillStyle=col; x.globalAlpha=.22; x.fill(); x.globalAlpha=1;
    x.lineJoin="round";
    x.lineWidth=4.5*u; x.strokeStyle="rgba(4,18,31,.75)"; x.stroke();
    x.lineWidth=2.5*u; x.strokeStyle=col; x.stroke();
    // The ROI's number at its centre, so the section can be read against the
    // plate without counting shapes.
    let cx=0, cy=0;
    for(let i=0;i<pg.v.length;i+=2){ cx+=pg.v[i]; cy+=pg.v[i+1]; }
    const nv=pg.v.length/2;
    const [CX,CY]=img2can(cx/nv, cy/nv, g);
    x.save();
    x.font="bold "+(NUM_PX_SEED*ns*u)+"px system-ui";
    x.textAlign="center"; x.textBaseline="middle";
    x.lineWidth=4*u; x.strokeStyle="#04121f"; x.lineJoin="round";
    x.strokeText(pg.roi||"", CX, CY);
    x.fillStyle=col; x.fillText(pg.roi||"", CX, CY);
    x.restore();
    // The CORNERS, but only while no new ring is being drawn. That is the whole
    // of the editing rule: with a draft open every click belongs to it, and
    // handles under the cursor would be a trap rather than an affordance.
    if(!draft) for(let i=0;i<pg.v.length;i+=2){
      const [X,Y]=img2can(pg.v[i],pg.v[i+1],g);
      x.beginPath(); x.arc(X,Y,3.5*u,0,6.284);
      x.fillStyle="#7ee787"; x.fill();
      x.lineWidth=1.5*u; x.strokeStyle="#04121f"; x.stroke();
    }
    // ...and an edge midpoint to click for a new one.
    if(!draft) for(let i=0,j=pg.v.length-2;i<pg.v.length;j=i,i+=2){
      const [X,Y]=img2can((pg.v[i]+pg.v[j])/2, (pg.v[i+1]+pg.v[j+1])/2, g);
      x.beginPath(); x.arc(X,Y,2*u,0,6.284);
      x.fillStyle="#04121f"; x.fill();
      x.lineWidth=1.2*u; x.strokeStyle="#7ee787"; x.stroke();
    }
  });
  // The ring being clicked out. Left OPEN, and dashed, so an unfinished polygon
  // never looks like a finished one.
  if(draft && draft.length){
    const col = (gRoi() || {}).hex || "#d29922";
    x.save(); x.setLineDash([6*u, 4*u]);
    x.beginPath();
    for(let i=0;i<draft.length;i+=2){
      const [X,Y]=img2can(draft[i],draft[i+1],g);
      i ? x.lineTo(X,Y) : x.moveTo(X,Y);
    }
    x.lineWidth=2.5*u; x.strokeStyle=col; x.stroke();
    x.restore();
    // The first vertex gets a ring, because clicking it is what closes the shape
    // and an invisible target is not a target.
    const [FX,FY]=img2can(draft[0],draft[1],g);
    x.beginPath(); x.arc(FX,FY,closeR()*(g.D/(secImg.naturalWidth||SEC_GRID)),0,6.284);
    x.lineWidth=2*u; x.strokeStyle=col; x.stroke();
    for(let i=0;i<draft.length;i+=2){
      const [X,Y]=img2can(draft[i],draft[i+1],g);
      x.beginPath(); x.arc(X,Y,2.5*u,0,6.284); x.fillStyle=col; x.fill();
    }
  }
  // A landmark is a point now, not a disc. Nothing anatomical is measured by a
  // radius any more, so the ring shrinks to a marker and the number is the whole
  // of what it says. Background discs keep their radius: theirs is the area the
  // detector's false-positive rate is measured over.
  let nLm=0, nBg=0;
  s.pairs.forEach(p=>{
    const [X,Y]=img2can(p[0],p[1],g);
    if(isBg(p)) mark(x,X,Y,"B"+(++nBg),BG_COL,u,pairR(p),ns);
    else        mark(x,X,Y,++nLm,"#4da3ff",u,3*u,ns);
  });
  const nextLabel = bgMode ? "B"+(bgPairs(s).length+1)
                  : guided ? gTarget : roiPairs(s).length+1;
  const nextCol = bgMode ? BG_COL : "#d29922";
  if(pending){ const [X,Y]=img2can(pending[0],pending[1],g);
               mark(x,X,Y,nextLabel,nextCol,u,pending[2]||defaultR(),ns); }
  if(ptDrag){ const [X,Y]=img2can(ptDrag.ix,ptDrag.iy,g);
              mark(x,X,Y,nextLabel,nextCol,u,ptDrag.r,ns); }
}
function drawPl(){
  const c=el("cPl"), x=c.getContext("2d");
  if(!active) return;
  const img=plateImg();
  if(!img.naturalWidth){ img.addEventListener("load", drawPl, {once:true}); return; }
  fit(c,img); x.drawImage(img,0,0);
  const s=st(active), P=PLATES[s.plate], u=uiScale(c), done=usedRois(s);
  const ns=numScale(P, c, u);
  // ---- the ROIs, as areas --------------------------------------------------
  //
  // An ROI is what is being asked for, so an ROI is what the plate draws: one
  // shape per region per lobe, shaded in the atlas's own colour for it. Reading
  // a region's extent off a scatter of separately numbered dots was a job the
  // reader should never have had.
  //
  // The dots stay, smaller, and every dot of an ROI carries THAT ROI's number.
  // A done ROI goes hollow and the target gets a bright ring, so progress is
  // visible without reading anything.
  const HL = hullsOn ? (P.hulls || []) : [];
  const isTgtRoi = h => guided && h.roi === gTarget;
  HL.forEach(h => {
    if(h.v.length < 3) return;                 // a dot or a segment; drawn below
    x.beginPath();
    h.v.forEach((v,i) => { const X=v[0]*c.width, Y=v[1]*c.height;
                           i ? x.lineTo(X,Y) : x.moveTo(X,Y); });
    x.closePath();
    const tgt = isTgtRoi(h), dn = done.has(h.roi);
    // Colour off the seed, never a table - the same rule the region key follows,
    // and the reason the two panes cannot drift apart.
    x.fillStyle = h.hex || "#4da3ff";
    x.globalAlpha = tgt ? .34 : dn ? .07 : .15; x.fill();
    x.globalAlpha = 1;
    // Cased: a dark stroke under the colour. The atlas draws Dl in pure yellow
    // and prints its own yellow markers on these plates, so an uncased yellow
    // line on pale tissue is close to invisible - measured on this pane.
    x.lineJoin = "round";
    x.lineWidth = (tgt ? 6 : 3.6) * u;
    x.strokeStyle = "rgba(4,18,31,.75)"; x.stroke();
    x.lineWidth = (tgt ? 3.5 : 1.8) * u;
    x.strokeStyle = tgt ? "#7ee787" : (h.hex || "#4da3ff"); x.stroke();
  });
  // One- and two-seed ROIs are ordinary - Vs and Vc carry four seeds in the
  // whole atlas - and a one-vertex shape strokes no pixels at all, so both are
  // drawn as what they are rather than silently skipped.
  HL.forEach(h => {
    if(h.v.length > 2) return;
    const tgt = isTgtRoi(h);
    x.lineCap = "round";
    if(h.v.length === 2){
      x.beginPath();
      x.moveTo(h.v[0][0]*c.width, h.v[0][1]*c.height);
      x.lineTo(h.v[1][0]*c.width, h.v[1][1]*c.height);
      x.lineWidth = 9*u; x.strokeStyle = "rgba(4,18,31,.75)"; x.stroke();
      x.lineWidth = 6*u; x.strokeStyle = tgt ? "#7ee787" : (h.hex || "#4da3ff");
      x.globalAlpha = .8; x.stroke(); x.globalAlpha = 1;
    } else {
      x.beginPath(); x.arc(h.v[0][0]*c.width, h.v[0][1]*c.height, 9*u, 0, 6.284);
      x.lineWidth = 4*u; x.strokeStyle = "rgba(4,18,31,.75)"; x.stroke();
      x.lineWidth = 2*u; x.strokeStyle = tgt ? "#7ee787" : (h.hex || "#4da3ff");
      x.stroke();
    }
    x.lineCap = "butt";
  });
  P.seeds.forEach(sd=>{
    const N=sd.roi, X=sd.xf*c.width, Y=sd.yf*c.height;
    const isDone=done.has(N), isTgt=guided && N===gTarget;
    const base = HL.length ? 3.5 : 5;          // smaller once a shape carries the meaning
    x.beginPath(); x.arc(X,Y,(isTgt?7:base)*u,0,6.284);
    x.fillStyle=sd.hex||"#4da3ff"; x.globalAlpha=isDone?.25:.85; x.fill();
    x.globalAlpha=1; x.lineWidth=(isTgt?3:1.2)*u;
    x.strokeStyle=isTgt?"#3fb950":"#000"; x.stroke();
  });
  // The NUMBER goes once per ROI, not once per dot. Every dot of an ROI carries
  // the same number now, so drawing it on each of six Dl seeds would print "1"
  // six times over the anatomy it is meant to label. Once, at the shape's
  // centre, says the same thing and covers five sixths less tissue.
  HL.forEach(h => {
    const N = h.roi;
    const isDone = done.has(N), isTgt = guided && N === gTarget;
    const cx = h.v.reduce((a,v)=>a+v[0],0)/h.v.length*c.width;
    const cy = h.v.reduce((a,v)=>a+v[1],0)/h.v.length*c.height;
    x.save();
    const fs=(isTgt?NUM_PX:NUM_PX_SEED)*ns;
    x.font="bold "+(fs*u)+"px system-ui";
    x.textAlign="center"; x.textBaseline="middle";
    x.lineWidth=4*u; x.strokeStyle="#04121f"; x.lineJoin="round";
    x.strokeText(N, cx, cy);
    x.fillStyle = isTgt ? "#7ee787" : isDone ? "#6e7681" : "#fff";
    x.fillText(N, cx, cy);
    x.restore();
  });
  // The region's NAME, under its number. This pane can afford text where the
  // section cannot: the plate is a drawing with room in it, and knowing an ROI
  // is number 3 is not the same as knowing it is Dl. One label per lobe, so a
  // bilateral region says its name twice and reads as two.
  HL.forEach(h => {
    if(h.v.length < 3) return;
    const cx = h.v.reduce((a,v)=>a+v[0],0)/h.v.length*c.width;
    const cy = h.v.reduce((a,v)=>a+v[1],0)/h.v.length*c.height
             + NUM_PX_SEED*ns*0.85*u;         // clear of the number above it
    x.save();
    x.font = "bold "+(NUM_PX_SEED*ns*0.55*u)+"px system-ui";
    x.textAlign="center"; x.textBaseline="middle";
    x.lineWidth=4*u; x.strokeStyle="#04121f"; x.lineJoin="round";
    // The ambiguity group, not the atlas name, wherever there is one - Vd, Vv
    // and POA cannot be told apart at this level and the pane must not claim
    // they can. `?` is the atlas's own doubt, kept separate from ours.
    const nm = (h.amb || h.region) + (h.unk ? "?" : "");
    x.strokeText(nm, cx, cy); x.fillStyle = h.hex || "#4da3ff";
    x.fillText(nm, cx, cy);
    x.restore();
  });
  // ONLY FREE PAIRS get a blue mark here, and the reason is that blue means
  // "an ROI on the section" everywhere else in this page.
  //
  // A GUIDED pair's plate point IS the seed - commitPoint stores sd.xf*P.w,
  // sd.yf*P.h, and P.w is the plate canvas width - so this was drawing a second
  // marker exactly on top of a seed already drawn above, carrying the same
  // number but in section blue instead of the atlas's own colour. Since guided
  // placement is the normal process, that meant a blue ROI appearing on the
  // atlas for every ROI placed on the section.
  //
  // A BACKGROUND disc has no plate point at all. Its (0,0) put a stray blue
  // numbered ROI in the top-left corner of every plate - a mark for something
  // the atlas has no opinion about whatsoever.
  //
  // A free pair is the one case worth drawing: the operator picked that point
  // on the plate by hand and nothing else on this pane shows it. Numbered by
  // its position among the ROIs, the same way drawSec numbers it, so the two
  // panes agree about which pair is which.
  let nRoi = 0;
  s.pairs.forEach(p => {
    if(isBg(p)) return;
    nRoi++;
    if(p[4]) return;
    mark(x, p[2], p[3], nRoi, "#4da3ff", u, null, ns);
  });
}
// Both canvases are drawn at their bitmap's own resolution and then fitted into
// the pane by CSS, so a size in CANVAS pixels is not a size on SCREEN: a 1427 px
// plate in a 493 px pane shrinks everything by 2.9x. That is what made the
// landmark numbers 5 px tall - drawn all along, and effectively invisible.
// Every annotation is therefore given in screen pixels and divided back through.
function uiScale(c){
  const b=c.getBoundingClientRect();
  const k=Math.min(b.width/c.width, b.height/c.height);
  return k>0 ? 1/k : 1;
}
// A landmark is its ring plus its NUMBER, and the number is the half that says
// which point on the plate answers which point on the section. It gets a filled
// badge because it sits over whatever the atlas or the tissue happens to be
// there, and plain text was unreadable against the pale plates.
// One knob for how large every annotation number is drawn, in SCREEN pixels
// before uiScale divides it back through. The numbers carry the click-through
// order, so they are the part that has to be readable at a glance rather than
// squinted at; the dots they label stay small so the tissue underneath is not
// covered up.
const NUM_PX = 36;                      // landmark badge and seed number
const NUM_PX_SEED = 30;                 // plate seeds, of which there can be 30
// ...but only where they fit. A plate carrying 30 seeds gives each one about
// 35 screen pixels of clear space and a full "10 Dm" label wants around 55, so
// on the dense plates the labels ran into each other. P.nn is that plate's
// median nearest-neighbour distance as a fraction of its diagonal, measured in
// 04l's plate build; converting it against the CURRENT canvas means the numbers
// re-scale when the window changes instead of being sized once for a pane that
// no longer exists. Floored at half, so dense plates still read at roughly twice
// the size they were before any of this.
const NUM_TARGET = 55;
function numScale(P, c, u){
  if(!P || !P.nn) return 1;
  const nnScreen = P.nn * Math.hypot(c.width, c.height) / u;
  return Math.max(0.5, Math.min(1, nnScreen / NUM_TARGET));
}
// A landmark now has a RADIUS as well as a position - see secDown(). It is drawn
// as the circle, and the ring is what the number is anchored to.
function mark(x,X,Y,n,col,u,rad,ns){
  u = u || 1; const NP = NUM_PX * (ns || 1);
  const R = rad || 8*u;
  x.beginPath(); x.arc(X,Y,R,0,6.284); x.lineWidth=2.5*u; x.strokeStyle=col; x.stroke();
  x.beginPath(); x.arc(X,Y,1.5*u,0,6.284); x.fillStyle=col; x.fill();   // the point itself
  const br=NP*0.62*u, off=(R+br*0.85)*0.72;
  const bx=X+off, by=Y-off;
  x.beginPath(); x.arc(bx,by,br,0,6.284);
  x.fillStyle=col; x.fill(); x.lineWidth=1.5*u; x.strokeStyle="#04121f"; x.stroke();
  x.save();
  x.fillStyle="#04121f"; x.font="bold "+(NP*u)+"px system-ui";
  x.textAlign="center"; x.textBaseline="middle";
  x.fillText(n, bx, by);
  x.restore();
}
// `object-fit:contain` fits the bitmap inside the element and centres it, so the
// element box is NOT the drawn area - there is a letterbox on two sides whose
// size depends on the aspect ratios. Scaling by width alone, as this used to,
// would put every landmark off-target by the size of that band. Undo the fit.
const canvasXY = (c,e) => {
  const r=c.getBoundingClientRect(), k=Math.min(r.width/c.width, r.height/c.height);
  const ox=r.left+(r.width-c.width*k)/2, oy=r.top+(r.height-c.height*k)/2;
  return [(e.clientX-ox)/k, (e.clientY-oy)/k];
};

// Rotating and placing a landmark are separated by the MODE, not by watching how
// far the mouse moved. An earlier version guessed from the drag distance and
// suppressed the click that followed; once `secDown` also had to return early
// when the tool was closed, that flag could be left set from the last rotation
// and would silently swallow the next genuine click. The mode makes it
// unnecessary, so it is gone: `live` below is local to one drag and never
// consulted by the click handler.
let rotDrag=null, rotMode=false, draftRot=null;
const DEG_PER_PX = 0.4, DEG_PER_PX_FINE = 0.05;
// The angle actually drawn: the live draft mid-drag, otherwise what is saved for
// this section - and since the drag commits on release those are the same value
// a moment later. The draft exists only so the section can follow the mouse.
const effRot = () => (rotMode && draftRot!==null) ? draftRot : (st(active).rot||0);

// Rotate is a MODE, so dragging cannot be mistaken for placing a landmark and
// vice versa. While it is on, clicks on the section do not place points.
function toggleRotMode(){
  if(!active) return;
  rotMode = !rotMode;
  draftRot = null;            // nothing is ever left uncommitted; this is belt and braces
  el("cSec").classList.toggle("rotmode", rotMode);
  drawSec(); status();
}
// "Original" is the orientation 04a_reformat produced - the frame every stored
// coordinate already lives in - so restoring it is exactly rot = 0. It commits
// immediately, and discards any draft, because there is nothing to preview.
function restoreTilt(){
  if(!active) return;
  draftRot = null; st(active).rot = 0; save(); drawSec(); status(); paintCell(active);
}
function secDown(e){
  if(!active || e.button!==0) return;
  // preventDefault below stops the browser moving focus here, so take it
  // explicitly - otherwise focus stays on whatever was clicked last and the
  // arrow keys keep going to that instead of the plate.
  el("cSec").focus();
  if(rotMode){                               // the rotate tool owns the mouse
    rotDrag={x:e.clientX, rot:effRot(), live:false}; e.preventDefault();
    return;
  }
  // A polygon is CLICKED OUT, vertex by vertex, not dragged. On a 256 px frame
  // one pixel spans about 25 um, so a lasso would be sketching an outline at a
  // scale where every pixel is four nuclei wide; clicking puts each corner where
  // it was meant to go, and leaves it there to be nudged afterwards.
  // Background mode wins over the guided walk. A background disc is placed with
  // the press-drag-release gesture below, and if the walk intercepted the click
  // first the disc could never be placed at all while guided was on - which is
  // always, since it is the default.
  if(guided && !bgMode){
    e.preventDefault();
    syncFrame(active);
    const [vx,vy] = can2img(...canvasXY(el("cSec"), e), secGeom());
    // Not drawing yet: a click may be grabbing a corner of a finished polygon,
    // or asking for a new one on an edge. Editing wins over starting a ring,
    // because a click that lands on a handle was aimed at that handle.
    if(!draft && grabVertex(vx, vy)) return;
    if(!gTarget){ status(); return; }        // plate finished - nothing to draw
    addVertex(vx, vy);
    return;
  }
  syncFrame(active);
  const [ix,iy] = can2img(...canvasXY(el("cSec"), e), secGeom());
  ptDrag = {ix, iy, r: defaultR()};
  e.preventDefault(); drawSec(); status();
}
// Where the pointer last was, in section image pixels. Delete has no
// coordinates of its own, and asking which corner to remove is the whole
// question, so it is remembered here rather than guessed at.
let lastSec = null;
addEventListener("mousemove", e=>{
  if(active && secImg.naturalWidth){
    try { lastSec = can2img(...canvasXY(el("cSec"), e), secGeom()); } catch(err){}
  }
  // A corner of a finished polygon, following the cursor. One undoMark was taken
  // when the grab happened; its 900 ms coalescing makes the whole drag one step.
  if(vDrag && active){
    const [mx,my] = can2img(...canvasXY(el("cSec"), e), secGeom());
    const pg = polysOf(st(active))[vDrag.pi];
    if(pg){ pg.v[vDrag.vi] = mx; pg.v[vDrag.vi+1] = my; drawSec(); }
    return;
  }
  if(ptDrag){
    // radius = how far the mouse has travelled from the point, in image pixels,
    // so the circle follows the cursor and what you see is what is stored
    const [mx,my] = can2img(...canvasXY(el("cSec"), e), secGeom());
    const d = Math.hypot(mx-ptDrag.ix, my-ptDrag.iy);
    ptDrag.r = Math.max(2*imgK(), d);
    drawSec(); status();
    return;
  }
  if(!rotDrag) return;
  const dx=e.clientX-rotDrag.x;
  if(!rotDrag.live && Math.abs(dx)<=3) return;   // ignore the jitter of a plain press
  rotDrag.live = true;
  el("cSec").classList.add("rotating");
  const per = e.shiftKey ? DEG_PER_PX_FINE : DEG_PER_PX;   // shift = fine
  draftRot = ((rotDrag.rot + dx*per) % 360 + 360) % 360;
  drawSec(); status();
  paintCellRot(active, draftRot);       // the strip follows the drag, not the release
});
// The tilt commits itself on release. An angle the operator has to remember to
// press a button for is an angle that gets lost - and losing it was silent,
// because the section simply sprang back and looked like it had never been
// turned. It is stored per section like every other decision, so returning to a
// section shows it at the angle it was left at.
addEventListener("mouseup", ()=>{
  if(vDrag){
    vDrag = null;
    save(); drawSec(); status(); paintCell(active);
    return;
  }
  if(ptDrag){
    const {ix, iy, r} = ptDrag;
    ptDrag = null;
    commitPoint(ix, iy, r);
    return;
  }
  if(!rotDrag) return;
  const committed = rotDrag.live && active && draftRot!==null;
  rotDrag = null;
  el("cSec").classList.remove("rotating");
  if(committed){ st(active).rot = draftRot; draftRot = null; save(); paintCell(active); }
  drawSec(); status();
});

// ---- guided mode: the plate's own seeds as a numbered click-through list ----
//
// Free correspondence takes two clicks and the operator has to find the SAME
// anatomical point twice, once on each picture. Guided mode replaces the plate
// half with the seed itself: the list is walked in its fixed order, and one
// click on the section says "seed N is here". Half the clicks, and the plate
// point is exact rather than eyeballed.
//
// What it changes about the RESULT, and this is worth being plain about: a
// landmark placed this way is the operator asserting where a region is, so the
// warp reproduces that assertion at that point exactly - a thin-plate spline
// interpolates its landmarks with zero residual by construction. Seeds that were
// NOT clicked are still atlas-derived, interpolated from the ones that were, and
// those are the rows the atlas is actually doing work for. The residual stops
// being an independent check on a guided pair, so every landmark records the
// seed it came from (or blank for a free click) and the exports carry it. Which
// method produced a number stays recoverable instead of being lost in the mean.
// ON by default, because this IS the curation process rather than an
// alternative to it: the plate's ROIs are numbered, one click places the next
// one on the section at the size you drag, and z steps back. Free
// correspondence is still there behind the button for the cases where the
// useful matching feature is not a region centre, but it is no longer what you
// get by accident on first load.
let guided=true, gTarget=0;
const seedsOf   = s => PLATES[s.plate].seeds;
// ---- the guided walk is over ROIs, not seeds ------------------------------
//
// An ROI is an AREA - one region, one lobe - and the several atlas dots under it
// are samples of it, not things to be measured one by one. So the cursor walks
// the plate's ROIs and asks for a polygon each, and the number it names is the
// number every dot of that ROI carries.
//
// The seeds keep their own numbering underneath; see `region_hulls`. Only what
// is DRAWN and what a polygon RECORDS is the ROI number.
const roisOf = s => (PLATES[s.plate].hulls || []);
// Which ROIs this section already answers. Derived from the polygons rather than
// kept as a separate fact that could disagree with them - the same reason the
// seed cursor was derived from the pairs.
const usedRois = s => new Set(polysOf(s).map(pg => pg.roi).filter(n => n));
// Resume where the section was left off.
function firstUnusedRoi(s){
  const u = usedRois(s), n = roisOf(s).length;
  for(let i = 1; i <= n; i++) if(!u.has(i)) return i;
  return 0;                                  // 0 = nothing left on this plate
}
function gSync(){ gTarget = active ? firstUnusedRoi(st(active)) : 0; }
function gAdvance(){
  // Bounded by the ROI count, not the seed count. Bounding on seeds would run
  // the cursor from 1 to 356 over a list of 134 and point it at nothing.
  const s = st(active), n = roisOf(s).length, u = usedRois(s);
  let t = gTarget + 1; while(t <= n && u.has(t)) t++;
  gTarget = t <= n ? t : 0;
}
// The ROI the cursor is on, or null once the plate is finished.
const gRoi = () => {
  if(!active || !gTarget) return null;
  return roisOf(st(active)).find(h => h.roi === gTarget) || null;
};
function toggleGuided(){
  guided=!guided;
  pending=null;            // a half-made free pair is not a guided one
  draft=null;              // nor is a half-drawn ring
  if(guided) gSync();
  drawSec(); drawPl(); status();
}
// A region that is not on this section is skipped, not outlined somewhere vague.
function skipRoi(){ if(!guided || !active || !gTarget) return;
  draft=null; gAdvance(); drawSec(); drawPl(); status(); }

// ---- placing a landmark: press, size it, release --------------------------
//
// A landmark is a position AND a radius. The radius is set in the same gesture
// that places it: press where the point is, drag out to the size you want, let
// go. A plain click without moving keeps the default, so nothing is slower than
// it was. Sizing afterwards would mean selecting the landmark again and
// remembering which one it was - the size is known at the moment of placing, so
// that is when it is asked for.
//
// This is why the canvas has no onclick any more: a click handler would fire
// after mouseup and place the point a second time.
// Default radius for a new ROI, in canonical grid px. Set once and reused, so
// placing twenty ROIs of the same size is twenty clicks rather than twenty
// drags; dragging still overrides it for the one being placed. Kept in the same
// store as everything else, so it survives a reload like every other decision.
const PT_R_KEY = "ls_roi_curator_v1_size";
let PT_R_CANON = 8;
try { const v = parseFloat(localStorage.getItem(PT_R_KEY)); if(v > 0) PT_R_CANON = v; }
catch(e){}
function onRoiSize(v){
  PT_R_CANON = Math.max(1, +v || 1);
  try { localStorage.setItem(PT_R_KEY, String(PT_R_CANON)); } catch(e){}
  el("roiSizeVal").textContent = PT_R_CANON;
  drawSec();
}
const imgK = () => (secImg.naturalWidth || SEC_GRID) / SEC_GRID;
const defaultR = () => PT_R_CANON * imgK();
// ---- the frame a section's pairs are in ------------------------------------
// Every pair is stored in the pixels of the image the section was SHOWN with,
// and that is not one number per page: a section with a colour composite is
// shown at 768 (04o renders at 3x the canonical grid), one without falls back
// to the 256 greyscale. Both kinds sit on one page. So the frame is recorded on
// the section's record the moment a pair is stored, and export divides each
// section by its OWN frame rather than by whatever happens to be on screen.
//
// A record with no frame predates this. Its pairs were placed on whatever image
// the page showed for that section, which is what the rgb flag says - the same
// rule 04q_import_curation.py uses when it rebuilds a store from the CSVs.
const RGB_FRAME = 3 * SEC_GRID;
const frameOf = uid => D_BY[uid]?.rgb ? RGB_FRAME : SEC_GRID;
const frameIn = (s, uid) => s.frame || frameOf(uid);
// A store written without --rgb holds 256-frame pairs; opened under --rgb the
// section is 768 wide and the pairs would sit in the top-left ninth of it. So
// when the image on screen is not the frame the record says, the pairs are
// lifted into it - positions and radii, so nothing moves relative to the
// tissue - and the record updated. Export reads canonical either way.
function syncFrame(uid){
  const s = S[uid], w = secImg.naturalWidth;
  // Polygons count as something to lift: a section curated entirely with
  // regions has no pairs at all, and stopping here would leave its vertices in
  // the old frame - the top-left ninth of the picture, silently.
  if(!s || !w || !(s.pairs.length || (s.polys && s.polys.length))) return;
  const have = frameIn(s, uid);
  if(have === w) { if(!s.frame){ s.frame = w; } return; }
  const k = w / have;
  s.pairs.forEach(p => { p[0]*=k; p[1]*=k; if(p[5]) p[5]*=k; });
  (s.polys || []).forEach(pg => { pg.v = pg.v.map(c => c * k); });
  s.frame = w; save();
}
// Called wherever a pair is pushed: the frame is the image it was clicked on.
const stampFrame = (s, uid) => { syncFrame(uid); s.frame = secImg.naturalWidth || frameOf(uid); };
const pairR = p => p[5] || defaultR();      // 4- and 5-element pairs predate this
let ptDrag = null;                          // {ix, iy, r} while the button is down

// ---- background discs -----------------------------------------------------
//
// A second kind of disc, marking tissue the operator judges to carry no real
// signal. Everything downstream measures it with the SAME detector as a real
// ROI - that identity is the whole point, because "how many cells does the
// detector find where there are none" is a false-positive rate, and it is
// measured per section rather than assumed.
//
// It is not a negative control. The primary antibody is still on that tissue,
// so this is non-specific binding plus autofluorescence, not zero. It sharpens
// relative comparisons; it does not license absolute positivity.
//
// Stored as a 7th element on an ordinary pair. Pairs are 5 or 6 long already,
// so this is additive and every existing saved section loads unchanged - the
// same reason `companion` extends reformat()'s return rather than altering it.
const BG_MARK = "bg";
const isBg      = p => p[6] === BG_MARK;
const roiPairs  = s => s.pairs.filter(p => !isBg(p));
const bgPairs   = s => s.pairs.filter(isBg);
// Distinct from ROI blue, pending amber, ambiguous gold and guided green, and
// still legible on dark tissue.
const BG_COL = "#f778ba";
let bgMode = false;

// A mode rather than a modifier key, matching Rotate: two or three go down in a
// row, and a held key that slips would silently file a background disc as a
// region - the error that costs most and shows least.
function toggleBgMode(){
  if(!active) return;
  bgMode = !bgMode;
  if(bgMode) rotMode = false;          // two modes owning the mouse is one too many
  el("cSec").classList.toggle("bgmode", bgMode);
  el("cSec").classList.toggle("rotmode", rotMode);
  drawSec(); status();
}

// ---- region polygons ------------------------------------------------------
//
// A region drawn as itself, instead of sampled by a ring of discs. Dl is a
// continuous structure carrying five or six atlas seeds per lobe; five small
// circles on it measure five small circles, not Dl.
//
// A polygon lives BESIDE `pairs`, not inside it, and that separation is the
// point. A pair is a CORRESPONDENCE - two points that answer each other, one on
// the section and one on the plate - and a polygon answers no single point on
// the plate. Keeping them apart is what leaves the landmark fit exactly as it
// was: `transform()` never sees a polygon, so the affine and the spline are
// fitted to the same clicks they always were.
const polysOf = s => (s.polys || (s.polys = []));

// Even-odd ray cast. This runs on a click and a redraw over a dozen vertices,
// not in a loop over pixels, so the obvious algorithm is the right one.
function inPoly(px, py, v){
  let inside = false;
  for(let i = 0, j = v.length - 2; i < v.length; j = i, i += 2){
    const xi = v[i], yi = v[i+1], xj = v[j], yj = v[j+1];
    if((yi > py) !== (yj > py) &&
       px < (xj - xi) * (py - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

// The seeded pairs a polygon encloses - DERIVED, never stored. A vertex dragged
// off a landmark has to stop claiming it, and a stored list would go on saying
// otherwise from the moment the shape changed.
//
// Both are in the section's own frame, the one `syncFrame` keeps them in, so
// this is a plain geometric test with no transform anywhere near it.
// Shoelace, on a flat vertex list. Used to throw out a warped outline with no
// interior: three near-collinear seeds hull to a sliver, and a region of no area
// would reach 06a as a density of something per nothing.
function polyArea(v){
  let a = 0;
  for(let i = 0, j = v.length - 2; i < v.length; j = i, i += 2)
    a += v[j]*v[i+1] - v[i]*v[j+1];
  return Math.abs(a) / 2;
}

// The hull a polygon answers, looked up rather than copied. Colour and the two
// uncertainty flags are properties of the atlas, and reading them off the plate
// each time is what stops the panes from ever disagreeing - the same rule the
// region key already follows. A plate reassigned to one without this region
// leaves the polygon intact and unhulled; it is still the operator's region.
const hullOf = (P, pg) => ((P && P.hulls) || []).find(
  h => h.region === pg.region && h.part === pg.part) || null;
const polyCol = (P, pg) => (hullOf(P, pg) || {}).hex || "#4da3ff";

let draft = null;        // flat [x,y,x,y,...] of the ring being clicked out
// {pi, vi} while a corner of a FINISHED polygon is being dragged. Editing and
// drawing are mutually exclusive by construction: `grabVertex` is only reached
// when `draft` is null, and `addVertex` only when nothing was grabbed.
let vDrag = null;
// The hulls can be taken off the plate. On a crowded plate the shapes overlap
// the seeds they were built from, and sometimes the numbered list is the thing
// being read; `h` puts the plate back the way it was.
let hullsOn = true;
function toggleHulls(){ hullsOn = !hullsOn; drawPl(); status(); }

// How near the first vertex counts as closing the ring, and how near a corner
// counts as grabbing it. In image pixels, so it is the same distance on screen
// whatever frame the section is rendered at.
const closeR = () => 6 * imgK();

function addVertex(ix, iy){
  if(!draft) draft = [];
  // Clicking the first vertex closes the ring. That is how a polygon says it is
  // finished without reaching for a second control mid-gesture; Enter and a
  // double-click do the same thing for anyone who would rather not aim.
  if(draft.length >= 6 &&
     Math.hypot(ix - draft[0], iy - draft[1]) <= closeR()){ commitPoly(); return; }
  draft.push(ix, iy);
  drawSec(); status();
}

function commitPoly(){
  // Three vertices is the floor. Two are a line: it encloses no tissue, and 05a
  // would hand 05c a box with no area in it.
  if(!draft || draft.length < 6 || !active || !gTarget){ return; }
  const h = gRoi();
  if(!h){ return; }
  // ...and an area, not a sliver. Three collinear clicks pass the count and
  // still enclose nothing.
  if(polyArea(draft) < 4 * imgK() * imgK()){ return; }
  undoMark(active, "region polygon");
  const s = st(active);
  stampFrame(s, active);
  // `n` is how many landmarks the section carried when this outline closed.
  // That is the whole order stamp: if it still carries that many, nothing has
  // been placed since and this region is the newer of the two. See undoZ.
  polysOf(s).push({v: draft.slice(), roi: h.roi, region: h.region, part: h.part,
                   n: s.pairs.length});
  draft = null;
  gAdvance();
  save(); drawSec(); drawPl(); status(); paintCell(active);
}

// ---- editing a finished polygon -------------------------------------------
//
// A closed outline stays live: its corners can be moved, added to and removed
// for as long as no new ring is being drawn. That proviso is the whole of the
// interaction rule - while `draft` is open every click is a corner of the ring
// being built, and afterwards every click is aimed at an existing one.

/** Grab a corner, or insert one on an edge and grab that. True if it took. */
function grabVertex(ix, iy){
  const s = st(active), tol = closeR();
  const P = polysOf(s);
  for(let pi = 0; pi < P.length; pi++){
    const v = P[pi].v;
    for(let i = 0; i < v.length; i += 2)
      if(Math.hypot(v[i] - ix, v[i+1] - iy) <= tol){
        undoMark(active, "move corner");
        vDrag = {pi, vi: i};
        return true;
      }
  }
  // Then an edge midpoint, which puts a new corner there and starts dragging it.
  // Same order the atlas tracer used: a corner beats an edge, because moving one
  // is much the commoner action and must not be stolen by a hit on the line.
  for(let pi = 0; pi < P.length; pi++){
    const v = P[pi].v;
    for(let i = 0, j = v.length - 2; i < v.length; j = i, i += 2){
      const mx = (v[i] + v[j]) / 2, my = (v[i+1] + v[j+1]) / 2;
      if(Math.hypot(mx - ix, my - iy) <= tol){
        undoMark(active, "add corner");
        v.splice(i, 0, mx, my);
        vDrag = {pi, vi: i};
        save(); drawSec(); status();
        return true;
      }
    }
  }
  return false;
}

/** Remove the corner under the cursor. Never below three. */
function dropCorner(ix, iy){
  if(draft || !active) return false;
  const s = st(active), tol = closeR();
  for(const pg of polysOf(s)){
    for(let i = 0; i < pg.v.length; i += 2){
      if(Math.hypot(pg.v[i] - ix, pg.v[i+1] - iy) > tol) continue;
      // A polygon of two corners is a line and encloses nothing, so the floor is
      // three. Refusing is better than deleting the shape out from under a
      // mis-aimed key.
      if(pg.v.length <= 6) return false;
      undoMark(active, "remove corner");
      pg.v.splice(i, 2);
      save(); drawSec(); status(); paintCell(active);
      return true;
    }
  }
  return false;
}

// `z` takes back a vertex of the ring being drawn, because that is what the last
// thing placed was. With no ring open it falls through to undoPt.
function dropVertex(){
  if(!draft || !draft.length) return false;
  draft.splice(-2, 2);
  if(!draft.length) draft = null;
  drawSec(); status();
  return true;
}

// True when the last region on the section was placed after the last landmark.
//
// A region records `n`, the number of landmarks that existed when it closed, so
// the two become comparable without a clock: still that many means nothing has
// been placed since and the region is newer; more means a landmark has. A pair
// needs no stamp of its own - it is a positional array with nowhere to put one -
// and there is nothing to keep in step, because `n` lives inside the record that
// undo snapshots and restores.
//
// No `n` means the region predates the stamp, or came back through
// 04q_import_curation.py, which rebuilds polys from roi_regions.csv and has no
// column to rebuild it from. Those read as newer: it is what this did before,
// and it never reaches past an outline to take a landmark instead.
function regionIsNewer(s){
  const polys = polysOf(s);
  if(!polys.length) return false;
  const n = polys[polys.length - 1].n;
  if(n === undefined) return true;
  return s.pairs.length <= n;
}

// What `z` takes back: the last thing placed, whichever kind it was. A vertex
// while a ring is open, then whichever of the last region and the last landmark
// is the newer.
//
// What this fixes: with no ring open, `z` used to go straight to undoPt. Finish
// an outline, press z, and a landmark quietly disappeared while the outline
// stayed - and since undoPoly is on no key at all, `u` was the only way to take
// a region back.
function undoZ(){
  if(dropVertex()) return;
  if(!active) return;
  const s = st(active);
  if(regionIsNewer(s)){ undoPoly(); return; }
  // Nothing placed is not an undo. Marking it would put an entry on the stack
  // that restores the state it was already in.
  if(pending || s.pairs.length) undoPt();
}

function undoPoly(){
  if(!active) return;
  const s = st(active);
  if(!polysOf(s).length) return;
  undoMark(active, "remove region");
  polysOf(s).pop();
  gSync();
  save(); drawSec(); drawPl(); status(); paintCell(active);
}

function commitPoint(ix, iy, r){
  // One mark for all three landings - background disc, guided, and the free
  // pair below - because they are one action to whoever placed it.
  undoMark(active, bgMode ? "background disc" : "place point");
  const s=st(active);
  stampFrame(s, active);
  if(bgMode){
    // No plate coordinate, and deliberately no seed number: the guided cursor
    // must not advance, or placing a background disc would silently consume the
    // next region and desync the click-through order for the rest of the plate.
    s.pairs.push([ix, iy, 0, 0, 0, r, BG_MARK]);
    save(); drawSec(); drawPl(); status(); paintCell(active);
    return;
  }
  // No guided branch any more. It used to push a pair whose PLATE coordinate
  // was the seed's own position - `sd.xf*P.w, sd.yf*P.h` - and under ROI
  // numbering there is no single `sd` to take it from: an ROI is three to six
  // dots. Picking a representative would quietly change what the affine and the
  // spline are fitted to, so the branch goes rather than being adapted. Guided
  // mode draws polygons now; landmarks are placed free, section then plate.
  pending = [ix, iy, r];                     // free mode waits for the plate
  drawSec(); status();
}
function clickPl(e){
  if(!active) return;
  const [px,py]=canvasXY(el("cPl"), e);
  // RE-AIMING. Clicking a region on the plate points the cursor at it, which is
  // how you go back to one you skipped or jump ahead to one you can plainly see.
  // Same gesture the seed walk offered, now over areas.
  if(guided){
    const c=el("cPl"), P=PLATES[st(active).plate], fx=px/c.width, fy=py/c.height;
    let hit=null;
    for(const h of (P.hulls||[])){
      if(h.v.length>=3 && inPoly(fx, fy, h.v.flat())){ hit=h; break; }
    }
    // Falling back to the nearest hull matters more than it looks: a one- or
    // two-seed ROI has no interior to click into at all, and Vl, Vc and Vs are
    // nothing but those. Without this they could never be aimed at.
    if(!hit && (P.hulls||[]).length){
      let bd=Infinity;
      for(const h of P.hulls){
        for(const v of h.v){
          const d=Math.hypot(v[0]-fx, v[1]-fy);
          if(d<bd){ bd=d; hit=h; }
        }
      }
      if(bd > 0.06) hit = null;          // a click on empty plate aims at nothing
    }
    if(hit){ gTarget = hit.roi; draft = null; drawPl(); drawSec(); status(); }
    return;
  }
  if(!pending) return;
  stampFrame(st(active), active);
  st(active).pairs.push([pending[0],pending[1],px,py,0,pending[2]||defaultR()]);
  pending=null;
  save(); drawSec(); drawPl(); status(); paintCell(active);
}
// GENERAL UNDO - one step back, whatever the last thing was.
//
// `z` / "Undo point" is narrow on purpose: it takes back the last landmark and
// nothing else, which is right in the middle of placing a row of them. It does
// nothing about the other eight ways a section's record changes - plate,
// assigned, favourite, no-ROI, exclude, rotation, background disc, a cleared
// set of points - and those are exactly the ones that are easy to hit by
// accident and awkward to reconstruct by hand.
//
// SNAPSHOTS, NOT INVERSE OPERATIONS. Every action here is a small edit to one
// section's record, so storing the record as it was is both simpler and safer
// than writing an inverse for each one: a missing inverse silently half-undoes,
// while a snapshot cannot. `prev: null` records that the section had NO entry,
// so undoing the first edit to an untouched section removes the record rather
// than leaving an empty one the export would report.
const UNDO = [];
const UNDO_MAX = 80;
let undoAt = 0;

function undoMark(uid, label){
  if(!uid) return;
  // COALESCE A DRAG. The slider fires oninput per pixel, so a single scrub from
  // plate 12 to plate 30 would otherwise bury everything else under eighteen
  // identical-looking steps. Same section, same label, within a moment: keep the
  // OLDEST snapshot, because that is the state the drag started from.
  const last = UNDO[UNDO.length - 1];
  const now = Date.now();
  if(last && last.uid === uid && last.label === label && now - last.at < 900){
    last.at = now;
    return;
  }
  UNDO.push({uid, label, at: now,
             prev: Object.prototype.hasOwnProperty.call(S, uid)
                   ? JSON.stringify(S[uid]) : null});
  if(UNDO.length > UNDO_MAX) UNDO.shift();
  undoState();
}

function undoLast(){
  const e = UNDO.pop();
  if(!e){ undoState(); return; }
  // ORDER MATTERS HERE, and getting it wrong silently dropped the plate.
  //
  // select() writes s.plate as a side effect - the slider deliberately does not
  // follow the section, so selecting one records whatever plate is on screen.
  // Restoring first and selecting second therefore undid everything EXCEPT the
  // plate, which select() promptly overwrote again. So the section is shown
  // first, and the record put back afterwards.
  if(DATA.some(d => d.uid === e.uid)) select(e.uid);
  if(e.prev === null) delete S[e.uid];
  else {
    S[e.uid] = JSON.parse(e.prev);
    // and move the slider to what the restored record says, rather than leaving
    // it pointing at a plate the section no longer claims.
    if(active === e.uid){
      el("slider").value = S[e.uid].plate;
      onSlide(S[e.uid].plate);
    }
  }
  save();
  syncReinstated();       // a reinstatement undone has to leave the strip again
  render(); status(); undoState();
}

function undoState(){
  const b = el("undoBtn");
  if(!b) return;
  const e = UNDO[UNDO.length - 1];
  b.disabled = !e;
  b.title = e ? `Undo: ${e.label} on ${e.uid}  (u)`
              : "Nothing to undo (u)";
}

function undoPt(){
  if(!active) return;
  undoMark(active, "undo point");
  if(pending){ pending=null; } else st(active).pairs.pop();
  gSync();                       // the cursor follows the pairs, both ways
  save(); drawSec(); drawPl(); status(); paintCell(active);
}
// Everything placed on this section goes: the landmarks, a half-made pair, a
// half-drawn ring and the regions. This cleared only the landmarks and the
// half-made pair - it was written before regions existed and was never extended
// for them, while every other place that discards work in progress clears
// `pending` and `draft` together (toggleGuided, skipRoi). So an outline
// survived the button that says it clears, and since undoPoly pops one at a
// time there was no way to clear a section's regions at all.
//
// One undo mark covers the lot, so `u` puts the whole section back.
function clearPts(){
  if(!active) return;
  undoMark(active, "clear section");
  const s = st(active);
  s.pairs = [];
  s.polys = [];
  pending = null;
  draft = null;
  save();
  gSync(); drawSec(); drawPl(); status(); paintCell(active);
}

function status(){
  if(!active) return;
  const s=st(active), T=transform(s.pairs);
  const nRoi = roiPairs(s).length, nBg = bgPairs(s).length;
  el("npair").textContent = nRoi;
  el("bgBtn").textContent = bgMode ? "Background \u2713" : "Background";
  el("bgBtn").classList.toggle("bg-on", bgMode);
  el("bgBtn").title = "mark tissue with no real signal - this measures the"
                    + " false-positive rate of the detector on this section";
  // Landmarks are numbered in the order they are placed, so the pair being built
  // right now has a number before it exists. Both panes say which one, and which
  // half of it is outstanding - counting rings to work out "am I on 4 or 5?" is
  // exactly the bookkeeping the numbers are there to remove.
  const nextN = nRoi + 1;
  const roiList = roisOf(s), tgt = gRoi();
  const nRois = roiList.length, nDone = usedRois(s).size;
  const nPoly = polysOf(s).length;

  el("guideBtn").textContent = guided ? "Guided ✓" : "Guided";
  el("guideBtn").classList.toggle("guide-on", guided);
  el("guideBtn").disabled = !nRois;
  el("guideBtn").title = nRois ? ""
    : "this plate carries no regions, so there is no list to walk";
  el("skipBtn").disabled = !(guided && gTarget);
  if(guided){
    // The ambiguity group, not the atlas name, wherever there is one: Vd, Vv and
    // POA cannot be told apart at this level and the pane must not claim they
    // can. `?` is the atlas's own doubt, kept separate from ours.
    const nameOf = h => h ? (h.amb || h.region) + (h.unk ? "?" : "")
                          + (h.n_parts > 1 ? " lobe " + h.part : "") : "";
    const nv = draft ? draft.length / 2 : 0;
    el("secTitle").textContent = tgt
      ? (draft ? `SECTION - drawing ROI ${gTarget} (${nameOf(tgt)}) - ${nv} corners`
               : `SECTION - draw ROI ${gTarget} (${nameOf(tgt)})`)
      : "SECTION - every ROI on this plate is drawn";
    el("plTitle").textContent = tgt
      ? `ATLAS PLATE - ROI ${gTarget} of ${nRois} is the target`
      : "ATLAS PLATE - list finished; click an ROI to go back to it";
    el("lmHint").innerHTML = tgt
      ? `<b style="color:${tgt.hex||"#4da3ff"}">ROI ${gTarget}</b> &middot; `
        + `<b>${nameOf(tgt)}</b> &middot; ${nDone} of ${nRois} drawn`
        + `<br><span style="color:#9aa0a8">click each corner &middot; `
        + `<b>Enter</b>, a double-click or the first corner closes it &middot; `
        + `z drops a corner &middot; Skip if it is not on this section</span>`
      : `all ${nRois} ROIs drawn - click one on the plate to redo it`;
    if(!draft && nPoly) el("lmHint").innerHTML +=
      `<br><span style="color:#9aa0a8">drag a corner to move it &middot; click an`
      + ` edge to add one &middot; Delete removes one</span>`;
  } else {
    el("secTitle").textContent = pending
      ? "SECTION - landmark " + nextN + " placed"
      : "SECTION - click to place landmark " + nextN;
    el("plTitle").textContent = pending
      ? "ATLAS PLATE - click the matching point for landmark " + nextN
      : "ATLAS PLATE - place the section point first";
    el("lmHint").innerHTML = pending
      ? `now click the matching point on the plate for <b>landmark ${nextN}</b>`
      : `click section, then plate - next is <b>landmark ${nextN}</b>`;
  }
  // Sizing owns the hint line while the button is down, but only the hint - the
  // rest of the panel keeps updating underneath.
  if(bgMode){
    el("secTitle").textContent = "SECTION - click tissue with NO signal (background "
                              + (nBg + 1) + ")";
    el("lmHint").innerHTML =
      `<b style="color:${BG_COL}">background mode</b> &middot; ${nBg} placed`
      + `<br><span style="color:#9aa0a8">click tissue you judge to carry no real`
      + ` signal &middot; 2-3 per section &middot; b to leave</span>`;
  }
  // The guided hint says the one thing the picture cannot: WHICH ROI is being
  // asked for, and how far through the plate you are.
  el("hullBtn").textContent = hullsOn ? "Hulls \u2713" : "Hulls";
  el("hullBtn").classList.toggle("reg-on", hullsOn);
  el("hullBtn").title = "show each ROI on the plate as one shape rather than"
                      + " loose seeds (h)";
  el("undoPolyBtn").disabled = !nPoly;
  if(ptDrag){
    el("lmHint").innerHTML =
      `radius <b>${(ptDrag.r/imgK()).toFixed(1)} px</b> `
      + `<span style="color:#9aa0a8">drag out to size &middot; release to place</span>`;
  }
  // Residual per landmark: a mis-clicked pair shows as a large error instead of
  // quietly dragging the whole fit.
  let html="";
  if(T){
    let tot=0;
    roiPairs(s).forEach(([sx,sy,px,py],i)=>{
      const [X,Y]=apply(T,px,py), r=Math.hypot(X-sx,Y-sy); tot+=r;
      html += `<div class="${r>25?"bad":""}"><span>#${i+1}</span><span>${r.toFixed(1)} px</span></div>`;
    });
    // Both counts are LANDMARKS. `tot` is summed over roiPairs, so dividing by
    // s.pairs.length would have shrunk the mean residual by however many
    // background discs the section carried - a fit quietly reported as better
    // than it is, and better the more background was marked.
    el("fit").innerHTML = T.kind==="tps"
      ? `<b style="color:#7c5cff">thin-plate spline</b> on ${nRoi} points `
        + `&middot; residual is 0 by construction`
      : `<b>affine</b> &middot; mean residual <b>${(tot/nRoi).toFixed(1)} px</b>`;
    const P=PLATES[s.plate];
    // Ambiguous regions are listed as their group and flagged, so the summary
    // never reads as a firmer claim than the section supports.
    // The names were printed in one flat colour under a legend reading
    // "gold = not separable", so the legend pointed at nothing and the caveat
    // read as covering the whole list. It covers exactly one entry. Dl, Dm and
    // the rest are distinct locations and are not qualified by anything -
    // colouring the ambiguous entry is what makes that visible.
    const names = [...new Set(P.seeds.map(x => x.amb || x.region))];
    const gold = new Set(P.seeds.filter(x => x.amb).map(x => x.amb));
    const shown = names.map(n => gold.has(n)
      ? `<span style="color:#e3b341">${n}</span>` : n).join(", ");
    el("regInfo").innerHTML = P.seeds.length
      ? `<b>${usedRois(s).size}</b> of <b>${(P.hulls||[]).length}</b> drawn: ${shown}`
        + bgLine(s)
        + (gold.size ? `<div style="color:#9aa0a8;margin-top:4px">`
                  + `<span style="color:#e3b341">gold</span> is ONE group whose members`
                  + ` cannot be told apart without the rostrocaudal level.`
                  + ` Every other region listed is a distinct place.</div>` : "")
      : "<span class='unlab'>this plate has no region seeds</span>";
  } else {
    el("fit").textContent = "";
    el("regInfo").innerHTML = `${nRoi} landmark${nRoi === 1 ? "" : "s"} placed`
      + bgLine(s);
    roiPairs(s).forEach((_,i)=>html+=`<div><span>#${i+1}</span><span>-</span></div>`);
  }
  el("lmlist").innerHTML = html;
  const sa = st(active);
  el("noroiBtn").textContent = sa.noroi ? "No ROI here ✓" : "No ROI here";
  el("noroiBtn").style.borderColor = sa.noroi ? "#3fb950" : "";
  el("favBtn").textContent = sa.fav ? "Favourite ★" : "Favourite";
  el("favBtn").classList.toggle("fav-on", !!sa.fav);
  el("exclBtn").textContent = sa.excl ? "Excluded ✕" : "Exclude";
  el("exclBtn").classList.toggle("kill-on", !!sa.excl);
  // Two facts now, not three: is the tool open, and what is drawn. There is no
  // uncommitted state left to report, because the drag commits itself.
  const saved = sa.rot||0;
  // Outside the transform branch on purpose: the colour key is a fact about
  // the plate on screen, and it is most wanted before three landmarks exist,
  // not after.
  regionKey(PLATES[st(active).plate], st(active));
  navState();
  dapiBtnState();
  el("rotBtn").textContent = rotMode ? "Rotate ✓" : "Rotate";
  el("rotBtn").classList.toggle("mode-on", rotMode);
  el("rotReset").disabled = !(saved || draftRot);
  const dim = t => `<span style="color:#9aa0a8">${t}</span>`;
  el("rotInfo").innerHTML =
      rotDrag ? `tilt <b>${effRot().toFixed(1)}&deg;</b> ` + dim("release to keep")
    : rotMode ? `tilt <b>${saved.toFixed(1)}&deg;</b> ` + dim("drag left/right &middot; shift = fine &middot; kept on release")
    : saved   ? `tilted <b>${saved.toFixed(1)}&deg;</b> ` + dim("view only, landmarks unaffected")
    : dim("press Rotate to tilt the view");
}

// Called by the slider's oninput, which fires ONLY on user interaction -
// setting .value from script does not dispatch it. That is what makes the
// distinction between "the operator chose this plate" and "this section has
// never been looked at" reliable.
function onSlideUser(v){
  undoMark(active, "plate");
  const s=st(active); s.assigned=true; save(); onSlide(v); paintCell(active);
}
function markAssigned(){ if(active){ undoMark(active, "assign plate"); st(active).assigned=true; save(); paintCell(active); status(); } }
// Favourite marks the subset chosen for actual quantification. It is ORTHOGONAL
// to the plate assignment - a section can be worth quantifying before anyone has
// landmarked it - so it sets no other flag and the export carries it on its own.
function toggleFav(){
  if(!active) return;
  undoMark(active, "favourite");
  const s=st(active); s.fav=!s.fav; save(); paintCell(active); status();
}
function toggleNoRoi(){
  if(!active) return;
  undoMark(active, "no ROI");
  const s=st(active); s.noroi=!s.noroi; if(s.noroi) s.assigned=true;
  save(); paintCell(active); status();
}

// EXCLUDE is not "no ROI here". No-ROI says the section is fine and simply has
// nothing to measure at this level; exclude says the section itself should not
// be used. They are recorded separately because they mean different things to
// whoever reads the export.
function toggleExcl(){
  if(!active) return;
  undoMark(active, "exclude");
  const s=st(active);
  s.excl = !s.excl;
  save(); paintCell(active); status();
}

// The buttons and the arrow keys are the same two moves, so they are the same
// two functions. Wiring the buttons to their own copy would let the pair drift -
// and it is the kind of drift nobody notices, because both still appear to work.
function stepPlate(d){
  if(!active) return;
  const v = Math.min(PLATES.length - 1, Math.max(0, +el("slider").value + d));
  el("slider").value = v;
  onSlide(v);
  navState();
}
function stepSection(d){
  if(!active) return;
  const list = rows(), i = list.findIndex(x => x.uid === active);
  const j = i + d;
  if(i < 0 || j < 0 || j >= list.length) return;
  select(list[j].uid);            // the plate stays put, as with the arrow keys
}
// Grey a button out at the ends rather than have it silently do nothing - the
// strip already shows where you are, and this says where you can still go.
function navState(){
  const list = rows(), i = list.findIndex(x => x.uid === active);
  const v = +el("slider").value;
  el("secPrev").disabled = !(i > 0);
  el("secNext").disabled = !(i >= 0 && i < list.length - 1);
  el("plPrev").disabled = !active || v <= 0;
  el("plNext").disabled = !active || v >= PLATES.length - 1;
}

function onSlide(v){
  const s=st(active); s.plate=+v; save();
  gSync();                     // a different plate is a different seed list
  const P=PLATES[+v];
  el("plName").textContent = P.id;
  el("plLab").innerHTML = P.labelled
    ? `<span class="lab">${P.seeds.length} region seeds: ${[...new Set(P.seeds.map(x=>x.region))].join(", ")}</span>`
    : `<span class="unlab">no region labels on this plate</span>`;
  drawPl(); status();
  // NO render() here. render -> select -> onSlide -> render was a cycle: on load
  // it recursed until the stack blew, leaving the page half-built with dead
  // handlers - which looks exactly like "the buttons do nothing".
}

function select(uid, keep){
  // THE SECTION MAY NOT BE IN THE FILTERED VIEW, and this used to be a crash
  // that left the tool lying about what was selected.
  //
  // `rows()` is the strip AFTER the filters. Ticking "hide excluded" or
  // "favourites only" while a section is active drops it out, and the next
  // select() found i = -1, took list[-1] as undefined, and threw on `d.uid` -
  // but `active` had already been reassigned on the line above. So the big view
  // still showed the PREVIOUS section while every subsequent edit went to the
  // hidden one: assigning a plate wrote plate and assigned=true onto a section
  // that was not on screen, which reads as "this section will not take a plate".
  //
  // So the row is looked up in the unfiltered set when the filtered one does not
  // have it, and the position line says the filter is hiding it rather than
  // claiming a place in a list it is not in. Nothing is reassigned before we
  // know the section can actually be drawn.
  const list = rows();
  const i = list.findIndex(d => d.uid === uid);
  const d = i >= 0 ? list[i] : DATA.find(x => x.uid === uid);
  if(!d) return;                  // not a section this page has at all
  active = uid; pending = null; gSync();
  const s = st(uid);
  el("secInfo").innerHTML = `<b>${d.uid}</b><br>section ${d.order} &middot; `
    + (i >= 0 ? `${i + 1} of ${list.length}`
              : `<span style="color:var(--warn,#d29922)">hidden by the current filter</span>`);
  // The plate slider does NOT follow the section. Serial sections sit at
  // neighbouring atlas levels, so the plate just scrubbed to is nearly always
  // still the right one; reloading each section's stored plate meant every z/x
  // snapped the slider back and the level had to be found again by hand.
  // The one exception is a section carrying a real decision - assigned, or
  // landmarked - where the stored plate IS the thing worth seeing.
  draftRot = null;            // a tilt drafted on one section is not another's
  // Landmarks, not all pairs: a background disc says where there is no signal,
  // which is no evidence at all about which plate this section is - snapping
  // the slider on one would jump to the default plate and look like a decision.
  const decided = s.assigned || roiPairs(s).length > 0;
  const p = decided ? s.plate : Math.min(PLATES.length - 1, +el("slider").value || 0);
  el("slider").value = p;
  secImg.src = d.img;
  onSlide(p);
  document.querySelectorAll(".cell").forEach(c=>c.classList.toggle("active", c.dataset.uid===uid));
  if(!keep) document.querySelector(`[data-uid="${CSS.escape(uid)}"]`)
    ?.scrollIntoView({inline:"center", block:"nearest"});
}
// LANDMARKS, not pairs: a background disc is a pair too, and three of them
// would light the cell green with nothing registered.
const nRoi     = uid => S[uid]?.pairs ? roiPairs(S[uid]).length : 0;
const isDone   = uid => nRoi(uid) >= 3;
const isNoRoi  = uid => !!S[uid]?.noroi;
// A REINSTATEMENT BEATS THE EXCLUSION FLAG. Both live in the same record, and
// a section that is flagged excluded while carrying act:"restore" would be
// hidden by "hide excluded", drawn red, and counted as excluded - by the same
// tool the operator just used to put it back. revAct() clears the flag too, so
// this is a belt on top of that; it also covers a store written before that
// existed.
const isExcl   = uid => !!S[uid]?.excl && S[uid]?.rev?.act !== "restore";
const isReinstated = uid => S[uid]?.rev?.act === "restore";
// Plate chosen deliberately but not landmarked - a real decision, and one the
// export used to discard.
const isPlateOnly = uid => !!S[uid]?.assigned && !isDone(uid) && !isNoRoi(uid);

// One source of truth for a cell's appearance, so the full build and the
// single-cell update cannot drift apart.
function cellClass(uid){
  // Exclusion wins the cell's appearance - it is the fact that decides whether
  // anything else about the section matters.
  const base = isExcl(uid) ? "excl"
             : isDone(uid) ? "done" : isNoRoi(uid) ? "noroi"
             : isPlateOnly(uid) ? "plateonly" : "";
  const cls = isReinstated(uid) ? (base + " reinstated").trim() : base;
  return S[uid]?.fav ? cls + " fav" : cls;
}
function cellTag(uid){
  const s=S[uid], n=nRoi(uid);
  if(isExcl(uid)) return "excluded";
  // Said on the cell, because a reinstated section is curatable but is NOT in
  // the index yet, and nothing else on the strip distinguishes it.
  if(isReinstated(uid) && !n) return "reinstated";
  return isNoRoi(uid) ? "no ROI" : n ? n+" pts"
       : isPlateOnly(uid) ? PLATES[s.plate].id.replace("plate_","pl ") : "";
}
function counts(){
  const list=rows();
  el("nsec").textContent    = list.length;
  el("ndone").textContent   = list.filter(d=>isDone(d.uid)).length;
  el("nassign").textContent = list.filter(d=>isPlateOnly(d.uid)).length;
  el("nnoroi").textContent  = list.filter(d=>isNoRoi(d.uid)).length;
  // counted over the animal, not the filtered view, so it does not collapse to
  // the list length the moment "favourites only" is ticked
  el("nfav").textContent    = inScope().filter(d=>S[d.uid]?.fav).length;
  el("nexcl").textContent   = inScope().filter(d=>isExcl(d.uid)).length;
}
// Update ONE strip cell. Every interaction used to rebuild all 87 cells and
// reload their images, which is why it felt slow even when it was not recursing.
// The strip preview turns with the section. A tilt set in the big view but not
// reflected in the strip leaves the two disagreeing about what a section looks
// like, and the strip is the thing being scanned when hunting for one.
//
// Read S directly rather than through st(): this runs for every visible cell on
// every render, and st() would create a state entry for each one, turning "shown
// in the strip" into "has a record".
// Which colour means which region, taken from the seeds themselves so it can
// never drift from what is drawn. Counted per region, because "Dl" appearing
// fourteen times on a plate is worth knowing when reading the overlay - and the
// numbers those seeds carry are the order they are placed in.
function bgLine(s){
  const n = bgPairs(s).length;
  if(n >= 2) return `<div style="margin-top:4px;color:${BG_COL}">`
                  + `<b>${n}</b> background discs</div>`;
  // Only nag where it matters. A section nobody has decided to measure does not
  // need a background level yet, so the prompt waits for the favourite.
  const want = s.fav ? `<div style="margin-top:4px;color:#d29922">`
                     + `<b>${n}</b> background ${n === 1 ? "disc" : "discs"} - `
                     + `2-3 give this section a reference level and a `
                     + `false-positive rate (press b)</div>`
             : `<div style="margin-top:4px;color:#9aa0a8">${n} background discs</div>`;
  return want;
}

function regionKey(P, s){
  const box = el("regKey");
  if(!box) return;
  const HL = (P && P.hulls) || [];
  if(!HL.length){ box.innerHTML = ""; return; }
  // One row per ROI, because an ROI is the thing being drawn. It used to be one
  // row per region with a count of its seeds, which answered "how many dots does
  // Dl have" - a question nobody asks - instead of "which shapes do I still owe".
  //
  // Keyed on the atlas's OWN region name, not the ambiguity group: grouping Vd,
  // Vv and POA gave them one swatch when they are drawn in three colours, and a
  // key showing red for a grey dot is worse than no key. Membership is flagged
  // on each row instead.
  const done = s ? usedRois(s) : new Set();
  box.innerHTML = HL.map(h => {
    const isDone = done.has(h.roi);
    const tip = `ROI ${h.roi} - ${h.region}`
              + (h.n_parts > 1 ? `, lobe ${h.part} of ${h.n_parts}` : "")
              + (h.amb ? `  -  one of ${h.amb}, which cannot be told apart`
                       + ` without the rostrocaudal level` : "")
              + (isDone ? "  -  drawn" : "  -  not drawn yet");
    return `<div title="${tip}"><i style="background:${h.hex}"></i>`
         + `<b style="${h.amb ? "color:#e3b341" : ""}${isDone ? ";opacity:.45" : ""}">`
         + `${h.roi}. ${h.region}${h.unk ? "?" : ""}`
         + `${h.n_parts > 1 ? " /" + h.part : ""}</b>`
         + `<span>${isDone ? "\u2713" : ""}</span>`
         + (h.amb ? `<span style="color:#e3b341">&#9670;</span>` : "")
         + `</div>`;
  }).join("")
    // Background is not a region on the plate, so it has no seed to read a
    // colour off - but it IS drawn on the section, and a key showing every
    // colour except the pink one would be a key with a hole in it.
    + `<div title="tissue marked as carrying no real signal - measured by the`
    + ` same detector, so it reports a false-positive rate">`
    + `<i style="background:${BG_COL}"></i><b>background</b>`
    + `<span>B1, B2, ...</span></div>`;
}

function rotOf(uid){ return (S[uid] || {}).rot || 0; }

// A square rotated inside a square box overflows it by (|cos|+|sin|), so scale
// by the inverse to keep the whole section visible. Same reasoning as the main
// canvas being the diagonal of the image - nothing gets cropped by turning it -
// applied to the box the strip already has.
function rotCss(deg){
  if(!deg) return "";
  const a = deg * Math.PI / 180;
  const k = 1 / (Math.abs(Math.cos(a)) + Math.abs(Math.sin(a)));
  return `rotate(${deg}deg) scale(${k.toFixed(4)})`;
}

// Just the transform, for the live update during a drag - paintCell() also
// rewrites classes and recounts, which is far too much to do per mousemove.
function paintCellRot(uid, deg){
  const img = document.querySelector(`[data-uid="${CSS.escape(uid)}"] img`);
  if(img) img.style.transform = rotCss(deg === undefined ? rotOf(uid) : deg);
}

function paintCell(uid){
  const c=document.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
  if(!c) return;
  c.className = "cell " + cellClass(uid) + (active===uid ? " active" : "");
  const cap=c.querySelector(".cap");
  if(cap) cap.innerHTML = `${DATA.find(d=>d.uid===uid).order}<br>${cellTag(uid)}`;
  paintCellRot(uid);
  counts();
}
// Full rebuild. Only on load and on animal change - not on interaction.
// Why the strip is empty, said in terms this page can vouch for.
//
// It does NOT guess at the reason a channel is missing for an animal - that is
// a property of the analysis set and was decided upstream. What it can state is
// the count it holds: "LS53 has no pERK sections here, it has 73 PCNA ones" is
// a fact, and it is also exactly what the operator needs in order to act.
function emptyNote(){
  const a = el("animal").value, m = el("marker").value;
  const mine = DATA.filter(d => d.animal === a);
  if(!mine.length) return `<b>${a}</b> has no sections in this page at all.`;
  const label = {}; MARKERS.forEach(k => label[k.id] = k.label);
  const by = {};
  for(const d of mine) by[d.m] = (by[d.m] || 0) + 1;
  const have = Object.keys(by).sort()
    .map(k => `<b>${by[k]}</b> ${label[k] || k}`).join(" and ");
  return `<b>${a}</b> has no ${label[m] || m} sections in this subset`
       + ` - it has ${have}. Change the channel selector to see them.`;
}

// Nothing selected: blank everything that describes a section.
//
// render() used to leave the panes alone when the list came back empty. active
// went null, select() was never called, and the section canvas, the plate and
// the whole sidebar kept showing the PREVIOUS animal - so choosing LS53, which
// has no pERK sections at all, left LS22's section on screen under LS53's name.
// An empty strip with someone else's tissue above it is worse than an error.
function showEmpty(){
  const note = emptyNote();
  el("strip").innerHTML = `<div class="empty">${note}</div>`;
  el("secTitle").textContent = "SECTION - nothing to show";
  el("plTitle").textContent = "ATLAS PLATE";
  el("secInfo").innerHTML = note;
  el("rotInfo").textContent = "";
  el("lmHint").textContent = "";
  el("lmlist").innerHTML = "";
  el("regInfo").textContent = "";
  el("regKey").innerHTML = "";
  el("fit").textContent = "";
  el("npair").textContent = "0";
  el("plName").textContent = "-";
  el("plLab").innerHTML = "";
  for(const id of ["cSec", "cPl"]){
    const c = el(id);
    c.getContext("2d").clearRect(0, 0, c.width, c.height);
  }
  navState();
}

function render(){
  const list=rows();
  counts();
  el("strip").innerHTML = list.map(d=>
    `<div class="cell ${cellClass(d.uid)} ${active===d.uid?"active":""}"
      data-uid="${esc(d.uid)}">
      <img src="${d.img}" loading="lazy" alt="" style="transform:${rotCss(rotOf(d.uid))}">
      <div class="cap">${d.order}<br>${cellTag(d.uid)}</div></div>`).join("");
  if(active && !list.some(d=>d.uid===active)) active=null;
  if(list.length) select(active && list.some(d=>d.uid===active) ? active : list[0].uid, true);
  else showEmpty();
}

addEventListener("keydown", e=>{
  // Ctrl/Cmd/Alt chords belong to the browser - Ctrl+F finds, Ctrl+X cuts -
  // and a chord must never read as the bare letter. Shift is a real modifier
  // here (Shift+drag snaps), so it is left alone.
  if(e.ctrlKey || e.metaKey || e.altKey) return;
  // A focused control eats its own keys - but only the ones it actually uses.
  //
  // This used to bail on ANY input, which killed the arrows for good: tick
  // "hide excluded" once and focus sits on that checkbox, and clicking the
  // section cannot take it back because a canvas is not focusable and secDown
  // calls preventDefault. Left and right then did nothing for the rest of the
  // session, with nothing on screen to explain why.
  //
  // Only two controls genuinely need protecting: the plate slider steps itself
  // on the arrows (so letting them through moves two plates per press), and the
  // animal select does type-ahead that would swallow the letter shortcuts.
  const t = e.target, tag = t && t.tagName;
  if(tag==="TEXTAREA" || tag==="SELECT") return;
  if(tag==="INPUT"){
    if(t.type==="range" && e.key.startsWith("Arrow")) return;
    if(t.type==="text" || t.type==="search" || t.type==="number") return;
  }
  // Review mode has its OWN keys and must not fall through to the ROI ones.
  // Every letter below is bound: `x` excludes a section from measurement, `b`
  // starts a background disc. Firing those from a screen that is about the
  // upstream decisions would be a silent edit to work the operator is not
  // looking at.
  if(revOn){
    if(e.key==="ArrowDown"){ revStep(1); e.preventDefault(); }
    else if(e.key==="ArrowUp"){ revStep(-1); e.preventDefault(); }
    else if(e.key==="d" || e.key==="D"){ revLayer("dapi"); }
    // `k` for the marker, because `m` is already the mask and moving a binding
    // people have in their fingers costs more than an imperfect mnemonic.
    else if(e.key==="k" || e.key==="K"){ revLayer("mark"); }
    else if(e.key==="v" || e.key==="V"){ revLayer("art"); }
    else if(e.key==="c" || e.key==="C"){ revLayer("cen"); }
    else if(e.key==="m" || e.key==="M"){ revLayer("apply"); }
    else if(e.key==="f" || e.key==="F"){ revFull(); }
    // Escape closes it. With native fullscreen refused there is no
    // fullscreenchange to listen for, so the key has to be handled directly -
    // otherwise the only way out of a maximised card is the button, and a
    // maximised card is exactly when the button is easiest to lose.
    else if(e.key==="Escape" && el("revImgCard")
            && el("revImgCard").classList.contains("imgmax")){
      revFull(false); e.preventDefault();
    }
    return;
  }
  if(!active) return;
  const list=rows(), i=list.findIndex(d=>d.uid===active);
  if(e.key==="ArrowRight"){ stepPlate(1); e.preventDefault(); }
  else if(e.key==="ArrowLeft"){ stepPlate(-1); e.preventDefault(); }
  // Arrows move, letters act. x used to be "next section", paired with z; the
  // up/down arrows do that now, so the pair is retired rather than left half
  // bound - leaving z on prev while x excluded would make the muscle memory of
  // one a trap for the other.
  else if(e.key==="ArrowDown"){ stepSection(1); e.preventDefault(); }
  else if(e.key==="ArrowUp"){ stepSection(-1); e.preventDefault(); }
  else if(e.key==="a" || e.key==="A"){ markAssigned(); }
  else if(e.key==="f" || e.key==="F"){ toggleFav(); }
  else if(e.key==="x" || e.key==="X"){ toggleExcl(); }
  // One key, whichever thing was placed last - vertex, then region, then
  // landmark. See undoZ.
  else if(e.key==="z" || e.key==="Z"){ undoZ(); }
  else if(e.key==="r" || e.key==="R"){ restoreTilt(); }
  // Enter closes the ring, Escape abandons it. Both only while one is open, so
  // neither steals a key from the rest of the page.
  else if(e.key==="Enter" && draft){ commitPoly(); e.preventDefault(); }
  else if(e.key==="Escape" && draft){ draft=null; drawSec(); status(); e.preventDefault(); }
  // Delete removes the corner under the cursor. Only meaningful with no ring
  // open, which `dropCorner` enforces rather than trusting the caller.
  else if(e.key==="Delete" || e.key==="Backspace"){
    if(active && lastSec) dropCorner(lastSec[0], lastSec[1]);
    e.preventDefault();
  }
  else if(e.key==="h" || e.key==="H"){ toggleHulls(); }
  // u is the general undo, d is the background DISC, and b is deliberately
  // unbound: it was the disc for long enough to be muscle memory, and a key
  // that used to place something and now undoes is the worst of both. Leaving
  // it dead is the safe end of that trade.
  else if(e.key==="u" || e.key==="U"){ undoLast(); }
  else if(e.key==="d" || e.key==="D"){ toggleBgMode(); }
  else if(e.key==="g" || e.key==="G"){ toggleGuided(); }
  else if(e.key==="s" || e.key==="S"){ skipRoi(); }
  else if(e.key==="[" || e.key==="]"){
    const step = e.key === "]" ? 1 : -1;
    const v = Math.min(60, Math.max(1, PT_R_CANON + step));
    el("roiSize").value = v; onRoiSize(v); e.preventDefault();
  }
});

function exportCsv(){
  // THREE files, because there are three different decisions and collapsing them
  // loses one. A plate assignment is a judgement in its own right - "this section
  // is plate_020" - and it used to be discarded whenever it carried fewer than
  // three landmarks, which is exactly the case where the operator has decided the
  // section is not worth landmarking.
  const pl=[["scene_uid","animal","marker","subset","section_order","plate_set","plate_id","plate_index",
             "plate_has_seeds","n_landmarks","n_background","transform","status",
             "favorite","view_rotation_deg",
             "excluded"]];
  // seed_n / seed_region say whether a landmark was placed against a numbered
  // atlas seed (guided) or free-clicked, and which one. A guided pair is the
  // operator asserting a region position, so the spline reproduces it exactly
  // and its residual is not an independent check - the analysis has to be able
  // to tell the two apart, and blank means free.
  const lm=[["scene_uid","animal","marker","section_order","plate_set","plate_id","pair",
             "sec_x","sec_y","sec_r","plate_x","plate_y","residual_px",
             "seed_n","seed_region"]];
  // sec_r is the radius the ROI was placed with - the area to quantify - and
  // seed_n says which numbered atlas ROI it answers.
  //
  // roi_kind separates the two kinds of disc, and it is the ONLY thing that
  // separates them: identical columns, identical units, identical meaning of
  // sec_x/sec_y/sec_r. Everything downstream measures both the same way, which
  // is what makes the background rows a false-positive rate rather than a
  // different quantity that happens to live nearby.
  // roi_shape is a SECOND AXIS, not a replacement for roi_kind. A row is still
  // a real ROI or a background reference; what roi_shape adds is whether its
  // geometry is a radius or a ring of vertices.
  //
  // sec_r is BLANK on a polygon row, deliberately. A polygon has no radius, and
  // writing an equivalent-area one would put a number in a column every reader
  // treats as a measurement. sec_x/sec_y stay filled with the centroid, because
  // 06a's nucleus-to-ROI join is positional and wants a position.
  //
  // New columns are APPENDED. Every reader of this file indexes by header, and
  // an older one that has never heard of a polygon keeps working.
  const rg=[["scene_uid","animal","marker","plate_set","plate_id","roi_kind","region",
             "region_ambiguous","ambiguity_group","region_uncertain_in_atlas",
             "sec_x","sec_y","sec_r","seed_n","n_landmarks","transform",
             "mean_residual_px","roi_shape","part","sec_poly","roi_n",
             // How many landmarks the section carried when this outline was
             // closed - the order stamp `z` compares against, written out so it
             // survives 04q_import_curation.py rather than being lost on the way
             // back in. Named for what it holds: `n_landmarks` two columns over
             // is the section's count now, this one is the count back then.
             // Blank on every row that is not a polygon.
             "landmarks_at_draw"]];

  for(const d of DATA){
    const s=S[d.uid];
    // A favourite is a decision too, so it is reported even with no plate yet.
    // An exclusion is a judgement in its own right, exactly like a favourite or
    // a bare plate assignment, so it is reported even when nothing else was done
    // to the section.
    // Background discs are work too, so a section carrying only those is
    // reported rather than dropped for having made no other decision.
    if(!hasRoiWork(s)) continue;
    const P=PLATES[s.plate], n=roiPairs(s).length, nBg=bgPairs(s).length;
    const T=transform(s.pairs);
    const chosen = s.assigned || n>0;   // is the plate a decision, or still the default?
    // isExcl(), not s.excl: a Review-mode reinstatement beats the flag, and the
    // strip already honours that. The two must not disagree.
    const excl = isExcl(d.uid);
    const status = excl ? "excluded"
                 : s.noroi ? "no_roi" : n>=3 ? "registered"
                 : chosen ? "plate_only" : "favourite_only";
    // Blank rather than plate_001 when no plate was ever chosen - otherwise a
    // favourite with no assignment reads as a deliberate call on plate_001.
    pl.push([d.uid,d.animal,d.m,d.sub,d.order,PLATE_SET, chosen?P.id:"", chosen?s.plate:"",
             chosen?(P.labelled?1:0):"", n, nBg, T?T.kind:"", status,
             s.fav?1:0, (s.rot||0).toFixed(1),
             excl?1:0]);
    // Gate on the landmarks themselves, NOT on status - a section that was
    // landmarked and then excluded still has that work, and keying this on
    // status would silently drop it from both files the moment the exclude
    // button was pressed. The exclusion is recorded in roi_plates.csv; dropping
    // a section is a filter on that, not a hole in this one.
    // Coordinates are captured in the pixels of the image the SECTION was shown
    // with, and 04o renders that at a multiple of the canonical grid only where
    // it has built a composite. Divide by each section's own multiple on the
    // way out so sec_x/sec_y always mean canonical-frame pixels - the same
    // frame the masks and every other reformatted product live in. Residuals
    // are a length in the same space, so they scale too.
    //
    // This used to read the image on screen once and divide every row by it,
    // which was right only while every section on the page had the same frame.
    // With composites for some sections and greyscale for the rest, the rows
    // of whichever kind was not active were three times too large or too
    // small, and nothing on screen said so.
    const K = frameIn(s, d.uid) / SEC_GRID;

    // Background discs need neither a transform nor three landmarks: they are
    // positions on the section, full stop. Emitting them ABOVE the gate means a
    // section the operator landmarked lightly still contributes its background
    // measurement - and that measurement is per section, so losing it would
    // leave the section's own ROIs with no reference level of their own.
    for(const pr of bgPairs(s)){
      rg.push([d.uid,d.animal,d.m,PLATE_SET, chosen?P.id:"", "background","__background__",
               0,"",0,
               (pr[0]/K).toFixed(2),(pr[1]/K).toFixed(2),(pairR(pr)/K).toFixed(2),
               "", n, "", "", "disc","","","",""]);
    }

    // Polygons count. A region drawn over tissue is an ROI whether or not a
    // single landmark was placed on that section, and gating on `n` alone would
    // have dropped exactly the sections curated the new way.
    if(!n && !polysOf(s).length) continue;   // nothing placed - nothing to say

    // The residual needs a transform; the POSITION does not. This used to be
    // gated as `n < 3 || !T`, which made a fit the price of admission for both
    // files - so a section with two landmarks, or three collinear ones, exported
    // nothing at all and looked exactly like a section nobody had touched.
    //
    // Since the automatic placement was removed, a landmark and an ROI are both
    // just things the operator put somewhere. They are recorded whether or not a
    // transform happens to exist, and the residual columns go blank when it does
    // not, which is the honest way to say "not measurable" rather than "zero".
    let tot=0;
    roiPairs(s).forEach((pr,i)=>{
      const [sx,sy,px,py,sn]=pr;
      let r=null;
      if(T){ const [X,Y]=apply(T,px,py); r=Math.hypot(X-sx,Y-sy); tot+=r; }
      const sd = sn ? P.seeds[sn-1] : null;
      lm.push([d.uid,d.animal,d.m,d.order,PLATE_SET,P.id,i+1,
               (sx/K).toFixed(2),(sy/K).toFixed(2),(pairR(pr)/K).toFixed(2),
               px.toFixed(2),py.toFixed(2), r===null ? "" : (r/K).toFixed(2),
               sn||"", sd ? ((sd.amb || sd.region) + (sd.unk ? "?" : "")) : ""]);
    });
    // T is null below three landmarks, so n is never 0 where this divides.
    const mr = T ? (tot/n/K).toFixed(2) : "";
    // One row per REGION drawn. The vertex list is the geometry; the centroid
    // is written into sec_x/sec_y so a positional join still has a position to
    // work with, and sec_r is left empty because there is no radius to state.
    //
    // roi_n is which numbered ROI on the plate this area answers. It is the
    // identity now - one number per region per lobe, the same number every dot
    // of that ROI carries on the atlas - and it replaces seed_n, which named a
    // single dot and cannot name an area.
    for(const pg of polysOf(s)){
      const h = hullOf(P, pg);
      const vs = [];
      let cx=0, cy=0;
      for(let i=0;i<pg.v.length;i+=2){
        cx += pg.v[i]; cy += pg.v[i+1];
        vs.push((pg.v[i]/K).toFixed(2) + " " + (pg.v[i+1]/K).toFixed(2));
      }
      const nv = pg.v.length/2;
      rg.push([d.uid,d.animal,d.m,PLATE_SET,P.id,"roi",pg.region,
               h&&h.amb?1:0, (h&&h.amb)||"", h&&h.unk?1:0,
               (cx/nv/K).toFixed(2),(cy/nv/K).toFixed(2),"",
               "", n, T?T.kind:"", mr,
               // Not `pg.n || ""`: the stamp is 0 for a region drawn before
               // any landmark, and that is a real value, not a missing one.
               "polygon", pg.part, vs.join(";"), pg.roi || "",
               pg.n === undefined ? "" : pg.n]);
    }
  }
  beginExport();
  dl(pl,"roi_plates.csv");
  dl(lm,"roi_landmarks.csv");
  dl(rg,"roi_regions.csv");
}
// Every cell goes through csvq: a field with a comma, a quote or a newline is
// RFC-4180 quoted, anything else is written as it was. Region names like
// "Rm (Raphe) ??" and subsets like roi_worklist:core are already in these
// files, and the first name to carry a comma would have shifted every column
// after it - in a file whose readers index columns by header.
// ===========================================================================
// EXPORT DESTINATION
//
// Every export - the five CSVs and the Shotgun deck - goes through saveExport,
// so where a file lands and what it is called is decided in ONE place instead
// of at six call sites that each built their own name.
//
// The stamp is per ACTION, not per file. exportCsv writes three CSVs that are
// three views of one set of decisions; they belong in one folder under one
// name, and a stamp taken per file would scatter them across three folders
// whenever the clock ticked over mid-export. beginExport() is called once at
// the top of each export, and every file it writes carries that stamp.
//
// Destination, in order:
//   1. a directory the operator picked, via the File System Access API. The
//      dated folder is created inside it and the files written into it.
//   2. a clicked <a download>, everywhere the API is absent - Firefox, Safari,
//      and QtWebEngine inside the app. Browsers strip path separators from the
//      download attribute, so the fallback cannot make a folder; the stamp
//      rides in the filename and the host decides the directory. The app reads
//      the stamp back off the name and rebuilds the same folder.
const EXPORT_DIR = __EXPORTDIR__;   // configured target, shown when no folder is picked
let expStamp = null;                // DD.MM.YYYY_HH.MM for the action in progress
let expDir = null;                  // chosen directory handle, if there is one
let expSub = null;                  // the dated folder inside it, for this action
let expQueue = Promise.resolve();   // writes are serialised - see saveExport

const expPad2 = n => (n < 10 ? "0" : "") + n;

function expStampNow(){
  const d = new Date();
  return expPad2(d.getDate()) + "." + expPad2(d.getMonth() + 1) + "." + d.getFullYear()
       + "_" + expPad2(d.getHours()) + "." + expPad2(d.getMinutes());
}

function beginExport(){ expStamp = expStampNow(); expSub = null; }

// name.csv -> name_DD.MM.YYYY_HH.MM.csv. The extension stays last so the file
// still opens by double-click, and 05a's roi_regions*.csv glob still matches.
function expName(base){
  const i = base.lastIndexOf(".");
  const stem = i < 0 ? base : base.slice(0, i);
  const ext  = i < 0 ? ""   : base.slice(i);
  return stem + "_" + (expStamp || expStampNow()) + ext;
}

function expSay(msg){ const e = el("expStat"); if(e) e.textContent = msg; }

function expShow(){
  const e = el("expDirLbl");
  if(!e) return;
  e.textContent = expDir ? expDir.name : (EXPORT_DIR || "Downloads");
  e.title = expDir ? "exports are written into this folder, in a dated subfolder"
                   : (EXPORT_DIR ? "where the app files exports; a browser download goes to Downloads"
                                 : "no folder chosen - exports go to the browser download folder");
}

// A handle survives a reload, so the folder is chosen once rather than per
// session. The browser can still drop the permission, which is why every write
// re-checks it; re-granting needs a user gesture, and an export click is one.
const EXP_DB = "ls_curator_export", EXP_KEY = "dir";
function expIdb(run){
  return new Promise((res, rej) => {
    let req;
    try { req = indexedDB.open(EXP_DB, 1); } catch(e){ return rej(e); }
    req.onupgradeneeded = () => req.result.createObjectStore("h");
    req.onerror = () => rej(req.error);
    req.onsuccess = () => {
      const db = req.result;
      let inner;
      try {
        const tx = db.transaction("h", "readwrite");
        inner = run(tx.objectStore("h"));
        tx.oncomplete = () => { db.close(); res(inner ? inner.result : undefined); };
        tx.onerror = () => { db.close(); rej(tx.error); };
      } catch(e){ db.close(); rej(e); }
    };
  });
}

async function expGrant(handle){
  if(!handle.queryPermission) return true;
  if(await handle.queryPermission({mode: "readwrite"}) === "granted") return true;
  return await handle.requestPermission({mode: "readwrite"}) === "granted";
}

async function chooseExportDir(){
  if(!window.showDirectoryPicker){
    expSay("this browser cannot choose a folder - exports go to the download folder");
    return;
  }
  let handle;
  try {
    handle = await window.showDirectoryPicker({mode: "readwrite", id: "ls-curator-exports"});
  } catch(err){
    // Cancelling the picker is not a failure and should not say anything.
    if(err && err.name !== "AbortError") expSay("folder not chosen: " + (err.message || err));
    return;
  }
  expDir = handle;
  try { await expIdb(st => st.put(handle, EXP_KEY)); } catch(e){}
  expShow();
  expSay("exports will go to " + handle.name + "/<date>/");
}

async function expRestoreDir(){
  if(!window.showDirectoryPicker) return;
  try {
    const handle = await expIdb(st => st.get(EXP_KEY));
    if(handle){ expDir = handle; expShow(); }
  } catch(e){}
}

// Serialised: exportCsv fires three writes back to back, and letting them race
// would have three of them create the dated folder at once.
function saveExport(blob, base){
  expQueue = expQueue.then(() => expWrite(blob, base)).catch(() => {});
  return expQueue;
}

async function expWrite(blob, base){
  const name = expName(base);
  if(expDir){
    try {
      if(!await expGrant(expDir)) throw new Error("permission not granted");
      if(!expSub) expSub = await expDir.getDirectoryHandle(expStamp || expStampNow(), {create: true});
      const fh = await expSub.getFileHandle(name, {create: true});
      const w = await fh.createWritable();
      await w.write(blob);
      await w.close();
      expSay("wrote " + (expStamp || "") + "/" + name);
      return;
    } catch(err){
      // A dropped permission or a deleted folder must not lose the export.
      // Fall through to the download, and say why the folder was not used.
      expSay("could not write to " + expDir.name + " (" + (err.message || err)
             + ") - downloaded instead");
    }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
}

function dl(rowsArr,name){
  const b=new Blob([rowsArr.map(r=>r.map(csvq).join(",")).join("\\n")],{type:"text/csv"});
  saveExport(b, name);
}
// Write the seed through on first load, so this browser holds it like any other
// decision rather than depending on the page it came from.
try { if(!localStorage.getItem(KEY) && Object.keys(S).length) save(); } catch(e){}

// When this browser already holds something, it wins - but silence is wrong when
// what it holds is one stale section and the page is carrying 257. Neither
// answer should be automatic: overwriting loses work, ignoring loses the point
// of seeding. So the page says what it has and makes taking it one click.
(function(){
  const seedN = Object.keys(SEED_STATE || {}).length;
  if(!seedN) return;
  const missing = Object.keys(SEED_STATE).filter(u => hasDecision(SEED_STATE[u]) && !hasDecision(S[u])).length;
  if(!missing) return;
  const el2 = el("seedOffer");
  el2.style.display = "";
  el2.innerHTML = `<span style="color:#d29922">this page carries `
    + `<b>${seedN}</b> curated sections, ${missing} not in this browser</span> `
    + `<button class="btn-plate" style="padding:2px 8px;font-size:12px" `
    + `onclick="adoptSeed()">Load them</button>`;
})();

// Merge, not replace: anything decided in this browser stays, and the seed fills
// what it does not have. Replacing would make the button a way to lose work.
function adoptSeed(){
  const before = Object.keys(S).length;
  for(const [uid, v] of Object.entries(SEED_STATE || {}))
    if(hasDecision(v) && !hasDecision(S[uid])) S[uid] = v;
  save();
  el("seedOffer").style.display = "none";
  render(); status();
  console.log(`adopted seed: ${before} -> ${Object.keys(S).length} sections`);
}
// ---- Shotgun: the favourites, as a PowerPoint deck -------------------------
//
// One slide per atlas plate per marker, split down the middle by treatment.
// What goes on it is exactly the pair of decisions this tool exists to record -
// **favourite** (worth quantifying) and **a plate** (the level it was matched
// to) - so the deck is the curation, laid out. Nothing here is computed from
// the registration: no warped seeds, no ROI discs, no residuals. It is the
// tissue, side by side, at a matched level.
//
// THIS READS THE GROUP KEY, at stage 04l, which blinding._note in config.json
// forbids for anything before 06b. It is a deliberate exception and a narrow
// one: the key reaches the LAYOUT and nothing else. No count, no threshold and
// no curation decision depends on it - the state this reads was written before
// the key was ever loaded - but a deck arranged by treatment is, by
// construction, not blind. With no key declared the button disables itself,
// which is what keeps the exception opt-in.
//
// Written by hand rather than with a library because the page has no build step
// and no network: a .pptx is a ZIP of XML, the ZIP is written with the *stored*
// method (PNGs are already compressed, so deflate would buy nothing but a
// dependency), and the deck uses real picture and text-box shapes so everything
// on the slide can still be moved, resized and edited in PowerPoint.

const SHOT_COLS = 5, SHOT_ROWS = 2, SHOT_ROWS_REGION = 4;
const SHOT_PER_HALF = SHOT_COLS * SHOT_ROWS;
// A region slide has no plate picture to make room for - a region spans several
// plates, and drawing any one of them would assert a level the slide does not
// have - so the band the plate occupied goes back to the grid: four rows a side
// rather than two.
const perHalf = by => SHOT_COLS * (by === "region" ? SHOT_ROWS_REGION : SHOT_ROWS);
const EMU = 914400;                             // EMU per inch, the OOXML unit
const SLIDE_W = 12192000, SLIDE_H = 6858000;    // 13.333 x 7.5 in, 16:9
const inch = v => Math.round(v * EMU);

// One block, in inches, so the geometry can be tuned without hunting through
// the writer. Pictures are deliberately TINY: the PNG in the file is the whole
// composite at full resolution, so enlarging one in PowerPoint shows real
// pixels rather than a blur.
const SHOT_L = {
  margin: 0.30, gutter: 0.10,
  titleY: 0.14, titleH: 0.42, titleSz: 1600,
  plateY: 0.62, plateH: 1.32,
  headY: 2.10, headH: 0.34, headSz: 1300,
  gridY: 2.58, cell: 1.15, gapX: 0.08, gapY: 0.10, capH: 0.20, capSz: 800,
  divTop: 0.58, divBot: 7.20,
};
// The same block with the plate band reclaimed. Cell size, gaps and type sizes
// are deliberately shared, so a region slide and a plate slide are comparable
// side by side rather than merely similar.
const SHOT_L_REGION = Object.assign({}, SHOT_L,
  {headY: 0.66, gridY: 1.14, divTop: 0.58, divBot: 6.98});

const INK = "1A1A1A", DIM = "6E7681", RULE = "C9D1D9";

// Served over http the canvas is clean and fetch works; opened straight off
// disk neither is true - a file:// image taints the canvas and toBlob throws,
// which is the same trap markerOnly() above is written to avoid. Say so on the
// button instead of failing at the click.
function shotWhyNot(){
  if(location.protocol === "file:")
    return "this page was opened from disk, and a file:// page cannot read its own "
         + "images back, so no deck can be built. Serve it instead: run "
         + "serve_curators.bat (or python scripts/serve_curators.py), or open the "
         + "curator from the app - everything else on this page works either way";
  if(!(GROUPS && GROUPS.order && GROUPS.order.length
       && GROUPS.by_animal && Object.keys(GROUPS.by_animal).length))
    return "no group key declared - fill in groups.order and groups.by_animal in "
         + "config.json and regenerate the page";
  return "";
}

function shotBtnState(){
  const why = shotWhyNot();
  el("shotBtn").disabled = !!why;
  el("shotBtn").title = why
    || "favourites with a plate, one slide per plate, split by treatment";
  // Same gate, both decks: neither can read a tainted canvas, and neither can be
  // laid out without the key.
  el("shotRegBtn").disabled = !!why;
  el("shotRegBtn").title = why
    || "the same favourites, one slide per atlas region - a section appears on "
     + "every region it carries an ROI for";
  // Say it ON SCREEN, not only in a tooltip. A disabled button with no visible
  // reason is indistinguishable from a broken one, and nobody hovers a control
  // they have already decided is dead.
  //
  // WRITES ONLY WHEN DISABLED, and deliberately does not clear the span
  // otherwise: shotStat is also where shotSay() puts the build progress and the
  // final "wrote N slides" summary, and this function runs at the end of that
  // chain. Clearing here would wipe the result the moment the button
  // re-enabled itself.
  if(why) el("shotStat").innerHTML = `<b>Shotgun off</b> - ${why}`;
}
const shotSay = m => { el("shotStat").textContent = m; };

// ---- what goes in ----------------------------------------------------------

// The same rule exportCsv() uses, deliberately: a plate is a decision when it
// was assigned or landmarked, and never merely because the slider sat there.
// Two definitions of "has a plate" in one file is one too many.
function shotPick(){
  const take = [], noPlate = [], noGroup = [], excluded = [];
  for(const d of DATA){
    const s = S[d.uid];
    if(!s || !s.fav) continue;
    if(s.excl){ excluded.push(d.uid); continue; }
    if(!(s.assigned || roiPairs(s).length > 0)){ noPlate.push(d.uid); continue; }
    const g = GROUPS.by_animal[d.animal];
    if(!g){ noGroup.push(d.uid); continue; }
    take.push({d, s, g});
  }
  return {take, noPlate, noGroup, excluded};
}

// Which regions a section carries, read from the seeds its ROIs answer. A
// free-clicked ROI has no seed and therefore no region - exactly how exportCsv
// treats it - so the region deck can say nothing roi_regions.csv does not.
// Which regions this section actually carries, for the Shotgun "by region" deck.
//
// Read off the POLYGONS now. It used to walk the pairs and resolve each one's
// seed number through `P.seeds[n-1]`, which was right while a landmark was also
// an ROI; landmarks carry no seed number any more, so that loop would have
// returned an empty list for every section and the region deck would have come
// out blank without erroring.
function secRegions(s){
  const out = [];
  for(const pg of polysOf(s))
    if(pg.region && out.indexOf(pg.region) < 0) out.push(pg.region);
  return out;
}

// Slides are (plate x marker), in plate order, pERK before PCNA - or
// (region x marker) when `by` is "region", where a section lands on every region
// slide it carries an ROI for, and on none at all if it carries no seeded ROI.
//
// Regions run in the order of the FIRST plate they appear on rather than by
// name, so the deck still reads rostral to caudal: alphabetical would open on
// the anterior tuberal nucleus and interleave telencephalon with diencephalon.
//
// A half holding more than perHalf(by) runs on to a continuation slide rather
// than being cut short - both halves advance together, so a row always faces its
// counterpart.
function shotSlides(take, by){
  const order = MARKERS.map(m => m.id);
  const per = perHalf(by);
  const groups = new Map();
  const add = (key, meta, it) => {
    if(!groups.has(key)) groups.set(key, Object.assign({items: []}, meta));
    const g = groups.get(key);
    g.items.push(it);
    g.at = Math.min(g.at, it.s.plate);
  };
  for(const it of take){
    if(by === "region")
      for(const r of secRegions(it.s))
        add(r + "|" + it.d.m, {region: r, marker: it.d.m, at: it.s.plate}, it);
    else
      add(it.s.plate + "|" + it.d.m,
          {plate: it.s.plate, marker: it.d.m, at: it.s.plate}, it);
  }
  const anim = a => +a.slice(2);
  const out = [];
  const keys = [...groups.keys()].sort((a, b) => {
    const A = groups.get(a), B = groups.get(b);
    return A.at - B.at
        || String(A.region || "").localeCompare(String(B.region || ""))
        || order.indexOf(A.marker) - order.indexOf(B.marker);
  });
  for(const k of keys){
    const g = groups.get(k), items = g.items;
    const halves = GROUPS.order.map(gr => items.filter(it => it.g === gr)
      .sort((a, b) => anim(a.d.animal) - anim(b.d.animal) || a.d.order - b.d.order));
    const pages = Math.max(1, ...halves.map(h => Math.ceil(h.length / per)));
    for(let p = 0; p < pages; p++)
      out.push({plate: g.plate, region: g.region, marker: g.marker,
                page: p + 1, pages, n: items.length,
                halves: halves.map(h => h.slice(p * per, (p + 1) * per))});
  }
  return out;
}

// ---- pictures --------------------------------------------------------------

const shotLoad = src => new Promise((res, rej) => {
  const im = new Image();
  im.onload = () => res(im);
  im.onerror = () => rej(new Error("could not load " + src));
  im.src = src;
});

// The tile as the operator curated it: DAPI stripped where there is a composite
// to strip it from, and turned by the tilt they left on it. The tilt is a
// viewing aid everywhere else in this tool and stays one here - it moves no
// stored coordinate - but a level comparison reads wrong when half the sections
// are lying at a different angle from the other half.
//
// Black behind, because a rotated image leaves transparent corners and a white
// slide would show them as notches cut out of a black square.
function shotTile(img, rgb, rot){
  const w = img.naturalWidth, h = img.naturalHeight;
  const src = rgb ? markerOnly(img) : img;
  const c = document.createElement("canvas"), x = c.getContext("2d");
  if(rot){
    const D = Math.ceil(Math.hypot(w, h));
    c.width = D; c.height = D;
    x.fillStyle = "#000"; x.fillRect(0, 0, D, D);
    x.translate(D / 2, D / 2); x.rotate(rot * Math.PI / 180); x.drawImage(src, -w / 2, -h / 2);
  } else {
    c.width = w; c.height = h;
    x.fillStyle = "#000"; x.fillRect(0, 0, w, h);
    x.drawImage(src, 0, 0);
  }
  return c;
}

const shotBytes = blob => blob.arrayBuffer().then(b => new Uint8Array(b));
const shotPng = c => new Promise((res, rej) =>
  c.toBlob(b => b ? res(b) : rej(new Error("toBlob returned nothing")), "image/png"));

// ---- ZIP, stored -----------------------------------------------------------

const SHOT_CRC = (function(){
  const t = new Uint32Array(256);
  for(let n = 0; n < 256; n++){
    let c = n;
    for(let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(b){
  let c = 0xFFFFFFFF;
  for(let i = 0; i < b.length; i++) c = SHOT_CRC[(c ^ b[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

// Method 0 - stored. Every part is either already-compressed PNG or a few KB of
// XML, so deflate would trade a real dependency for nothing worth having, and
// the format allows it: PowerPoint reads a stored package like any other.
function zipStore(files, when){
  const enc = new TextEncoder(), parts = [], cen = [];
  const T = ((when.getHours() << 11) | (when.getMinutes() << 5) | (when.getSeconds() >> 1)) & 0xFFFF;
  const D = (((when.getFullYear() - 1980) << 9) | ((when.getMonth() + 1) << 5) | when.getDate()) & 0xFFFF;
  let off = 0;
  for(const f of files){
    const name = enc.encode(f.name), body = f.bytes, crc = crc32(body), n = body.length;
    const lh = new DataView(new ArrayBuffer(30));
    lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true);
    lh.setUint16(6, 0, true); lh.setUint16(8, 0, true);
    lh.setUint16(10, T, true); lh.setUint16(12, D, true);
    lh.setUint32(14, crc, true); lh.setUint32(18, n, true); lh.setUint32(22, n, true);
    lh.setUint16(26, name.length, true); lh.setUint16(28, 0, true);
    parts.push(new Uint8Array(lh.buffer), name, body);
    const ch = new DataView(new ArrayBuffer(46));
    ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true);
    ch.setUint16(8, 0, true); ch.setUint16(10, 0, true);
    ch.setUint16(12, T, true); ch.setUint16(14, D, true);
    ch.setUint32(16, crc, true); ch.setUint32(20, n, true); ch.setUint32(24, n, true);
    ch.setUint16(28, name.length, true); ch.setUint16(30, 0, true); ch.setUint16(32, 0, true);
    ch.setUint16(34, 0, true); ch.setUint16(36, 0, true); ch.setUint32(38, 0, true);
    ch.setUint32(42, off, true);
    cen.push({h: new Uint8Array(ch.buffer), name});
    off += 30 + name.length + n;
  }
  const start = off;
  let size = 0;
  for(const c of cen){ parts.push(c.h, c.name); size += c.h.length + c.name.length; }
  const eo = new DataView(new ArrayBuffer(22));
  eo.setUint32(0, 0x06054b50, true); eo.setUint16(4, 0, true); eo.setUint16(6, 0, true);
  eo.setUint16(8, cen.length, true); eo.setUint16(10, cen.length, true);
  eo.setUint32(12, size, true); eo.setUint32(16, start, true); eo.setUint16(20, 0, true);
  parts.push(new Uint8Array(eo.buffer));
  return parts;
}

// ---- OOXML -----------------------------------------------------------------

const xs = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                         .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const XML_HEAD = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`;
const NS_A = `xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"`;
const NS_R = `xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"`;
const NS_P = `xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"`;
const REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

let shotId = 1;
const xfrm = (x, y, w, h) =>
  `<a:xfrm><a:off x="${x}" y="${y}"/><a:ext cx="${w}" cy="${h}"/></a:xfrm>`;

function tbox(x, y, w, h, text, sz, bold, colour, align){
  return `<p:sp><p:nvSpPr><p:cNvPr id="${++shotId}" name="t${shotId}"/>`
    + `<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>`
    + `<p:spPr>${xfrm(x, y, w, h)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>`
    + `<a:noFill/></p:spPr>`
    + `<p:txBody><a:bodyPr wrap="square" lIns="0" rIns="0" tIns="0" bIns="0" anchor="ctr">`
    + `<a:noAutofit/></a:bodyPr><a:lstStyle/><a:p><a:pPr algn="${align}"/>`
    + `<a:r><a:rPr lang="en-US" sz="${sz}" b="${bold ? 1 : 0}" dirty="0">`
    + `<a:solidFill><a:srgbClr val="${colour}"/></a:solidFill></a:rPr>`
    + `<a:t>${xs(text)}</a:t></a:r></a:p></p:txBody></p:sp>`;
}

function pic(x, y, w, h, rid, name){
  return `<p:pic><p:nvPicPr><p:cNvPr id="${++shotId}" name="${xs(name)}"/>`
    + `<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>`
    + `<p:blipFill><a:blip r:embed="${rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>`
    + `<p:spPr>${xfrm(x, y, w, h)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>`;
}

function vline(x, y0, y1){
  return `<p:sp><p:nvSpPr><p:cNvPr id="${++shotId}" name="rule"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>`
    + `<p:spPr>${xfrm(x, y0, 0, y1 - y0)}<a:prstGeom prst="line"><a:avLst/></a:prstGeom>`
    + `<a:ln w="9525"><a:solidFill><a:srgbClr val="${RULE}"/></a:solidFill></a:ln></p:spPr>`
    + `<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>`;
}

const slideXml = body => XML_HEAD
  + `<p:sld ${NS_A} ${NS_R} ${NS_P}><p:cSld><p:bg><p:bgPr>`
  + `<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>`
  + `<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>`
  + `<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>`
  + `<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>`
  + body + `</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>`;

const rels = list => XML_HEAD
  + `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`
  + list.map(r => `<Relationship Id="${r.id}" Type="${r.type}" Target="${r.target}"/>`).join("")
  + `</Relationships>`;

// A theme is not optional - PowerPoint refuses a package without one - but it
// can be plain. Office colours, one font pair, the three-entry style lists the
// schema requires and nothing beyond them.
const THEME = XML_HEAD
  + `<a:theme ${NS_A} name="Shotgun"><a:themeElements><a:clrScheme name="Office">`
  + `<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>`
  + `<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>`
  + `<a:dk2><a:srgbClr val="44546A"/></a:dk2><a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>`
  + `<a:accent1><a:srgbClr val="4472C4"/></a:accent1><a:accent2><a:srgbClr val="ED7D31"/></a:accent2>`
  + `<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4>`
  + `<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6>`
  + `<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink>`
  + `</a:clrScheme><a:fontScheme name="Office">`
  + `<a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>`
  + `<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>`
  + `</a:fontScheme><a:fmtScheme name="Office">`
  + `<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>`
  + `<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>`
  + `<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>`
  + `<a:lnStyleLst>`
  + `<a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>`
  + `<a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>`
  + `<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>`
  + `<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle>`
  + `<a:effectStyle><a:effectLst/></a:effectStyle>`
  + `<a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>`
  + `<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>`
  + `<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>`
  + `<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>`
  + `</a:fmtScheme></a:themeElements></a:theme>`;

const EMPTY_TREE = `<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>`
  + `</p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>`
  + `<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree>`;

const MASTER = XML_HEAD
  + `<p:sldMaster ${NS_A} ${NS_R} ${NS_P}><p:cSld>${EMPTY_TREE}</p:cSld>`
  + `<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2"`
  + ` accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6"`
  + ` hlink="hlink" folHlink="folHlink"/>`
  + `<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>`
  + `</p:sldMaster>`;

const LAYOUT = XML_HEAD
  + `<p:sldLayout ${NS_A} ${NS_R} ${NS_P} type="blank" preserve="1">`
  + `<p:cSld name="Blank">${EMPTY_TREE}</p:cSld>`
  + `<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>`;

const PRESPROPS = XML_HEAD + `<p:presentationPr ${NS_A} ${NS_R} ${NS_P}/>`;

// ---- the deck --------------------------------------------------------------

function shotgun(by){
  const why = shotWhyNot();
  if(why){ shotSay(why); return; }
  el("shotBtn").disabled = true;
  el("shotRegBtn").disabled = true;
  return shotBuild(by)
    .catch(err => { shotSay("shotgun failed: " + ((err && err.message) || err)); throw err; })
    .then(() => shotBtnState(), () => shotBtnState());
}

async function shotBuild(by){
  // Normalised once, here, rather than trusted from the caller: everything below
  // branches on it, and a stray truthy value would half-build a region deck.
  const mode = by === "region" ? "region" : "plate";
  const L = mode === "region" ? SHOT_L_REGION : SHOT_L;
  const got = shotPick();
  const take = got.take;
  if(!take.length){
    shotSay("nothing to build: no favourite has a plate assigned"
      + (got.noPlate.length ? " (" + got.noPlate.length + " favourite"
          + (got.noPlate.length > 1 ? "s" : "") + " with no plate)" : ""));
    return;
  }
  const slides = shotSlides(take, mode);
  // Reachable only in region mode, and worth its own message: every favourite
  // can have a plate and still produce no region slide, because the regions come
  // from seeded ROIs and a section can be landmarked with none.
  if(!slides.length){
    shotSay("nothing to build: no favourite carries an ROI placed on a numbered "
      + "atlas seed, so there is no region to group by");
    return;
  }
  shotSay("building " + slides.length + " slide" + (slides.length > 1 ? "s" : "") + "...");

  shotId = 1;
  const media = [];             // {name, bytes}
  const bySrc = new Map();      // source -> media index, so a plate shown on six
                                // slides is stored once rather than six times
  async function addMedia(src, bytesFn){
    if(bySrc.has(src)) return bySrc.get(src);
    const i = media.length;
    media.push({name: "image" + (i + 1) + ".png", bytes: await bytesFn()});
    bySrc.set(src, i);
    return i;
  }

  const half = (SLIDE_W / 2) - inch(L.margin) - inch(L.gutter);
  const gridW = SHOT_COLS * inch(L.cell) + (SHOT_COLS - 1) * inch(L.gapX);
  const rowH = inch(L.cell) + inch(L.capH) + inch(L.gapY);
  // The region column exists only on a region deck. Adding it unconditionally
  // would put an always-blank column in a file that is already read elsewhere.
  const manifest = [mode === "region"
    ? ["slide", "plate_set", "region", "plate_id", "marker", "treatment", "half",
       "scene_uid", "animal", "section_order", "view_rotation_deg"]
    : ["slide", "plate_set", "plate_id", "marker", "treatment", "half",
       "scene_uid", "animal", "section_order", "view_rotation_deg"]];
  // plate_012 -> p012, because the caption has 1.15 inches and the full id does
  // not fit beside the animal and the section number.
  const shortPlate = i => (PLATES[i] ? PLATES[i].id : "").replace("plate_", "p");

  const slideXmls = [], slideRels = [];
  for(let si = 0; si < slides.length; si++){
    const sl = slides[si];
    // Undefined rather than a plate in region mode - a region has no single one,
    // and picking any would assert a level the slide does not have.
    const P = sl.plate === undefined ? null : PLATES[sl.plate];
    const head = mode === "region" ? sl.region : P.id;
    const mk = MARKERS.find(m => m.id === sl.marker);
    const rel = [{id: "rId1", type: REL + "/slideLayout",
                  target: "../slideLayouts/slideLayout1.xml"}];
    const addPic = async (src, bytesFn) => {
      const i = await addMedia(src, bytesFn);
      const id = "rId" + (rel.length + 1);
      rel.push({id, type: REL + "/image", target: "../media/image" + (i + 1) + ".png"});
      return id;
    };

    let body = "";
    body += tbox(inch(L.margin), inch(L.titleY),
                 SLIDE_W - 2 * inch(L.margin), inch(L.titleH),
                 head + "   " + (mk ? mk.label : sl.marker) + "   " + sl.n + " section"
                   + (sl.n > 1 ? "s" : "")
                   + (sl.pages > 1 ? "   (" + sl.page + " of " + sl.pages + ")" : ""),
                 L.titleSz, true, INK, "l");
    body += tbox(inch(L.margin), inch(L.titleY),
                 SLIDE_W - 2 * inch(L.margin), inch(L.titleH),
                 PLATE_SET, L.capSz + 100, false, DIM, "r");

    // The plate the sections were matched to, at its own aspect and its own
    // resolution: fetched as bytes rather than redrawn, so nothing is resampled.
    if(P){
      const pw = Math.round(inch(L.plateH) * (P.w / P.h));
      const prid = await addPic(P.img, () => fetch(P.img).then(r => {
        if(!r.ok) throw new Error("plate " + P.id + ": HTTP " + r.status);
        return r.arrayBuffer();
      }).then(b => new Uint8Array(b)));
      body += pic(Math.round(SLIDE_W / 2 - pw / 2), inch(L.plateY),
                  pw, inch(L.plateH), prid, P.id);
    }
    // Drawn in both modes: the split down the middle is the point of the slide,
    // not decoration around the plate.
    body += vline(Math.round(SLIDE_W / 2), inch(L.divTop), inch(L.divBot));

    for(let h = 0; h < GROUPS.order.length; h++){
      const x0 = h === 0 ? inch(L.margin)
                         : Math.round(SLIDE_W / 2) + inch(L.gutter);
      body += tbox(x0, inch(L.headY), half, inch(L.headH),
                   String(GROUPS.order[h]).toUpperCase(), L.headSz, true, INK, "ctr");
      const gx = x0 + Math.round((half - gridW) / 2);
      const cells = sl.halves[h];
      for(let i = 0; i < cells.length; i++){
        const it = cells[i];
        const cx = gx + (i % SHOT_COLS) * (inch(L.cell) + inch(L.gapX));
        const cy = inch(L.gridY) + Math.floor(i / SHOT_COLS) * rowH;
        const rid = await addPic(it.d.uid, async () => {
          const img = await shotLoad(it.d.img);
          return shotBytes(await shotPng(shotTile(img, it.d.rgb, it.s.rot || 0)));
        });
        body += pic(cx, cy, inch(L.cell), inch(L.cell), rid, it.d.uid);
        // On a region slide the plate has left the title, so each cell carries
        // its own. The level is what makes two tiles comparable; without it the
        // grid is only sections that share a region name.
        body += tbox(cx, cy + inch(L.cell), inch(L.cell), inch(L.capH),
                     it.d.animal + " " + it.d.order
                       + (mode === "region" ? "  " + shortPlate(it.s.plate) : ""),
                     L.capSz, false, DIM, "ctr");
        // plate_id is the SECTION's plate on a region deck - each cell has its
        // own - and the slide's plate on a plate deck, where by construction
        // they are the same thing.
        manifest.push(mode === "region"
          ? [si + 1, PLATE_SET, sl.region, shortPlate(it.s.plate), it.d.m, it.g, h + 1,
             it.d.uid, it.d.animal, it.d.order, (it.s.rot || 0).toFixed(1)]
          : [si + 1, PLATE_SET, P.id, it.d.m, it.g, h + 1,
             it.d.uid, it.d.animal, it.d.order, (it.s.rot || 0).toFixed(1)]);
      }
    }
    slideXmls.push(slideXml(body));
    slideRels.push(rels(rel));
    shotSay("slide " + (si + 1) + " of " + slides.length + "...");
  }

  // ---- package -------------------------------------------------------------
  const enc = new TextEncoder(), files = [];
  const put = (name, text) => files.push({name, bytes: enc.encode(text)});

  put("[Content_Types].xml", XML_HEAD
    + `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">`
    + `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>`
    + `<Default Extension="xml" ContentType="application/xml"/>`
    + `<Default Extension="png" ContentType="image/png"/>`
    + `<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>`
    + `<Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/>`
    + `<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>`
    + `<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>`
    + `<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>`
    + slideXmls.map((_, i) => `<Override PartName="/ppt/slides/slide${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>`).join("")
    + `</Types>`);

  put("_rels/.rels", rels([{id: "rId1", type: REL + "/officeDocument",
                            target: "ppt/presentation.xml"}]));

  const sldIds = slideXmls.map((_, i) => `<p:sldId id="${256 + i}" r:id="rId${i + 2}"/>`).join("");
  put("ppt/presentation.xml", XML_HEAD
    + `<p:presentation ${NS_A} ${NS_R} ${NS_P}>`
    + `<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>`
    + `<p:sldIdLst>${sldIds}</p:sldIdLst>`
    + `<p:sldSz cx="${SLIDE_W}" cy="${SLIDE_H}"/>`
    + `<p:notesSz cx="${SLIDE_H}" cy="${SLIDE_W}"/></p:presentation>`);

  put("ppt/_rels/presentation.xml.rels", rels(
    [{id: "rId1", type: REL + "/slideMaster", target: "slideMasters/slideMaster1.xml"}]
    .concat(slideXmls.map((_, i) => ({id: "rId" + (i + 2), type: REL + "/slide",
                                      target: "slides/slide" + (i + 1) + ".xml"})))
    .concat([{id: "rId" + (slideXmls.length + 2), type: REL + "/theme",
              target: "theme/theme1.xml"},
             {id: "rId" + (slideXmls.length + 3), type: REL + "/presProps",
              target: "presProps.xml"}])));

  put("ppt/presProps.xml", PRESPROPS);
  put("ppt/theme/theme1.xml", THEME);
  put("ppt/slideMasters/slideMaster1.xml", MASTER);
  put("ppt/slideMasters/_rels/slideMaster1.xml.rels", rels([
    {id: "rId1", type: REL + "/slideLayout", target: "../slideLayouts/slideLayout1.xml"},
    {id: "rId2", type: REL + "/theme", target: "../theme/theme1.xml"}]));
  put("ppt/slideLayouts/slideLayout1.xml", LAYOUT);
  put("ppt/slideLayouts/_rels/slideLayout1.xml.rels", rels([
    {id: "rId1", type: REL + "/slideMaster", target: "../slideMasters/slideMaster1.xml"}]));
  for(let i = 0; i < slideXmls.length; i++){
    put("ppt/slides/slide" + (i + 1) + ".xml", slideXmls[i]);
    put("ppt/slides/_rels/slide" + (i + 1) + ".xml.rels", slideRels[i]);
  }
  for(const m of media) files.push({name: "ppt/media/" + m.name, bytes: m.bytes});

  const now = new Date();
  const _unused_stamp = now.getFullYear() + pad2(now.getMonth() + 1) + pad2(now.getDate())
              + "_" + pad2(now.getHours()) + pad2(now.getMinutes());
  const blob = new Blob(zipStore(files, now),
    {type: "application/vnd.openxmlformats-officedocument.presentationml.presentation"});
  // Named apart so a region deck cannot silently overwrite a plate one, and so
  // the pair of files that belong together stay recognisable as a pair.
  const tag = mode === "region" ? "by-region_" : "";
  beginExport();
  shotSave(blob, "shotgun_" + tag + PLATE_SET + ".pptx");
  dl(manifest, "shotgun_manifest" + (mode === "region" ? "_by-region" : "") + ".csv");

  const bits = [slides.length + " slides", take.length + " sections",
                media.length + " images"];
  if(got.noPlate.length)  bits.push(got.noPlate.length + " favourites skipped (no plate)");
  if(got.noGroup.length)  bits.push(got.noGroup.length + " skipped (not in the group key)");
  if(got.excluded.length) bits.push(got.excluded.length + " skipped (excluded)");
  shotSay(bits.join(" - "));
  return {slides: slides.length, sections: take.length, files, blob};
}

const pad2 = n => (n < 10 ? "0" : "") + n;

// Same route as the CSV exports - saveExport decides the folder and the name,
// so the deck and its manifest land beside the CSVs under one stamp.
function shotSave(blob, name){
  saveExport(blob, name);
}

// ===========================================================================
// REVIEW MODE - the four stages that decided a section's fate before this page
// ever loaded it.
//
// The rest of the curator works on SURVIVORS: it loads reformat_index, which is
// the list of sections that got through. So 1,066 exclusions and 2,099 artifact
// masks were decisions nobody could inspect from the tool they spend their time
// in. This mode carries all 2,572 SCANNED sections, from the CZI scene onward.
//
// PROV is emitted as arrays under a shared header, not objects - 22 field names
// repeated 2,572 times would roughly double the page for nothing.
const PROV = __PROV__;
// Pooled columns arrive as an index into PROV.p[field]; everything else is the
// value. Decoded once, here, so nothing downstream has to know which is which.
const PROWS = PROV.r.map(r => Object.fromEntries(PROV.f.map((k, i) =>
  [k, PROV.p[k] ? PROV.p[k][r[i]] : r[i]])));
const P_BY = Object.fromEntries(PROWS.map(p => [p.scene_uid, p]));

// The three image paths are derived rather than carried - 275 KB of the table
// was spent restating a fixed rule. 04p records only WHETHER each file exists,
// which is the part that cannot be derived, and writes the same paths from the
// same rule; if one of these moves, both move.
function revSrc(p, what){
  const ov = k => `../overviews/${p.animal}/${p.marker}/${p.scene_uid}_${k}.png`;
  // RGB is DAPI + marker together; MARK is the marker alone. Both exist for
  // every scanned section, so "remove DAPI" is a different file rather than a
  // composite that would have to be built - and it is exact, not approximated.
  if(what === "overview") return p.has_overview ? ov(REV.dapi ? "RGB" : "MARK") : "";
  if(what === "dapi")     return p.has_overview ? ov("DAPI") : "";
  if(what === "section"){
    // Colour where there is colour, at the SIZE THE GRID DRAWS.
    //
    // The composite is what the operator is looking at everywhere else in this
    // page, and a grid of grey thumbnails next to a colour detail reads as two
    // different datasets. But the composite is 768px and 448 KB for a cell
    // drawn at 78px - one animal is 56.6 MB of picture nobody sees at that
    // size, which is the overview mistake again with smaller numbers. 04o
    // --thumbs writes a 256px copy at 61 KB; that is what the grid asks for.
    //
    // Three steps down, because each one is a separate fact about the disk:
    // thumbnail, then composite, then the greyscale every section has. Nothing
    // here infers one file from another - 1,066 sections have no composite and
    // a failed <img> is silent.
    if(!p.has_section) return "";
    const dir = `sections${p.marker === "AF568" ? "_AF568" : ""}`;
    const sub = p.has_section_thumb ? "_rgb_thumb"
              : p.has_section_rgb   ? "_rgb" : "";
    return `${dir}${sub}/${p.scene_uid}.png`;
  }
  if(what === "censor")   return p.has_censor
      ? `../censor/${p.scene_uid}_censor.png` : "";
  if(what === "tissue")   return p.has_tissue
      ? `../tissue/${p.scene_uid}_tissue.png` : "";
  return p.has_mask ? `../artifacts/${p.scene_uid}_artifact.png` : "";
}

// Independent layers, not a cycle.
//
// This started as one button cycling masked -> unmasked -> overlay, which is
// fine for answering "what did the mask remove" and useless for anything else:
// you cannot see the artifacts and the censored pixels at once, and you cannot
// take DAPI off to look at the marker alone. Four switches say what is on
// screen at all times, which a three-state cycle never does.
const REV = {dapi: true, mark: true, art: false, cen: false, apply: false};

function revLayer(k){
  REV[k] = !REV[k];
  revImg();
}

// Composite the masks onto a canvas over the section.
//
// Each mask is drawn through an offscreen pass: brightness(255) turns the
// artifact mask's 0/1/2 into a 0/255 stencil (the censor mask is already 0/255
// and is unharmed by it), then `source-in` fills the stencil with a flat colour
// and leaves everything else transparent. The result composites at a fixed
// alpha, so it reads over bright tissue and dark background alike.
//
// RED is an artifact, CYAN is a censored pixel, and they must not look alike:
// they mean opposite things. An artifact LEAVES the analysis; a censored pixel
// STAYS in the count and is positive by construction (04j).
//
// "Apply mask" is the other direction - paint the artifact black, which is what
// 04a does to the pixels - so it draws opaque instead of tinted.
function drawRevOverlays(p, hasCen){
  const c = el("revOv"), base = el("revImg");
  const W = c.clientWidth, H = c.clientHeight;
  if(!W || !H) return;
  c.width = W; c.height = H;
  const x = c.getContext("2d");
  x.clearRect(0, 0, W, H);
  const nw = base.naturalWidth, nh = base.naturalHeight;
  if(!nw || !nh) return;

  // Undo object-fit:contain. The element box is not the drawn area - the same
  // trap the ROI curator's click mapping had to solve - so the masks are placed
  // in the letterboxed rect the base image actually occupies, not the box.
  const k = Math.min(W / nw, H / nh);
  const dw = nw * k, dh = nh * k, dx = (W - dw) / 2, dy = (H - dh) / 2;

  const layer = (img, colour, alpha, clipToTissue) => {
    if(!img || !img.naturalWidth) return;
    const t = document.createElement("canvas");
    t.width = Math.round(dw); t.height = Math.round(dh);
    const g = t.getContext("2d");
    // brightness(255) turns the artifact mask's 1 and 2 into 255 and leaves 0
    // at 0; the censor mask is already 0/255 and passes through unchanged. Then
    // luminance becomes alpha, so the source-in below clips to the mask instead
    // of to the whole rectangle.
    g.filter = "brightness(255) url(#revLumAlpha)";
    g.drawImage(img, 0, 0, t.width, t.height);
    g.filter = "none";
    // HIDE THE PEN RING: keep only the part of the stencil that is on tissue.
    //
    // 96.4% of all censored pixels lie OUTSIDE the tissue - 169.0M censored,
    // 6.0M on tissue, measured over the 1,506 sections that have both masks -
    // because 04j censors every clipped pixel in the frame and the PAP pen ring
    // is saturated. 39% of sections with any censoring have NONE of it on
    // tissue at all. So the overlay is mostly pen and the real clipping is
    // invisible underneath it; intersecting with a tissue stencil leaves the
    // censoring that is actually on tissue.
    //
    // THRESHOLDING DAPI IN THE BROWSER WAS TRIED FIRST AND CANNOT WORK. In the
    // 8-bit overview DAPI has a median of 4/255 inside tissue against 1-2
    // outside; no cut separates them, and the one that looked plausible kept
    // 0.2% of the censoring 04j says is on tissue - a display that would have
    // read as "almost nothing is censored here" while the file said 10.6%.
    // The mask now comes from 04p, which runs the pipeline's own log-space
    // Otsu on the data it was designed for.
    //
    // Still a way of LOOKING, not a measurement - but do NOT reach for
    // `censored_fraction_in_tissue` as the number instead. That column is not
    // restricted to tissue: 04j takes its stencil as `DAPI > 0`, which is every
    // pixel that is not exactly black and covers 74-92% of the frame (mean 83%)
    // against 10-35% for real tissue. `cen[DAPI > 0].mean()` reproduces the
    // column to four decimals on every section checked, so the name promises a
    // restriction the arithmetic does not make, and the pen sits inside it.
    // That is why it runs ~7x the tissue-restricted overlap and correlates with
    // it only r=0.61.
    //
    // Reported, not fixed here: 04j belongs to the censoring work and this is
    // the viewer. Whoever lands that stage should decide what the column ought
    // to mean; this comment exists so the next person does not quote it as
    // "fraction in tissue" on the strength of its name.
    if(clipToTissue){
      const tsrc = el("revTissue");
      if(tsrc && tsrc.naturalWidth){
        g.globalCompositeOperation = "destination-in";
        g.filter = "url(#revLumAlpha)";       // already 0/255, only alpha needed
        g.drawImage(tsrc, 0, 0, t.width, t.height);
        g.filter = "none";
      }
    }
    g.globalCompositeOperation = "source-in";
    g.fillStyle = colour;
    g.fillRect(0, 0, t.width, t.height);
    x.globalAlpha = alpha;
    x.drawImage(t, dx, dy);
    x.globalAlpha = 1;
  };

  if(REV.apply && p.has_mask) layer(el("revMask"), "#000000", 1);
  if(REV.art   && p.has_mask) layer(el("revMask"), "#ff3b30", 0.75);
  if(REV.cen && hasCen)
    layer(el("revCensor"), "#00d5ff", 0.55,
          !!p.has_tissue && el("revPenChk") && el("revPenChk").checked);
}

// A src is assigned and the overlay drawn in the same breath, so the first draw
// usually runs before anything has decoded and naturalWidth is still 0 - which
// is a blank overlay and no error. Every load re-draws.
for(const id of ["revImg", "revMask", "revCensor", "revTissue"]){
  el(id).addEventListener("load", () => {
    const p = P_BY[revSel];
    // has_censor, not the marker - the same test as revImg. This handler kept
    // the old marker check after revImg moved off it, so every image load
    // redrew PCNA with the censor layer off and quietly wiped it.
    if(p) drawRevOverlays(p, !!p.has_censor);
  });
}

let revOn = false, revSel = null;

// Everything drawn here comes out of a CSV rather than out of this page, so it
// is escaped. The rest of the curator interpolates values it generated itself -
// animal ids, plate names - and does not need this; a recorded exclusion reason
// is operator-typed free text and does.
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

// dl() joins fields with commas and quotes nothing, which is fine for the
// numbers the other exports write. Exclusion reasons are free text and DO carry
// commas - "no tissue piece larger than 1.46 mm2 (threshold 2.5)" is tame, but
// several in excluded_sections.csv are already quoted at source - so anything
// operator-typed goes through this first.
const csvq = s => {
  const v = String(s == null ? "" : s);
  return /[",\\n\\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
};

// The decision lives in the SAME curation store, on the section's own entry,
// under a field nothing else reads. It therefore rides the existing autosave,
// the seeding and the app's file mirror for free, and cannot collide with ROI
// work on the same section. `st()` creates the entry lazily, so a section that
// is only looked at never grows one.
const revOf = uid => (S[uid] || {}).rev || null;

function toggleReview(){
  if(!PROWS.length){
    alert("no section_provenance.csv - run:\\n  python scripts/04p_section_provenance.py");
    return;
  }
  revOn = !revOn;
  el("review").classList.toggle("on", revOn);
  el("panes").style.display = revOn ? "none" : "";
  el("strip").style.display = revOn ? "none" : "";
  el("revBtn").classList.toggle("mode-on", revOn);
  if(revOn) revRender();
}

// Grouped animal -> slide, in scan order, because that is the order they came
// off the scanner and the order damage runs in - a bad slide is usually a run
// of neighbours, and seeing them adjacent is most of the review.
// The one list. The grid draws it and the stepper walks it, so "next" always
// means the next cell you can see - a stepper over a different set than the one
// on screen is the kind of thing that looks like a bug in the data.
function revList(){
  const want = el("animal").value;
  const f = el("revFilter") ? el("revFilter").value : "all";
  return PROWS
    .filter(p => want === "both" || !want || p.animal === want)
    .filter(p => f === "all" ? true
               : f === "excluded" ? p.status === "excluded"
               : f === "analysis" ? p.status !== "excluded"
               : f === "measured" ? p.status === "measured"
               : f === "masked"   ? !!p.has_mask : true)
    .sort((a, b) => (a.animal + a.slide + a.marker).localeCompare(
                     b.animal + b.slide + b.marker)
                 || (+a.section_order || 0) - (+b.section_order || 0));
}

// One section at a time, in the order the grid shows them.
function revStep(d){
  const list = revList();
  if(!list.length) return;
  const i = list.findIndex(p => p.scene_uid === revSel);
  const next = list[(i < 0 ? 0 : i + d + list.length) % list.length];
  revPick(next.scene_uid);
  const cell = document.querySelector(`.rc[data-uid="${next.scene_uid}"]`);
  if(cell) cell.scrollIntoView({block: "nearest"});
}

function revRender(){
  const g = el("revGrid");
  const rows = revList();
  const groups = new Map();
  for(const p of rows){
    const k = p.animal + " " + p.slide + p.marker;
    if(!groups.has(k)) groups.set(k, []);
    groups.get(k).push(p);
  }
  const parts = [];
  for(const [k, ps] of groups){
    ps.sort((a, b) => (+a.section_order || 0) - (+b.section_order || 0));
    const lab = ps[0].marker === "AF568" ? "pERK" : "PCNA";
    parts.push(`<div class="revGroup"><h4>${esc(ps[0].animal)} &middot; slide `
      + `${esc(ps[0].slide)} &middot; ${lab} &middot; ${ps.length} sections `
      + `&middot; ${esc(ps[0].czi_file)}</h4><div class="revCells">`
      + ps.map(revCell).join("") + `</div></div>`);
  }
  g.innerHTML = parts.join("") || "<div class='kv'>nothing for this animal</div>";
  revCount();
}

function revCell(p){
  const r = revOf(p.scene_uid);
  const cls = ["rc"];
  if(p.status === "excluded") cls.push("excluded");
  else if(p.status === "measured") cls.push("measured");
  else if(p.status === "censored_out") cls.push("censored");
  // A proposal the program made, which the operator has not overruled. Dashed,
  // exactly as 04d draws it.
  if(p.proposed_excluded === "1" && p.status !== "excluded") cls.push("proposed");
  if(p.scene_uid === revSel) cls.push("sel");
  const flag = r ? `<span class="flag ${r.act === "restore" ? "rs"
                     : r.act === "drop" ? "dr" : "um"}">`
                 + (r.act === "restore" ? "IN" : r.act === "drop" ? "OUT" : "NOMASK")
                 + `</span>` : "";
  // THE 256px THUMBNAIL, at 61 KB, not the overview at 556 KB.
  //
  // The grid draws a few hundred cells at 78 px, and the overview is
  // 1632x1862 - LS61's pERK sections alone are 98 MB of PNG against 2.3 MB
  // reformatted. Loading the big ones left most cells blank behind `loading
  // ="lazy"` and the grid looked broken rather than slow.
  //
  // The overview was chosen originally because it was the only picture EVERY
  // section had; that stopped being true once 04a --render-excluded gave the
  // excluded ones an image too. The fallback stays for a section that somehow
  // has neither.
  const src = revSrc(p, "section") || revSrc(p, "overview");
  return `<div class="${cls.join(" ")}" data-uid="${esc(p.scene_uid)}" `
       + `title="${esc(p.scene_uid)} - ${esc(p.status)}">`
       + (src ? `<img loading="lazy" src="${esc(src)}" alt="">`
              : `<div style="aspect-ratio:1"></div>`)
       + `<span class="n">${esc(p.section_order)}</span>${flag}</div>`;
}

function revPick(uid){
  revSel = uid;
  revDetail();
  revRender();
  const list = revList();
  const i = list.findIndex(p => p.scene_uid === uid);
  el("revPos").textContent = i < 0 ? "-" : `${i + 1} of ${list.length}`;
  // The maximised card carries its own copy of the position, because the card
  // that normally shows it is not on screen then.
  const fsp = el("revFsPos");
  if(fsp) fsp.textContent = el("revPos").textContent;
}

// One line per stage, in the order they ran. A stage that had nothing to say
// about this section is greyed rather than omitted - "04g found no artifact" and
// "04g never looked at this section" are different facts, and a missing row
// would read as the first when it is often the second.
function revChainRows(p){
  const out = [];
  const row = (name, txt, on) =>
    out.push(`<div class="st${on ? "" : " no"}"><b>${name}</b><span>${esc(txt)}</span></div>`);
  row("scan", `${p.czi_file} scene ${p.scene_index} - ${p.marker === "AF568" ? "pERK" : "PCNA"}`, true);
  row("01 overview", p.tissue_area_mm2
      ? `tissue ${p.tissue_area_mm2} mm2, focus ${p.focus_score}` : "no QC row", !!p.tissue_area_mm2);
  row("04f propose", p.proposed_excluded === "1"
      ? `proposed EXCLUDE${p.largest_mm2 ? ` - largest piece ${p.largest_mm2} mm2` : ""}`
      : p.proposed_excluded === "0" ? "no objection"
      : "not assessed (only survivors are)", p.proposed_excluded !== "");
  row("04d decide", p.status === "excluded"
      ? `EXCLUDED (${p.decision || "?"}) - ${p.decision_reason || "no reason recorded"}`
      : "kept", true);
  row("04g mask", p.has_mask
      ? `${p.n_artifact_objects || 0} objects, ${p.artifact_pct_of_tissue || 0}% of tissue`
      : "no mask built", !!p.has_mask);
  row("04a reformat", p.has_section
      ? "reformatted" + (p.status === "excluded" ? " (image predates the exclusion)" : "")
      : "not reformatted - original scan only", !!p.has_section);
  row("04j censor", p.in_analysis_set === "1" ? "in the analysis set"
      : p.in_analysis_set === "0" ? `CENSORED OUT - ${p.censor_reason || ""}`
      : "pERK only", p.in_analysis_set !== "");
  row("05a/05c", +p.n_nuclei ? `${p.n_rois} ROIs, ${p.n_nuclei} nuclei`
      : +p.n_rois ? `${p.n_rois} ROIs, not yet measured` : "nothing measured", !!+p.n_nuclei);
  return out.join("");
}

function revDetail(){
  const p = P_BY[revSel];
  if(!p){ el("revHint").textContent = "pick a section on the left"; return; }
  el("revTitle").textContent = p.scene_uid;
  el("revHint").innerHTML = `<b>${esc(p.status)}</b> &middot; ${esc(p.animal)} `
    + `&middot; section ${esc(p.section_order)}`;
  el("revChain").innerHTML = revChainRows(p);
  revImg();
  const r = revOf(revSel);
  el("revState").innerHTML = r
    ? `<b style="color:#7c5cff">${esc(r.act)}</b> - ${esc(r.why || "no reason given")}`
    : "no decision recorded";
  el("revWhy").value = r ? (r.why || "") : "";
  // Reinstating something that was never excluded, or rejecting a mask that
  // does not exist, are both meaningless - say so on the button.
  el("revRestore").disabled = p.status !== "excluded";
  // Same rule for the maximised copy, and it says which way it will go - there
  // is no separate Clear button up there, so the one button has to toggle.
  const fsr = el("revFsRestore");
  if(fsr){
    const on = r && r.act === "restore";
    fsr.disabled = p.status !== "excluded";
    fsr.textContent = on ? "Reinstated ✓" : "Reinstate";
    fsr.classList.toggle("mode-on", !!on);
    fsr.onclick = () => revAct(on ? "" : "restore");
  }
  el("revDrop").disabled = p.status === "excluded";
  el("revUnmask").disabled = !p.has_mask;
}

// ALL THREE STATES ARE THE SAME PICTURE, and that is the point.
//
// The obvious build showed the REFORMATTED image for "masked" and the overview
// for "unmasked". They are not the same frame - 256x256 rotated and cropped to
// the tissue, against 1404x1632 as scanned - so flicking between them changed
// the framing, the rotation and the scale, and the one thing it was supposed to
// isolate was lost in the middle of all that. A comparison whose two halves are
// not registered is not a comparison.
//
// So masking is applied HERE, over the overview, in the frame 04g's mask
// actually lives in ("the same pixel grid as the DAPI overview - *not* the
// reformatted frame"). The reformatted image is a different question and the
// chain says whether one exists.
function revImg(){
  const p = P_BY[revSel];
  if(!p) return;
  // WHETHER A CENSOR MASK EXISTS, not which marker this is.
  //
  // Censoring WAS pERK-only, and this asked `p.marker === "AF568"` because of
  // it: 04j thresholded the 8-bit _MARK.png at 255, which only means "clipped"
  // for AF568, whose display high is the 16-bit ceiling. AF488's is 37,263, so
  // the test did not generalise and PCNA had no masks. Reading the raw data
  // instead lifted that, both channels now have them, and a marker test would
  // silently refuse on half the dataset. The file is the authority.
  const hasCen = !!p.has_censor;

  // FOUR STATES, THREE FILES. The overview ships the composite, the marker
  // alone and DAPI alone, so every combination is a real image rather than a
  // channel knocked out of a composite - "marker off" shows the counterstain
  // that was actually recorded, not the composite with a plane zeroed.
  //
  // Marker in ITS OWN colour, matching the composites in the grid beside it -
  // red pERK, green PCNA - instead of the overview's yellow-for-both. See the
  // filter definitions for why this is exact and why DAPI is lifted.
  const perk = p.marker === "AF568";
  el("revImg").src = (REV.mark || !REV.dapi)
      ? revSrc(p, "overview")     // RGB when REV.dapi, MARK when not
      : revSrc(p, "dapi");
  el("revImg").style.filter = "url(#" + (
        !REV.mark && !REV.dapi ? "revBlank"
      : !REV.mark              ? "revDapiOnly"
      : REV.dapi               ? (perk ? "revPerkDapi" : "revPcnaDapi")
                               : (perk ? "revPerkOnly" : "revPcnaOnly")) + ")";
  el("revMask").src = revSrc(p, "mask");
  el("revCensor").src = hasCen ? revSrc(p, "censor") : "";
  el("revTissue").src = p.has_tissue ? revSrc(p, "tissue") : "";

  drawRevOverlays(p, hasCen);

  const on = (id, v, dis) => {
    el(id).classList.toggle("mode-on", !!v);
    el(id).disabled = !!dis;
  };
  const pen = el("revPenChk");
  if(pen){
    // The clip needs a real tissue mask. Without one the box is not merely
    // ineffective, it would be a lie about what is on screen.
    pen.disabled = !p.has_tissue;
    pen.parentElement.style.opacity = p.has_tissue ? "1" : ".45";
    pen.parentElement.title = p.has_tissue ? ""
      : "needs a tissue mask - run: python scripts/04p_section_provenance.py --tissue-masks";
  }
  on("revDapiBtn",  REV.dapi,  !p.has_overview);
  on("revMarkBtn",  REV.mark,  !p.has_overview);
  on("revArtBtn",   REV.art,   !p.has_mask);
  on("revCenBtn",   REV.cen,   !hasCen);
  on("revApplyBtn", REV.apply, !p.has_mask);
  el("revDapiBtn").textContent = REV.dapi ? "DAPI ✓" : "DAPI";
  el("revMarkBtn").textContent = REV.mark
    ? (perk ? "pERK ✓" : "PCNA ✓") : (perk ? "pERK" : "PCNA");
  el("revCenBtn").title = hasCen ? "" :
    "no censor mask for this section - run 04j_censor_clipped.py";

  // The 4x is named rather than left to be noticed. A viewer that quietly
  // rescales one channel invites reading brightness off the screen, and DAPI
  // here is 4x further from its neighbours than it looks.
  const mk = perk ? "pERK red" : "PCNA green";
  el("revImgH").textContent = "IMAGE - "
    + (REV.mark && REV.dapi ? mk + " + DAPI blue x4"
     : REV.mark            ? mk.replace(/ (red|green)$/, "") + " only"
     : REV.dapi            ? "DAPI blue x4, no marker"
                           : "both channels hidden - masks only")
    + (REV.apply ? ", artifacts removed" : "");
  const bits = [];
  bits.push(p.has_mask
    ? `${p.n_artifact_objects || 0} artifact objects, `
      + `${p.artifact_pct_of_tissue || 0}% of tissue`
    : "no artifact mask");
  if(hasCen && p.censored_fraction_in_tissue !== ""){
    const pen = el("revPenChk") && el("revPenChk").checked;
    bits.push(`${(100 * (+p.censored_fraction_in_tissue || 0)).toFixed(2)}% of `
            + `tissue censored` + (pen ? "" : " - pen ring shown too"));
  }
  el("revImgNote").textContent = bits.join("  ·  ");
}

// A REINSTATED SECTION JOINS THE STRIP IMMEDIATELY.
//
// Review mode used to end at "recorded, now re-run 04a" - the decision was
// written, the section stayed invisible to the curator, and the only way to act
// on it was a pipeline run. Every scanned section now has a reformatted image
// and a composite, so the picture the strip needs already exists and the wait
// was for nothing.
//
// WHAT THIS DOES NOT DO IS PUT IT INTO THE ANALYSIS. The index is what does
// that, and only 04a writes the index. ROIs placed here are real curation and
// they export, but the nuclei behind them are not measured until 04a and 05c
// have run - which is exactly what exportReview() already warns about. The
// subset is written as "reinstated" so the export says where the row came from
// rather than implying it was in the worklist all along.
function reinstatedRow(p){
  const dir = "sections" + (p.marker === "AF568" ? "_AF568" : "")
            + (p.has_section_rgb ? "_rgb" : "");
  return {uid: p.scene_uid, animal: p.animal, m: p.marker, sub: "reinstated",
          order: +p.section_order || 0, rgb: !!p.has_section_rgb,
          img: dir + "/" + p.scene_uid + ".png", reinstated: true};
}

// Add the ones that are restored, drop the ones that no longer are, so undoing
// a reinstatement takes the section back out instead of leaving it stranded in
// a strip it can no longer be removed from.
function syncReinstated(){
  const want = new Set(Object.keys(S).filter(u =>
    S[u] && S[u].rev && S[u].rev.act === "restore"
    && P_BY[u] && P_BY[u].has_section));
  let changed = false;
  for(const uid of want){
    if(!DATA.some(d => d.uid === uid)){ DATA.push(reinstatedRow(P_BY[uid])); changed = true; }
  }
  for(let i = DATA.length - 1; i >= 0; i--){
    if(DATA[i].reinstated && !want.has(DATA[i].uid)){ DATA.splice(i, 1); changed = true; }
  }
  return changed;
}

// FULLSCREEN, and the redraw that has to go with it.
//
// The overlay canvas is stretched over the image by CSS, but what it holds is a
// bitmap sized in drawRevOverlays from clientWidth at the moment it was drawn.
// Resizing the element without redrawing would leave a ~320px bitmap scaled up
// to fill a 1400px box - a blurry mask sitting a few pixels off the artifact it
// is supposed to be marking, which is worse than no overlay because it still
// looks like an answer.
function revFull(on){
  const card = el("revImgCard");
  if(!card) return;
  const want = on === undefined ? !card.classList.contains("imgmax") : !!on;
  card.classList.toggle("imgmax", want);
  // Native fullscreen ON TOP of the class, never instead of it. It is allowed
  // to fail silently - the class has already filled the viewport - which is
  // what keeps this working from file:// and inside an embedding viewer.
  try {
    if(want && card.requestFullscreen && !document.fullscreenElement){
      const r = card.requestFullscreen();
      if(r && r.catch) r.catch(() => {});
    } else if(!want && document.fullscreenElement && document.exitFullscreen){
      const r = document.exitFullscreen();
      if(r && r.catch) r.catch(() => {});
    }
  } catch(e){ /* class-only is a complete answer */ }
  revRedrawOverlays();
  const b = el("revFullBtn");
  if(b) b.textContent = want ? "✖ Exit" : "⛶ Full";
}

// REDRAW WHEN THE BOX ACTUALLY CHANGES SIZE, not a guessed number of frames
// after asking it to.
//
// drawRevOverlays sizes the canvas bitmap from clientWidth at the moment it
// runs, and the canvas is then stretched over the wrapper by CSS. Get the
// timing wrong and the bitmap keeps the OLD dimensions while the box has the
// new ones - going fullscreen and back left a 1258x567 bitmap stretched into a
// 324x324 box, which is not merely blurry: the aspect ratios differ, so the
// overlay lands somewhere other than the artifact it is marking while still
// looking like a real answer.
//
// A double requestAnimationFrame was the first attempt and is a guess about
// how long layout takes - it held when the box grew and lost the race when it
// shrank. This asks the browser instead, and covers every cause at once:
// fullscreen in and out, a resized window, a resized panel.
const revBoxObserver = typeof ResizeObserver === "function"
  ? new ResizeObserver(() => {
      const p = P_BY[revSel];
      if(p) drawRevOverlays(p, !!p.has_censor);
    })
  : null;
if(revBoxObserver && el("revImgWrap")) revBoxObserver.observe(el("revImgWrap"));

// Kept for the browsers without ResizeObserver, and harmless where it observes:
// a second draw at the same size is idempotent.
function revRedrawOverlays(){
  const p = P_BY[revSel];
  if(!p) return;
  requestAnimationFrame(() => requestAnimationFrame(() =>
    drawRevOverlays(p, !!p.has_censor)));
}
// Leaving native fullscreen by Escape or the browser's own control does not go
// through revFull(), so the class has to be taken off here or the card would
// stay pinned over the page with no obvious way out.
document.addEventListener("fullscreenchange", () => {
  if(!document.fullscreenElement) {
    const card = el("revImgCard");
    if(card && card.classList.contains("imgmax")) revFull(false);
  } else revRedrawOverlays();
});
// The window can also change size under a maximised card - a real fullscreen
// transition, or just a resized window - and the bitmap is sized in pixels.
addEventListener("resize", () => {
  const card = el("revImgCard");
  if(card && (card.classList.contains("imgmax") || document.fullscreenElement))
    revRedrawOverlays();
});

function revAct(act){
  const p = P_BY[revSel];
  if(!p) return;
  // st() CREATES a record for whatever it is given, and `excl` below is enough
  // to make the export treat that record as a decision. Undoing a reinstatement
  // on a section nobody had otherwise touched would then leave an operator
  // exclusion it never made.
  //
  // `mine` is carried ON the decision rather than recomputed, because by the
  // time undo runs the record always exists - the restore created it - so
  // asking "did this exist?" at that moment always says yes. It has to be
  // answered once, when review first touches the section, and remembered.
  //
  // It cannot be inferred from content either: a record holding nothing but
  // excl:true is exactly what the 227 exclusions the operator really did record
  // look like, so there is no telling them apart afterwards.
  const had = Object.prototype.hasOwnProperty.call(S, revSel);
  const e = st(revSel);
  const mine = e.rev ? e.rev.mine : !had;
  // The exclusion to put back on undo is THE ONE THAT WAS THERE, captured once,
  // not one re-derived from p.status. The curator's flag and the pipeline's
  // status are different facts: an operator can exclude a section 04a happily
  // reformatted, and rebuilding the flag from the status would throw that
  // decision away the moment a reinstatement was undone.
  const wasExcl = e.rev ? e.rev.wasExcl : !!e.excl;
  if(!act){ delete e.rev; }
  else { e.rev = {act, why: el("revWhy").value.trim(), status: p.status,
                  mine, wasExcl}; }
  // Reinstating IS a curation decision, so the curator's own exclusion flag
  // follows it rather than contradicting it. Undo puts back exactly what was
  // there before review touched the section.
  e.excl = act === "restore" ? false : wasExcl;
  // Undo means undo. A record this call invented, carrying nothing but the
  // exclusion the pipeline already decided, says nothing the pipeline has not
  // said - and roi_plates.csv reports sections the OPERATOR touched.
  if(!act && mine && !e.assigned && !e.fav && !e.noroi && !e.pairs.length
     && !e.rot){
    delete S[revSel];
  }
  save();
  syncReinstated();
  revDetail();
  revRender();
  render();          // the strip, so the section is curatable without a reload
  status();
}

function revCount(){
  const all = Object.entries(S).filter(([, v]) => v && v.rev);
  const n = a => all.filter(([, v]) => v.rev.act === a).length;
  el("revCount").innerHTML = `${n("restore")} reinstate &middot; ${n("drop")} drop `
    + `&middot; ${n("unmask")} mask rejected`;
}

// Written in the SAME shape 04a_reformat.load_overrides already reads, one file
// per marker. `decision="restored"` is not new: 04a already counts how often the
// 04f proposal was overruled and reports it, so reinstating needs no format
// change and no change to 04a. `mask_rejected` is the one new column.
function exportReview(){
  const all = Object.entries(S).filter(([, v]) => v && v.rev);
  if(!all.length){ alert("no review decisions to export"); return; }
  const restores = all.filter(([, v]) => v.rev.act === "restore").length;
  if(restores && !confirm(
      `${restores} section(s) would be put back into the pipeline.\\n\\n`
    + `That changes the analysis set, so 05c_detect_rois.py has to run again for `
    + `the sections it changes - the nuclei already measured do not cover them. `
    + `Nothing is applied by this export; it writes the decisions for `
    + `04a_reformat.py --apply-overrides to act on.\\n\\nExport anyway?`)) return;

  const rows = [["scene_uid", "marker", "extra_rotation", "flip", "excluded",
                 "decision", "mask_rejected", "reason", "prior_status"]];
  for(const [uid, v] of all){
    const p = P_BY[uid] || {};
    const r = v.rev;
    rows.push([uid, p.marker || "", "", "",
               r.act === "drop" ? 1 : 0,
               r.act === "restore" ? "restored" : r.act === "drop" ? "manual" : "",
               r.act === "unmask" ? 1 : 0,
               // dl() quotes every cell now; quoting here too would double it.
               r.why || "", r.status || ""]);
  }
  beginExport();
  dl(rows, "section_review.csv");
}

el("roiSize").value = PT_R_CANON;
el("roiSizeVal").textContent = PT_R_CANON;
// Before the first render: a reinstatement made in an earlier session is still
// one, and the section has to be back in the strip for it to be curatable.
syncReinstated();
scopeLabel();
shotBtnState();
render();
// The picked folder outlives the page; the button is hidden where the browser
// has no picker, because offering it there would be a lie.
if(!window.showDirectoryPicker){ const b = el("expDirBtn"); if(b) b.style.display = "none"; }
expShow();
expRestoreDir();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--animal", default=None)
    ap.add_argument("--marker", choices=("AF488", "AF568"), default="AF568",
                    help="which channel the page OPENS on. Both are always loaded - "
                         "the selector next to the sample selector switches - so this "
                         "chooses the starting view, not what is in the page. "
                         "AF568 = pERK (the channel that gets quantified), AF488 = PCNA")
    ap.add_argument("--analysis-set", action="store_true",
                    help="narrow the pERK side to perk_analysis_set.csv. A pERK "
                         "subset only; PCNA keeps its full set")
    ap.add_argument("--worklist", nargs="?", const=WORKLIST_CSV, default=None,
                    metavar="CSV",
                    help="order the pERK side by 04n_roi_worklist.py, so stopping "
                         "part way still leaves every animal and every level covered. "
                         "Keyed on pERK uids, so PCNA keeps its full set")
    ap.add_argument("--tier", default=None,
                    help="with --worklist: only this tier (e.g. core)")
    ap.add_argument("--no-seed", action="store_true",
                    help="do not carry the app's curation into the page. The "
                         "page normally embeds whatever is in "
                         "out_root/curation so a browser copy opens with the "
                         "same work; this leaves it empty instead")
    ap.add_argument("--rgb", action="store_true",
                    help="show the two-colour composites from 04o_section_rgb.py "
                         "(DAPI blue + marker) instead of the greyscale DAPI the "
                         "geometry was computed on. Same frame either way.")
    ap.add_argument("--export-dir", default=EXPORT_DIR, metavar="DIR",
                    help="where exports are filed, one dated DD.MM.YYYY_HH.MM "
                         "folder per export. Shown in the page; honoured by the "
                         "app. A browser writes here only once the operator has "
                         "picked the folder with the page's own Folder... button, "
                         "because a web page cannot be handed a path")
    ap.add_argument("--out", default=CURATOR_HTML, metavar="HTML",
                    help="where to write the page (default: the live curator under "
                         "out_root). tests/run.sh points this at tests/build/ so a "
                         "test run never rewrites the page being curated in")
    args = ap.parse_args()
    if args.worklist and not os.path.exists(args.worklist):
        raise SystemExit(f"--worklist: {args.worklist} not found - run 04n_roi_worklist.py first")

    # Both channels go into one page. They are separate physical sections and
    # stay independently curated - this shares the TOOL, not the decisions - so
    # each channel is assembled on its own terms and tagged with its own subset.
    def build(marker):
        index_csv, img_dir = marker_paths(marker)
        rgb_dir = img_dir + "_rgb"
        with open(index_csv, newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r["kind"] == "section"]
        before, subset = len(rows), "all"

        if args.analysis_set and marker == "AF568":
            keep, _n_perk, _unpaired = analysis_uids(marker)
            rows = [r for r in rows if r["id"] in keep]
            subset = "perk_analysis_set"

        # The worklist is keyed on pERK uids, because that is the channel being
        # quantified. Reaching the PCNA side means following the pairing, which
        # the 30 unpaired sections do not survive and which would make one
        # channel's job depend on the other's. So it narrows pERK only; PCNA is
        # curated on its own full set, by the same logic in the same tool.
        rank = None
        if args.worklist and marker == "AF568":
            with open(args.worklist, newline="", encoding="utf-8") as fh:
                wl = [r for r in csv.DictReader(fh)
                      if not args.tier or r["tier"] == args.tier]
            rank = {r["scene_uid"]: int(r["rank"]) for r in wl}
            rows = [r for r in rows if r["id"] in rank]
            subset = "roi_worklist" + (":" + args.tier if args.tier else "")

        if args.animal:
            rows = [r for r in rows if r["animal"] == args.animal]
        rows.sort(key=lambda r: (rank[r["id"]],) if rank
                  else (r["animal"], int(r["section_order"] or 0)))

        # Per section, not per run: a channel can be part-built, and a page that
        # claimed a composite it does not have would show a broken image and
        # offer a DAPI toggle that does nothing. Whatever is missing falls back
        # to the greyscale the geometry was computed on.
        out = []
        for r in rows:
            has = args.rgb and os.path.exists(
                os.path.join(REFORMAT_DIR, rgb_dir, r["id"] + ".png"))
            out.append({"uid": r["id"], "animal": r["animal"], "m": marker,
                        "sub": subset, "rgb": bool(has),
                        "order": int(r["section_order"] or 0),
                        "img": (rgb_dir if has else img_dir) + "/" + r["id"] + ".png"})
        return out, subset, before

    per_marker, markers = {}, []
    for mk in ("AF568", "AF488"):
        got, subset, before = build(mk)
        per_marker[mk] = (got, subset, before)
        markers.append({"id": mk, "label": "pERK" if mk == "AF568" else "PCNA",
                        "n": len(got), "sub": subset})
    data = per_marker["AF568"][0] + per_marker["AF488"][0]

    with open(os.path.join(PLATE_DIR, "plates.csv"), newline="", encoding="utf-8") as fh:
        plates = list(csv.DictReader(fh))
    # Loaded and numbered by the shared helpers above, so this tool and the
    # atlas region tracer agree about which seed is seed 4.
    seeds = load_seeds()

    pl = []
    for p in sorted(plates, key=lambda p: p["plate_id"]):
        img = os.path.join(PLATE_DIR, p["image_file"])
        if not os.path.exists(img):
            continue
        sd = seeds.get(p["plate_id"], [])
        # The ROI grouping, and the number every seed under it carries.
        hulls = region_hulls(sd)
        tag_rois(sd, hulls)
        # How much room a label actually has on THIS plate: the median distance
        # from a seed to its nearest neighbour, as a fraction of the plate
        # diagonal. A fraction rather than pixels because the page has to turn it
        # into screen pixels against whatever size the pane currently is - bake
        # in pixels and the scaling goes stale the moment the window changes.
        nn = 0.0
        if len(sd) > 1:
            pw, ph = int(p["px_w"]), int(p["px_h"])
            pts = [(x["xf"] * pw, x["yf"] * ph) for x in sd]
            diag = math.hypot(pw, ph)
            near = sorted(min(math.dist(a, b) for j, b in enumerate(pts) if j != i)
                          for i, a in enumerate(pts))
            nn = near[len(near) // 2] / diag
        pl.append({"id": p["plate_id"], "nn": round(nn, 5),
                   # Original plate, NOT reformatted: the seeds are fractions of
                   # this image, so no transform chain is needed.
                   "img": f"../atlas/{PLATE_SET}/{p['image_file']}",
                   "w": int(p["px_w"]), "h": int(p["px_h"]),
                   "labelled": int(bool(sd)), "seeds": sd,
                   # What a REGION is on this plate, as opposed to where its
                   # individual seeds are. One entry per region per lobe.
                   "hulls": hulls})

    # The curation the app has on file, carried into the page so a browser copy
    # opens with the same work rather than empty. --no-seed leaves it out, which
    # is what you want when handing the file to someone who should start clean.
    seed = {}
    if not args.no_seed:
        seed_path = os.path.join(OUT_ROOT, "curation", "ls_roi_curator_v1.json")
        try:
            with open(seed_path, encoding="utf-8") as fh:
                seed = json.load(fh)
        except (OSError, ValueError):
            seed = {}

    page = IO.fill(PAGE, {
        "__SEED__": seed, "__PROV__": load_provenance(), "__DATA__": data,
        "__PLATES__": pl, "__PLATESET__": PLATE_SET, "__MARKERS__": markers,
        "__MARKER__": args.marker, "__SECGRID__": SEC_GRID, "__GROUPS__": GROUPS,
        "__EXPORTDIR__": args.export_dir})
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)

    lab = [p for p in pl if p["labelled"]]
    print(f"wrote {args.out}")
    # Loud, because a page that can lay itself out by treatment is a page that
    # is no longer blind, and that should never be discovered by accident.
    if GROUPS["by_animal"] and GROUPS["order"]:
        n = len(GROUPS["by_animal"])
        print(f"  UNBLINDED: group key loaded for {n} animals "
              f"({' / '.join(GROUPS['order'])}) - the Shotgun deck is laid out by "
              f"treatment. Nothing else in the page reads it.")
    else:
        print("  no group key in config.json - Shotgun is disabled in this page "
              "(fill in groups.order and groups.by_animal to enable it)")
    if seed:
        print(f"  carrying {len(seed)} curated sections into the page")
    for m in markers:
        got, _sub, before = per_marker[m["id"]]
        nrgb = sum(1 for d in got if d["rgb"])
        note = "" if m["sub"] == "all" else f"  [{m['sub']}]"
        print(f"  {m['label']:5} {m['n']:4} of {before} sections{note}"
              f"   {nrgb} with a colour composite")
    print(f"  {len(data)} sections in the page, {len(pl)} plates, "
          f"{sum(len(p['seeds']) for p in pl)} region seeds")
    print(f"  {len(lab)} plates carry seeds"
          + (f": {lab[0]['id']} .. {lab[-1]['id']}" if lab else " - no region can be placed yet"))

    # The lobe split is the one thing about the hulls that can be silently wrong,
    # so it is reported rather than assumed. A region that comes out in ONE part
    # on a plate where it is bilateral would be drawn as a band across the whole
    # brain - the failure `04f_exclusion_candidates.py` documents for solidity -
    # and the widest hull is what makes that visible at a glance. On the current
    # atlas: Dl and Dm split in two on all 17 of their plates, POA and the tuberal
    # regions stay in one at the midline, and the widest hull is 0.20 of a plate
    # against 0.90 without the split.
    hulls = [h for p in pl for h in p["hulls"]]
    if hulls:
        wide = max((max(v[0] for v in h["v"]) - min(v[0] for v in h["v"]), h)
                   for h in hulls)
        multi = sorted({h["region"] for h in hulls if h["n_parts"] > 1})
        one = sorted({h["region"] for h in hulls if h["n_parts"] == 1})
        print(f"  {len(hulls)} region hulls, widest {wide[0]:.2f} of a plate "
              f"({wide[1]['region']})")
        print(f"    split per lobe: {', '.join(multi) if multi else '(none)'}")
        print(f"    one part:       {', '.join(one) if one else '(none)'}")
        if wide[0] > 0.5:
            print(f"    WARNING: a hull spans more than half the plate. The lobe "
                  f"split at LOBE_GAP={LOBE_GAP} is not separating hemispheres "
                  f"on this plate set.")
    print()
    print("Scrub the plate slider until it matches, then click matching points -")
    print("section first, then plate. From three pairs there is a transform and a")
    print("per-landmark residual; from six it is a thin-plate spline. Nothing is")
    print("warped onto the section - the residual is the check.")
    print()
    print("Then press e for Region mode: click a region's shape on the plate to")
    print("say which one you are drawing, and click out its outline on the")
    print("section. A region drawn over its landmarks takes them over, so they")
    print("stay landmarks and stop being discs. h hides the hulls.")
    print()
    print("Only the plates listed above have regions to give. A section assigned")
    print("elsewhere gets no ROIs, so there is no reason to place landmarks on it -")
    print("the working subset selects itself.")
    print()
    print("Export writes roi_landmarks.csv (every pair, with its residual) and")
    print("roi_regions.csv (one row per ROI placed, at the radius it was placed")
    print("at - nothing positioned by the transform). Background discs share that")
    print("file and are told apart by roi_kind, because they are measured the")
    print("same way: what the detector finds in them is its false-positive rate.")
    print()
    print(f"Exports are filed under {args.export_dir}, one folder per export named")
    print("DD.MM.YYYY_HH.MM, with the same stamp on every file in it - so a second")
    print("export an hour later sits beside the first rather than over it.")
    print()
    print("In a browser that has the folder picker (Chrome, Edge) the page writes")
    print("there directly once you have pressed Folder... and chosen it; the choice")
    print("is remembered. Everywhere else - Firefox, Safari, and the app - the file")
    print("is downloaded with the stamp in its name and the host files it: the app")
    print("reads the stamp back off the name and rebuilds the same folder.")


if __name__ == "__main__":
    main()
