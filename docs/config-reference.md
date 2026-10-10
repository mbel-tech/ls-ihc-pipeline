# Configuration reference

GENERATED from `SPEC` in `scripts/ls_config.py` by
`python scripts/ls_config.py --docs docs/config-reference.md`.
Edit the spec, not this file.

Every setting a study can carry. **Read by** names the stages that consume a
key; a key nothing reads says so, rather than looking like every other one.
A key marked *required* has to be present before any stage will run.

| Key | Type | Default | Read by | What it is |
|---|---|---|---|---|
| `schema_version` | int | `1` | `ls_config` | Config format version. Written by the app; do not edit by hand. |
| `study.name` | str | `""` | `app` | A short name for this study, shown in the app's study picker. |
| `source_dir` | path_dir | *required* | `00_manifest`, `00b`, `00d`, `01b_pick`, `01e`, `01h`, `01_overviews`, `05a`, `05c`, `06b`, `app` | The folder holding the .czi files. |
| `out_root` | path_dir_create | *required* | `every stage` | Where every result is written. Needs room - overviews alone run to several GB. |
| `atlas_pdf` | path_file | *required* | `04a_atlas_extract`, `04a2`, `04a4`, `app` | The atlas the plates and region seeds are extracted from. |
| `export_dir` | path_dir_opt |  | `04l`, `05a`, `app/curator_view` | Where the ROI curator files its exports. Empty means <out_root>/exports. |
| `source_files` | list_str_opt |  | `00_manifest`, `app/import_slides` | Optional allowlist of filenames to process. Empty means every file in source_dir. |
| `slide_naming.pattern` | regex | *required* | `00_manifest`, `app/slides` | Regex matching your slide filenames, with a named group 'subject'. Optional named groups 'slide' and 'replicate'; any others are carried through as manifest columns. |
| `slide_naming.example` | str | `""` | `app/slides` | One real filename, used by the app to preview the parse. |
| `slide_naming.case_insensitive` | bool | `true` | `00_manifest`, `app/slides` | Match filenames case-insensitively. |
| `section_order_convention` | str | `"S_scan_order"` | `00_manifest` | How serial section order is recovered from the scan. |
| `pixel_size_um` | float | *required* | `01c`, `01e`, `01f`, `01_overviews`, `05a`, `05c`, `06a` | Camera pixel size at the objective used, in micrometres. |
| `section_thickness_um` | float | *required* | `06a` | How thick the sections were cut, in micrometres. |
| `overview_target_um_per_px` | float | `5.2` | `01_overviews`, `01_overviews.groovy` | Resolution the per-section overviews are exported at. |
| `acquisition.layout` | str | `"multiplex"` | `01_overviews`, `02_pair_passes`, `04a_reformat`, `05c`, `app` | How the markers were imaged: one multi-channel scan per section, or one scan per marker. |
| `acquisition.channels` | raw | `[]` | `01_overviews`, `05c`, `app` | What each CZI channel is: its name, what it is for, and how it is found in a file. |
| `acquisition.markers` | raw | `[]` | `01k_saturation_raw`, `04a_reformat`, `04g_artifact_mask`, `04j_censor_clipped`, `04l_roi_curator`, `04o_section_rgb`, `05a_roi_geometry` | The markers a `paired` study measures, in the order they should appear. Not used under `multiplex`. |
| `display.composite` | raw | `[]` | `04l_roi_curator`, `04o_section_rgb` | Which markers are shown in the composite and the curator's Review pane, and in what order. What colour each one is drawn in is `display.colours`. |
| `display.colours` | raw | `{}` | `04l_roi_curator`, `04o_section_rgb` | What colour each marker is drawn in, as marker -> colour name or #rrggbb. The nuclear counterstain has its own key below. |
| `display.nuclear_colour` | str | `"blue"` | `04l_roi_curator`, `04o_section_rgb` | What colour the nuclear counterstain is drawn in. |
| `channels.dapi_index` | int | `0` | `05c` | Which CZI channel plane is the nuclear counterstain. |
| `channels.marker_index` | int | `1` | `05c` | Which CZI channel plane carries the marker. |
| `marker_identity` | raw |  | recorded here, read by no stage | Which fluorophore is which marker. Filled in by 00c_channel_identity.py, then confirmed by the operator. |
| `detection.nucleus_diameter_um` | float | `7.0` | `05c` | Expected nucleus diameter, the scale StarDist is run at. |
| `detection.abercrombie.enabled` | bool | `true` | `06a` | Correct counted nuclear profiles to nuclei. |
| `detection.threshold.mad_k` | float | `3.0` | `05c` | How many robust standard deviations above the background median a pixel must be to count as signal, for the `threshold` backend. |
| `detection.threshold.min_area_um2` | float | `5.0` | `05c` | The smallest object the `threshold` backend will report, in square micrometres. |
| `atlas_source` | str | `"salmon"` | `04e`, `04k`, `04l`, `04w`, `04x` | Which atlas the run uses: salmon (the default) or wullimann1996. |
| `atlas_polygon_mirror` | bool | `false` | `04l` | Wullimann only: mirror the plate outlines about the midline. |
| `atlas_plate_set.dir` | str | `"plates"` | `04e`, `04k`, `04l` | Which plate set the ROI curator and the registration use. |
| `atlas_figure_sections.two_sections` | str_opt |  | `04a3b` | Inclusive figure-number range, as a string, of merged figures holding two sections each - e.g. "31-47". Empty leaves every figure at whatever 04a2 detected. |
| `atlas_figure_sections.drop_inset_boxes` | raw | `{}` | `04a3b` | Merged figure id -> the 1-based index of the box to drop, counted top to bottom. |
| `atlas_scope` | raw |  | recorded here, read by no stage | Which regions the atlas already labels, and which are still wanted. |
| `groups.order` | list_str | `[]` | `04l`, `06c`, `06d` | Which treatment is the LEFT half of every Shotgun slide, and the order the halves are drawn in. |
| `groups.by_animal` | raw | `{}` | `04l`, `05c`, `06c`, `06d` | Subject ID -> treatment, using exactly the labels in groups.order. |

## Keys removed in schema v1

A config written before these were dropped is not broken and its author was not
confused. `python scripts/ls_config.py --check` reports them as removed, with
the reason, rather than as mistakes.

- `blinding` — a convention this file cannot enforce; the rule is recorded on groups.by_animal, and stage metadata is what marks the unblinding step
- `channels.exposure_ms` — exposures are read per file from the CZI metadata by 00_manifest, so a hand-copied duplicate could only go stale
- `detection.local_contrast_inner_factor` — the 03a calibration sweep is not a stage; StarDist replaced the local-contrast detector
- `detection.local_contrast_outer_factor` — the 03a calibration sweep is not a stage; StarDist replaced the local-contrast detector
- `detection.local_contrast_threshold` — the 03a calibration sweep is not a stage; StarDist replaced the local-contrast detector
- `detection_target_um_per_px` — 05c detects at pixel_size_um directly, without resampling
- `flatfield` — read only by 01a_flatfield.groovy, which is retired and NOT_LISTED
- `section_interval_um` — never read; the argument it carried is now in the detection.abercrombie note
- `triage_target_um_per_px` — no stage resamples for triage
