"""Stage 5c - count nuclei in every placed ROI, and measure the marker in them.

Reads the CZI at native 0.65 um/px over the boxes `05a` computed, segments
nuclei on DAPI, and measures the marker channel inside each nuclear mask.

**Segment on DAPI, never on the marker.** Detecting on the marker channel would
define "number of pERK+ cells" by the threshold twice over: once to find the
object and again to call it positive, so the count and the cut could never be
varied independently. Nuclei come from the counterstain; the marker is measured
afterwards; positivity is decided last and can be changed without re-reading a
single CZI. The rest of the pipeline already leans on DAPI for the same reason -
`04a_reformat` decides all its geometry there because "the marker channel is a
sparse signal and a poor silhouette".

That is the DEFAULT, and it is what the live study does. A study may declare
`segment: own` on a marker whose objects are not nuclei at all - fibre
staining, processes, plaques - and then the argument above does not apply,
because there is no nuclear mask those objects could be measured inside. The
cost is exactly the one named above and is not avoidable for such a marker:
the count and the positivity cut both come off one channel. Which route each
marker took is recorded per row in `segmented_on` / `backend` /
`nucleus_shaped`, so a reader can tell them apart without the config that made
them. No study declares `segment: own` today.

**StarDist, not threshold-and-watershed.** Not a general preference: watershed
under-segments where nuclei touch, and Vv, Vd and POA are periventricular. The
error would be worst in exactly those ROIs and mild in Dm and Dl, and a
region-correlated counting bias survives into the results looking like an
anatomical finding.

**What a background disc is for.** It is measured by this stage identically to a
real ROI - same read, same segmentation, same statistics, distinguished only by
`roi_kind`. Two things come out of that: a per-section reference level measured
rather than inferred, and a false-positive rate, since the same detector runs
over tissue the operator called empty. It is NOT a negative control: the primary
antibody is on that tissue too, so it measures non-specific binding plus
autofluorescence, not zero.

Writes `results/roi_nuclei.csv`, one row per nucleus. That is the artefact that
matters - with per-nucleus intensities on disk the positivity cut becomes a
decision about a table rather than a reason to re-read 130 CZI scenes.

Under the `threshold` backend, and only there, an ROI whose frame breaks that
backend's background assumption is written to
`qc/roi_background_assumption.csv` and counted at the end of the run. The
assumption is that most of a fluorescence frame is background, so its median
estimates it; past about half coverage the median lands inside an object, the
cut is derived from the object, and the ROI reports zero objects - which this
stage answers with `continue`, so it contributes no rows and 06a publishes
n = 0 and a density of 0.0 for it. That file is what makes such a zero
different from an empty ROI's. Nothing in the live study reaches it: both its
markers are `segment: nuclear`, which is StarDist.

Under `multiplex`, and only there, it also writes
`results/roi_colocalisation.csv`: which object of one marker contains which
object of another, both directions recorded. Under `paired` that file is not
written AT ALL, because paired markers are separate scans of different
sections and an empty file would read as "nothing overlaps" rather than "the
question does not apply". The live study is paired, so it has no such file.

Run:  python 05c_detect_rois.py
      python 05c_detect_rois.py --limit 5
      python 05c_detect_rois.py --qc            # also write overlay crops to
                                                # qc/roi_detections/ - green =
                                                # counted, red = outside the disc
"""

import argparse
import csv
import importlib.util
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_g5", os.path.join(_HERE, "05a_roi_geometry.py"))
G5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G5)

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
# ls_config resolves LS_CONFIG, applies the defaults and validates once for
# the whole process. Imported, not re-implemented: this block used to be four
# lines copy-pasted into every stage.
from ls_config import CONFIG, CONFIG_PATH  # noqa: E402
import ls_naming as NM  # noqa: E402
import czi_read as CR  # noqa: E402
import ls_channels as CH  # noqa: E402
import ls_segment as SG  # noqa: E402
import ls_coloc as CO  # noqa: E402
OUT_ROOT = G5.OUT_ROOT
REFORMAT_DIR = G5.REFORMAT_DIR
RESULTS = os.path.join(OUT_ROOT, "results")
NUCLEI_CSV = os.path.join(RESULTS, "roi_nuclei.csv")
QC_DIR = os.path.join(OUT_ROOT, "qc", "roi_detections")

#: The ROIs whose frames broke the threshold backend's background assumption,
#: one row each, with the numbers behind the flag - see
#: ls_segment.background_check. Not a count and not an input to one: it is the
#: trace that says a zero in roi_nuclei.csv means "the estimate failed here"
#: rather than "nothing was stained here".
#:
#: WRITTEN ONLY WHEN SOMETHING FAILED. An empty file would read as "checked,
#: nothing found", and it would sit beside every StarDist run - which checks
#: nothing at all, because StarDist estimates no background. That is the same
#: distinction `paired` writes no roi_colocalisation.csv for. It is appended to
#: across resumes and dropped by --force with the measurements it describes, so
#: it stays in step with roi_nuclei.csv rather than accumulating rows about
#: objects that have since been re-segmented.
BACKGROUND_CSV = os.path.join(OUT_ROOT, "qc", "roi_background_assumption.csv")
BACKGROUND_COLUMNS = ["scene_uid", "roi_index", "marker", "segmented_on",
                      "backend", "n_objects", "cut", "above_cut",
                      "below_background"]

BASE_PX_UM = CONFIG["pixel_size_um"]
DAPI_C = CONFIG["channels"]["dapi_index"]
MARK_C = CONFIG["channels"]["marker_index"]
NUC_UM = CONFIG["detection"]["nucleus_diameter_um"]

# ---- how each marker's objects are found -----------------------------------
#
# A study says this in its channel table: `segment: nuclear` measures the
# marker inside the nuclear mask - the route this stage has always taken - and
# `segment: own` segments the marker's own channel with a declared backend.
#
# THE LIVE STUDY HAS NO CHANNEL TABLE. It is `paired`, so it declares none by
# definition: each of its scans carries the counterstain plus one marker. Every
# helper below therefore has to answer from a fallback as well as from a
# channel, and the fallback is exactly what this stage did before any of this
# existed. `_BY_NAME` being empty is the normal case, not a fault.
_ACQ = CONFIG.get("acquisition") or {}
_CHANNELS = CH.parse(_ACQ.get("channels"))
_NUCLEAR = CH.nuclear(_CHANNELS)
_BY_NAME = {c.name: c for c in _CHANNELS}

#: The declared nuclear channel's name, or None when there is no channel table.
NUCLEAR_NAME = _NUCLEAR.name if _NUCLEAR else None

#: What the `segmented_on` column records when the counterstain is real but
#: undeclared. A paired study's nuclear plane has no name to record - writing
#: an empty cell would leave a reader unable to tell "segmented on the
#: counterstain" from "this column was not filled in".
NUCLEAR_FALLBACK = "nuclear"

#: Which plane the counterstain is on. The channel table when there is one,
#: and the legacy `channels.dapi_index` when there is not.
NUCLEAR_C = int(_NUCLEAR.index) if (
    _NUCLEAR is not None and _NUCLEAR.index is not None) else DAPI_C

_THRESH = (CONFIG.get("detection") or {}).get("threshold") or {}
MAD_K = float(_THRESH.get("mad_k", 3.0))
MIN_AREA_UM2 = float(_THRESH.get("min_area_um2", 5.0))


def _segments_own(marker):
    """Whether this marker's objects come from its own channel.

    A marker that is in no channel table is NOT `own`. That is the live
    study's case, and its markers are measured inside nuclei.
    """
    c = _BY_NAME.get(marker)
    return c is not None and c.segment == CH.SEGMENT_OWN


def segment_plane_for(marker):
    """Which channel's pixels this marker's objects come from.

    `segment: nuclear` measures a marker inside the nuclear mask, so the
    objects are the nuclear channel's. `segment: own` segments the marker's own
    channel. A study with no nuclear channel has every marker on `own`, which
    ls_channels.parse already defaults for it.
    """
    if _segments_own(marker):
        return marker
    return NUCLEAR_NAME or NUCLEAR_FALLBACK


def backend_for(marker):
    """Which backend produces this marker's objects.

    A nuclear-segmented marker inherits the nuclear channel's segmentation,
    which is StarDist - that is the route this pipeline has always taken and
    the one the LS numbers came from.
    """
    if not _segments_own(marker):
        return "stardist"
    return _BY_NAME[marker].backend or "stardist"


def nucleus_shaped_for(marker):
    """Whether this marker's objects are nucleus-shaped.

    Nuclear-segmented objects ARE nuclei, whatever the marker declares about
    itself - the shape belongs to the mask, not to the antibody. 06a's
    Abercrombie gate is the consumer: N = n * T/(T+h) assumes spherical,
    randomly positioned objects.
    """
    if not _segments_own(marker):
        return True
    return bool(_BY_NAME[marker].nucleus_shaped)


def plane_index_for(marker):
    """Which plane of the file this marker's pixels are on.

    `channels.marker_index` is ONE index for the whole study, which is right
    for `paired` - each scan carries the counterstain plus one marker - and
    wrong for `multiplex`, where every marker is a different plane of the same
    scan and reading them all off one index would measure the same pixels
    under several names.

    The declared index, not a resolution by `czi_name`: resolving by name needs
    the channel names the FILE reports, and this stage does not read a file's
    metadata. That is the fallback ls_channels.resolve() would have used
    anyway, and a multiplex study whose planes move between files needs
    czi_meta wired in here before this stage can be trusted with it.
    """
    c = _BY_NAME.get(marker)
    if c is not None and c.index is not None:
        return int(c.index)
    return MARK_C


# ---- co-localisation -------------------------------------------------------
#
# A is co-localised with B when A's centroid falls inside B's mask. That needs
# B's MASK, not just its centroid, so it cannot be done from roi_nuclei.csv
# afterwards, and persisting every object mask would cost far more disk than
# this pipeline uses. It is computed here, where the label images exist.
#
# THIS STAGE MEASURES ONE MARKER PER RUN (--marker), so "both markers' labels
# are already in memory" is not true: the partner's plane is read and segmented
# in the same pass, in the run of whichever marker is declared FIRST, so a pair
# is computed once rather than twice and mirrored.
#
# Under `paired` it is not computed at all and the file is not written. Those
# markers are separate physical scans of DIFFERENT sections, so their objects
# are not in one coordinate frame; an empty roi_colocalisation.csv would read
# as "nothing overlaps", which is a different claim from "the question does not
# apply".
LAYOUT = G5.LAYOUT
COLOC_CSV = os.path.join(RESULTS, "roi_colocalisation.csv")
COLOC_COLUMNS = ["scene_uid", "roi_index", "marker_a", "object_a",
                 "marker_b", "object_b", "a_centroid_in_b", "b_centroid_in_a"]


def coloc_applies(marker_a, marker_b):
    """Whether relating these two markers' objects means anything.

    Markers that are both `segment: nuclear` share the SAME nuclear objects,
    so every object would contain itself and the table would be a diagonal.
    That is what the plane comparison catches.
    """
    if marker_a == marker_b:
        return False
    if LAYOUT != CH.LAYOUT_MULTIPLEX:
        return False
    return segment_plane_for(marker_a) != segment_plane_for(marker_b)


def coloc_partners(marker):
    """The markers this marker's run is responsible for relating it to.

    Declared order decides ownership: the pair (A, B) is computed in A's run
    and B's run does nothing with it. Both runs would otherwise write the same
    relation, once as (A, B) and once as (B, A) - the same fact twice, in a
    table where a reader counting rows would double it.
    """
    order = list(G5.MARKERS)
    if marker not in order:
        return []
    return [m for m in order[order.index(marker) + 1:]
            if coloc_applies(marker, m)]


def objects_inside(labels, inside, Minv, x0, y0):
    """The label ids whose centroid maps back inside the ROI shape.

    The same membership rule the measurement loop applies to its own marker,
    for the PARTNER's objects: a co-localisation row must point at two rows
    that exist in roi_nuclei.csv, and an object outside the ROI is not one.
    """
    from skimage.measure import regionprops

    ids = set()
    for p in regionprops(labels):
        cy, cx = p.centroid
        gx, gy = G5.apply_affine(Minv, x0 + cx, y0 + cy)
        if inside(gx, gy):
            ids.add(int(p.label))
    return ids


def only(labels, ids):
    """`labels` with everything outside `ids` set to background."""
    if not ids:
        return np.zeros_like(labels)
    return np.where(np.isin(labels, list(ids)), labels, 0)


class _Rect:
    """czi_read takes a rectangle object; this file has loose coordinates."""

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

COLUMNS = ["scene_uid", "animal", "marker", "roi_kind", "region", "seed_n",
           "roi_index", "nucleus_id",
           "czi_x", "czi_y", "sec_x", "sec_y",
           "area_um2", "equiv_diam_um",
           "dapi_mean", "marker_mean", "marker_median", "marker_p90",
           "censored", "artifact", "off_tissue",
           # How this object was produced. Recorded per row rather than left to
           # be re-derived from config, because a dataset outlives the config
           # that made it and 06a's Abercrombie gate depends on the answer.
           "segmented_on", "backend", "nucleus_shaped"]

#: What the three provenance columns mean when a file predates them, and the
#: EXACT strings they get filled in with - the same ones the emit loop writes
#: today for a nuclear-segmented marker, so an upgraded file is
#: indistinguishable from one written fresh.
#:
#: This is not a guess about old rows. Before the provenance columns existed
#: this stage had exactly one route: segment the counterstain with StarDist and
#: measure the marker inside the nuclear mask. Every object in such a file came
#: that way, so absence means nuclear - which is also how 06a's Abercrombie
#: gate reads a missing column, for the same reason.
#:
#: `segmented_on` is the counterstain's name AS THIS STUDY DECLARES IT, not the
#: literal "nuclear", so a backfilled row and a freshly appended one in the
#: same file say the same thing rather than two spellings of it. For the live
#: study that string IS "nuclear": it is paired, so it declares no channel
#: table and its counterstain has no declared name - which is what
#: NUCLEAR_FALLBACK exists for.
LEGACY_PROVENANCE = {"segmented_on": NUCLEAR_NAME or NUCLEAR_FALLBACK,
                     "backend": "stardist",
                     "nucleus_shaped": "1"}

#: The header of a roi_nuclei.csv written before the provenance columns: the
#: current columns with those three removed, in the order they were in.
LEGACY_COLUMNS = [c for c in COLUMNS if c not in LEGACY_PROVENANCE]


def min_area_px_for(min_area_um2=None, px_um=None):
    """The threshold backend's minimum object area, in pixels.

    At 0.65 um/px the default 5 um2 is 12 px. The arguments exist so the rule
    can be exercised at a value no config declares; both default to the
    study's.

    NEVER BELOW 1. `min_area_um2: 0` in a study config would otherwise ask for
    a minimum of zero, and the minimum is the only thing between "a stained
    region" and "a pixel that was noisy": at k=3 over a megapixel frame,
    hundreds of single pixels clear the cut by chance.

    The floor is a floor and not a filter, and it is worth being exact about
    which: an object of exactly one pixel has area 1, `1 < 1` is False, and it
    survives a minimum of 1 as it survives a minimum of 0. What the clamp
    guarantees is that the comparison keeps meaning something - a zero or
    negative minimum drops nothing at all and cannot be told apart from a
    minimum nobody configured.
    """
    um2 = MIN_AREA_UM2 if min_area_um2 is None else float(min_area_um2)
    px = BASE_PX_UM if px_um is None else float(px_um)
    return max(1, int(round(um2 / (px ** 2))))


def bg_row(uid, roi_index, marker, seg_on, backend, labels, report):
    """One row of BACKGROUND_CSV: which ROI, and the numbers behind the flag.

    `n_objects` is on it because the failure has two faces: the collapse to
    zero, and the biased count before it. A row saying 0 is the silent zero
    this file exists for; a row saying 40 is a count that was measured against
    a cut derived from the objects themselves.
    """
    return [uid, roi_index, marker, seg_on, backend, int(labels.max()),
            round(float(report.get("cut", 0.0)), 2),
            round(float(report.get("above_cut", 0.0)), 4),
            round(float(report.get("below_background", 0.0)), 4)]


def point_in_poly(px, py, v):
    """Is (px, py) inside the ring `v`, an (N, 2) array of canonical-grid points?

    Even-odd ray cast, in plain Python. It is called once per detected nucleus
    over a ring of a dozen or so vertices, which is nothing beside the
    segmentation that produced the nucleus, and keeping it here means the
    membership rule is one readable function rather than a matplotlib Path whose
    boundary convention would have to be looked up to be trusted.

    A nucleus exactly on the boundary is not worth a rule of its own: the ROI is
    drawn at 25 um per pixel and a nucleus is 7 um, so the boundary is thicker
    than the question.
    """
    inside = False
    n = len(v)
    j = n - 1
    for i in range(n):
        xi, yi = v[i][0], v[i][1]
        xj, yj = v[j][0], v[j][1]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def backfill_header(path, columns, legacy):
    """Rewrite `path` under `columns`, filling in the ones it does not have.

    EVERY row, not just the new ones. The alternative - accept the old header
    and let new rows carry the extra fields - produces a file whose rows are
    two different widths, and csv.DictReader hands the absent fields back as
    None rather than raising. None is falsy, so 06a would read
    `nucleus_shaped=None` on the 961,233 rows that are perfectly nuclear and
    withhold the Abercrombie correction from every one of them. That is the
    failure this rewrite exists to make impossible: after it, the file is one
    width and every row says what it is.

    Through a temp file and one atomic replace, for the reason `drop_rows`
    gives: this runs against a drive that has dropped writes, and a
    half-rewritten roi_nuclei.csv is the whole dataset. Columns are matched by
    NAME here rather than by position, because the point is to move rows from
    one header to another.

    Returns the number of rows rewritten.
    """
    tmp = path + ".tmp"
    n = 0
    with open(path, newline="", encoding="utf-8") as rf, \
            open(tmp, "w", newline="", encoding="utf-8") as tf:
        rd, tw = csv.reader(rf), csv.writer(tf)
        old = next(rd, None) or []
        at = {c: i for i, c in enumerate(old)}
        tw.writerow(list(columns))
        for row in rd:
            if not row:
                continue
            tw.writerow([row[at[c]] if c in at else legacy[c] for c in columns])
            n += 1
    os.replace(tmp, path)
    return n


def header_of(path):
    """The first row of `path`, or [] when it has none."""
    with open(path, newline="", encoding="utf-8") as rf:
        return next(csv.reader(rf), None) or []


def check_header(path, columns, legacy=None):
    """Refuse to append to a roi_nuclei.csv whose header is not `columns`.

    This stage appends positionally, and the file is shared across runs and
    both markers. COLUMNS gained `off_tissue` on 2026-09-02; a resume against a
    file written before that appended 21-field rows under a 20-field header,
    and nothing failed: csv.DictReader maps the extra field to key None, so in
    06a every NEW nucleus read `off_tissue` as None - the same as absent - and
    06g_flag_off_tissue.py cannot backfill a file that is half old and half
    new. Order is checked too, not just the set: a permuted header would take
    every appended row scrambled.

    `legacy` names the columns a file may be missing and what their absence
    means, and turns that one case from a refusal into a rewrite: the file is
    backfilled to `columns` in place, atomically, and the resume goes ahead.
    COLUMNS gained the three provenance columns on 2026-09-08, and refusing
    them cost more than the check was worth - the operator's live file holds
    961,233 rows and re-running the stage means re-segmenting all of them with
    StarDist. Nothing else is guessed at: the header must be exactly `columns`
    minus the legacy ones, in the same order.

    Callers that do NOT pass `legacy` are unchanged, and that is the safe
    default: a future append path that forgets it gets a refusal, never a file
    whose rows are two different widths.
    """
    header = header_of(path)
    if header == list(columns):
        return
    if legacy and header == [c for c in columns if c not in legacy]:
        # Said out loud, because it rewrites the operator's dataset - and
        # names what the filled-in values are, since "absence means nuclear"
        # is a claim about their data, not a formatting detail.
        print(f"  {os.path.basename(path)} predates "
              f"{', '.join(legacy)} - backfilling "
              f"{', '.join(f'{k}={v!r}' for k, v in legacy.items())}, which "
              f"is what every row in it already is: before those columns "
              f"existed this stage segmented the counterstain with StarDist "
              f"and had no other route.")
        n = backfill_header(path, columns, legacy)
        print(f"  {n} rows rewritten under the current header")
        return
    missing = [c for c in columns if c not in header]
    extra = [c for c in header if c not in columns]
    why = (f"missing {missing}" if missing else "") + \
          (f" extra {extra}" if extra else "") or "same columns, different order"
    raise SystemExit(
        f"!! {path} has a different header from the one this stage writes "
        f"({why}). Appending to it would give the new rows a different layout "
        f"from the old ones. If `off_tissue` is what is missing, run "
        f"06g_flag_off_tissue.py to backfill it first - which leaves the file "
        f"at the header 06h_backfill_provenance.py takes, so the two together "
        f"get an old file all the way to the current one. (06h is also the way "
        f"to add the provenance columns WITHOUT a detection run; this stage "
        f"backfills them itself when it resumes onto a file that predates "
        f"them.) Anything else - a permuted header, a column this stage does not "
        f"write - is not something to guess at: move the file aside and start "
        f"a new one.\n"
        f"   NOT --force: this check runs before the forced drop, so a "
        f"re-run cannot get past it either. The advice to try that was here "
        f"before the provenance columns were and was never true.")


def drop_rows(path, marker, uids, marker_col="marker"):
    """Rewrite `path` without the rows of `marker` whose scene_uid is in `uids`.

    THE ONLY PATH IN THE PIPELINE THAT DELETES MEASURED DATA, so it is exact:
    other markers' rows and this marker's other sections are kept as they are.
    `--force --limit N` used to drop EVERY row of the marker and then
    re-measure N sections, silently discarding the rest; the caller now passes
    its todo list and nothing outside it is touched.

    `marker_col` is which column names the owner of a row: `marker` in
    roi_nuclei.csv, `marker_a` in roi_colocalisation.csv, whose rows belong to
    the run of the first-declared marker of the pair. The two files are forced
    together and must be dropped by the same rule, or a re-run would leave a
    section's old relations beside its new measurements.

    It may also be a SEQUENCE of columns, and a row goes if the marker is
    named in any of them. That is what roi_colocalisation.csv needs: a row
    names two markers, ownership decides only which run computed it, and a
    marker whose objects have just been re-segmented and renumbered is stale on
    that row whichever side of it the marker sits. Keyed on `marker_a` alone,
    a forced re-run of the SECOND-declared marker of a pair dropped nothing.

    Through a temp file and one atomic replace, because this stage runs against
    a drive that has dropped writes and a half-written roi_nuclei.csv is the
    whole dataset. Returns (dropped, kept).
    """
    uids = set(uids)
    cols = [marker_col] if isinstance(marker_col, str) else list(marker_col)
    tmp = path + ".tmp"
    dropped = kept = 0
    with open(path, newline="", encoding="utf-8") as rf, \
            open(tmp, "w", newline="", encoding="utf-8") as tf:
        rd, tw = csv.reader(rf), csv.writer(tf)
        header = next(rd, None)
        absent = [c for c in cols if not header or c not in header]
        if not header or absent or "scene_uid" not in header:
            tf.close()
            os.remove(tmp)
            raise SystemExit(f"!! {path} has no {'/'.join(cols)}/scene_uid "
                             f"column - cannot tell whose rows to drop")
        tw.writerow(header)
        mis = [header.index(c) for c in cols]
        ui = header.index("scene_uid")
        for row in rd:
            if row and row[ui] in uids and any(row[i] == marker for i in mis):
                dropped += 1
                continue
            tw.writerow(row)
            kept += 1
    os.replace(tmp, path)
    return dropped, kept


def load_model():
    """StarDist's pretrained fluorescence model.

    Downloaded on first use, so the first run needs network access.

    `from_pretrained` finishes by creating a SYMLINK next to the extracted
    weights, and Windows refuses that without Developer Mode or elevation -
    WinError 1314, "a required privilege is not held by the client". The
    download and extraction have already succeeded by then, so the fallback
    below opens the extracted folder directly and needs no privilege at all.
    Same weights, same thresholds; only the convenience link is missing.
    """
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    from stardist.models import StarDist2D
    print("loading StarDist 2D_versatile_fluo (downloads on first use)...")
    try:
        return StarDist2D.from_pretrained("2D_versatile_fluo")
    except OSError as exc:
        base = os.path.expanduser("~/.keras/models/StarDist2D/2D_versatile_fluo")
        extracted = os.path.join(base, "2D_versatile_fluo_extracted")
        if not os.path.exists(os.path.join(extracted, "weights_best.h5")):
            raise
        print(f"  ({exc.__class__.__name__}: {exc.strerror or exc}) "
              f"- loading the extracted weights directly")
        return StarDist2D(None, name="2D_versatile_fluo_extracted", basedir=base)


def balanced_order(uids, done=()):
    """Alternate treatment and control, one section at a time.

    This is the same idea as `04n_roi_worklist.py` - an order chosen so that ANY
    PREFIX is a usable dataset - carried one step further. That stage balances
    across animals; this balances across groups too, so a run stopped half way
    has both arms measured to about the same depth rather than five control
    animals finished and every exercise animal untouched.

    Within a group it round-robins the animals, and within an animal it walks
    the sections in order, so the depth stays even at every level at once.

    **THIS READS THE GROUP KEY, and config.blinding says no stage before 06b
    may.** The exemption is narrow and worth stating: the group decides only the
    ORDER sections are measured in. Nothing downstream of it - not the
    segmentation, not the per-section threshold, not a single number in the
    output - depends on when a section was processed, and the finished dataset
    is identical whichever order was used. It is `--order uid` away from being
    blind again, and the run prints which order it used.
    """
    groups = CONFIG.get("groups") or {}
    by_animal = groups.get("by_animal") or {}
    if not by_animal:
        print("  no group key in config - falling back to plain uid order")
        return uids

    # animal -> its sections, in order
    per = {}
    for u in uids:
        per.setdefault(NM.subject_of(u), []).append(u)
    for v in per.values():
        v.sort()

    order = [g for g in (groups.get("order") or []) if g] or sorted(
        {by_animal.get(a, "") for a in per} - {""})
    arms = {g: [a for a in sorted(per, key=NM.natural_key)
                if by_animal.get(a) == g] for g in order}
    unknown = [a for a in per if by_animal.get(a) not in order]
    if unknown:
        print(f"  animals with no group: {unknown} - appended at the end")

    have = {g: sum(len(per[a]) for a in arms[g]) for g in order}

    # Count what a previous run already measured, so a RESUME corrects an
    # imbalance rather than preserving it. Strict alternation would only keep
    # the remainder even; taking from whichever arm is furthest behind keeps the
    # CUMULATIVE totals even, which is the property that actually matters when
    # the operator stops half way and looks at the numbers.
    cum = dict.fromkeys(order, 0)
    for u in (done or ()):
        g = by_animal.get(NM.subject_of(u))
        if g in cum:
            cum[g] += 1
    if any(cum.values()):
        print(f"  already measured: " + ", ".join(f"{g} {cum[g]}" for g in order))

    out = []
    cursor = {g: 0 for g in order}
    while any(per[a] for g in order for a in arms[g]):
        live_arms = [g for g in order if any(per[a] for a in arms[g])]
        g = min(live_arms, key=lambda x: (cum[x], order.index(x)))
        live = [a for a in arms[g] if per[a]]
        a = live[cursor[g] % len(live)]        # round-robin the animals within it
        cursor[g] += 1
        out.append(per[a].pop(0))
        cum[g] += 1
    for a in unknown:
        out.extend(per[a])
    print("  order: balanced - "
          + ", ".join(f"{g} {have[g]} to do ({len(arms[g])} animals)"
                      for g in order))
    return out


def mask_at(uid, kind):
    """The 256-frame artifact or censor mask, or None."""
    p = os.path.join(REFORMAT_DIR, "sections_AF568", f"{uid}_{kind}.npy")
    if not os.path.exists(p):
        p = os.path.join(REFORMAT_DIR, "sections", f"{uid}_{kind}.npy")
    return np.load(p) if os.path.exists(p) else None


def write_overlay(uid, bi, b, image, labels, kept):
    """One PNG per ROI: the SEGMENTED crop with the segmentation drawn on it.

    `image` is whichever plane produced `labels` - the counterstain under
    `segment: nuclear`, the marker's own channel under `segment: own`. Drawing
    boundaries over a plane they were not found on would make a correct
    segmentation look wrong and hide one that is.

    What this is for. The nucleus-diameter check in the docs says the
    segmentation is finding objects of about the right SIZE; it cannot say they
    are in the right PLACES, that touching nuclei were split rather than merged,
    or that a disc landed where the operator meant it to. Those are visual
    facts, and until now the only way to see one was to re-read the box in a
    notebook - so in practice nobody looked.

    Boundaries, not filled labels: a filled overlay hides the very thing being
    judged, which is whether the outline follows the nucleus.

    GREEN is a nucleus that was COUNTED. RED is one StarDist found inside the
    bounding box but outside the ROI itself, so it was dropped. Drawing the
    rejects is the point - a box that is mostly red means the shape is small or
    misplaced relative to what was segmented, and that is invisible in any
    table. It is the direct check on a drawn region too: a polygon traced off
    the anatomy shows as a crescent of red down one side.
    """
    from PIL import Image

    lo, hi = np.percentile(image, (1, 99.8))
    g = np.clip((image - lo) / max(hi - lo, 1e-6), 0, 1)
    rgb = np.repeat((g * 255).astype(np.uint8)[:, :, None], 3, axis=2)

    # A boundary pixel is one whose label differs from a neighbour. Computed
    # with shifts rather than skimage.find_boundaries so this adds no import
    # that the frozen build would have to carry.
    lab = labels
    edge = np.zeros(lab.shape, bool)
    edge[:-1, :] |= lab[:-1, :] != lab[1:, :]
    edge[1:, :] |= lab[1:, :] != lab[:-1, :]
    edge[:, :-1] |= lab[:, :-1] != lab[:, 1:]
    edge[:, 1:] |= lab[:, 1:] != lab[:, :-1]
    edge &= lab > 0

    keep_mask = np.isin(lab, list(kept)) if kept else np.zeros(lab.shape, bool)
    rgb[edge & keep_mask] = (0, 255, 0)
    rgb[edge & ~keep_mask] = (255, 0, 0)

    os.makedirs(QC_DIR, exist_ok=True)
    name = f"{uid}_roi{bi:02d}_{b['roi_kind']}_{b['region'] or 'na'}.png"
    name = name.replace(" ", "_").replace("/", "_")
    Image.fromarray(rgb).save(os.path.join(QC_DIR, name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only the first N sections")
    ap.add_argument("--order", choices=("balanced", "uid"), default="balanced",
                    help="balanced alternates treatment and control, one section "
                         "at a time, so a partial run is still a comparison; "
                         "uid is plain scene_uid order")
    ap.add_argument("--qc", action="store_true",
                    help="write one overlay PNG per ROI to qc/roi_detections: "
                         "DAPI with nucleus boundaries, green counted, red "
                         "found but outside the disc")
    # argparse does NOT validate a string default against `choices`, so a
    # hardcoded default here is not caught by the derived choices beside it: on
    # a study without that fluorophore, omitting --marker would run the
    # nucleus-measuring stage under a marker the study does not have, silently.
    # The first declared marker is what the rest of the pipeline already treats
    # as the default side.
    _default = G5.MARKERS[0] if G5.MARKERS else None
    ap.add_argument("--marker", choices=G5.MARKERS, default=_default,
                    help=f"which marker's boxes to measure (default {_default}). "
                         "Appends to the same roi_nuclei.csv - the markers "
                         "have disjoint sections.")
    ap.add_argument("--force", action="store_true", help="redo finished sections")
    args = ap.parse_args()

    G5.use_marker(args.marker)
    if not os.path.exists(G5.BOX_CSV):
        print(f"no {G5.BOX_CSV} - run 05a_roi_geometry.py --marker {args.marker} first")
        return 1
    print(f"marker: {args.marker}  ({os.path.basename(G5.BOX_CSV)})")
    boxes = G5.load_csv(G5.BOX_CSV)
    geom = {g["scene_uid"]: g for g in G5.load_csv(G5.GEOM_CSV)}
    os.makedirs(RESULTS, exist_ok=True)
    if args.qc:
        os.makedirs(QC_DIR, exist_ok=True)

    # Resume by section, because a section is the unit that costs something:
    # one CZI open and a model call per ROI in it.
    by_sec = {}
    for b in boxes:
        by_sec.setdefault(b["scene_uid"], []).append(b)

    # Resume by section, scoped to THIS MARKER. roi_nuclei.csv holds both once
    # the PCNA pass has run, and while scene uids are disjoint - so a raw
    # `done` set would still skip the right sections - the balanced-order
    # counter below counts what each arm has already had, and the other
    # marker's sections would inflate both arms and misdirect the ordering.
    exists = os.path.exists(NUCLEI_CSV)
    if exists:
        # Before anything else: appending to a file with a different header
        # corrupts it quietly (see check_header), and the check is one line.
        # LEGACY_PROVENANCE is passed here and NOWHERE ELSE: this is the only
        # path that appends to roi_nuclei.csv, so it is the only one that can
        # backfill it, and every other caller keeps the plain refusal.
        check_header(NUCLEI_CSV, COLUMNS, legacy=LEGACY_PROVENANCE)

    # Which markers this run must relate its own objects to. Empty for every
    # study that exists: LS is paired, and co-localisation is a multiplex
    # question. Decided from the box file's marker column rather than from
    # --marker so the loop below and this decision cannot disagree.
    coloc_by_marker = {m: coloc_partners(m) for m in {b["marker"] for b in boxes}}
    coloc_wanted = any(coloc_by_marker.values())
    coloc_exists = coloc_wanted and os.path.exists(COLOC_CSV)
    # A FORCED RE-RUN HAS TO CLEAN UP RELATIONS IT DOES NOT OWN. `coloc_wanted`
    # is false in the run of the SECOND-declared marker of a pair - ownership
    # belongs to the first, so this run neither computes the pair nor writes
    # it - but it does re-segment this marker's objects and renumber them, and
    # every row of roi_colocalisation.csv naming this marker still points at
    # the ids of the run before. So the drop below is decided by whether the
    # FILE exists, not by whether this run would append to it.
    coloc_present = os.path.exists(COLOC_CSV)
    if coloc_exists or (coloc_present and args.force):
        check_header(COLOC_CSV, COLOC_COLUMNS)
    done = set()
    if exists and not args.force:
        # Streamed with csv.reader, not load_csv: this needs one column and
        # load_csv would build a dict per row - about five million of them once
        # PCNA is in the file, on the resume of the run this stage exists to
        # make resumable. 06c reads the same file the same way for the same
        # reason.
        with open(NUCLEI_CSV, newline="", encoding="utf-8") as rf:
            rd = csv.reader(rf)
            next(rd, None)
            for row in rd:
                if row and row[0] in by_sec:
                    done.add(row[0])
        print(f"resuming: {len(done)} {args.marker} sections already measured")
    todo = [u for u in sorted(by_sec) if u not in done]
    if args.order == "balanced":
        todo = balanced_order(todo, done)
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("nothing to do")
        return 0
    print(f"{len(todo)} sections, {sum(len(by_sec[u]) for u in todo)} ROIs")

    # The model is loaded only if something in this run needs it. A study whose
    # markers are all `segment: own` with the threshold backend has no use for
    # StarDist, and load_model() DOWNLOADS weights on first use - so making it
    # unconditional would put a network fetch in front of a run that never
    # calls it. Decided from the boxes rather than from --marker so a box file
    # naming a different marker cannot reach SG.segment with model=None.
    run_markers = {b["marker"] for u in todo for b in by_sec[u]}
    # A co-localisation partner is segmented in this run too, so its backend
    # decides whether the model is needed just as much as the run's own.
    run_markers |= {p for m in set(run_markers)
                    for p in coloc_by_marker.get(m, ())}
    model = (load_model()
             if any(backend_for(m) == "stardist" for m in run_markers)
             else None)
    from pylibCZIrw import czi as pyczi
    from skimage.measure import regionprops

    # --force MUST NOT TRUNCATE THE OTHER MARKER'S ROWS, NOR THE SECTIONS IT
    # IS NOT ABOUT TO REDO.
    #
    # roi_nuclei.csv is shared: the two markers have disjoint sections and
    # append to one file. Opening it "w" to redo one marker would discard the
    # other's entirely - `--marker AF488 --force` deleting ~895,000 pERK rows,
    # or a forced pERK re-run deleting the PCNA ones. Nothing would error; 06a
    # and 06c would just report the missing marker at 0 coverage. That is the
    # same hazard Phase 3.1 removed from 05a's box files, one stage later, and
    # here the cost is hours of irrecoverable detection.
    #
    # The same applied within the marker: `--force --limit 5` dropped every
    # section of the marker and re-measured five. So the drop is scoped to
    # `todo` - exactly the sections whose rows are about to be replaced - and
    # done after load_model(), so a model that fails to load leaves the file
    # as it was.
    if exists and args.force:
        dropped, kept = drop_rows(NUCLEI_CSV, args.marker, todo)
        print(f"  --force: dropped {dropped} {args.marker} rows over {len(todo)} "
              f"sections, kept {kept}")
    if coloc_present and args.force:
        # The relations of a section are derived from its measurements, so
        # they are dropped by the same rule and at the same moment. Leaving
        # them would pair the new objects of a re-measured section with the
        # old object ids of its partner.
        #
        # BOTH COLUMNS, because a row names two markers and this run has
        # renumbered this marker's objects whichever side it is on. The rows
        # that go as `marker_b` belong to another marker's run and are NOT
        # recomputed here: they come back when that marker is re-run, and
        # until then the pair is absent rather than wrong. Multiplex-only, so
        # no study today has a row for this to reach.
        dropped, kept = drop_rows(COLOC_CSV, args.marker, todo,
                                  marker_col=("marker_a", "marker_b"))
        print(f"  --force: dropped {dropped} co-localisation rows naming "
              f"{args.marker} on either side, kept {kept}")
    # The same rule again for the background-assumption record: it describes
    # the frames of the sections being redone, and those frames are about to be
    # segmented again. A file whose header is not this one is started afresh
    # rather than refused - it is a QC trace, and refusing to detect 130
    # sections over the state of one is the wrong trade. roi_nuclei.csv, which
    # is the dataset, keeps its refusal.
    bg_exists = (os.path.exists(BACKGROUND_CSV)
                 and header_of(BACKGROUND_CSV) == BACKGROUND_COLUMNS)
    if bg_exists and args.force:
        dropped, _ = drop_rows(BACKGROUND_CSV, args.marker, todo)
        if dropped:
            print(f"  --force: dropped {dropped} background-assumption rows")

    fh = open(NUCLEI_CSV, "a" if exists else "w", newline="", encoding="utf-8")
    w = csv.writer(fh)
    if not exists:
        w.writerow(COLUMNS)

    # Opened on the first ROI that fails the check and not before - see
    # BACKGROUND_CSV for why an empty one would be a claim rather than a file.
    bfh = bgw = None

    # Opened only when something in this run has a partner, so a study that
    # cannot co-localise has no such file to explain. An EMPTY one would read
    # as "nothing overlaps", which is a different claim from "the question
    # does not apply to this layout".
    cfh = cw = None
    if coloc_wanted:
        cfh = open(COLOC_CSV, "a" if coloc_exists else "w", newline="",
                   encoding="utf-8")
        cw = csv.writer(cfh)
        if not coloc_exists:
            cw.writerow(COLOC_COLUMNS)

    px_area = BASE_PX_UM ** 2
    min_area_px = min_area_px_for()
    total_nuc = 0
    total_rel = 0
    total_bg = 0
    no_tissue_mask = []
    for n, uid in enumerate(todo, 1):
        g = geom[uid]
        M = np.array([[float(g["m00"]), float(g["m01"]), float(g["m02"])],
                      [float(g["m10"]), float(g["m11"]), float(g["m12"])]])
        Minv = G5.invert_affine(M)              # CZI px -> 256 grid
        art = mask_at(uid, "artifact")
        cen = mask_at(uid, "censor")
        # The DAPI tissue silhouette 04a_reformat.py carried into this same 256
        # frame - the tissue definition every other stage and the curator use.
        # Without it there is no way to tell a nucleus on the section from one
        # on the glass, so a section with no mask is skipped rather than
        # measured: silently calling every nucleus on-tissue is the failure this
        # check exists to stop.
        tis = mask_at(uid, "mask")
        if tis is None:
            no_tissue_mask.append(uid)
            continue
        path = os.path.join(CONFIG["source_dir"], g["czi_file"])
        rows = []
        coloc_rows = []
        bg_rows = []
        with pyczi.open_czi(path) as doc:
            for bi, b in enumerate(by_sec[uid], 1):
                x0, y0 = int(b["czi_x0"]), int(b["czi_y0"])
                bw, bh = int(b["czi_w"]), int(b["czi_h"])
                if bw < 8 or bh < 8:
                    continue
                marker = b["marker"]
                partners = coloc_by_marker.get(marker, ())
                # One read call, so every plane of this ROI comes off the same
                # scene rectangle. A partner's plane is only in here when this
                # run owns that pair; for every study that exists it is not.
                want = {"dapi": NUCLEAR_C, "mark": plane_index_for(marker)}
                for other in partners:
                    want["coloc_" + other] = plane_index_for(other)
                planes = CR.read_planes(
                    doc, _Rect(x0, y0, bw, bh), want,
                    scene=int(g["scene_index"]))
                dapi = planes["dapi"].astype(np.float32)
                mark = planes["mark"].astype(np.float32)
                if dapi.ndim != 2 or dapi.shape != mark.shape:
                    continue
                # WHICH PLANE IS SEGMENTED is the study's declaration, and
                # under `segment: own` it is the marker's OWN channel - which
                # is the plane already read as `mark`, because the channel a
                # marker is measured on and the channel it segments itself on
                # are the same channel by definition. No second read: this is
                # the one place a "segment on X, measure Y" study would need
                # one, and no such study exists.
                #
                # The tiling that makes StarDist tractable moved to
                # ls_segment.stardist_labels with the finding that justifies
                # it; it is not a tuning knob and does not belong at a call
                # site.
                seg_img = mark if _segments_own(marker) else dapi
                seg_on = segment_plane_for(marker)
                seg_backend = backend_for(marker)
                seg_shaped = int(nucleus_shaped_for(marker))
                report = {}
                labels = SG.segment(seg_img, seg_backend, model=model,
                                    k=MAD_K, min_area_px=min_area_px,
                                    report=report)
                # BEFORE the `continue`, which is the whole point of it being
                # here: the frames this fires on are usually the ones that
                # report no objects, an ROI with no objects writes no rows, and
                # so a background estimate that failed reached 06a as n = 0 and
                # a density of 0.0 with nothing anywhere to say so. `report` is
                # empty under StarDist, which estimates no background.
                if report.get("failed"):
                    bg_rows.append(bg_row(uid, bi, marker, seg_on, seg_backend,
                                          labels, report))
                if labels.max() == 0:
                    continue

                # Which nuclei are actually IN the ROI. The shape is drawn on
                # the 256 grid and is something else here - a circle becomes an
                # ellipse, a polygon a differently-proportioned polygon - so
                # membership is decided by mapping the centroid BACK to the grid
                # and testing it there, never against a radius in CZI px.
                #
                # That is why a drawn region needs no new machinery: the test
                # changes from "inside this circle" to "inside this ring", and
                # everything either side of it stays as it was.
                sx, sy = float(b["sec_x"]), float(b["sec_y"])
                sr = float(b["sec_r"] or 0)
                poly = G5.parse_poly(b.get("sec_poly", ""))
                inside = ((lambda gx, gy: point_in_poly(gx, gy, poly))
                          if poly is not None else
                          (lambda gx, gy: (gx - sx) ** 2 + (gy - sy) ** 2 <= sr * sr))
                props = regionprops(labels, intensity_image=mark)
                dprops = {p.label: p for p in regionprops(labels, intensity_image=dapi)}
                kept = set()
                for p in props:
                    cy, cx = p.centroid
                    gx, gy = G5.apply_affine(Minv, x0 + cx, y0 + cy)
                    if not inside(gx, gy):
                        continue
                    kept.add(p.label)
                    vals = p.image_intensity[p.image]
                    ix, iy = int(round(gx)), int(round(gy))
                    inb = lambda m: (m is not None and 0 <= iy < m.shape[0]
                                     and 0 <= ix < m.shape[1] and bool(m[iy, ix]))
                    # Outside the silhouette, or off the frame entirely, means
                    # the nucleus is not on the section - glass, mounting
                    # medium, or a neighbouring scene. `inb` is False for an
                    # out-of-bounds index, so both cases land here. Recorded
                    # rather than dropped, the way `artifact` is: 06a decides,
                    # and the QC overlay can still show what was found.
                    off_tis = int(not inb(tis))
                    rows.append([
                        uid, b["animal"], b["marker"], b["roi_kind"], b["region"],
                        b["seed_n"], bi, p.label,
                        round(x0 + cx, 1), round(y0 + cy, 1),
                        round(float(gx), 2), round(float(gy), 2),
                        round(p.area * px_area, 2),
                        round(2 * np.sqrt(p.area * px_area / np.pi), 2),
                        round(float(dprops[p.label].image_intensity[
                            dprops[p.label].image].mean()), 1),
                        round(float(vals.mean()), 1),
                        round(float(np.median(vals)), 1),
                        round(float(np.percentile(vals, 90)), 1),
                        int(inb(cen)), int(inb(art)), off_tis,
                        seg_on, seg_backend, seg_shaped])

                # CO-LOCALISATION, while both label images exist for this ROI.
                #
                # Both sides are cut down to the objects that are IN the ROI
                # first, because a row of this table points at two rows of
                # roi_nuclei.csv and an object outside the shape has none.
                #
                # THE ROI IS ASSUMED TO BE THE SAME ROI for both markers. Under
                # multiplex the two markers are one scan of one section, so the
                # box at index `bi` is the same region for both - but each
                # marker has its OWN roi_boxes file, exported separately, and
                # nothing here checks that the two exports agree. A multiplex
                # study whose markers were curated to different boxes would
                # join `object_b` to the partner's own run under a roi_index
                # that means something else there. That is the first thing to
                # check when a real multiplex study arrives.
                for other in partners:
                    o_img = planes["coloc_" + other].astype(np.float32)
                    if o_img.shape != labels.shape:
                        continue
                    o_backend = backend_for(other)
                    o_report = {}
                    o_labels = SG.segment(o_img, o_backend, model=model,
                                          k=MAD_K, min_area_px=min_area_px,
                                          report=o_report)
                    # The partner's plane is segmented in this run, so its
                    # frames are this run's to report on too.
                    if o_report.get("failed"):
                        bg_rows.append(bg_row(uid, bi, other,
                                              segment_plane_for(other),
                                              o_backend, o_labels, o_report))
                    if o_labels.max() == 0:
                        continue
                    o_kept = objects_inside(o_labels, inside, Minv, x0, y0)
                    for rel in CO.pairs(only(labels, kept),
                                        only(o_labels, o_kept)):
                        coloc_rows.append([
                            uid, bi, marker, rel["object_a"],
                            other, rel["object_b"],
                            int(rel["a_centroid_in_b"]),
                            int(rel["b_centroid_in_a"])])

                if args.qc:
                    write_overlay(uid, bi, b, seg_img, labels, kept)
        w.writerows(rows)
        fh.flush()
        if bg_rows:
            if bfh is None:
                os.makedirs(os.path.dirname(BACKGROUND_CSV), exist_ok=True)
                bfh = open(BACKGROUND_CSV, "a" if bg_exists else "w",
                           newline="", encoding="utf-8")
                bgw = csv.writer(bfh)
                if not bg_exists:
                    bgw.writerow(BACKGROUND_COLUMNS)
            bgw.writerows(bg_rows)
            bfh.flush()
            total_bg += len(bg_rows)
        if cw is not None:
            # Flushed with the measurements, section by section, so a run that
            # stops half way leaves the two files describing the same sections.
            cw.writerows(coloc_rows)
            cfh.flush()
            total_rel += len(coloc_rows)
        total_nuc += len(rows)
        print(f"\r  {n}/{len(todo)}  {uid}  {len(rows)} nuclei  "
              f"({total_nuc} total)          ", end="")
    fh.close()
    if cfh is not None:
        cfh.close()
    if bfh is not None:
        bfh.close()
    print(f"\n{total_nuc} nuclei -> {NUCLEI_CSV}")
    if coloc_wanted:
        print(f"{total_rel} co-localisation pairs -> {COLOC_CSV}")
    if total_bg:
        # Said once, at the end, rather than per ROI: this is a loop over
        # thousands of them and a line each would be a line nobody reads.
        print(f"!! {total_bg} ROI frames FAILED THE BACKGROUND CHECK - over "
              f"{SG.BACKGROUND_FAILED:.0%} of the frame lay below the median "
              f"the cut was derived from, so the median was inside an object "
              f"rather than in the background. Those ROIs' counts are biased, "
              f"and a zero among them means the estimate failed, NOT that "
              f"nothing was stained.")
        print(f"   one row each, with the numbers -> {BACKGROUND_CSV}")
    if no_tissue_mask:
        print(f"!! {len(no_tissue_mask)} sections SKIPPED for want of a tissue "
              f"mask in reformatted/: {no_tissue_mask[:5]}")
        print("   Run 04a_reformat.py for them before trusting any count.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
