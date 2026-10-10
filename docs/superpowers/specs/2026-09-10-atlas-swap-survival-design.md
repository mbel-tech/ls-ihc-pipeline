# Curation survives an atlas swap

2026-09-10

P2a of the replaceable-atlas sub-project. P2b (ingesting a different PDF) and P2c (PPT)
are separate specs and are deliberately not designed here.

## Why

A curated section records which atlas plate it sits on as **an integer index into a sorted
array**, not as a plate identity. `04q_import_curation.py:190` restores it with
`int(num(idx)) if idx else 0`, and `app/import_exports.py:177` — the second importer, a
deliberate mirror — does the same. The page then dereferences `PLATES[s.plate]` at fourteen
sites with no bounds check.

Swap the atlas and every one of those integers silently means a different plate.

**This has already happened once.** On 2026-09-06 the operator moved from `plates` to
`plates_final`. Both sets list exactly `plate_001`…`plate_064` with identical `image_file`
names, and **34 of 64 rows differ in geometry** while the images differ byte for byte. An
id-keyed restore would have succeeded and been wrong; an index-keyed restore was wrong in a
different way. Nothing anywhere reported a discrepancy.

Two smaller defects sit in the same code:

- `04l:5063` sorts the plate array with `key=lambda p: p["plate_id"]` — a **string** sort,
  correct only because this atlas zero-pads to three digits. An atlas numbering
  `plate_1`…`plate_100` orders `plate_1, plate_10, plate_100, plate_2` and every stored
  index means a different plate, with no error.
- `04l:5065`'s `if not os.path.exists(img): continue` **drops the plate and shifts every
  later index by one**. A single missing PNG silently renumbers the back half of the atlas.

And the plate set itself is resolved twice, differently. `04e`, `04k` and `04l` read
`CONFIG["atlas_plate_set"]["dir"]`; `04a_reformat:84`, `04b_atlas_match:64` and
`04c_atlas_match:99` hardcode `atlas/plates`. On this operator's drive the config says
`plates_final`, so **04b proposes matches against silhouettes of images the curator never
shows**, and `04a_reformat` reformats the wrong plate pictures.

**What is not at risk:** quantification. `plate_id` is empty on all 1,236 rows of
`roi_measurements.csv` and `05a` never writes it. An atlas swap does not move a single count
or density. This is a curation-integrity problem exclusively.

## Scope

**In:** making a stored plate assignment survive, or visibly fail, when the plate set
changes. **Out:** ingesting a new atlas (P2b/P2c), converting landmarks to fractional
coordinates, the broken `_reframe_proposals.json` link, and any change to how registration
computes a transform.

## Design

### 1. `scripts/ls_atlas.py` — plate identity in one place

A new module, the only thing in the tree that answers *which plate set* and *is this the
same plate*.

```python
set_dir(cfg)                  -> "plates_final"          # the one resolution
plate_dir(cfg)                -> "<out_root>/atlas/plates_final"
fingerprint(png_path)         -> "sha256:1f4a…"          # of the image bytes
fingerprints(set_dir)         -> {plate_id: digest}      # cached, see below
verify(stored, current)       -> OK | RESIZED | CHANGED | GONE
plate_order(rows)             -> rows, numeric-aware
```

**The fingerprint is the plate image's bytes** — a SHA-256 of the PNG file. Not the
geometry row, which is what `plates.csv` records about the *source page* and which two
different renderings of the same anatomy share; not the plate id, which the 09-06 swap
proved is reused across sets. The image is the thing the operator drew on.

Hashing 64 PNGs on every page build is not free, so `fingerprints()` caches to
`atlas/<set>/fingerprints.csv` (`plate_id,image_file,bytes,mtime,digest`) and re-hashes only
a plate whose size or mtime moved. The cache is derived data: delete it and it rebuilds.

`verify()` compares a stored `(plate_id, digest, px_w, px_h)` against the current set:

| Result | Condition |
|---|---|
| `OK` | id present, digest equal |
| `RESIZED` | id present, digest differs, aspect ratio equal within 1% |
| `CHANGED` | id present, digest differs, aspect ratio differs |
| `GONE` | id absent from the current set |

`RESIZED` is the re-render case: same plate, new dimensions. `CHANGED` is the 09-06 case:
same id, genuinely different picture.

`plate_order()` sorts on the trailing integer of `plate_id` when every id has one, and falls
back to a plain string sort when they do not — so `plate_1 … plate_100` orders correctly and
an atlas with non-numeric ids still orders deterministically.

### 2. What curation stores

`roi_plates.csv` — the export both importers read — gains three columns:

| Column | Meaning |
|---|---|
| `plate_set` | the set the assignment was made against (`plates_final`) |
| `plate_fp` | the fingerprint of the plate image at the time of assignment |
| `plate_px` | the plate image's `WxH` at the time of assignment, e.g. `1089x643` |
| `plate_verified` | `1`, or a reason: `resized`, `changed`, `gone`, `by_index` |

`plate_px` exists solely so §3's rescale has an old dimension to divide by. Once the plate
image has changed, the current set can no longer tell you what size it used to be.

`plate_index` **stays in the export** and stays written. It is not the key any more; it is a
record of what the array looked like, and the last-resort fallback for a file exported before
this change.

The page's own state (`localStorage`, and `curation/ls_roi_curator_v1.json`) stores
`plate_id` and `plate_fp` alongside the existing integer, so a session saved mid-curation
survives the same way an export does.

### 3. Restoring: one rule, two importers

`04q_import_curation.py` and `app/import_exports.py` are deliberate mirrors — the P1.4 work
established that fixing one and not the other is how the 3× coordinate displacement survived.
They get **one shared implementation** in `ls_atlas`, called from both.

The rule, in order:

1. `plate_id` present and `verify()` says `OK` → restore, `plate_verified = 1`.
2. `plate_id` present, `RESIZED` → restore, rescale that section's landmark plate
   coordinates by the size ratio, `plate_verified = resized`.
3. `plate_id` present, `CHANGED` or `GONE` → **restore the assignment anyway**, mark it
   `changed` / `gone`, and withhold its landmarks from registration until confirmed.
4. No `plate_id`, `plate_index` present → restore by index, mark `by_index`.
5. Neither → unassigned, as today.

**Nothing is discarded and nothing is silently trusted.** The operator sees what they chose;
the tool refuses to compute on it until they say it is still right.

The rescale in step 2 uses `plate_x`/`plate_y` scaled by `new_px_w / old_px_w`, the old width read from `plate_px`.
Sections whose landmarks were rescaled are marked for review rather than accepted, because a
re-render can crop as well as scale and the ratio cannot tell the two apart.

### 4. What the operator sees

On load, the page counts sections by verification state and shows a banner when any is not
`1`:

> **12 sections need re-confirming.** 9 plates changed, 3 were re-rendered at a new size.
> Their landmarks are not being used until you confirm each one.

An unverified section carries a marker in the section list and in its header. Confirming is
one click and sets `plate_verified = 1` with the current fingerprint. A section left
unconfirmed exports with its reason intact, so the state survives a round trip rather than
being laundered by the next export.

`04k_level_curator.py:181`'s level anchors are `uid -> plate index` and get the same
treatment: anchors resolve by id, and an anchor that fails verification is dropped from the
monotonic constraint rather than silently anchoring to a different level.

### 5. The plate set, resolved once

`04a_reformat:84`, `04b_atlas_match:64` and `04c_atlas_match:99` call `ls_atlas.plate_dir()`
instead of hardcoding `atlas/plates`; `04e`, `04k` and `04l` delegate their existing
`CONFIG.get("atlas_plate_set", …)` line to the same function. `04a_atlas_extract`,
`04a2_atlas_remerge` and `04a4_plate_rebuild` keep their fixed output directories — they are
the producers of the sets, not consumers of the choice.

**This changes 04b's and 04c's output on this study**, because they currently match against
the wrong images. That is the fix, not a regression, and it is the one behaviour change in
this spec that is not bit-identical. It is stated here so it is not discovered as a surprise.

## Testing

The blocking gap: **there is no atlas fixture anywhere.** `tests/_fixture.py:63` creates a
zero-byte `atlas.pdf`, so no stage that opens an atlas has ever been exercised by a test.

`tests/_atlas_fixture.py` builds two plate sets with PIL, `before` and `after`, four plates each:

| plate | after |
|---|---|
| `plate_001` | byte-identical → `OK` |
| `plate_002` | same image at 1.5× → `RESIZED` |
| `plate_003` | re-cropped, same id, new aspect → `CHANGED` |
| `plate_004` | absent → `GONE` |

That is exactly the shape of the 2026-09-06 swap, at four plates instead of sixty-four.

`tests/test_ls_atlas.py` covers `verify()`'s four outcomes, `plate_order()` on padded,
unpadded and non-numeric ids, and the fingerprint cache invalidating on mtime and on size.

`tests/test_import_curation.py:72,221` **currently pins the bug**: it supplies
`plate_id: "plate_010"` with `plate_index: "9"` — deliberately disagreeing — and asserts
`state["A_s01a_sc00"]["plate"] == 9`, the index. Those rows and that assertion are rewritten
to assert the id wins and the index is the fallback. Rewritten, not deleted: the surrounding
cases (`assigned`, the 3× frame scale, the background-disc recovery) are load-bearing and
stay exactly as they are.

The curator page suites in `tests/run.sh` get a bounds case: `PLATES[s.plate]` with a stored
index past the end of a shorter array must not throw and must not render a wrong plate.

**Unchanged-for-LS guarantees, as tests:**

- `plate_order()` over the live 64-row `plates.csv` returns the identical order to today's
  string sort.
- Importing the operator's Sep 7 export against `plates_final` verifies every assigned
  section as `OK` — the fingerprints match because that is the set they were drawn on.
- `06a` and `06c` in-process over the live `roi_nuclei.csv` are byte-identical, as always.

## Risks

- **The operator's authoritative curation is not in the file a migration would target.**
  `curation/ls_roi_curator_v1.json` is dated Sep 3, has 288 sections and **zero polygons**;
  the real work — 612 polygons over 138 sections — is in the browser's `localStorage` and in
  `D:\LS-analysis\reformatted\roi_regions_used_AF568.csv`. The design deliberately makes
  the *importers* the migration path, so anything that loads gets upgraded. **Export before
  changing the atlas** is the operating instruction, and it should be in the banner.
- **A first load after this lands will mark sections unverified** for any section whose
  stored assignment predates fingerprints — every existing one. Step 4 handles that: an
  export with no `plate_fp` restores by index and is marked `by_index`, which is honest
  about what it is. The alternative — fingerprinting on first load and calling it verified —
  would launder exactly the 09-06 failure into a green tick.
- **`verify()`'s `RESIZED` test uses aspect ratio**, which cannot distinguish a rescale from
  a symmetric crop. That is why rescaled landmarks are flagged rather than accepted.
- **04b and 04c change output on this study.** See §5.
- **Not fixed here:** `04c_atlas_match.py` is a second, older matcher that overlaps `04b`;
  whether it should exist at all is a separate question and is not touched beyond §5.
