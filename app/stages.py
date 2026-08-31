"""The pipeline, as data.

One entry per stage. This is a transcription of `scripts/run_all.sh` plus the
04-series curation chain, not a second opinion about the order - `run_all.sh`
stays the authority, and if the two ever disagree that is a bug here.

Each stage says what it is, how to run it, and how to tell whether it has already
run. That last part is what lets the window show status without executing
anything: every stage in this pipeline is resumable and skips completed work, so
`done()` is a hint for the operator rather than a gate on running.

Stages the app does NOT run are still listed, with `cli_only` and a reason. The
Fiji tile-field chain is finished for this dataset and its outputs are on disk,
but someone starting a fresh dataset needs to know the steps exist - hiding them
would turn "we chose not to wrap this" into "this does not exist".
"""

import os


class Stage:
    """One pipeline step.

    `outputs` are checked for existence to decide `done`. They are relative to
    out_root, because that is the only root a stage's products ever live under.
    `argv` is what would follow the script name on a command line.
    """

    def __init__(self, sid, title, group, script=None, argv=(), outputs=(),
                 blurb="", cli_only=None, curator=None, needs=()):
        self.sid = sid
        self.title = title
        self.group = group
        self.script = script
        self.argv = list(argv)
        self.outputs = list(outputs)
        self.blurb = blurb
        self.cli_only = cli_only          # reason string, or None if runnable
        self.curator = curator            # html filename, for the embedded view
        self.needs = list(needs)          # stage ids that must be done first

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


# Groups, in the order they appear in the sidebar.
GROUPS = ["Slides", "Extraction", "Atlas", "Curation", "Quantification"]

# StarDist pulls in TensorFlow, which would roughly quadruple the 494 MB
# frozen build for a stage that runs once per curation pass. The app lists it
# and says where to run it rather than hiding it.
DL_REASON = ("needs StarDist and TensorFlow, which are not in the packaged app "
             "- they would quadruple its size for a stage that runs once per "
             "curation pass. Run: python scripts/05c_detect_rois.py")

FIJI_REASON = ("needs Fiji, which the app does not drive. Already complete for "
               "this dataset - qc/flatfield/tilefield_c*.npy are on disk. Run "
               "via scripts/run_all.sh if starting a new dataset.")

STAGES = [
    # ---- Slides -----------------------------------------------------------
    Stage("manifest", "Read slide headers", "Slides",
          script="00_manifest.py",
          outputs=["manifest/manifest_files.csv", "manifest/manifest_scenes.csv"],
          blurb="Parses every CZI header without extracting, reconstructs the "
                "slide layout and renders the slide maps."),

    Stage("verify", "Verify extraction", "Slides",
          script="00b_verify_extraction.py",
          outputs=["qc/extraction_status.csv"],
          needs=["manifest"],
          blurb="Checks extracted CZIs against the zip central directories. "
                "--crc checks content rather than size alone."),

    Stage("pick_sections", "Pick tile-field sample", "Slides",
          script="01b_pick_sections.py", argv=["--n", "96", "--scenes-per-file", "4"],
          outputs=["qc/tilefield_sample.csv"],
          cli_only="only feeds the Fiji sample export, which the app does not run.",
          blurb="Chooses the sections the tile-field characterisation measures."),

    # ---- Extraction -------------------------------------------------------
    Stage("fiji_export", "Export sample sections (Fiji)", "Extraction",
          cli_only=FIJI_REASON,
          outputs=["qc/test_sections"],
          blurb="Exports the sample at 2.6 um/px for the tile-field build."),

    Stage("tilefield", "Build tile-correction field", "Extraction",
          cli_only=FIJI_REASON,
          outputs=["qc/flatfield/tilefield_c0.npy", "qc/flatfield/tilefield_c1.npy"],
          blurb="Measures the repeating illumination pattern at the tile pitch. "
                "01_overviews applies it, and works without it."),

    Stage("overviews", "Export section overviews", "Extraction",
          script="01_overviews.py",
          outputs=["overviews", "qc/focus.csv"],
          needs=["manifest"],
          blurb="Every section at exactly 5.2 um/px with a frozen display range, "
                "plus per-section QC. Needs pylibCZIrw."),

    Stage("contactsheets", "Contact sheets and gallery", "Extraction",
          script="01d_contactsheets.py",
          outputs=["contactsheets"],
          needs=["overviews"],
          blurb="Per-animal montages in rostro-caudal order, plus an HTML gallery."),

    Stage("pair", "Pair the two marker passes", "Extraction",
          script="02_pair_passes.py",
          outputs=["pairs.csv"],
          needs=["overviews"],
          blurb="Matches AF568 and AF488 scans onto the same physical sections "
                "via stage coordinates."),

    Stage("channel_identity", "Infer marker identity", "Extraction",
          script="00c_channel_identity.py",
          outputs=["qc/channel_identity"],
          needs=["overviews"],
          blurb="Infers which fluorophore carries which marker from spatial "
                "signature. Reports the call; does not commit it to config."),

    # ---- Atlas ------------------------------------------------------------
    Stage("atlas_extract", "Extract atlas plates and seeds", "Atlas",
          script="04a_atlas_extract.py",
          outputs=["atlas/plates_final/plates.csv", "atlas/plates_final/seeds.csv"],
          blurb="Pulls the labelled plate series and region seed points out of "
                "the atlas PDF."),

    # ---- Curation ---------------------------------------------------------
    Stage("reformat", "Reformat sections to a common frame", "Curation",
          script="04a_reformat.py",
          outputs=["reformatted/reformat_index.csv",
                   "reformatted/reformat_index_AF568.csv"],
          needs=["overviews"],
          blurb="Normalises sections and atlas plates into one frame - the "
                "canonical grid every later coordinate is expressed in."),

    Stage("worklist", "Order the ROI queue", "Curation",
          script="04n_roi_worklist.py",
          outputs=["reformatted/roi_worklist.csv"],
          needs=["reformat"],
          blurb="Orders curation so any prefix is a usable dataset: every animal "
                "advanced to the same fraction, spread across each brain."),

    # One stage per channel. The ROI curator carries both, so building only one
    # leaves half its sections falling back to greyscale - and the curator says
    # nothing about why, because a section without a composite is a legitimate
    # state. Two rows make the gap visible in the status list instead.
    Stage("rgb_perk", "Colour composites - pERK", "Curation",
          script="04o_section_rgb.py", argv=["--marker", "AF568", "--all"],
          outputs=["reformatted/sections_AF568_rgb"],
          needs=["reformat"],
          blurb="DAPI blue plus the marker, in the reformatted frame, so the "
                "curator shows the channel being quantified. Skips composites "
                "that already exist."),

    Stage("rgb_pcna", "Colour composites - PCNA", "Curation",
          script="04o_section_rgb.py", argv=["--marker", "AF488", "--all"],
          outputs=["reformatted/sections_rgb"],
          needs=["reformat"],
          blurb="The same for the PCNA channel, which the curator offers "
                "alongside pERK."),

    Stage("rotation_curator", "Rotation curator", "Curation",
          script="04d_rotation_curator.py",
          outputs=["reformatted/rotation_curator.html"],
          curator="reformatted/rotation_curator.html",
          needs=["reformat"],
          blurb="Adjudicate each section's rotation by dragging it upright."),

    Stage("level_curator", "Level curator", "Curation",
          script="04k_level_curator.py",
          outputs=["reformatted/level_curator.html"],
          curator="reformatted/level_curator.html",
          needs=["reformat"],
          blurb="Assign atlas levels by anchoring a few sections and "
                "interpolating between them."),

    Stage("roi_curator", "ROI curator", "Curation",
          script="04l_roi_curator.py",
          argv=["--marker", "AF568", "--worklist", "--rgb"],
          outputs=["reformatted/roi_curator.html"],
          curator="reformatted/roi_curator.html",
          needs=["worklist", "rgb_perk", "rgb_pcna", "atlas_extract"],
          blurb="Assign a plate, place numbered landmarks, warp the atlas "
                "regions onto the section, export the three CSVs."),

    # ---- Quantification ---------------------------------------------------
    Stage("roi_geometry", "Place the ROIs on the slide", "Quantification",
          script="05a_roi_geometry.py",
          outputs=["reformatted/roi_geometry.csv", "reformatted/roi_boxes.csv"],
          needs=["roi_curator"],
          blurb="Inverts the reformat transform, so an ROI drawn on the 256 px "
                "normalised frame becomes a rectangle in CZI pixels. Reads the "
                "roi_regions.csv the curator exported; --verify checks the map "
                "against the transform it inverts."),

    Stage("detect", "Count nuclei in the ROIs", "Quantification",
          script="05c_detect_rois.py",
          outputs=["results/roi_nuclei.csv"],
          needs=["roi_geometry"],
          cli_only=DL_REASON,
          blurb="Reads the CZI at 0.65 um/px over each ROI, segments nuclei on "
                "DAPI with StarDist and measures the marker inside them. One "
                "row per nucleus, so the positivity cut can change later "
                "without re-reading a single CZI."),

    Stage("roi_dataset", "Per-ROI dataset", "Quantification",
          script="06a_roi_dataset.py",
          outputs=["results/roi_measurements.csv",
                   "results/detector_specificity.csv"],
          needs=["detect"],
          blurb="Counts, positivity against each section's own background discs, "
                "and the Abercrombie correction. Still keyed by animal only - "
                "no group label is read here."),

    Stage("join_sampling", "Join the experiment (UNBLINDS)", "Quantification",
          script="06b_join_sampling.py",
          outputs=["results/roi_dataset.csv", "results/animal_metadata.csv"],
          needs=["roi_dataset"],
          blurb="The first stage permitted to read a group label - config's "
                "blinding note names 06b exactly. Joins LSnn to Fish ID in the "
                "sampling workbook and asserts the cohort matches the sheet's "
                "own 'slicing IHC July 2025' column."),
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
