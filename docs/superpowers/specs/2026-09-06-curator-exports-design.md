# Curator exports: chosen directory, timestamped folder and filenames

2026-09-06

## Why

Every export the ROI curator produces is written by a clicked `<a download>`, which means
the destination is whatever the host decides: the PySide6 app intercepts the download and
forces it into `reformatted/`, and a plain browser drops it in the user's Downloads folder.
Neither is chosen, and every export overwrites the last one of the same name — `roi_regions.csv`
today is the only copy, and the browser's `roi_regions(1).csv` disambiguation is what
`05a_roi_geometry.py` currently has to reason about ("the newest wins", 05a:330).

The operator wants exports to land in a directory they choose, grouped into one folder per
export action, with the same timestamp on the folder and on every file in it.

## Timestamp

Format `DD.MM.YYYY_HH.MM` — for example `06.09.2026_18.20`. Local time.

**One stamp per export action, not per file.** `exportCsv()` writes three CSVs that are
three views of one decision set; they belong in one folder under one stamp. `beginExport()`
sets the stamp at the top of each of the three export entry points (`exportCsv`, `shotgun`,
`exportReview`) and every file written until the next `beginExport()` uses it.

```
<export-root>/06.09.2026_18.20/roi_plates_06.09.2026_18.20.csv
                               roi_landmarks_06.09.2026_18.20.csv
                               roi_regions_06.09.2026_18.20.csv
```

## Architecture

### One sink

Exports currently reach the browser through exactly two functions: `dl(rows, name)` at
04l:3093 for all five CSVs, and the blob helper at 04l:3724 for the Shotgun `.pptx`. Both
are routed through a new `saveExport(blob, baseName, ext)`, which is the only place that
knows about stamps, folders or destinations. The six call sites keep passing a plain base
name and learn nothing new.

### Destination, in order

1. **A directory handle**, if the page holds one. `showDirectoryPicker()` (File System
   Access API) returns one; `getDirectoryHandle(stamp, {create:true})` makes the dated
   subfolder and `getFileHandle(name, {create:true})` writes into it. Secure context is
   required and `http://127.0.0.1` qualifies, so this works under `serve_curators.py` in
   Chrome and Edge.
2. **`<a download>` with the timestamped filename**, everywhere else — Firefox, Safari, and
   QtWebEngine inside the app, none of which implement the picker. Browsers strip path
   separators from the `download` attribute, so the fallback cannot make a folder itself;
   the file arrives as `roi_regions_06.09.2026_18.20.csv` and the host decides where.

The handle is persisted in IndexedDB so it survives a reload. A browser may still drop the
permission, in which case the page re-requests it on the next export; that request needs a
user gesture, which an export click supplies.

### The control

A **Choose folder…** button beside Export, showing the current target — the picked
directory name, or the configured `--export-dir`, or "Downloads" when neither applies. It
is hidden where `showDirectoryPicker` is absent, since offering it there would be a lie.

### The two hosts

`04l_roi_curator.py --export-dir PATH` bakes a default target into the page for display,
and is what the app honours.

`app/curator_view.py::_on_download` currently sends every download to the page's own
folder. It gains one step: read the trailing `DD.MM.YYYY_HH.MM` off the incoming filename,
and save into `<export-dir>/<stamp>/` instead. Where the filename carries no stamp — an
older page, or a download from some other curator — the existing behaviour is unchanged.
This is what gives the app the same folder layout without the API it does not have.

## Downstream

`05a_roi_geometry.py` resolves its input by looking at `reformatted/roi_regions.csv` and
globbing `~/Downloads/roi_regions*.csv`, newest mtime winning (05a:330-338). The glob still
matches a timestamped filename, but not one inside a subfolder. Its resolver learns to look
one level deep as well — `<dir>/*/roi_regions*.csv` — across `reformatted/`, the export
directory and Downloads. The "newest wins" rule is unchanged; only the search widens.

`04q_import_curation.py` takes `--plates`, `--landmarks` and `--regions` as required
arguments and needs no change.

## Verification

- Both hosts write to the expected place, and three CSVs from one Export share one folder
  and one stamp.
- A second Export a minute later lands in its own folder rather than overwriting.
- `05a_roi_geometry.py` with no argument finds the newest export inside a dated folder.
- The Shotgun `.pptx` and its manifest share the folder and the stamp.
- Falling back to `<a download>` still produces a timestamped filename.

## Not in scope

Restructuring the generated page. `roi_curator.html` is 892 KB and the export code is a
small island in it; the change stays at the two chokepoints plus the new control.
