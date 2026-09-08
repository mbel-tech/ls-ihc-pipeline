# Setting up a study

A **study** is one dataset and the settings that describe it: where the slides
are, where results go, which atlas, how a filename is read. It is a single JSON
file with a name. Everything the pipeline does is rooted in that file, so the
first question is always which study you are working on, and the app keeps the
answer in the status bar rather than leaving it to be inferred.

Every setting a study can carry is listed in
[`config-reference.md`](config-reference.md), which is generated from the same
table that validates it.

## Where studies live

```
~/.ls-pipeline/
  settings.json          which study was open last
  studies/
    ls-dec-2025.json
    pilot-2027.json
```

Set `LS_HOME` to put that somewhere else — a shared drive, or a USB stick for a
portable install. The tests set it to a temp directory, which is how running
them can never change which study you have open.

## Bringing an existing config in

If you already have a `config.json` at the repo root, it keeps working exactly
as before; nothing has to change. To give it a name and move it into the store:

```bash
python scripts/ls_config.py --migrate "LS Dec 2025"
```

That **copies**. The original is left where it was, so the move is reversible
by deleting one file, and anything still resolving to it — a bare
`python scripts/XX.py`, `run_all.sh`, a fresh clone — carries on working.

`python scripts/ls_config.py --studies` lists what is there and which is active.

## Making a new one

In the app: **Pipeline ▸ Studies… ▸ New study…**. Name it, then fill in the
settings dialog. Three are required and have no sensible default:

- **Slides folder** — where the `.czi` files are.
- **Analysis output** — where everything is written. Overviews alone run to
  several GB; put it on a drive with room.
- **Atlas PDF** — the atlas plates and region seeds are extracted from.

Everything else has a default that is stated in the reference rather than
buried in the code.

## The filename pattern

The pipeline reads the subject, the slide and the replicate out of each
filename, and builds the `scene_uid` that every later table joins on. It has to
be told how your names are shaped.

**Pipeline ▸ Settings ▸ Filename pattern ▸ Build…** shows a real filename;
select a run of characters and say what it is. Everything you do not mark is
matched literally, so the pattern can never be looser than the example. The
generated regex stays editable, because most naming schemes have an exception
that no marking-up will cover.

Underneath is the part that matters: every filename that was found, checked
against the pattern, failures first. **A file the pattern misses never reaches
any stage and nothing else will tell you** — so Save stays disabled until the
misses are either fixed or ticked as deliberate exclusions.

One named group is required, `subject`. `slide` and `replicate` are optional;
any other group you add rides along as an extra column. A subject cannot
contain `_`, because the uid separates on it.

Studies whose filenames carry less degrade on their own:

| filename groups | scene uid |
|---|---|
| subject, slide, replicate | `LS105_s10a_sc03` |
| subject, slide | `AB12_s03_sc05` |
| subject only | `Fish07_sc05` |

## Choosing a segmentation backend

Under `multiplex`, `acquisition.channels` says what each channel is. For a
marker it also says **where its objects come from and what finds them** — three
settings that decide what gets counted, and one of which changes how the
numbers are corrected downstream.

```json
{"name": "pERK", "role": "marker", "czi_name": "AF568", "index": 1,
 "segment": "nuclear"},
{"name": "GFAP", "role": "marker", "czi_name": "AF647", "index": 2,
 "segment": "own", "backend": "threshold", "nucleus_shaped": false}
```

**`segment`: whose pixels the objects come from.**

- `nuclear` — the default wherever the study declares a nuclear channel. Nuclei
  are segmented on the counterstain and the marker is measured *inside* each
  nuclear mask. The count and the positivity cut then come off different
  channels, so the cut can be changed later without re-reading a single CZI.
  This is what the pipeline has always done and what every existing number came
  from.
- `own` — the marker's own channel is segmented. Use it when the objects are
  not cells with nuclei: fibre staining, processes, plaques. The cost is real
  and unavoidable for such a marker: the count and the positivity cut now both
  come off one channel, so they cannot be varied independently. A study with no
  nuclear channel at all gets `own` for every marker automatically, because
  there is no nuclear mask to measure inside.

**`backend`: what turns pixels into objects.** Only read under `segment: own`;
a nuclear-segmented marker inherits the counterstain's segmentation, which is
StarDist.

- `stardist` — for anything nucleus-shaped. It separates touching nuclei, which
  a threshold cannot, and that matters most in periventricular regions where an
  under-segmentation error would look like an anatomical finding.
- `threshold` — for everything else. Median + `detection.threshold.mad_k` ×
  1.4826 × MAD of the frame being segmented, then connected components above
  `detection.threshold.min_area_um2`. It finds stained **regions** and does not
  pretend they are cells: two touching objects are one object here. That is a
  limitation of connected components and it is the honest count for the things
  this backend is for.

**`backend: stardist` together with `nucleus_shaped: false` is refused**, at
settings time, by `ls_config.py --check` and by the app. StarDist segments
star-convex, nucleus-shaped objects; pointed at fibre or process staining it
finds few objects and **reports no error at all**. The failure is a quiet
undercount that announces itself nowhere later — not in a log, not in a count
that looks wrong, not in a figure. There is no point downstream at which it
could be caught, so it is caught here.

**`nucleus_shaped` also decides whether the Abercrombie correction applies.**
Sections are cut at a finite thickness and imaged in one plane, so what is
counted is object *profiles*, and `N = n × T/(T+h)` converts them to objects.
That formula assumes spherical, randomly positioned objects. A threshold region
on a fibre-stained channel is neither, so for a marker declared
`nucleus_shaped: false` the correction is **withheld**: the factor is 1.0, the
corrected density equals the raw one, and
`abercrombie_withheld_reason` — a column in `roi_measurements.csv` and on the
workbook's `by_roi` sheet — says why, in the row itself. A blank there means
the correction was applied. Withholding is recorded rather than silent
precisely so that an uncorrected density is never mistaken for an omission.

A `roi_nuclei.csv` written before these columns existed has none of them, and
is read as nuclear / StarDist / nucleus-shaped — which is what every row in
such a file is, since that was the only route detection had.

**Co-localisation** is computed only under `multiplex`, and only between
markers whose objects are actually different. **A is co-localised with B when
A's centroid falls inside B's mask.** There is no overlap fraction and so no
cutoff to tune: objects from two markers are not the same shapes — one may be a
nuclear mask and another a threshold region — and a fraction would not be
comparable between pairs. Containment is asymmetric, since a small object's
centroid can sit inside a large one while the reverse is false, so **both
directions are computed and both are written**, to
`results/roi_colocalisation.csv`, with the direction named.

Two cases produce no file rather than an empty one:

- A `paired` study. Its markers are separate physical scans of *different*
  sections, so their objects are not in one coordinate frame and relating them
  would mean nothing. An empty `roi_colocalisation.csv` would read as "nothing
  overlaps", which is a different claim from "the question does not apply".
- Two markers that are both `segment: nuclear`. They share the same nuclear
  objects, so every object would contain itself and the table would be a
  diagonal.

None of the `segment: own` path has met a real study yet. The backends, the
co-localisation pairs and the withheld correction are covered by synthetic
fixtures that check the rules are what is written above; they cannot check that
the threshold backend segments a real fibre stain usefully. The first study to
declare `segment: own` should expect to find things.

## Which config a stage actually reads

In order:

1. `LS_CONFIG` — an absolute path. This is what the app exports before running
   anything, and what `run_all.sh` and the Fiji stages read directly.
2. `LS_STUDY` — a study name. Naming one that does not exist is an **error**,
   not a fallback: quietly analysing a different study than you asked for is
   the failure this whole layer exists to prevent.
3. The study last opened in the app.
4. The repo's own `config.json`, if there is one.

`LS_CONFIG_STRICT=1` stops at step 1. `tests/run.sh` sets it so a test that
forgets to name its own config fails loudly instead of quietly analysing
whatever you have open.

## Checking a config

```bash
python scripts/ls_config.py --check
```

Errors are things no stage can run on — a required key missing, a value of the
wrong shape. Warnings are not fatal: an unknown key, or a path that is not
there right now. A drive being unplugged should not stop 45 stages from
loading, so it warns at import and fails in the one stage that opens the file.

Keys removed in this schema version are reported as removed, with the reason,
rather than as mistakes.

## What is not generic yet

Be aware of what this layer does and does not cover. The configuration,
filename grammar and study store are general. Three things are still shaped
around the LS salmon experiment and are being worked on separately:

- **Markers and channels.** `channels.dapi_index` / `marker_index` assume one
  nuclear channel and one marker, and the marker names `AF568`/`AF488` are
  written into stage ids, output paths and CSV column names.
- **The atlas.** Plate images can be swapped, but the region seeds are read
  from the Salmon Atlas PDF's vector drawing list and its text layer, neither
  of which a different atlas will reproduce.
- **The metadata join.** Stage 06b parses one specific workbook's sheet XML
  with eleven mandatory columns, and treatment currently reaches the figures
  from `groups.by_animal` in the config rather than from that join.

Each has its own design document under `docs/superpowers/specs/`.
