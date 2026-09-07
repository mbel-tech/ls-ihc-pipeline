# Study config foundation

2026-09-07

## Why

The pipeline works, but only for one study. Everything that sounds generic is pinned to
the LS salmon experiment: `00_manifest.py:58` hardcodes an `LS` prefix in the filename
grammar, `AF568`/`AF488` appear at 197 load-bearing sites across 36 files,
`04a_atlas_extract.py` reads the Salmon Atlas PDF's vector drawing list and text layer to
find regions, and `06b_join_sampling.py` hand-parses one specific workbook's
`xl/worksheets/sheet1.xml`. The goal is a tool another lab can point at its own slides,
markers, atlas and metadata table.

That is four projects. This one is the first: the configuration layer the other three plug
into. Channels and markers, the replaceable atlas, and the customisable metadata join each
get their own spec.

This one has to come first because **there is no config module**. The loader

```python
CONFIG_PATH = os.environ.get("LS_CONFIG") or os.path.join(...)
with open(CONFIG_PATH, encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)
```

is copy-pasted verbatim into 37 scripts. There is no schema, no validation, no defaults,
and eight config keys are read by no code at all — including `blinding`, whose `_note`
declares the rule that no stage before 06b may read a group label, and which nothing
enforces. `tests/test_config_resolver.py:66` greps each stage's *source text* for the
string `os.environ.get("LS_CONFIG")`, because there is no object to ask.

Nothing generic can be built on that.

## What stays the same

`LS_CONFIG` — an absolute path to the active config — remains the only thing a stage sees.
`scripts/run_all.sh` and the three Groovy stages parse it directly with JsonSlurper and
need no change; they read only required keys that have no defaults. With `LS_CONFIG`
unset, a stage still falls back to the repo-root `config.json`, so a bare
`python scripts/XX.py` and a fresh clone keep working.

`scene_uid` keeps its format. It is the primary key every table in the pipeline joins on,
built at `00_manifest.py:540`, and it is also a filename component and a key in the
curation JSON. Making its *shape* configurable would let a user orphan every prior result
by editing a string. Only its field values come from the study's parse; existing LS uids
are byte-identical.

## Architecture

### One spec table

`scripts/ls_config.py` holds a declarative table, one entry per key: dotted path, type,
required, default, a one-line doc, the consuming stages, and a status of `live`,
`documented` or `retired`. That single table generates four things:

- validation errors — typed, naming the file and key, using the doc line as the hint
- `config.example.json`
- the config reference table in the docs
- the field list for the app's settings dialog

Four consumers from one source is why this is hand-rolled rather than `jsonschema`, which
would supply only the first and leave the other three to drift by hand.
`tests/test_config_example.py` exists today to test for exactly that drift between
`config.json` and `config.example.json`; generation makes the drift impossible, and that
suite shrinks to "the generator output matches the committed file".

Stage headers collapse from six lines to one:

```python
from ls_config import CONFIG, OUT_ROOT, SOURCE_DIR
```

Sibling imports already work in-process and frozen — `ls_io.py`, `czi_meta.py` and
`atlas_pdf.py` are imported this way, and `app/runner.py` puts `scripts_dir` on `sys.path`
before exec.

An unknown key **warns**, naming the file and the key, rather than failing. A stale config
should surface, not abort a twelve-hour run.

### Studies

```
~/.ls-pipeline/                 override with LS_HOME
  settings.json                 last_study, studies_dir, atlas_library, recent[]
  studies/
    LS.json                     migrated from the current config.json
```

The app gains a study picker, replacing `config_dialog.ensure_config()`. Switching study
rewrites `LS_CONFIG` and nothing else. The existing `config.json` is copied into
`studies/LS.json` on first run and left in place untouched. The study folder is a
convenience layer above `LS_CONFIG`, not a replacement for it.

### Dead keys

Dropped, because nothing reads them: `triage_target_um_per_px`,
`detection_target_um_per_px`, `section_interval_um`, `channels.exposure_ms`, `flatfield`,
and `blinding.enabled`. The last is dropped rather than wired because blinding is now
always on — a toggle that never toggled anything is worse than no toggle.

One caveat on `flatfield`: it is dead to every Python stage, but `01a_flatfield.groovy`
still reads it. That stage is retired and listed in `NOT_LISTED`, so dropping the key is
safe; it is recorded here so the removal is not mistaken for an oversight later.

Kept and marked `documented`: `atlas_scope` and `marker_identity`. Neither is read, but
both carry operator knowledge recorded nowhere else — the confirmed AF568 = pERK
assignment, and which social-behaviour-network nodes the atlas already labels. The
channel work and the atlas work will wire them.

`channels.*` and `groups.*` stay exactly as they are. The channel project replaces the
first and the metadata project replaces the second; changing them twice is worse than
changing them once.

### Slide naming

```json
"slide_naming": {
  "pattern": "^(?P<subject>LS\\d+)_(?P<slide>\\d+)(?P<replicate>[a-z])(-?)(_[A-Za-z0-9]+)?\\.czi$",
  "example": "LS105_10a.czi",
  "case_insensitive": true
}
```

One required named group, `subject`. `slide` and `replicate` optional; any further named
groups ride through as extra manifest columns. Both `00_manifest.parse_name()` and
`app/slides.name_pattern()` consume the same compiled pattern, which is the stated purpose
of the Add-slides screen: a misnamed file is invisible, and the screen exists to say so.

The app builds the pattern interactively. It lists the filenames it found, the user marks
the subject / slide / replicate spans on one example, everything outside the marked spans
is escaped, the pattern is anchored, and a live match/fail table runs over all files. The
regex stays editable for anyone who would rather type it. It cannot be saved while files
fail to match unless the user explicitly accepts those exclusions.

Three places currently re-derive the subject from the uid instead of reading a column, and
all three go away: `06d_excel_by_slide.py:43` (its own `^(?P<animal>LS\d+)_s...` regex),
`06c_excel_dataset.py:357` (`uid.split("_")[0]`), and `analysis/plot_roi_figures.R:189`
(`sub("^LS", "", ...)`, used only for sort order). That leaves the literal `LS` in exactly
one place, `app/slides.py:28`, as a bootstrap fallback used only before a study exists.

## Testing

`tests/test_config_resolver.py` flips from a textual assertion to a functional one: import
each stage with `LS_CONFIG` pointing somewhere unexpected and assert it resolved there.
Strictly stronger than grepping source for a string.

`tests/test_ls_regression.py` is the guarantee for the existing study. Because this work
changes how config is read and not what stages compute, the sharp check is to import every
numbered stage under the old `config.json` and again under the migrated `studies/LS.json`,
and assert every derived module-level constant — paths, thresholds, indices — is
identical. It catches a mistyped key or a wrong default without running data, which
matters: stage scripts overwrite `out_root`, so running one is never a test.

New suites cover validation, defaults, the unknown-key warning, example-config generation,
the naming parser, and the migration.

## Risks

**A silent path change** is the one that would hurt: a mistyped key or wrong default
pointing a stage at a different directory, quietly writing beside the real data. The
constants diff is the mitigation, and it gates the bulk migration of the remaining stages.

**`app/runner.py` caches stage modules and invalidates on config mtime alone**
(`_config_changed`). Stage modules read config at import into module constants, so an edit
within timestamp granularity serves stale values. Fixed here by hashing content.

Two problems found while surveying, out of scope but recorded because the atlas project
will hit them immediately: curation stores the atlas plate as an **integer index into the
sorted plate array**, not a plate id (`curation/ls_roi_curator_v1.json`, restored from the
index at `04q_import_curation.py:136-140`), so swapping atlases silently remaps every
curated section — and `atlas/_reframe_proposals.json` is read by
`04a3_plate_reframe.py:46` but written by nothing in tracked code.
