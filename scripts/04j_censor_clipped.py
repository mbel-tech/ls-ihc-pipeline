"""Stage 4j - censor clipped pixels and fix the analysis set, per marker.

Clipping is information loss, not miscalibration: a pixel pinned at the
16-bit ceiling has lost its value and no normalisation recovers it. See LOGS.md -
restricted to clip-free sections the two apparent "staining batches" turn out to
be identical, so the whole 1.86x background gap is produced by the clipping
itself.

Two mechanisms, and they are deliberately separate because they mean different
things:

**Section level - a 1% tolerance, on tissue.** Sections with 1% or more of
their *tissue* pixels at the ceiling are set aside. Not deleted: recorded in
`perk_analysis_set.csv` with `in_analysis_set = 0`, so the decision is visible
and reversible. The frame fraction is kept beside it as `censored_fraction`, and
`gate` records which of the two decided.

**Pixel level - censoring, not masking.** Within the sections that stay, clipped
pixels are marked as **right-censored**: their true value is unknown but at least
the ceiling.

*That is not the same as the artifact mask and must not be treated as it.* An
artifact pixel is not tissue and should leave the analysis entirely. A censored
pixel is real signal that happens to be unmeasurable, so:

  * it MUST be excluded from any intensity statistic - mean, median, the negative
    peak UniFORM aligns on - because including a floor value biases every one of
    them downward;
  * it MUST NOT be excluded from detection or from positivity, because a pixel at
    the ceiling is unambiguously positive. Dropping it would bias positive counts
    *down* in exactly the animals with the brightest staining.

Getting that backwards would turn a data-quality problem into a group difference.

Where the mask comes from
-------------------------

`qc/censor_raw/<uid>_clipped.png`, written by `01k_saturation_raw.py` off the
**raw** 16-bit marker plane.

**It used to come from the 8-bit overview, and that was wrong.** The AF568
display high is 65535, so value 255 in `_MARK.png` looks like exactly the clipped
set - and the docstring here used to defend it by reporting a median absolute
difference of 0.00000 against `saturated_fraction` in `focus.csv`. That agreement
was real and it proved nothing, because **both sides were measured after
`apply_tile_field()`**. Dividing by a gain above 1 lifts a pixel off the ceiling
and it stops reading as clipped, while its value is exactly as lost as before -
the field cannot restore what the sensor never recorded. `tilefield_c1` runs
0.812-1.097 and exceeds 1.0 over **54%** of its area, so the old mask held only
about **46%** of the clipped pixels:

    LS45_1a.czi sc14   raw 0.28314   corrected 0.13611   (focus.csv: 0.13611)
    LS53_2b.czi sc11   raw 0.42662   corrected 0.20842
    median raw / corrected = 1.97 over the corpus

The missing half did not merely go uncounted. After division each of those
pixels carries a plausible-looking `65535/gain` value, so it entered every
intensity statistic as an ordinary measurement - which is the precise failure
this stage exists to prevent.

**What it did and did not change.** The section-level tolerance barely moves: the
split is strongly bimodal - the analysis set sits at p99 0.33% clipped against a
censored-out median of 10.6% - so the correction crosses only 4 of 454 sections.
The pixel-level mask is where it matters, because `05c_detect_rois.py` samples it
into the per-nucleus `censored` column and `06a_roi_dataset.py` decides
positive-but-unusable from that.

Correcting the mask means the per-nucleus flags must be recomputed;
`06f_recensor_nuclei.py` does that from the stored positions rather than by
re-running StarDist.

Both markers, because AF488 was never actually checked
------------------------------------------------------

This stage used to be pERK-only, on the stated grounds that "AF488 cannot clip,
so there is nothing to censor". That was an inference from the same broken test,
not a measurement. AF488's display high is 37,263, so a value of 255 in its 8-bit
overview means "at or above the display high" - it cannot distinguish a bright
pixel from a clipped one, and the question was unanswerable rather than answered.

Measured on the raw 16-bit plane, **AF488 does clip**: on most sections, at a
median of 0.000007 of frame, reaching **1.3%** on the worst. Small, and far below
the 1% section tolerance almost everywhere - but not zero, and a clipped PCNA
pixel is right-censored for exactly the reasons set out above. `--marker AF488`
writes `pcna_analysis_set.csv` alongside the same shared censor directory; scene
uids carry the pass letter, so the two cannot collide.

For a future `05c` run to pick the AF488 masks up in the 256 frame, `04a_reformat
--censor --marker AF488` has to run as well - `05c` reads the `.npy`, not the PNG.

What "tissue" means here, and what it used to mean
---------------------------------------------------

The gate used to be decided on the **frame** fraction, and
`censored_fraction_in_tissue` was measured against `DAPI overview > 0`. Neither
was tissue. `01_overviews.py` stretches the 8-bit overview from the frame's 1st
percentile (`LO_PCT = 1.0`), so `> 0` is simply the frame minus its darkest
percent - measured, 81-93% of the frame on five sections, against 23-41% for
the pipeline's own tissue mask. The "in tissue" column therefore tracked the
frame fraction (ratio in_tissue/frame median 1.17 on disk), and the gate set
sections aside for clipping that never touched a nucleus: with the real mask,
**96.6% of censored pixels are outside the tissue**, on the PAP pen ring
(`04p_section_provenance.py` had already put the figure at 82% and built
`tissue/<uid>_tissue.png` for exactly this reason).

Now: the tissue mask is `tissue/<uid>_tissue.png` (04p `--tissue-masks`,
overview frame) when present, else rebuilt the way 04p builds it -
`04a_reformat.tissue_mask` on the DAPI overview squashed to the work grid, the
log-space Otsu every other stage uses. The section verdict is
`censored_fraction_in_tissue < tolerance`. Where no tissue mask can be built
the frame fraction decides, `gate = frame`, and the count is printed - that is
the old behaviour, kept only as a fallback and made visible.

Recomputed read-only against the same censor masks, this moves 184 of 718 pERK
sections from set-aside to kept (450 -> 634); none go the other way. LS53 goes
from 0 measurable sections to 9 and LS85 from 3 to 45. The pixel-level
censoring is untouched - a clipped pixel on tissue is as censored as it ever was.

Run:  python 04j_censor_clipped.py
      python 04j_censor_clipped.py --marker AF488
      python 04j_censor_clipped.py --tolerance 0.005
"""

import argparse
import csv
import importlib.util
import json
import os

import sys
import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_channels as CH  # noqa: E402
import ls_naming as NM  # noqa: E402
import ls_paths as LP  # noqa: E402

# The markers this study measures, in declared order. ls_channels is the
# single source of that list; naming a fluorophore here would pin the stage
# to one study.
MARKERS = list(CH.marker_names(CONFIG))

OUT_ROOT = CONFIG["out_root"]
OVERVIEW_DIR = os.path.join(OUT_ROOT, "overviews")
REFORMAT_DIR = os.path.join(OUT_ROOT, "reformatted")
QC_CSV = os.path.join(OUT_ROOT, "qc", "focus.csv")
CENSOR_DIR = os.path.join(OUT_ROOT, "censor")
# Per-marker output.
#
# The name is ls_paths' to state, not this stage's. It was a LEGACY_ANALYSIS_SET
# dict here and, separately, the bare literal `perk_analysis_set.csv` in 04l -
# two copies of one fact, kept in step by a comment in each pointing at the
# other, and 04l's copy was wrong for every study whose first marker is not
# AF568. ls_paths already carried both names in its LEGACY table; the rule that
# reads them now lives beside it.
#
# What the rule says has not changed: `perk_analysis_set.csv` and
# `pcna_analysis_set.csv` are FILES THAT EXIST on the operator's drive, read by
# 04l, 04m and 04p and by the app's stage table, so those two names cannot
# move; every other marker - and every other study - gets a name derived from
# the marker itself.
NAMES = LP.for_config(CONFIG)


def analysis_set_path(marker):
    """Where this marker's analysis set is written."""
    return NAMES.analysis_set_path(marker)


#: The same table the old dict literal was, now built for whatever markers the
#: study declares. Kept for readers and for anything that wants to see all of
#: them at once; the single use site calls analysis_set_path() so that a marker
#: outside this table is a derived name rather than a KeyError.
ANALYSIS_SET = {m: analysis_set_path(m) for m in MARKERS}
# Display names for the markers, when the study gives them one. A paired study
# names its markers by fluorophore, so this is usually empty and the marker's
# own name is what gets shown.
LABEL = {c.name: c.name for c in
         CH.markers(CH.parse((CONFIG.get("acquisition") or {}).get("channels")))}

_spec = importlib.util.spec_from_file_location(
    "_rf", os.path.join(os.path.dirname(os.path.abspath(__file__)), "04a_reformat.py"))
RF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RF)

_lsio = importlib.util.spec_from_file_location(
    "_lsio", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ls_io.py"))
IO = importlib.util.module_from_spec(_lsio)
_lsio.loader.exec_module(IO)

TOLERANCE = 0.01         # section-level: 1% of TISSUE pixels at the ceiling
# The analysis-set columns, pinned rather than read off rows[0]: an empty
# result must still leave a file with a header behind.
ANALYSIS_KEYS = ["scene_uid", "animal", "section_order", "censored_fraction",
                 "censored_fraction_in_tissue", "recorded_saturated_fraction",
                 "recorded_saturated_fraction_raw", "in_analysis_set", "gate",
                 "reason"]
RAW_MASK_DIR = os.path.join(OUT_ROOT, "qc", "censor_raw")
TISSUE_DIR = os.path.join(OUT_ROOT, "tissue")   # 04p --tissue-masks, overview frame


def censor_mask(uid):
    """Right-censored pixels: at the 16-bit ceiling, value unknown but >= it.

    Read from 01k_saturation_raw.py, which measures the RAW plane. This used to
    threshold the exported 8-bit `_MARK.png` at 255, which is a post-tile-field
    image: dividing by a gain above 1 lifts a pixel off the ceiling so it stops
    reading as clipped, even though its value is just as gone. `tilefield_c1`
    exceeds 1.0 over 54% of its area, so that mask missed roughly half the
    clipped pixels - and they went on into `05c_detect_rois.py`'s per-nucleus
    `censored` column carrying a fabricated 65535/gain value.
    """
    p = os.path.join(RAW_MASK_DIR, uid + "_clipped.png")
    if not os.path.exists(p):
        return None
    try:
        return np.asarray(Image.open(p).convert("L")) > 0
    except OSError:
        return None


def build_tissue_mask(dapi_path):
    """Tissue mask in the overview frame, built the way 04p.write_tissue_masks
    builds it: `04a_reformat.tissue_mask` (log-space Otsu, dark background) on
    the DAPI overview squashed to the WORK_SIZE grid, then stretched back with
    nearest-neighbour. Same function, same grid, so this is the pipeline's own
    opinion of tissue and not a fresh one. None when it cannot be built."""
    try:
        im = np.asarray(Image.open(dapi_path).convert("L")).astype(np.float32)
    except OSError:
        return None
    small = np.asarray(Image.fromarray(im).resize(
        (RF.WORK_SIZE, RF.WORK_SIZE), Image.BILINEAR)).astype(np.float32)
    t = RF.tissue_mask(small, light_background=False)
    if t is None:
        return None
    big = Image.fromarray(t.astype(np.uint8) * 255).resize(
        (im.shape[1], im.shape[0]), Image.NEAREST)
    return np.asarray(big) > 0


def load_tissue_mask(uid, dapi_path, tissue_dir=TISSUE_DIR):
    """`tissue/<uid>_tissue.png` when 04p has written it, else rebuilt from the
    DAPI overview. None when neither is possible - the caller falls back to the
    frame and says so."""
    p = os.path.join(tissue_dir, uid + "_tissue.png")
    if os.path.exists(p):
        try:
            return np.asarray(Image.open(p).convert("L")) > 0
        except OSError:
            pass
    if not os.path.exists(dapi_path):
        return None
    return build_tissue_mask(dapi_path)


def tissue_fraction(cen, tissue_mask):
    """Fraction of TISSUE pixels that are censored; nan without a tissue mask."""
    if tissue_mask is None or not tissue_mask.any():
        return float("nan")
    return float(cen[tissue_mask].mean())


def section_verdict(frac_frame, frac_tissue, tolerance):
    """The section-level decision, as the columns it is written out with.

    Decided on the in-tissue fraction. The frame fraction is recorded but does
    not decide unless there is no tissue mask at all, and `gate` says which."""
    if frac_tissue == frac_tissue:      # not nan
        gate, deciding, where = "tissue", frac_tissue, "of tissue pixels"
    else:
        gate, deciding, where = "frame", frac_frame, "of frame pixels (no tissue mask)"
    keep = deciding < tolerance
    return {
        "censored_fraction": round(frac_frame, 6),
        "censored_fraction_in_tissue": round(frac_tissue, 6),
        "in_analysis_set": int(keep),
        "gate": gate,
        "reason": "" if keep
                  else f"{100 * deciding:.1f}% {where} at the 16-bit ceiling "
                       f"(tolerance {100 * tolerance:.0f}%)",
    }


def unmeasured_row(uid, animal, section_order):
    """A section 01k has no raw mask for. Present in the file with a BLANK
    in_analysis_set, so 04m can say "unmeasured" rather than reading an absent
    row as censored - which is a false statement about clipping."""
    return {"scene_uid": uid, "animal": animal, "section_order": section_order,
            "censored_fraction": "", "censored_fraction_in_tissue": "",
            "recorded_saturated_fraction": "", "recorded_saturated_fraction_raw": "",
            "in_analysis_set": "", "gate": "",
            "reason": "no raw clipping mask - run 01k_saturation_raw.py"}


def is_complete(rows):
    return all(r["in_analysis_set"] != "" for r in rows)


def guard_partial(out_csv, rows, allow):
    """Refuse to replace a COMPLETE analysis set with a partial one.

    A 04j run on a half-built censor_raw/ used to shrink the set silently and
    every section it lacked became "censored" downstream. Now it stops, unless
    --allow-partial says the shrink is meant.
    """
    if allow or is_complete(rows) or not os.path.exists(out_csv):
        return None
    with open(out_csv, newline="", encoding="utf-8") as fh:
        old = list(csv.DictReader(fh))
    if old and is_complete(old):
        n_un = sum(1 for r in rows if r["in_analysis_set"] == "")
        raise SystemExit(f"{out_csv} is complete ({len(old)} rows) but this run has "
                         f"{n_un} unmeasured section(s). Run 01k_saturation_raw.py "
                         f"first, or pass --allow-partial to write anyway.")
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tolerance", type=float, default=TOLERANCE,
                    help="section is set aside at or above this clipped fraction")
    ap.add_argument("--allow-partial", action="store_true",
                    help="write the analysis set even if it has unmeasured sections "
                         "and the file on disk is complete")
    _default = MARKERS[0] if MARKERS else None
    ap.add_argument("--marker", default=_default, choices=MARKERS,
                    help=f"which marker to process (default {_default})")
    args = ap.parse_args()
    marker = args.marker
    label = LABEL.get(marker, marker)
    out_csv = analysis_set_path(marker)
    os.makedirs(CENSOR_DIR, exist_ok=True)
    # Scene uids carry the pass letter (..._s03a_ vs ..._s03b_), so both markers
    # can share one censor directory without colliding.
    print(f"{label} ({marker}) -> {out_csv}")

    foc = {r["scene_uid"]: r for r in csv.DictReader(open(QC_CSV, encoding="utf-8"))}
    with open(RF.marker_paths(marker)["index"], newline="", encoding="utf-8") as fh:
        kept = [r for r in csv.DictReader(fh) if r["kind"] == "section"]

    rows, missing, no_tissue = [], [], []
    for i, r in enumerate(kept, 1):
        uid, animal = r["id"], r["animal"]
        dapi = os.path.join(OVERVIEW_DIR, animal, marker, uid + "_DAPI.png")
        cen = censor_mask(uid)
        if cen is None:
            missing.append(uid)
            rows.append(unmeasured_row(uid, animal, r["section_order"]))
            continue
        tis = load_tissue_mask(uid, dapi)
        if tis is not None and tis.shape != cen.shape:
            tis = None
        if tis is None:
            no_tissue.append(uid)

        frac_frame = float(cen.mean())
        frac_tissue = tissue_fraction(cen, tis)
        # Both, so the size of the old undercount stays visible in the output
        # rather than only in a log entry.
        recorded = float(foc.get(uid, {}).get("saturated_fraction", "nan") or "nan")
        recorded_raw = float(foc.get(uid, {}).get("saturated_fraction_raw", "nan") or "nan")

        # Written for every section, including the ones set aside - a later stage
        # may want to know what it is missing.
        Image.fromarray((cen * 255).astype(np.uint8)).save(
            os.path.join(CENSOR_DIR, uid + "_censor.png"))

        v = section_verdict(frac_frame, frac_tissue, args.tolerance)
        rows.append({
            "scene_uid": uid, "animal": animal, "section_order": r["section_order"],
            "censored_fraction": v["censored_fraction"],
            "censored_fraction_in_tissue": v["censored_fraction_in_tissue"],
            "recorded_saturated_fraction": recorded,
            "recorded_saturated_fraction_raw": recorded_raw,
            "in_analysis_set": v["in_analysis_set"],
            "gate": v["gate"],
            "reason": v["reason"],
        })
        if i % 100 == 0:
            print(f"\r  {i}/{len(kept)}", end="")
    print(f"\r  measured {len(rows)} {label} sections        ")
    if missing:
        # Loud, not silent. A missing raw mask used to be
        # indistinguishable from a section with no clipping, which is
        # the difference between "measured zero" and "never measured".
        print(f"  !! {len(missing)} sections have no raw clipping mask in "
              f"{RAW_MASK_DIR} and are in the file as UNMEASURED "
              f"(blank in_analysis_set).")
        print(f"     Run 01k_saturation_raw.py first. First few: {missing[:5]}")
    if no_tissue:
        print(f"  !! {len(no_tissue)} sections have no tissue mask (none in {TISSUE_DIR} "
              f"and none could be built from the DAPI overview); their verdict was")
        print(f"     decided on the FRAME fraction (gate = frame). First few: {no_tissue[:5]}")

    guard_partial(out_csv, rows, args.allow_partial)
    IO.atomic_write_csv(out_csv, rows, ANALYSIS_KEYS)

    keep = [r for r in rows if r["in_analysis_set"] == 1]
    drop = [r for r in rows if r["in_analysis_set"] == 0]
    unmeasured = [r for r in rows if r["in_analysis_set"] == ""]
    cf = np.array([r["censored_fraction_in_tissue"] for r in keep if r["gate"] == "tissue"])
    print()
    print("=" * 74)
    print(f"{len(rows)} {label} sections -> {out_csv}")
    print(f"  in the analysis set (< {100 * args.tolerance:.0f}% of TISSUE clipped) : "
          f"{len(keep)} ({100 * len(keep) / len(rows):.0f}%)")
    print(f"  set aside                                : {len(drop)}")
    print(f"  unmeasured (no raw mask)                 : {len(unmeasured)}")
    print(f"  decided on the frame (no tissue mask)    : {len(no_tissue)}")
    print(f"  censor masks written to {CENSOR_DIR}/<uid>_censor.png")
    if len(cf):
        print()
        print(f"  within the analysis set, censored fraction of tissue: median {np.median(cf):.5f}, "
              f"p95 {np.percentile(cf, 95):.5f}, max {cf.max():.5f}")
        print(f"  sections with NO censored pixels on tissue: {int((cf == 0).sum())}")

    per = {}
    for r in rows:
        d = per.setdefault(r["animal"], [0, 0])
        d[0] += 1
        d[1] += 1 if r["in_analysis_set"] == 1 else 0
    print()
    print(f"  {'animal':<8}{label:>7}{'in set':>8}{'%':>6}")
    for a in sorted(per, key=NM.natural_key):
        t, k = per[a]
        print(f"  {a:<8}{t:>7}{k:>8}{100 * k / t:>5.0f}%")
    lost = [a for a, (t, k) in per.items() if k == 0]
    if lost:
        print(f"\n  ANIMALS WITH NOTHING LEFT: {', '.join(sorted(lost))}")
        print("  They cannot contribute to the marker analysis at any tolerance that")
        print("  excludes them; that is a decision about n, not about thresholds.")
    print()
    print("Censored != masked. A clipped pixel is real signal whose value is lost:")
    print("  exclude it from intensity statistics, KEEP it for detection and")
    print("  positivity. Dropping it from counts would bias positive rates DOWN in")
    print("  exactly the animals with the brightest staining.")
    print("=" * 74)


if __name__ == "__main__":
    main()
