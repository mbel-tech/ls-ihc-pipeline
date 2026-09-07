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
