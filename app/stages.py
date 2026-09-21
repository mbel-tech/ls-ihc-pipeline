"""The pipeline, as data.

One entry per stage, in the order and the groups of the workflow figure in
docs/pipeline-methods.md (Figure 1). That figure is the authority for what the
pipeline IS; `run_all.sh` is the authority for how the batch part of it is
run; this file is a transcription of both, and `tests/test_stages.py` holds it
to them - every numbered script is either a stage or is named in NOT_LISTED
with a reason, and every box on the figure has a stage id.

Each stage says what it is, how to run it, what it leaves behind, and two
facts the figure encodes in colour and outline:

  reader    which library decoded pixels for it - `pylibCZIrw` for anything
            whose numbers reach a result, `czifile` for instrument
            characterisation only, `fiji` for the one-time tile export, or
            `none` when no pixel is decoded;
  operator  True where a person decides - the red outline on the figure.

`done()` is existence-only: every stage is resumable and re-checks its own
inputs properly when run, so this is a hint for the operator, not a gate.

Stages the app does NOT run are still listed, with `cli_only` and a reason.
Hiding them would turn "we chose not to wrap this" into "this does not exist".
"""

import importlib.util
import os
import sys

READERS = ("pylibCZIrw", "czifile", "fiji", "none")


class Stage:
    """One pipeline step.

    `outputs` are checked for existence to decide `done`, relative to
    out_root. `argv` is what follows the script name; `{out_root}`, `{repo}`
    and `{scripts}` are expanded by the runner. `cli_only` is a reason string,
    None, or a callable returning either - detection depends on what the
    running interpreter can import.
    """

    def __init__(self, sid, title, group, script=None, argv=(), outputs=(),
                 blurb="", cli_only=None, curator=None, needs=(),
                 operator=False, reader="none", unblinds=False):
        self.sid = sid
        self.title = title
        self.group = group
        self.script = script
        self.argv = list(argv)
        self.outputs = list(outputs)
        self.blurb = blurb
        self.cli_only = cli_only
        self.curator = curator            # html page, relative to out_root
        self.needs = list(needs)
        self.operator = operator
        self.reader = reader
        self.unblinds = unblinds

    def cli_reason(self):
        return self.cli_only() if callable(self.cli_only) else self.cli_only

    def done(self, out_root):
        """True when every declared output exists.

        Deliberately existence-only. Reading row counts would be a better
        completeness check but turns a status refresh into disk work across
        thousands of files, and the stages themselves already re-check properly
        when run.
        """
        if not self.outputs:
            return False
        return all(os.path.exists(os.path.join(out_root, p)) for p in self.outputs)

    def missing(self, out_root):
        return [p for p in self.outputs
                if not os.path.exists(os.path.join(out_root, p))]

    def __repr__(self):
        return f"<Stage {self.sid} {self.title!r}>"


# The figure's bands, in sidebar order. "Acquisition" is the Add slides screen.
GROUPS = ["Ingest and QC", "Instrument characterisation", "Atlas",
          "Normalisation and curation", "Quantification", "Beyond blinding"]

FIJI_REASON = ("needs Fiji, which the app does not drive. A one-time "
               "instrument characterisation; run scripts/run_all.sh steps "
               "3-8 when starting a new dataset.")


def detect_cli_reason(frozen=None, has_stardist=None):
    """Why 05c cannot run here, or None when it can.

    StarDist pulls in TensorFlow, which would roughly quadruple the frozen
    build for a stage that runs once per curation pass, so the .exe does not
    carry it. From source the venv the app runs in does, and there is no reason
    to send the operator to a terminal for it.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if has_stardist is None:
        has_stardist = importlib.util.find_spec("stardist") is not None
    if frozen:
        return ("needs StarDist and TensorFlow, which the packaged app does not "
                "carry - they would quadruple its size. Run from source: "
                "work/appenv/Scripts/python.exe scripts/05c_detect_rois.py")
    if not has_stardist:
        return ("StarDist is not installed in this interpreter. "
                "pip install stardist tensorflow csbdeep scikit-image, or run "
                "work/appenv/Scripts/python.exe scripts/05c_detect_rois.py")
    return None


# Numbered scripts that are deliberately not stages. A script missing from
# both this and STAGES fails tests/test_stages.py.
NOT_LISTED = {
    "01_overviews.groovy": "retired: the Python port (01_overviews.py) replaced it "
                           "in 2026-08; kept for the record only.",
    "01a_flatfield.groovy": "retired Fiji flat-field; superseded by 01f/01h.",
    "04b_atlas_match.py": "automatic level assignment, measured to fail on "
                          "this data (LOGS 2026-08-12); kept as evidence.",
    "04c_atlas_match.py": "second automatic level matcher, also measured to "
                          "fail; the ROI curator assigns plates by hand.",
    "04e_register_elastix.py": "elastix registration is QC only - nothing "
                               "downstream reads it (methods section 9).",
}

REF = "reformatted/"

STAGES = [
    # ---- Ingest and QC -----------------------------------------------------
    Stage("manifest", "00  Read slide headers", "Ingest and QC",
          script="00_manifest.py",
          outputs=["manifest/manifest_files.csv", "manifest/manifest_scenes.csv"],
          blurb="Parses every CZI header without decoding a pixel, reconstructs "
                "the slide layout and renders the slide maps under five "
                "mounting conventions."),

    Stage("verify", "00b  Verify extraction", "Ingest and QC",
          script="00b_verify_extraction.py",
          outputs=["qc/extraction_status.csv"],
          needs=["manifest"],
          blurb="Checks extracted CZIs against the zip central directories. "
                "--crc checks content rather than size alone."),

    Stage("czi_selftest", "00d  CZI self-test", "Ingest and QC",
          script="00d_czi_selftest.py", reader="pylibCZIrw",
          outputs=["qc/czi_selftest.csv"],
          needs=[],
          blurb="Checks the four assumptions every pixel stage makes about the "
                "CZIs: scene-rectangle overlap, stored pyramid levels, sensor "
                "bit depth, and whether the pyramid and layer-0 frames share an "
                "origin. Gates on drifted frames and bad bit-depth metadata; "
                "scene overlap and pyramid levels are reported, not gated - "
                "they are true of this dataset. See docs/czi-reading-audit.md."),

    Stage("overviews", "01  Export section overviews", "Ingest and QC",
          script="01_overviews.py", reader="pylibCZIrw",
          outputs=["overviews", "qc/focus.csv"],
          needs=["manifest"],
          blurb="Every section at exactly 5.2 um/px with a frozen display "
                "range, plus per-section QC including clipping measured on the "
                "raw plane. Applies the tile field if one exists."),

    Stage("contactsheets", "01d  Contact sheets and gallery", "Ingest and QC",
          script="01d_contactsheets.py",
          outputs=["contactsheets"],
          needs=["overviews"],
          blurb="Per-animal montages in rostro-caudal order, plus an HTML gallery."),

    Stage("pair", "02  Pair the two marker passes", "Ingest and QC",
          script="02_pair_passes.py",
          outputs=["pairs.csv"],
          needs=["overviews"],
          blurb="Matches AF568 and AF488 scans onto the same physical sections "
                "via stage coordinates. Yields the canonical section identity."),

    Stage("channel_identity", "00c  Infer marker identity", "Ingest and QC",
          script="00c_channel_identity.py",
          outputs=["qc/channel_identity"],
          needs=["overviews"],
          blurb="Infers which fluorophore carries which marker from spatial "
                "signature. Reports the call; does not commit it to config."),

    # ---- Instrument characterisation --------------------------------------
    Stage("tile_geometry", "01e  Tile geometry from the CZI directory",
          "Instrument characterisation",
          script="01e_tile_geometry.py",
          outputs=["qc/tile_geometry.csv"],
          needs=["manifest"],
          blurb="Reads exact tile origins and pitch from the subblock directory "
                "- no pixel decoded. The pitch the field is folded at."),

    Stage("pick_sections", "01b  Pick the tile-field sample",
          "Instrument characterisation",
          script="01b_pick_sections.py", argv=["--n", "96", "--scenes-per-file", "4"],
          outputs=["qc/tilefield_sample.csv"],
          needs=["manifest"],
          blurb="Chooses the sections the tile-field characterisation measures."),

    Stage("fiji_export", "01b  Export the sample at 2.6 um/px (Fiji)",
          "Instrument characterisation",
          script="01b_export_section.groovy", reader="fiji",
          cli_only=FIJI_REASON,
          outputs=["qc/test_sections"],
          needs=["pick_sections"],
          blurb="Exports the sample sections as TIFFs for the tile-field build."),

    Stage("tilefield_build", "01f  Build the tile-correction field",
          "Instrument characterisation",
          script="01f_tilefield.py", argv=["build"],
          outputs=["qc/flatfield/tilefield_c0.npy", "qc/flatfield/tilefield_c1.npy"],
          needs=["fiji_export", "tile_geometry"],
          blurb="Folds the stitched sample at the tile pitch and takes the "
                "per-pixel median: anatomy averages out, illumination remains. "
                "01_overviews applies it, and works without it."),

    Stage("tilefield_verify", "01f  Apply the field to the sample",
          "Instrument characterisation",
          script="01f_tilefield.py", argv=["verify"],
          outputs=["qc/test_sections_corrected"],
          needs=["tilefield_build"],
          blurb="Writes corrected copies of the sample so the artifact can be "
                "measured after correction."),

    Stage("artifact_before", "01c  Measure the tile artifact before correction",
          "Instrument characterisation",
          script="01c_measure_tile_artifact.py",
          outputs=["qc/tile_artifact"],
          needs=["fiji_export"],
          blurb="Peak-to-trough of the folded tile profile as a percentage of "
                "mean signal: how much more a detection near a tile centre sees."),

    Stage("artifact_after", "01c  Measure the tile artifact after correction",
          "Instrument characterisation",
          script="01c_measure_tile_artifact.py",
          argv=["{out_root}/qc/test_sections_corrected/*.tif"],
          outputs=["qc/tile_artifact"],
          needs=["tilefield_verify"],
          blurb="The same measurement on the corrected sample. Compare with "
                "the run before correction."),

    Stage("tilefield_raw", "01h  Illumination field from raw tiles",
          "Instrument characterisation",
          script="01h_tilefield_raw.py", reader="czifile",
          outputs=["qc/flatfield"],
          needs=["manifest"],
          blurb="Per-pixel median across thousands of raw, unstitched tiles, "
                "mapped to the stitched domain. Instrument only - no value "
                "here reaches a result. Not promoted over 01f automatically."),

    Stage("saturation_raw", "01k  Clipping on the raw plane",
          "Instrument characterisation",
          script="01k_saturation_raw.py", reader="pylibCZIrw",
          outputs=["qc/saturation_raw.csv", "qc/censor_raw"],
          needs=["overviews"],
          blurb="Measures pixels at the 16-bit ceiling BEFORE the tile field, "
                "and writes the raw clipping mask per section. 04j and 01g "
                "read those masks; the post-correction count was a 2x "
                "undercount."),

    Stage("saturation_map", "01g  Where the clipping falls",
          "Instrument characterisation",
          script="01g_saturation_map.py",
          outputs=["qc/saturation/saturation_AF568.csv"],
          needs=["saturation_raw"],
          blurb="Separates cosmetic clipping (edges, debris) from consequential "
                "clipping (parenchyma) per section: in-tissue fraction, edge "
                "affinity, blob size, tissue coverage."),

    # ---- Atlas --------------------------------------------------------------
    Stage("atlas_extract", "04a  Extract atlas plates and seeds", "Atlas",
          script="04a_atlas_extract.py",
          outputs=["atlas/plates/plates.csv", "atlas/plates/seeds.csv"],
          blurb="Pulls every plate image and region seed point out of the atlas "
                "PDF. Markers found by size, not colour. 101 raw plates."),

    Stage("atlas_remerge", "04a2  Merge image strips into whole figures", "Atlas",
          script="04a2_atlas_remerge.py", argv=["--dpi", "300"],
          outputs=["atlas/plates_merged/plates.csv"],
          needs=["atlas_extract"],
          blurb="The PDF stores one figure as several strips; this renders each "
                "figure whole and remaps the seeds exactly. 101 strips -> 47 "
                "figures."),

    Stage("atlas_reframe", "04a3  Reframe figures into plates", "Atlas",
          script="04a3_plate_reframe.py",
          outputs=["atlas/plate_reframe.html"],
          curator="atlas/plate_reframe.html", operator=True,
          needs=["atlas_remerge"],
          blurb="Draw one box per section on each figure. Boxes are proposed "
                "from the tissue bands; only multi-section figures need a look. "
                "Export writes atlas/plate_boxes.csv."),

    Stage("atlas_enforce", "04a3b  Enforce the declared section counts", "Atlas",
          script="04a3b_enforce_sections.py", argv=["--apply"],
          outputs=["atlas/plate_boxes.prev.csv"],
          needs=["atlas_reframe"],
          blurb="Where the band detector mis-counts (touching sections, internal "
                "white bands), config.atlas_figure_sections is the authority. "
                "Merges or splits the boxes to match it."),

    Stage("atlas_rebuild", "04a4  Render the final plate set", "Atlas",
          script="04a4_plate_rebuild.py", argv=["--dpi", "300"],
          outputs=["atlas/plates_final/plates.csv", "atlas/plates_final/seeds.csv"],
          needs=["atlas_enforce"],
          blurb="Re-renders each box from the PDF at full resolution and carries "
                "the seeds across. This is the set the ROI curator uses "
                "(config.atlas_plate_set)."),
    # ---- Normalisation and curation ----------------------------------------
    Stage("reformat_pcna", "04a  Reformat PCNA sections", "Normalisation and curation",
          script="04a_reformat.py",
          outputs=[REF + "reformat_index.csv"],
          needs=["overviews", "atlas_extract"],
          blurb="Debris removed, rotated onto the principal axis, centred, "
                "cropped, padded square, 256 px - all on DAPI. The frame every "
                "later coordinate lives in. First pass, before curation."),

    Stage("exclusion", "04f  Propose unmeasurable sections", "Normalisation and curation",
          script="04f_exclusion_candidates.py",
          outputs=[REF + "exclusion_candidates.csv"],
          needs=["reformat_pcna"],
          blurb="Conservative proposals only: no tissue worth the name, or no "
                "resolvable nuclear detail. Every call carries its numbers and "
                "is adjudicated in the rotation curator."),

    Stage("symmetry", "04h  Propose symmetry-axis rotations", "Normalisation and curation",
          script="04h_symmetry_axis.py",
          outputs=[REF + "symmetry_proposals.csv"],
          needs=["exclusion"],
          blurb="A residual rotation that puts each section's midline vertical, "
                "pre-applied in the rotation curator so the manual pass fixes "
                "failures instead of rotating everything."),

    Stage("rotation_curator", "04d  Rotation and exclusion curator",
          "Normalisation and curation",
          script="04d_rotation_curator.py",
          outputs=[REF + "rotation_curator.html"],
          curator=REF + "rotation_curator.html", operator=True,
          needs=["symmetry"],
          blurb="Adjudicate each PCNA section: drag it upright, accept or "
                "overrule the exclusion proposals. Export writes "
                "rotation_overrides.csv."),

    Stage("reformat_pcna_curated", "04a  Reformat PCNA with the curation applied",
          "Normalisation and curation",
          script="04a_reformat.py", argv=["--apply-overrides"],
          outputs=[REF + "excluded_sections.csv"],
          needs=["rotation_curator"],
          blurb="Re-reformats with the manual rotations folded in and the "
                "exclusions recorded as flags in excluded_sections.csv."),

    Stage("artifact_pcna", "04g  Mask artifacts - PCNA", "Normalisation and curation",
          script="04g_artifact_mask.py", argv=["--include-excluded"],
          outputs=["artifacts/artifact_summary.csv"],
          needs=["reformat_pcna_curated"],
          blurb="Bright objects strictly inside the tissue - bubbles, aggregates, "
                "fibres - masked rather than excluded. Detected on DAPI at "
                "overview resolution, so the mask is the same for both markers."),

    Stage("censor_pcna", "04j  Censor clipped pixels - PCNA", "Normalisation and curation",
          script="04j_censor_clipped.py", argv=["--marker", "AF488"],
          outputs=[REF + "pcna_analysis_set.csv"],
          needs=["saturation_raw", "reformat_pcna_curated"],
          blurb="Sections above the 1% clipped tolerance are set aside with a "
                "flag; surviving clipped pixels are right-censored, not masked. "
                "AF488 clips rarely but measurably."),

    Stage("reformat_pcna_final", "04a  Reformat PCNA - masked and censored",
          "Normalisation and curation",
          script="04a_reformat.py",
          argv=["--apply-overrides", "--mask-artifacts", "--censor"],
          outputs=[REF + "sections"],
          needs=["artifact_pcna", "censor_pcna"],
          blurb="The analysis frame for PCNA: curation applied, artifact pixels "
                "blanked, censor masks carried into the 256 px frame. Run again "
                "whenever a mask or the curation changes."),

    Stage("propagate_perk", "04i  Carry the curation onto the pERK scans",
          "Normalisation and curation",
          script="04i_propagate_to_perk.py",
          outputs=[REF + "perk_overrides.csv"],
          needs=["pair", "reformat_pcna_final"],
          blurb="Exclusions transfer directly through pairs.csv; rotations are "
                "re-derived by aligning the pERK silhouette onto the curated "
                "PCNA one, because the scan boxes differ."),

    Stage("reformat_perk", "04a  Reformat pERK sections", "Normalisation and curation",
          script="04a_reformat.py", argv=["--marker", "AF568", "--apply-overrides"],
          outputs=[REF + "reformat_index_AF568.csv"],
          needs=["propagate_perk"],
          blurb="The pERK pass into the same frame, with the propagated "
                "curation applied."),

    Stage("artifact_perk", "04g  Mask artifacts - pERK", "Normalisation and curation",
          script="04g_artifact_mask.py", argv=["--marker", "AF568", "--include-excluded"],
          outputs=["artifacts/artifact_summary_AF568.csv"],
          needs=["reformat_perk"],
          blurb="The same detector on the pERK scan's DAPI. The two scans image "
                "different fields, so artifacts are not propagated."),

    Stage("censor_perk", "04j  Censor clipped pixels - pERK", "Normalisation and curation",
          script="04j_censor_clipped.py",
          outputs=[REF + "perk_analysis_set.csv", "censor"],
          needs=["saturation_raw", "reformat_perk"],
          blurb="The 1000 ms AF568 exposure pins pixels at the ceiling on a "
                "third of sections. Writes perk_analysis_set.csv - the "
                "measurable set - and the per-section censor mask."),

    Stage("reformat_perk_final", "04a  Reformat pERK - masked and censored",
          "Normalisation and curation",
          script="04a_reformat.py",
          argv=["--marker", "AF568", "--apply-overrides", "--mask-artifacts", "--censor"],
          outputs=[REF + "sections_AF568"],
          needs=["artifact_perk", "censor_perk"],
          blurb="The analysis frame for pERK. 05c reads the censor and artifact "
                "masks this writes."),

    Stage("render_excluded_perk", "04a  Render excluded pERK sections for Review",
          "Normalisation and curation",
          script="04a_reformat.py",
          argv=["--marker", "AF568", "--apply-overrides", "--render-excluded"],
          outputs=[REF + "sections_AF568"],
          needs=["reformat_perk_final"],
          blurb="pERK exclusions were applied before reformatting, so the 473 "
                "had no picture. Renders them for the curator's Review mode "
                "without adding an index row."),

    Stage("sections_dataset", "04m  Every pERK section and its fate",
          "Normalisation and curation",
          script="04m_sections_dataset.py",
          outputs=[REF + "perk_sections_dataset.csv"],
          needs=["censor_perk"],
          blurb="One row per pERK section - analysis set, censored out, or "
                "excluded and why - joined to its PCNA partner. The exclusion "
                "rate per animal is a result to check at unblinding."),

    Stage("worklist", "04n  Order the ROI queue", "Normalisation and curation",
          script="04n_roi_worklist.py",
          outputs=[REF + "roi_worklist.csv"],
          needs=["censor_perk"],
          blurb="Orders curation so any prefix is a usable dataset: every animal "
                "advanced to the same fraction, spread across each brain."),

    Stage("rgb_perk", "04o  Colour composites - pERK", "Normalisation and curation",
          script="04o_section_rgb.py", argv=["--marker", "AF568", "--all"],
          outputs=[REF + "sections_AF568_rgb"],
          needs=["reformat_perk_final"],
          blurb="DAPI blue plus the marker, in the reformatted frame, so the "
                "curator shows the channel being quantified."),

    Stage("rgb_pcna", "04o  Colour composites - PCNA", "Normalisation and curation",
          script="04o_section_rgb.py", argv=["--marker", "AF488", "--all"],
          outputs=[REF + "sections_rgb"],
          needs=["reformat_pcna_final"],
          blurb="The same for the PCNA channel."),

    Stage("thumbs_perk", "04o  Review thumbnails - pERK", "Normalisation and curation",
          script="04o_section_rgb.py", argv=["--marker", "AF568", "--thumbs"],
          outputs=[REF + "sections_AF568_rgb_thumb"],
          needs=["rgb_perk"],
          blurb="256 px colour thumbnails for the curator's Review grid."),

    Stage("thumbs_pcna", "04o  Review thumbnails - PCNA", "Normalisation and curation",
          script="04o_section_rgb.py", argv=["--marker", "AF488", "--thumbs"],
          outputs=[REF + "sections_rgb_thumb"],
          needs=["rgb_pcna"],
          blurb="The same for PCNA."),

    Stage("provenance", "04p  Trace every scanned section", "Normalisation and curation",
          script="04p_section_provenance.py", argv=["--tissue-masks"],
          outputs=[REF + "section_provenance.csv", "tissue"],
          needs=["artifact_pcna", "artifact_perk"],
          blurb="One row per scanned section - all 2,572, including the excluded "
                "ones no other table carries - joining what 04f proposed, what "
                "the operator decided, what 04g masked and what 04j censored. "
                "Feeds the ROI curator's Review mode."),

    Stage("roi_curator", "04l  ROI curator", "Normalisation and curation",
          script="04l_roi_curator.py",
          argv=["--marker", "AF568", "--worklist", "--rgb"],
          outputs=[REF + "roi_curator.html"],
          curator=REF + "roi_curator.html", operator=True,
          needs=["worklist", "rgb_perk", "rgb_pcna", "atlas_rebuild"],
          blurb="Assign a plate, place numbered landmarks and background discs, "
                "draw each region as a polygon against its hull on the plate, "
                "export the three CSVs. Review mode shows every prior decision."),

    Stage("import_curation", "04q  Import the curator's exports",
          "Normalisation and curation",
          script="04q_import_curation.py",
          argv=["--plates", "{out_root}/reformatted/roi_plates.csv",
                "--landmarks", "{out_root}/reformatted/roi_landmarks.csv",
                "--regions", "{out_root}/reformatted/roi_regions.csv", "--write"],
          outputs=["curation/ls_roi_curator_v1.json"],
          needs=["roi_curator"],
          blurb="Turns roi_plates / roi_landmarks / roi_regions back into the "
                "curator's seed state, so work exported from a browser reaches "
                "the app. Backs up the previous seed first."),

    Stage("level_curator", "04k  Level curator (superseded)", "Normalisation and curation",
          script="04k_level_curator.py",
          outputs=[REF + "level_curator.html"],
          curator=REF + "level_curator.html", operator=True,
          needs=["reformat_pcna_final", "atlas_extract"],
          blurb="Anchor a few sections to plates and interpolate the rest. "
                "Superseded by the ROI curator's own plate slider; kept for "
                "the record. Reads config.atlas_plate_set like 04l."),

    # ---- Quantification (blind) --------------------------------------------
    Stage("roi_geometry_verify", "05a  Verify the inverse transform", "Quantification",
          script="05a_roi_geometry.py", argv=["--verify"],
          outputs=[],
          needs=["reformat_perk_final"],
          blurb="Pushes coordinate planes through the real reformat and compares "
                "with the affine: expect 0.04-0.15 px. A check, not a product."),

    Stage("roi_geometry", "05a  Place the ROIs on the slide", "Quantification",
          script="05a_roi_geometry.py",
          outputs=[REF + "roi_geometry_AF568.csv", REF + "roi_boxes_AF568.csv"],
          needs=["roi_curator"],
          blurb="One affine per section and one CZI-pixel box per curated disc. "
                "Reads the newest roi_regions.csv export. Per marker, so a PCNA "
                "run cannot overwrite the pERK boxes."),

    Stage("detect", "05c  Detect and measure nuclei", "Quantification",
          script="05c_detect_rois.py", reader="pylibCZIrw",
          outputs=["results/roi_nuclei.csv"],
          needs=["roi_geometry"],
          cli_only=detect_cli_reason,
          blurb="Reads each box at 0.65 um/px, segments nuclei on DAPI with "
                "StarDist, measures the marker under each nuclear mask. One row "
                "per nucleus; hours, resumable per section."),

    Stage("recensor", "06f  Recompute the censored flag", "Quantification",
          script="06f_recensor_nuclei.py",
          outputs=["results/_pre_06f_backup"],
          needs=["detect", "saturation_raw"],
          blurb="Re-samples each stored nucleus position against the raw "
                "clipping mask, without re-running StarDist. Backs up "
                "roi_nuclei.csv first."),

    Stage("off_tissue", "06g  Flag nuclei off the section", "Quantification",
          script="06g_flag_off_tissue.py",
          outputs=["results/_pre_06g_backup"],
          needs=["detect"],
          blurb="Backfills off_tissue onto a roi_nuclei.csv written before 05c "
                "recorded it: nuclei outside the DAPI silhouette, which drag a "
                "background disc's cut down."),

    Stage("seg_provenance", "06h  Backfill segmentation provenance", "Quantification",
          script="06h_backfill_provenance.py",
          outputs=["results/_pre_06h_backup"],
          needs=["detect"],
          blurb="Backfills segmented_on / backend / nucleus_shaped onto a "
                "roi_nuclei.csv written before 05c recorded them. Every row in "
                "such a file is nuclear / stardist / nucleus-shaped - there was "
                "no other route - and 06a's Abercrombie gate reads them."),

    Stage("roi_dataset", "06a  Per-ROI dataset", "Quantification",
          script="06a_roi_dataset.py",
          outputs=["results/roi_measurements.csv", "results/detector_specificity.csv"],
          needs=["detect"],
          blurb="Positivity cut from each section's own background discs "
                "(median + 3 x 1.4826 x MAD), the detector's false-positive "
                "rate, two densities, Abercrombie. Still keyed by animal only."),

    # ---- Beyond blinding ----------------------------------------------------
    Stage("join_sampling", "06b  Join the experiment", "Beyond blinding",
          script="06b_join_sampling.py", unblinds=True,
          outputs=["results/roi_dataset.csv", "results/animal_metadata.csv"],
          needs=["roi_dataset"],
          blurb="THE UNBLINDING STEP - the first stage permitted to read a group "
                "label. Joins LSnn to the sampling workbook and asserts the "
                "cohort matches its own 'slicing IHC July 2025' column."),

    Stage("excel_sample", "06c  Spreadsheet - per sample", "Beyond blinding",
          script="06c_excel_dataset.py",
          outputs=["results/roi_dataset.xlsx"],
          needs=["roi_dataset"],
          blurb="One row per ROI per sample, plus per-disc, per-section and "
                "coverage sheets. A row here is one animal, which is why the "
                "per-ROI figures read this one. Buildable mid-run."),

    Stage("excel_slide", "06d  Spreadsheet - per slide", "Beyond blinding",
          script="06d_excel_by_slide.py",
          outputs=["results/roi_dataset_by_slide.xlsx"],
          needs=["roi_dataset"],
          blurb="The same table one level finer, so within-animal spread is "
                "visible. plot_by_slide.R draws that spread; the per-ROI "
                "figures and their statistics read 06c's per-animal sheet."),

    Stage("refresh_loop", "06e  Refresh datasets and figures hourly", "Beyond blinding",
          script="06e_refresh_loop.py",
          outputs=["results/ROI_plots"],
          needs=["roi_dataset"],
          cli_only="a long-running loop, not a one-shot stage - it would hold "
                   "the app's runner open for hours. Run: refresh_loop.bat",
          blurb="Rebuilds both spreadsheets and re-draws the figures every hour "
                "while detection runs, then stops when every section is measured."),
]

BY_ID = {s.sid: s for s in STAGES}


def in_group(group):
    return [s for s in STAGES if s.group == group]


def blocked_by(stage, out_root):
    """Stage ids this stage needs that are not done yet.

    Advisory, not enforced: the stages themselves fail with a clear message when
    an input is missing, and that message is better than anything guessed here.
    """
    return [n for n in stage.needs
            if n in BY_ID and not BY_ID[n].done(out_root)]
