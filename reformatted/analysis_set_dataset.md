# `analysis_set_dataset.csv` — reading guide

One row per **pERK section that survived clipped-pixel censoring**: 454 rows,
11 animals, both channels side by side. Built by `scripts/04m_analysis_set_table.py`
from four upstream files so they do not have to be joined by hand.

Primary key is `scene_uid` — the **pERK (AF568)** section id. Not the PCNA one.

---

## Read this before using either rotation column

The pipeline stores a column called `manual_rotation` for both channels and
**they do not mean the same thing.** This file renames them so the difference
cannot be missed:

| column | who produced it | trust it as |
|---|---|---|
| `pcna_manual_rotation_deg` | **the operator**, by hand, in `04d_rotation_curator.py` | a human decision |
| `perk_derived_rotation_deg` | **a machine**, in `04i_propagate_to_perk.py` | an estimate |

The pERK scan is a separate acquisition with its own hand-drawn scan box, so it
gets a different automatic angle from `04a`. Curation therefore could not be
copied across — `04i` says so directly: *"Rotations must be re-derived, not
copied."* The pERK figure is the difference between the rotation its silhouette
alignment measured and `04a`'s automatic angle for that scan.

**They disagree on 420 of the 424 paired sections.** Reading one as the other is
a substantive error, not a cosmetic one.

If you want "the angles a human chose", use `pcna_manual_rotation_deg`
(413 of 424 paired rows are nonzero).

---

## Loading it

```python
import pandas as pd
df = pd.read_csv("reformatted/analysis_set_dataset.csv")

paired    = df[df.paired == 1]                      # 424 rows
confident = df[df.pair_confidence == "high"]        # 369 rows
```

To join against the ROI curator exports, match on `scene_uid` **and filter the
curator rows to the pERK channel**, since those files now carry a `marker`
column and a PCNA landmark is a different datum:

```python
roi = pd.read_csv("roi_plates.csv")
merged = df.merge(roi[roi.marker == "AF568"], on="scene_uid", how="left")
```

---

## Columns

**Identity**

| column | meaning |
|---|---|
| `scene_uid` | pERK section id — the primary key |
| `animal` | LS22, LS37, … (11 animals; LS53 contributes none) |
| `section_order` | serial position within the animal |
| `pcna_scene_uid` | the paired PCNA section, empty when unpaired |
| `paired` | 1 if a PCNA partner exists, else 0 |

**Geometry — PCNA side (operator)**

| column | meaning |
|---|---|
| `pcna_manual_rotation_deg` | the hand-entered correction, degrees |
| `pcna_manual_flip` | 0/1; is 0 throughout this dataset |
| `pcna_final_angle_deg` | total angle actually applied = automatic + manual, mod 360 |

**Geometry — pERK side (derived)**

| column | meaning |
|---|---|
| `perk_derived_rotation_deg` | machine-estimated correction; **not** an operator choice |
| `perk_manual_flip` | 0/1; is 0 throughout |
| `perk_final_angle_deg` | total angle applied to the pERK scan |

**Signal quality — pERK**

| column | meaning |
|---|---|
| `censored_fraction` | fraction of the frame at the sensor ceiling |
| `censored_fraction_in_tissue` | the same, restricted to tissue — the one that matters |
| `recorded_saturated_fraction` | as reported by the instrument |

All three are near zero by construction: this file contains only sections that
already passed the 1% censoring tolerance. Observed maxima are 0.0095, 0.0110
and 0.0095. **They are not a quality ranking within this set** — the sections
that had a clipping problem are the 264 already excluded, not these.

**Pairing quality**

| column | meaning |
|---|---|
| `pair_align_iou` | silhouette overlap between the two channels, 0–1 |
| `pair_flip_margin` | how decisively the unflipped orientation beat the flipped one |
| `pair_confidence` | `high` (369) or `low` (55) |

Measured: IoU spans 0.158 to 0.979, median 0.805. The two confidence classes
separate cleanly — median 0.833 for `high` against 0.470 for `low` — so
`pair_confidence` is a usable filter and `pair_align_iou` is worth eyeballing on
anything marked `low`.

---

## The 30 unpaired sections

`paired == 0` for 30 of the 454. They are absent from `perk_overrides.csv`
altogether — **never paired, rather than paired and then dropped**.

Two consequences, and the second is easy to miss:

1. Every PCNA column is empty for them, so they do not appear in the curator's
   PCNA view (`--marker AF488 --analysis-set` yields 424, not 454).
2. **They carry no rotation correction at all.** `perk_derived_rotation_deg` is
   exactly 0 for all 30, and for no other row — the zero set and the unpaired set
   are identical. Their `perk_final_angle_deg` is purely `04a`'s automatic angle,
   with nothing derived on top. Their orientation has never been checked against
   anything.

They are kept in the file rather than filtered out, so excluding them stays a
decision the reader makes. Spread across animals:

    LS105 4   LS120 7   LS136 4   LS138 0   LS22 2   LS37 5
    LS45  1   LS61  3   LS69  2   LS85  0   LS87  2

---

## Provenance

Regenerate with:

```bash
python scripts/04m_analysis_set_table.py
```

Sources: `perk_analysis_set.csv` (which rows, and the censoring columns),
`reformat_index_AF568.csv` and `reformat_index.csv` (geometry per channel),
`perk_overrides.csv` (the pairing and its quality).

## What this file does not tell you

- **No experimental group.** The study is still blinded; the key is joined only
  at the final step.
- **No ROI or region assignment.** That comes from the ROI curator exports
  (`roi_plates.csv`, `roi_landmarks.csv`, `roi_regions.csv`).
- **No signal measurement.** These are geometry and quality columns only.
- Per-animal counts are very uneven — LS85 contributes 3 sections against
  LS120's 70. Any per-animal summary needs to account for that, and the
  exclusion rate itself must be checked against experimental group at unblinding.
