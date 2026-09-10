# P1 part 4 — finish the genericisation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second lab's study runs correctly end to end from the CLI and `run_all.sh`,
while the LS study's files, numbers and images do not move.

**Architecture:** One new module, `scripts/ls_paths.py`, owns the artifact-naming rule that
is currently copied eight times and inverted in several copies. `ls_channels` gains a
marker→colour map that feeds both the section composites and the curator's Review pane, so
the two can no longer disagree. Everything else is routing hardcoded literals through
functions that already exist.

**Tech Stack:** Python 3.13 (`work/appenv/Scripts/python.exe`), plain-script tests (no
pytest anywhere in this repo), Node for the curator page suites.

---

## Standing rules

- **Never `git add -A`, `git add .`, or `git commit -a`.** The owner's 13 files are in
  flight, and a sibling session is working on `scripts/06h_backfill_provenance.py`,
  `tests/test_backfill_provenance.py`, `tests/test_ls_regression.py` and
  `tests/test_config_resolver.py`. Stage only exact paths. **`app/stages.py` and
  `tests/test_stages.py` are off limits until Task 11.**
- **Never run a numbered stage script** (`scripts/NN_*.py`). They overwrite `out_root`,
  which holds 130 curated sections and a 961,233-row `roi_nuclei.csv`. `--help` is safe.
  To exercise one, call its functions in-process with output constants redirected to the
  scratchpad. **Never write anything under `D:\LS-analysis`.**
- **Never run `scripts/run_all.sh`.** `bash -n` checks its syntax.
- `config.json` and `config.json.*` are gitignored; never commit them.
- Do not use `\n` escapes inside `<<'PY'` heredocs — they become literal newlines. Use the
  Write/Edit tools for content with escape sequences.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

## The regression guarantee

After every commit:

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

Expected: `no stage derives anything different from the migrated study []`, all 46 stages.
**Read the output, not the exit code.** NEW constants are fine; CHANGED constants are not.

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && bash tests/run.sh 2>&1 | tail -25
```

63 suites, exactly ONE expected failure: `tests/test_join_metadata.py`, pre-existing from
the owner's uncommitted `analysis/plot_roi_figures.R` dropping a `SHAPES` constant. **Do
not fix it.** `tests/test_small_fixes.py` prints `all ok` (exit 0) — that is a pass.

## The live study, for reference

```
layout          paired
markers         ["AF568", "AF488"]
channels        []                     (paired declares no channel table)
DEFAULT_MARKER  AF488                  (04a: MARKERS[1], the UNSUFFIXED one)
```

`marker_paths()` returns **six** keys. Today:

```
AF568  overrides=perk_overrides.csv     uid_col=perk_scene_uid  sections=sections_AF568
       index=reformat_index_AF568.csv   excluded=excluded_sections_AF568.csv
       lost=lost_sections_AF568.csv
AF488  overrides=rotation_overrides.csv uid_col=scene_uid       sections=sections
       index=reformat_index.csv         excluded=excluded_sections.csv
       lost=lost_sections.csv
```

**The trap to keep in mind throughout:** the marker with the *unsuffixed* outputs is the
**second** declared. Any code that assumes "first = unsuffixed" is inverted.

---

## Task 1: `scripts/ls_paths.py` — one naming rule

**Files:** create `scripts/ls_paths.py`, `tests/test_ls_paths.py`

- [ ] **Step 1: Write the failing test**

`tests/test_ls_paths.py`, plain-script style with a local `chk()` ending
`sys.exit(1 if failures else 0)`. It must cover:

- `slug("AF568") == "af568"` — and that this is what `02_pair_passes.py` already writes,
  so `pairs.csv` needs no fallback. Also `slug("Marker 1") == "marker_1"`, and that two
  markers whose slugs collide are detectable.
- `geometry_source(["AF568","AF488"], "paired") == "AF488"` (the second declared), and
  under `multiplex` every marker is its own source (suffix is `""` for all).
- `Names.suffix(m)` is `""` for the geometry source and `"_<m>"` otherwise under paired;
  `""` for everything under multiplex.
- `Names.path("index", "AF568")` ends in `reformat_index_AF568.csv`;
  `Names.path("index", "AF488")` ends in `reformat_index.csv`. **These must match what
  `04a.marker_paths` returns today for both markers, all six keys** — assert against
  `04a.marker_paths` directly so the two cannot drift.
- `Names.read()` returns the legacy name **only when the legacy file exists** and the
  current one does not. Build a temp tree and prove all four combinations.
- When BOTH exist, the current one wins **and the fact is announced** (capture the
  announce callback).
- A fresh study that happens to name a marker `AF568` in an empty out_root never reaches a
  legacy branch.
- `LEGACY_GROUPS`: `roi_geometry` and `roi_boxes` are adopted together or not at all —
  one present and one absent must NOT adopt either (this is `05a.resolve_paths`'s existing
  rule; read it at `scripts/05a_roi_geometry.py:128-155` and preserve it exactly).

- [ ] **Step 2: Run it, watch it fail** with `ModuleNotFoundError: No module named 'ls_paths'`.

- [ ] **Step 3: Write `scripts/ls_paths.py`**

Structure (docstrings are load-bearing — they carry the reasoning):

```python
ARTIFACTS = {
    # key                subdir         stem                  ext     suffix rule
    "sections":         ("reformatted", "sections",           "",     True),
    "index":            ("reformatted", "reformat_index",     ".csv", True),
    "excluded":         ("reformatted", "excluded_sections",  ".csv", True),
    "lost":             ("reformatted", "lost_sections",      ".csv", True),
    "overrides":        ("reformatted", "rotation_overrides", ".csv", True),
    "sections_dataset": ("reformatted", "sections_dataset",   ".csv", True),
    "artifact_summary": ("artifacts",   "artifact_summary",   ".csv", True),
    # NOT suffix-ruled. 04j names EVERY marker's file after the marker,
    # including the geometry source (pcna_analysis_set.csv). That is what is on
    # disk, and a reader who assumes the suffix rule everywhere would go looking
    # for analysis_set.csv and find nothing.
    "analysis_set":     ("reformatted", "{marker}_analysis_set", ".csv", None),
    "roi_geometry":     ("reformatted", "roi_geometry_{marker}", ".csv", None),
    "roi_boxes":        ("reformatted", "roi_boxes_{marker}",    ".csv", None),
}
```

`LEGACY` is keyed on `(artifact, marker_name)` — **not on a role** — because a study whose
markers are `["Mk1","Mk2"]` must get `Mk1_...`, never `perk_...`. Entries:

```
("overrides",        "AF568") -> perk_overrides.csv
("sections_dataset", "AF568") -> perk_sections_dataset.csv
("analysis_set",     "AF568") -> perk_analysis_set.csv
("analysis_set",     "AF488") -> pcna_analysis_set.csv
("roi_geometry",     "AF568") -> roi_geometry.csv
("roi_boxes",        "AF568") -> roi_boxes.csv
```

with a comment saying these are **basenames that exist on one operator's drive**, not a
naming convention, and that `os.path.exists` decides — so the claim is about this
out_root rather than about what `AF568` means anywhere.

`LEGACY_GROUPS = [("roi_geometry", "roi_boxes")]`.

API: `slug(name)`, `geometry_source(markers, layout)`, and

```python
class Names:
    def __init__(self, out_root, markers, layout)
    def suffix(self, marker) -> str
    def path(self, artifact, marker) -> str        # where a WRITER writes. Never legacy.
    def legacy_path(self, artifact, marker) -> str | None
    def read(self, artifact, marker, announce=print) -> str
    def all_paths(self, artifact) -> dict          # {marker: path}

def for_config(cfg) -> Names                       # memoised on (out_root, markers, layout)
```

`read()`'s docstring must say why existence decides and why a both-exist case is printed
rather than silently resolved:

> Two files that mean the same thing and disagree in age is how a stale number survives a
> rename; a reader that silently prefers one of them is the same bug as a reader that
> silently prefers the other.

Print the older file's mtime when both exist.

- [ ] **Step 4: Add `--migrate`, which moves nothing**

`python scripts/ls_paths.py --migrate` walks `out_root`, lists every legacy file found and
the current name it maps to, and **moves nothing**. State that in the `--help` text.

- [ ] **Step 5: Verify and commit**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_ls_paths.py && work/appenv/Scripts/python.exe scripts/ls_paths.py --migrate && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

`--migrate` on the live study should list the legacy files that really are on the drive.
Commit `scripts/ls_paths.py tests/test_ls_paths.py`.

---

## Task 2: the directory rule, all eight copies

**This is the highest-value task.** It fixes the 3× coordinate displacement and the
zero-sections-measured.

**Files:** `scripts/04q_import_curation.py:111`, `app/import_exports.py:59`,
`scripts/05c_detect_rois.py:670`, `scripts/06g_flag_off_tissue.py:73`,
`scripts/04p_section_provenance.py:290`, `scripts/04l_roi_curator.py:498-500` and its two
JS sites (`:4035`, `:4484`)

- [ ] **Step 1: Write the failing tests FIRST, one per site**

The displacement is directly assertable. `tests/test_import_curation.py` already pins
`k_of` behaviour — add to it:

```python
# Under a study whose markers are NOT AF568/AF488, marker_dir must still give
# each marker the directory 04a actually wrote. The old rule returned
# "sections" for every marker, so k fell back to 1.0 while the page had drawn
# at K=3 - every disc, landmark and polygon vertex a third of the way to the
# origin, silently. This is the failure 04q's own docstring says it prevents.
```

Build a temp study with `markers: ["Mk1","Mk2"]`, lay down a 768-px PNG in the directory
`04a.marker_paths("Mk1")["sections"] + "_rgb"`, and assert `k_of(uid, "Mk1") == 3.0`.
**Confirm it returns 1.0 before the fix.**

Mirror it in `tests/test_import_exports.py` for `app/import_exports.py:59`.

For `05c.mask_at` and `06g.tissue_mask`: assert the probe list comes from
`04a.marker_paths(marker)["sections"]`, driven with a temp study whose markers are not
AF568/AF488, with a mask file laid down in the correct directory.

- [ ] **Step 2: Replace every copy with a delegation**

All eight become `RF.marker_paths(marker)["sections"]` (where `RF` is `04a_reformat`,
already imported as a sibling in several of these files — check each). For the two JS
sites, add a `__SECDIRS__` template token carrying `{marker: "<basename>"}` built in
Python from `marker_paths`, and have `revSrc()` and `reinstatedRow()` read it.

**Keep `05c.mask_at`'s fallback to the unsuffixed directory** — under multiplex that is
the correct path, and it is already relied on.

- [ ] **Step 3: Verify**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe tests/test_import_curation.py && work/appenv/Scripts/python.exe tests/test_import_exports.py && work/appenv/Scripts/python.exe tests/test_detect_backends.py && work/appenv/Scripts/python.exe tests/test_ls_regression.py && bash tests/run.sh 2>&1 | tail -20
```

Then confirm the LIVE study's directories are unchanged: print `marker_dir`/`mask_at`'s
probe list for both markers under the real config and compare against
`ls /d/LS-analysis/reformatted/`.

- [ ] **Step 4: Commit.** Body should lead with the 3× displacement — what it was, that it
was silent, and that one rule was copied eight times with several copies inverted.

---

## Task 3: `05a.build()` and `verify()`

**Files:** `scripts/05a_roi_geometry.py:481-483`, `:700`; `tests/test_roi_geometry.py`

- [ ] **Step 1: Write the failing test**

Under a temp study with markers `["Mk1","Mk2"]`, `build()` must find `Mk1`'s index. Today
it iterates the literal `("AF568","AF488")` and the literal filename pair, so every `Mk1`
uid falls into `skipped` as "not in reformat_index" and an **empty** `roi_boxes_Mk1.csv`
is written. Assert the boxes file is non-empty.

For `verify()`: assert that `--verify --marker Mk1` does not print a PASS computed from
`Mk2`'s rows. Today `want` is empty for Mk1, so line 718 falls back to "whatever is there"
— which is exactly the bug the comment at `:709-714` says was fixed, reintroduced one
level up. **Say that in the test's comment.**

- [ ] **Step 2: Replace both literals** with `for marker in MARKERS:` and
`RF.marker_paths(marker)["index"]` (or `ls_paths`). Preserve the legacy `resolve_paths`
branch at `:152` — it is a correctly-commented fact about files on the drive.

- [ ] **Step 3: Verify and commit.** The constants probe plus `tests/test_roi_geometry.py`.

---

## Task 4: the paired chain — `02` and `04i`

Both are `paired`-only via `ls_layouts.RESTRICTED`. **Paired is not "paired with these two
fluorophore names"** — both are reachable, and both silently produce nothing.

**Files:** `scripts/02_pair_passes.py:220-291`, `scripts/04i_propagate_to_perk.py:288-344`

- [ ] **Step 1: Write the failing tests**

`02`: with markers `["Mk1","Mk2"]`, `pairs.csv` must be written with rows. Today
`marker_a, marker_b = "AF568", "AF488"` at `:223` throws away the markers computed two
lines above at `:220`, so `chosen.get((animal, slide, "AF568"))` is `[]` for every slide
and `_write` prints "nothing to write". Assert rows exist.

`04i`: `tests/test_propagate_frames.py` is the home. The overview paths at `:327-328` use
literal `"AF488"`/`"AF568"` subdirectories while `:325-326` read the real channel out of
`focus.csv` **and discard it**. Assert the path built uses the channel from `focus.csv`.

- [ ] **Step 2: Fix**

`02:223` → `marker_a, marker_b = MARKERS[0], MARKERS[1]`. Turn the `len(markers) != 2`
warning into a `SystemExit` — 02 is paired-only and a three-marker paired study has no
meaning for it.

`02`'s derived column names: `f"{slug(m)}_file"`, `f"{slug(m)}_scene"`,
`f"{slug(m)}_scene_uid"`, `f"n_{slug(m)}"`, and statuses `f"unmatched_{m}"` /
`f"separate_slide_{m}"` using the **marker name verbatim** (that is what is on disk).
`slug("AF568") == "af568"`, so `pairs.csv` needs **no fallback** — pin that with a test
rather than relying on the coincidence silently.

`04i:327-328` → use `chan[uid][1]`, the channel already read at `:325-326`. Rename the
`to568`/`p488`/`p568`/`total488`/`a568` identifiers to `source`/`target`.

- [ ] **Step 3: Delete `qc/perk/`.** `04i:74` defines `REPORT_DIR` and `:284` creates it;
**nothing ever writes into it.** Remove both lines.

- [ ] **Step 4: Verify and commit.** Confirm `pairs.csv`'s columns are byte-identical for
the live study by generating them from `slug()` and comparing to the header on disk.

---

## Task 5: `04m` and `04n` — the crashers and the renames

**Files:** `scripts/04m_sections_dataset.py`, `scripts/04n_roi_worklist.py`,
`scripts/ls_layouts.py`, `scripts/ls_io.py`

- [ ] **Step 1: Add `ls_io.pick_column`**

```python
def pick_column(fieldnames, *candidates):
    """The first candidate present in a CSV header, or a refusal naming all of them.

    Never defaults. `r[uid_col]` raising KeyError 400 rows into a loop is worse
    than refusing at the header, and `.get()` returning "" for a moved column is
    worse than both: a blank cell and a renamed column look identical.
    """
```

Test it in `tests/test_small_fixes.py` or a new suite.

- [ ] **Step 2: Write the failing tests**

Under a temp study with markers `["Mk1","Mk2"]`, `04m.main()` must not raise
`FileNotFoundError`. Same for `04n`.

Then the column fallbacks: a `rotation_overrides_*.csv` with the **legacy**
`perk_scene_uid`/`pcna_scene_uid` header must still be read.

- [ ] **Step 3: Fix**

`04m`: route `:121-126` through `ls_paths` / `RF.marker_paths` / `04j.analysis_set_path`.
Rename its output to `sections_dataset_<marker>.csv` and its columns per the table:
`pcna_*` → `partner_*`, `perk_derived_rotation_deg` → `derived_rotation_deg`,
`perk_manual_flip` → `manual_flip`, `perk_final_angle_deg` → `final_angle_deg`.

**Keep `manual` on the partner and `derived` on the row.** That asymmetry is what 04m's
docstring exists to state (they disagree on 420 of 424 paired analysis-set rows); losing
it to symmetry would be the wrong kind of tidiness.

`04n`: `:69-70` through the same. Its `pcna_*` output columns → `partner_*`. Its
`tier_reason` string "no PCNA partner; rotation never checked" → "no partner in the
geometry-source pass; rotation never checked against anything". **Its `num(r, k)` helper
uses `.get()`** — route the three `partner_*` reads through `pick_column` on
`fieldnames`, once, before the loop.

Add `04m_sections_dataset.py` to `ls_layouts.RESTRICTED` as paired-only. Its universe is a
two-pass join and its `partner_kept` is meaningless without a partner;
`04p_section_provenance.py` already does the multiplex-shaped job.

- [ ] **Step 4: Verify and commit.** The live study's `04m` output must be identical apart
from the renamed columns — run it in-process with outputs redirected and diff.

---

## Task 6: `04p_section_provenance.py`

Everything in `04l`'s Review pane reads this table, and today every failure in it is
**silent** — `04p.load()` returns `[]` for a missing file.

**Files:** `scripts/04p_section_provenance.py:208, 235-239, 246-247, 290`

- [ ] **Step 1: Write the failing tests** in `tests/test_backfill_provenance.py`
(coordinate with the sibling session — if that file is still uncommitted, put them in a
new `tests/test_section_provenance.py` instead and say so).

Under markers `["Mk1","Mk2"]`:
- `sec_dir` for the geometry source must be the **unsuffixed** directory. `:290`'s
  `"sections" if mk == "AF488" else f"sections_{mk}"` is **exactly inverted** for any
  other pair, so the default marker's whole grid renders blank.
- the index/excluded/summary tuple at `:235-239` must cover both markers, not the literal
  pair — today the first marker is reported `not_reformatted` for every section.
- `count_rois` at `:208` must find `roi_boxes_<marker>.csv` — today it probes only
  `roi_boxes_AF568.csv`/`roi_boxes_AF488.csv` plus the unsuffixed fallback, so `n_rois` is
  0 for every section and nothing ever reaches `status = "curated"`.

- [ ] **Step 2: Fix.** Replace the literal tuple with `for m in MARKERS:` and route every
path through `ls_paths` / `RF.marker_paths` / `04j.analysis_set_path`.

- [ ] **Step 3: Make `04p.load()` distinguish absent from empty** for the files it
requires, so a future miss is loud. Say why in a comment.

- [ ] **Step 4: Verify and commit.** Confirm the live study's `section_provenance.csv` is
unchanged — run in-process with output redirected and diff.

---

## Task 7: colour, part 1 — the model and the composite

**Files:** `scripts/ls_channels.py`, `scripts/ls_config.py`, `scripts/04o_section_rgb.py`,
`tests/test_composite.py`

- [ ] **Step 1: Write the failing test**

`tests/test_composite.py` gains:

- `marker_colours(LS_CFG) == {"AF568": (1,0,0), "AF488": (0,1,0)}` with **nothing
  declared** — the positional default.
- `display.colours: {"AF568": "green", "AF488": "red"}` swaps them.
- An unknown colour name and a malformed hex are refused with `ChannelError`.
- A colour declared for an undeclared marker is an error; a marker with no colour is a
  **warning**, not an error.
- **The bit-identity guarantee:** `04o.composite(mark, dapi, (1,0,0))` is
  `np.array_equal` to the plane assignment it replaces, for both LS markers. Bytes, not
  behaviour. The constants probe does not see pixels, so this is the only thing that pins it.

- [ ] **Step 2: Add to `ls_channels.py`**

```python
NAMED_COLOURS = {"red": (1.,0.,0.), "green": (0.,1.,0.), "blue": (0.,0.,1.),
                 "cyan": (0.,1.,1.), "magenta": (1.,0.,1.), "yellow": (1.,1.,0.),
                 "orange": (1.,.5,0.), "white": (1.,1.,1.), "grey": (.5,.5,.5)}

def parse_colour(value)      # name or "#rrggbb" -> (r,g,b), else ChannelError
def composite_order(cfg)     # display.composite, else declared marker order
def marker_colours(cfg)      # {marker: (r,g,b)} - THE source of truth
def nuclear_colour(cfg)      # default blue
def validate_display(cfg)    # (errors, warnings), called from ls_config.validate
```

`marker_colours` defaults positionally: index 0 → red, index 1 → green, index ≥2 → **no
colour** (absent from the map). A closed colour set, because the settings dialog needs a
choice widget and the generated docs need to list them; an arbitrary string is a typo that
renders black.

`marker_planes` becomes private `_default_planes`, used only by `marker_colours`.
`ls_config.validate` moves from `marker_planes(cfg)` to `validate_display(cfg)`.

- [ ] **Step 3: Two Keys in `ls_config.SPEC`**, beside `display.composite`:
`display.colours` (type `raw`, default `{}`) and `display.nuclear_colour` (type `str`,
default `"blue"`, `choices=sorted(NAMED_COLOURS)`). Their notes must say that an
uncoloured marker is **not drawn** and that both the composite stage and the curator say
so rather than picking one.

`display.composite` keeps its Key; narrow its doc to *which markers are shown, in order* —
and note that its order is what the positional colour default reads.

- [ ] **Step 4: `04o_section_rgb.py`**

```python
def composite(marker_img, dapi_img, colour, nuclear=(0., 0., 1.)):
    """One marker in its own colour, over the counterstain in its own.

    Per plane the two contributions are combined with MAX, not sum. For a marker
    with no blue in it - which is every marker this pipeline has ever had -
    max(0, dapi) is dapi exactly, so the blue plane is still the byte-for-byte
    greyscale the geometry was decided on and --verify still means what it meant.

    Where they DO share a plane - a magenta marker is red plus blue, and blue is
    the counterstain - max keeps both readable and never clips. Sum was the
    alternative: it makes overlap brighter, the conventional way to read
    co-localisation, but it saturates to 255 and then a very bright marker and a
    marker-over-counterstain look identical. This picture exists so somebody can
    judge whether a section is measurable, so not clipping wins.
    """
```

**Also fix the docstring's two-plane claim.** `04o` builds **one marker per run** and
writes into that marker's own `sections*_rgb/`; under paired a composite is one marker plus
the counterstain, never two markers. The current text describes the set across two runs,
which is how a reader comes to believe otherwise.

Reword the existing "not composited" message at `:223-236` for colours and name the fix:
`display.colours: {"<marker>": "magenta"}`.

- [ ] **Step 5: Regenerate and verify**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && work/appenv/Scripts/python.exe scripts/ls_config.py --write-example && work/appenv/Scripts/python.exe scripts/ls_config.py --docs docs/config-reference.md && work/appenv/Scripts/python.exe tests/test_composite.py && work/appenv/Scripts/python.exe tests/test_config_example.py && work/appenv/Scripts/python.exe scripts/ls_config.py --check && work/appenv/Scripts/python.exe tests/test_ls_regression.py
```

`--check` must show no errors on the live config **without editing it** — both Keys have
defaults. Confirm that by running it, not by assuming it.

- [ ] **Step 6: Commit.**

---

## Task 8: colour, part 2 — the Review pane

**Files:** `scripts/04l_roi_curator.py`, `tests/review.test.js`, new
`tests/test_review_colour.py`

- [ ] **Step 1: Write the Python oracle FIRST — it bites on today's code**

`tests/test_review_colour.py`, under `temp_study` with the colours **swapped**:

```python
with temp_study(acquisition={"layout": "paired", "markers": ["AF568", "AF488"]},
                display={"colours": {"AF568": "green", "AF488": "red"}}) as s:
```

Assert `04l.review_filters(...)` gives AF568 a matrix whose marker coefficients are
`(0,1,0)`. Today the page emits `revPerkDapi` — red — for AF568 whatever the config says,
so **this fails on the current code with only two markers**. Cheapest test that bites.

Write the expected matrix **from the specification**, not by calling the function under
test:

```python
def expected(colour, nuclear, lift):
    """What a filter over (m, m, d) has to be, restated from the definition of
    feColorMatrix rather than by calling the function under test. Input R is the
    marker plane in every source this pane loads; input B is the counterstain in
    _RGB.png and the marker again in _MARK.png - which is why the marker-only
    variant must never read input B, and why there is a pair per channel rather
    than one filter with a toggle (see the page's own note at :963-965)."""
    return [colour[0], 0, lift*nuclear[0], 0, 0,
            colour[1], 0, lift*nuclear[1], 0, 0,
            colour[2], 0, lift*nuclear[2], 0, 0,
            0, 0, 0, 1, 0]
```

Also pin:
- Under the **LS default (nothing declared)**, `review_filters` reproduces the four
  existing matrices character for character. That is the LS-unchanged guarantee.
- `review_filters(...)["byMarker"][m]`'s coefficients == `CH.marker_colours(cfg)[m]` ==
  the vector `04o` composites with, for every marker. **This assertion cannot be written
  against today's code at all**, because 04l has no colour concept — which is the point.
- A three-marker study with one hex colour and one uncoloured marker: three distinct
  filter pairs, and the uncoloured one resolves to `fallback` (white/grey), **not** to any
  real marker's filter.

- [ ] **Step 2: Add `review_filters()` to `04l`**

```python
DAPI_LIFT = 4

def review_filters(markers, colours, nuclear, lift=DAPI_LIFT):
    """The Review pane's colour filters, as DATA rather than as HTML.

    The arithmetic is here, in Python, beside the composite's - one rule, so the
    picture in the grid and the picture in the pane cannot disagree, which is the
    whole point of this change. The page installs them; it does not compute them.

    Returns {"byMarker": {marker: {"dapi": id, "only": id}},
             "defs":     [{"id": id, "values": "<20 numbers>"}],
             "dapiOnly": id, "blank": id, "lumAlpha": id,
             "fallback": {"dapi": id, "only": id}}

    `fallback` is grey, for a marker this study declared no colour for. Grey says
    "no colour set"; green would be the current bug, which is a marker silently
    borrowing another marker's colour.
    """
```

The coefficient on input **G is always 0** — G duplicates R in every source this pane
loads. Preserve that.

- [ ] **Step 3: Ship it through a new `__FILTERS__` token**

Data, not raw HTML, for two reasons — put both in a comment:
1. `IO.fill` JSON-encodes every value (`embed()` → `json.dumps`), so raw HTML cannot go
   through it, and a separate `str.replace` throws away `fill()`'s one-pass guarantee.
2. **Decisive:** `tests/run.sh` lifts only the largest `<script>` block, so filters written
   as HTML in `<defs>` are invisible to every JS suite. As data in the script they are
   directly assertable.

A short JS installer writes the `<filter>` elements into the existing hidden `<defs>`.

Add `colour` (the resolved name or hex) to the `__MARKERS__` entries.

- [ ] **Step 4: Replace the eight JS sites**

```js
const F = FILTERS.byMarker[p.marker] || FILTERS.fallback;
el("revImg").style.filter = "url(#" + (
      !REV.mark && !REV.dapi ? FILTERS.blank
    : !REV.mark              ? FILTERS.dapiOnly
    : REV.dapi               ? F.dapi
                             : F.only) + ")";
```

- `:4255` and `:4319` `marker === "AF568" ? "pERK" : "PCNA"` → the marker's `label` from
  `MARKERS`. **Note `:4255` interpolates unescaped** while its siblings use `esc()` — a
  config-derived label must be escaped.
- `:4337` `"pERK only"` → the **first** marker's label (the analysis-set concept is
  first-marker-only), not the current marker's.
- `:4442` → `M.label + (REV.mark ? " ✓" : "")`.
- `:4449` → `` `${M.label} ${M.colour}` ``, `"no colour set"` when there is none. **Line
  4453's `mk.replace(/ (red|green)$/, "")` breaks on any other colour word** — fix it too.

- [ ] **Step 5: Replace the mirror test in `tests/review.test.js`**

Lines 109-155 compute `isPerk = masked.marker === "AF568"` — the page's own rule restated,
so it agrees with the page whatever the page does. Replace with assertions against the
**data the page was built with**, with no marker literal:

```js
// NOT `masked.marker === "AF568"`. That was the page's own rule restated, so it
// agreed with the page whatever the page did - including when the page gave
// every marker green. The expectation now comes from the DATA the page was
// built with.
chk("every marker in the page has its own filter pair",
    Object.keys(X.FILTERS.byMarker).sort().join(","),
    X.MARKERS.map(m => m.id).sort().join(","));
chk("...and no two markers share one",
    new Set(X.MARKERS.map(m => X.FILTERS.byMarker[m.id].dapi)).size,
    X.MARKERS.length);
```

The "no two share one" guard is **inert under LS's two markers** — it passes for a correct
implementation and for a two-marker-only one. Say so in a comment; the Python oracle in
Step 1 is what actually bites.

- [ ] **Step 6: Also fix 04l's four Python guards**

`:498-500` `marker_paths` → delegate to `RF.marker_paths` (as `04o:180` and `04g:365`
already do). `:512` `if marker != "AF568"` → `!= MARKERS[0]`. `:4740` and `:4751`
`marker == "AF568"` → `== MARKERS[0]` — today `--analysis-set` and `--worklist` silently do
nothing for any other study, so the operator gets front-to-back order with no warning.
Delete the dead `PERK_MAP_CSV` at `:254`. Add the missing comment at `:253` pointing at
`04j.LEGACY_ANALYSIS_SET`.

- [ ] **Step 7: Verify and commit**

Build the page against the live config into the scratchpad and confirm the lifted script
is byte-identical apart from the new `FILTERS` constant and the `colour` field.

---

## Task 9: the sweeps

**Files:** `scripts/01g_saturation_map.py:271`, `scripts/04b_atlas_match.py:219`,
`scripts/01k_saturation_raw.py:138`, `scripts/04o_section_rgb.py:214`,
`scripts/06e_refresh_loop.py:132-141`, `scripts/04f_exclusion_candidates.py:198`,
`scripts/00c_channel_identity.py:261`, `analysis/roi_plots.R:35`,
`analysis/plot_roi_figures.R:77-78,93,370`, `analysis/plot_by_sample.R:42`,
`analysis/plot_by_slide.R:41`

- [ ] **Step 1: The two argparse defaults with NO choices at all**

`01g:271` and `04b:219` declare `--marker` with a bare string default and **no `choices=`**,
so argparse cannot validate them under any circumstances — they accept any string and run
to completion on an empty filter. `01g` then writes an empty `saturation_AF568.csv` which
`app/stages.py:266` declares as its output. Give both `choices=MARKERS` and a derived
default.

- [ ] **Step 2: `01k:138`** — `pool = [r for r in scenes if r["marker_channel"] == "AF568"]`
inside `native_sample()`. Empty for any other study, so the resolution-dilution factor
comes back as "no data" with no message. Use `MARKERS[0]`.

- [ ] **Step 3: `04o:214`** — `uid_col = "pcna_scene_uid" if args.marker == "AF488" else
"scene_uid"` → compare against `RF.DEFAULT_MARKER`, and take the column name from
`RF.marker_paths(marker)["uid_col"]`.

- [ ] **Step 4: `06e:132-141`** — the `["AF568"]` fallbacks and the ordering that puts the
watched marker first. The intent (documented at `:137-139`) silently degrades to
alphabetical for any other study. Use `MARKERS[0]`. `tests/test_refresh_loop.py` has
**zero** marker references today — `marker_list()` is entirely untested.

- [ ] **Step 5: `04f:198`** — `chan.get(r["id"], "AF488")` names a non-existent directory
for another study, so the section is silently dropped from the candidate list. Use the
default marker, or skip explicitly.

- [ ] **Step 6: `00c:261`** — `call = {clustered: "PCNA", other: "pERK"}`, and with
`--accept` it **writes those two antibody names into the operator's `config.json`**
`marker_identity` block for a study that measures neither. Derive from the study, or refuse
when the study has not declared what its markers are called.

- [ ] **Step 7: the R scripts** — `roi_plots.R:35`'s `Sys.getenv("LS_MARKER", "AF568")`
default, and the four `MARKER == "AF568"` branches deciding output names in
`plot_roi_figures.R:77-78,93,370`, `plot_by_sample.R:42`, `plot_by_slide.R:41`. The rule
should be "the first declared marker", not the literal. `roi_plots.R:36`'s
`MARKER_LABEL` map and `:53-64`'s legacy branch are **correct and commented** — leave them.

**These files carry the owner's uncommitted work.** Check `git status --short analysis/`
first; if they are still modified, **do not touch them** — report Step 7 as blocked and
finish the rest.

- [ ] **Step 8: Verify and commit.** `--help` on every changed stage; the constants probe.

---

## Task 10: widen `tests/test_marker_choices.py`

Its regex is `choices\s*=\s*[\[(][^\])]*["']AF\d+["']` — it sees only `choices=`, so by
construction it cannot catch Task 9's two offenders, which declare no choices at all.

- [ ] **Step 1:** Add a check that flags any `--marker` argument whose `default=` is a
string literal rather than a derived expression.

- [ ] **Step 2: Verify the guard bites.** Reintroduce `default="AF568"` into one stage,
run the suite, confirm it FAILS, revert. **A guard nobody has seen fail is not known to
work** — paste the actual red output in the report.

- [ ] **Step 3: Commit.**

---

## Task 11: `app/stages.py` — **BLOCKED**

**Do not start until this prints nothing:**

```bash
cd /c/Users/marti/repos/ls-ihc-pipeline && git status --short app/stages.py tests/test_stages.py
```

If it prints anything, **stop and report the task as still blocked.** Do not work around it
with `git add -p` — the point is that the owner has not decided what their change is yet.

When unblocked: add `{marker0}` / `{marker1}` tokens to `app/runner.py`'s existing
`_expand` (which already substitutes `{out_root}`, `{repo}`, `{scripts}` — `app/runner.py:120`
is a comment sitting exactly where this belongs). Then:

- 10 argv literals (`app/stages.py:363, 390, 397, 414, 423, 447, 454, 460, 466, 482`) —
  these now **fail loudly** since choices are derived, so they are the safe half.
- 12 `outputs=` literals (`:266, 364, 383, 391, 398, 405, 415, 424, 433, 448, 461, 521`) —
  these make `Stage.done()` permanently False, so an affected stage shows as never-run and
  every `needs=` chain hanging off it stays blocked.
- Extend `Stage.done()` so an output entry that is a **tuple** is satisfied when **any**
  member exists, and `Stage.missing()` reports the first (current) name. That is how the
  renamed artifacts from Tasks 4-5 keep their tick.

Stage **ids** and **titles** (`reformat_pcna`, `censor_perk`, `"04a  Reformat PCNA
sections"`) are referenced by `needs=` and `tests/test_stages.py`. Leave them opaque —
renaming them is a larger change and they are internal identifiers, not output.

---

## Self-review

**Coverage of the approved plan.** `ls_paths` → Task 1. The eight directory-rule copies →
Task 2. `05a.build`/`verify` → Task 3. `02`/`04i` → Task 4. `04m`/`04n` → Task 5. `04p` →
Task 6. Colour → Tasks 7-8. The sweeps → Task 9. The widened guard → Task 10.
`app/stages.py` → Task 11, blocked.

**Names used consistently.** `ls_paths.slug/geometry_source/Names/for_config/ARTIFACTS/
LEGACY/LEGACY_GROUPS`; `ls_channels.parse_colour/composite_order/marker_colours/
nuclear_colour/validate_display/NAMED_COLOURS`; `04l.review_filters/DAPI_LIFT`;
`04o.composite`; `ls_io.pick_column`.

**Ordering rationale.** Tasks 1-3 are the silent-wrong-output fixes and land first. Task 6
comes after Task 2 because 04p reads the directory rule. Task 8 comes after Task 7 because
the pane consumes the colour model. Task 9 is independent and could run any time.

**What this plan does not fix, and says so.** `04n` under `multiplex` still reads a
paired-shaped dataset — whether `section_provenance.csv` substitutes row-for-row needs the
two column sets compared directly, which has not been done. A per-marker colour picker in
the settings dialog needs a new widget kind, since `config_dialog._widget_for` builds one
widget per `Key` with no access to another key's value. And renaming
`04i_propagate_to_perk.py` → `04i_propagate_geometry.py` is recommended but out of scope
until the operator says so: it appears in 13 files, and a missed one is a loud
`FileNotFoundError`, never a silent wrong answer.

**The risk that remains.** A legacy fallback wrong in one of eight readers reads a file as
**empty**, not as an error. `04p.load()` and `04n`'s `.get()` are the two that fail
silently; both are given `pick_column` on the header, once, before the loop. That is the
specific mitigation, and Task 6 Step 3 makes a future miss loud.
