# `perk_sections_dataset.csv` — reading guide

Every pERK section in the study — **1191 rows, 12 animals, 29 columns** — each
joined to its PCNA partner, with what happened to it and why. Built by
`scripts/04m_sections_dataset.py`.

Primary key is `scene_uid`, the **pERK (AF568)** section id. Not the PCNA one.

Rejected sections are in here rather than in a separate file on purpose. The
exclusion rate varies a great deal by animal, that variation is itself a result,
and it has to be checked against experimental group at unblinding — which is easy
to forget entirely if the rejects live somewhere else.

---

## `status` — the three fates

| status | n | meaning |
|---|---|---|
| `analysis_set` | 454 | measurable |
| `censored_out` | 264 | reformatted, then failed the 1% clipped-pixel tolerance |
| `excluded` | 473 | never reformatted; operator or measurement rejected it |

```python
import pandas as pd
df = pd.read_csv("reformatted/perk_sections_dataset.csv")
df[df.status == "analysis_set"]        # the 454 the ROI curator loads
```

### Per animal

| animal | total | analysis | censored | excluded | excl % |
|---|---:|---:|---:|---:|---:|
| LS105 | 108 | 28 | 40 | 40 | 37.0 |
| LS120 | 107 | 70 | 0 | 37 | 34.6 |
| LS136 | 101 | 27 | 23 | 51 | 50.5 |
| LS138 | 94 | 16 | 37 | 41 | 43.6 |
| LS22 | 102 | 62 | 0 | 40 | 39.2 |
| LS37 | 117 | 67 | 18 | 32 | 27.4 |
| LS45 | 117 | 55 | 25 | 37 | 31.6 |
| LS53 | 21 | **0** | 13 | 8 | 38.1 |
| LS61 | 100 | 53 | 0 | 47 | 47.0 |
| LS69 | 108 | 24 | 41 | 43 | 39.8 |
| LS85 | 110 | **3** | 65 | 42 | 38.2 |
| LS87 | 106 | 49 | 2 | 55 | 51.9 |

**Read the `censored` column before doing anything with per-animal counts.** It
is not noise and it is not evenly spread: LS120, LS22 and LS61 lose *nothing* to
censoring, while LS85 loses 65 of 110 and LS69 41 of 108. That is the clipping
problem, and it splits the animals into two groups on an axis that has nothing to
do with biology. **An apparent two-group effect in pERK intensity is the expected
artefact of this pattern, not a finding.** Any comparison has to be made at
matched levels between sections of comparable censoring, and the censoring
pattern itself has to be checked against experimental group at unblinding.

`LS53` contributes **no** measurable sections and `LS85` contributes 3. Neither
can support a per-animal estimate.

---

## Read this before using either rotation column

The pipeline stores a column called `manual_rotation` for both channels and
**they are not the same kind of value.** This file renames them so it cannot be
missed:

| column | who produced it | trust it as |
|---|---|---|
| `pcna_manual_rotation_deg` | **the operator**, by hand, in `04d_rotation_curator.py` | a human decision |
| `perk_derived_rotation_deg` | **a machine**, in `04i_propagate_to_perk.py` | an estimate |

The pERK scan is a separate acquisition with its own hand-drawn scan box, so it
gets a different automatic angle from `04a` and curation could not be copied
across. `04i` says so directly: *"Rotations must be re-derived, not copied."*

**They disagree on 420 of the 424 paired analysis-set sections.** For "the angles
a human chose", use `pcna_manual_rotation_deg` — 413 of those 424 are nonzero.

---

## `paired` and `pcna_kept` are different questions

| column | asks |
|---|---|
| `paired` | was a PCNA partner ever recorded for this section? (1134 of 1191) |
| `pcna_kept` | did that partner survive PCNA curation? (661 of 1191) |

An excluded section is normally `paired=1, pcna_kept=0` — it has a partner, and
that partner is exactly why it was excluded. Collapsing the two would read every
exclusion as a pairing failure.

The PCNA-side geometry columns are populated only when `pcna_kept=1`, since an
excluded PCNA section was never reformatted and has no angle.

---

## Columns

**Identity** — from `manifest_scenes.csv`, the only source covering rejected
sections. Complete on every row.

`scene_uid`, `animal`, `slide`, `variant`, `scene_index`, `section_order`

**Disposition**

| column | meaning |
|---|---|
| `status` | `analysis_set` / `censored_out` / `excluded` |
| `exclusion_class` | `tissue_damaged` (350), `no_tissue` (82), `out_of_focus` (41); empty unless excluded |
| `disposition_reason` | the verbatim reason — exclusion reason, or the censoring one; empty for `analysis_set` |

For excluded rows the reason is the **PCNA** one, followed through the pairing.
The pERK-side reason is always "PCNA partner excluded by the operator", which
records nothing useful.

**Pairing**

`pcna_scene_uid`, `paired`, `pcna_kept`, `pair_align_iou`, `pair_flip_margin`,
`pair_confidence`

Measured: IoU spans 0.158–0.979, median 0.785 over 661 rows; `pair_confidence` is
`high` on 574 and `low` on 87. Worth eyeballing anything marked `low`.

**Geometry** — empty where the section was never reformatted

`pcna_manual_rotation_deg`, `pcna_manual_flip`, `pcna_final_angle_deg`
`perk_derived_rotation_deg`, `perk_manual_flip`, `perk_final_angle_deg`

`*_final_angle_deg` is the total angle actually applied (automatic + correction,
mod 360). Both flip columns are 0 throughout.

**pERK signal quality** — populated for the 718 reformatted rows

`censored_fraction`, `censored_fraction_in_tissue`, `recorded_saturated_fraction`

`censored_fraction_in_tissue` is the one that matters. Within `analysis_set` all
three are near zero by construction — those rows already passed the 1% tolerance,
so they are **not** a quality ranking within that subset. The interesting values
are on the `censored_out` rows.

**PCNA tissue QC**

`qc_source`, `pcna_focus_score`, `pcna_largest_piece_mm2`,
`pcna_total_tissue_mm2`, `pcna_n_pieces`

Focus spans 0.028–0.511 (median 0.219, n=702); largest piece 0.07–64.89 mm²
(median 21.79, n=743).

### `qc_source` — where those numbers came from

| value | n | meaning |
|---|---:|---|
| `exclusion_candidates` | 661 | measured directly, all four columns present |
| `reason_string` | 123 | recovered from the rejection reason; only the one relevant column |
| *(empty)* | 407 | no measurement survives |

`exclusion_candidates.csv` was regenerated against the *curated* set, so it only
describes sections that survived. For a rejected section the number embedded in
its reason string — "focus 0.061", "larger than 0.30 mm2" — is the only surviving
record, so it is parsed back out. The 407 blanks are mostly the 350
`tissue_damaged` rows, where the judgement was visual and no number was ever
taken. **Do not compare a `reason_string` focus value against an
`exclusion_candidates` one without noticing you are doing it** — the first is a
below-threshold value from a rejected section, the second a passing one.

---

## The 30 unpaired analysis-set sections

Within `status == "analysis_set"`, 30 rows have `paired = 0` — absent from
`perk_overrides.csv` altogether, never paired rather than paired-and-dropped.
Two consequences, and the second is easy to miss:

1. Every PCNA column is empty, so they do not appear in the curator's PCNA view
   (`--marker AF488 --analysis-set` yields 424, not 454).
2. **They carry no rotation correction at all.** `perk_derived_rotation_deg` is
   exactly 0 for all 30 and for no other analysis-set row — the zero set and the
   unpaired set are identical. Their final angle is purely `04a`'s automatic one,
   never checked against anything.

They are kept rather than filtered, so excluding them stays your decision.

---

## Provenance

```bash
python scripts/04m_sections_dataset.py
```

Sources: `manifest_scenes.csv` (identity), `reformat_index_AF568.csv` and
`reformat_index.csv` (geometry), `excluded_sections*.csv` (rejections),
`perk_analysis_set.csv` (censoring), `perk_overrides.csv` (pairing),
`exclusion_candidates.csv` (tissue QC).

The script fails loudly if a section appears as both kept and excluded, or if a
uid is missing from the manifest.

## What this file does not contain

- **No experimental group.** The study is still blinded; the key is joined only
  at the final step. The per-animal exclusion and censoring rates above must be
  checked against group at that point.
- **No ROI or region assignment** — that is in the ROI curator exports
  (`roi_plates.csv`, `roi_landmarks.csv`, `roi_regions.csv`). Join on `scene_uid`
  and filter those to `marker == "AF568"`.
- **No signal measurement.** Geometry and quality only.
