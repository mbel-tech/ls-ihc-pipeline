---
title: "ROI Curator"
subtitle: "Assigning atlas plates and placing region landmarks on salmon brain sections"
date: "26 August 2026"
lang: en-GB
---

# What this tool is for

Every section in this study has to be matched to an **atlas plate**, and the
atlas's **region seeds** have to be placed onto the tissue so that pERK and PCNA
signal can be counted per region.

The ROI curator is where that is done by hand. It shows one section beside one
atlas plate, you tell it which plate the section is and where a handful of
matching points are, and it warps the atlas regions onto the section from those
points.

The matching is deliberately **not** automatic. Automatic level assignment was
measured twice on this data and failed both times — silhouette IoU correlated
with serial order at −0.05 to 0.17, and registered-intensity cross-correlation
at −0.18 to +0.09. The published tool for this task (SHARCQ) also has the
operator pick the plate by eye, so this does too. What is automated is the
registration, the warping, and the export.

```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```

# The window at a glance

![The curator with a section loaded, its atlas plate beside it, and the section strip along the bottom](img/01_overview.png)

Four regions, and each does one job:

| Region | What it is |
|---|---|
| **Toolbar** (top) | Filters on the left, actions on the right |
| **Section pane** (left) | The section you are working on. You click here |
| **Atlas plate pane** (middle) | The plate you are matching to. Numbered seeds |
| **Sidebar** (right) | Which section, which plate, landmarks, fit quality |
| **Strip** (bottom) | Every section in the current view, colour-coded by state |

# The toolbar

![Filters left, actions right](img/02_header.png)

The header is split so that **what narrows the view sits by the sample selector**
and **what acts on a section sits by Export**.

## Filters (left)

| Control | Effect |
|---|---|
| **Animal** | Which fish. Twelve of them |
| **Channel** | `pERK` (454 worklist sections), `PCNA` (788), or `both channels` (1242) |
| **favourites only** | Show only the sections you flagged for quantification |
| **hide excluded** | Hide rejected sections from the strip |

**pERK and PCNA are independent.** They are separate physical sections cut at
different times. The tool is shared; no judgement crosses between them. Nothing
you decide about a pERK section reaches its PCNA partner, and every export row
records the channel it was made on.

`hide excluded` is a **view, not a deletion**. Hidden sections keep their flag,
still appear in the excluded count, and are still written to `roi_plates.csv`
with `excluded=1`.

## Counters

`shown · registered · plate only · no ROI · favourite · excluded · pairs on this
section`, then the autosave clock (`saved 14:31:26`).

```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```

# The workflow

## 1. Find the plate

Scrub the **PLATE** slider in the sidebar, or press `←` / `→`,
until the plate matches the section. Only some plates carry region seeds; the
sidebar tells you which regions a plate has.

Press **Assign plate** (`a`) to record the plate as a deliberate
decision. This matters: a plate assignment is a judgement in its own right, and
is exported even if you place no landmarks at all.

## 2. Turn on Guided

![Guided mode: seed 1 is the target, ringed in green. Every seed carries its number](img/03_guided_target.png)

Press **Guided** (`g`). The plate's seeds are numbered in a **fixed
order** — down each column, columns left to right — so seed 4 is always the same
seed, in the tool, in every export, and on a re-run.

The order follows the anatomy: the left lateral arc first, then the medial strip
on the left of the midline, then the medial strip on the right, then the right
lateral arc. Consecutive numbers stay within one structure instead of jumping
across the brain.

The **current target** is ringed in green. Seeds you have already placed go
hollow, so progress down the plate is visible without reading anything.

## 3. Place each seed with one click

Click on the section where that seed belongs. One click makes the whole pair —
the plate half comes from the seed itself, so it is exact rather than eyeballed.
The cursor then advances to the next seed.

| Situation | What to do |
|---|---|
| The seed is not on this section | **Skip seed** (`s`) |
| You want to go back, or jump ahead | Click that seed on the plate to re-aim |
| You misplaced one | **Undo point** (`z`) — the cursor follows back |

Leaving a section and returning **resumes where you left off**. The cursor is
worked out from the pairs already placed, so it always points at the first gap.

## 4. Size the landmark as you place it

![Press, drag out to set the radius, release to place](img/08_sizing.png)

A landmark is a position **and a radius**. Press where the point is, drag out to
the size you want, and release. The readout shows the radius live. A plain click
without dragging keeps the default, so nothing is slower than it was.

The size is asked for at the moment of placing because that is when it is known —
sizing afterwards would mean finding the landmark again and remembering which one
it was.

```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```

## 5. Check the overlay, not the number

![Three landmarks placed; all 27 atlas seeds warped onto the tissue and numbered](img/04_section_overlay.png)

From **three pairs** the atlas regions are warped live onto the section in their
atlas colours. **This overlay is the check that matters, not the residual.**

The seeds on the section carry the **same numbers as the plate**, so you can say
"seed 17 landed in the wrong place" and both panes agree on what that means.

| Landmarks | Transform |
|---|---|
| 3–5 | Affine. The residual per landmark is meaningful |
| 6 or more | Thin-plate spline. Residual is 0 by construction |

# Rotating the view

![The rotate tool mid-drag, showing the tilt in degrees](img/07_rotate.png)

Press **Rotate**, then drag left or right on the section. Hold `shift`
for fine control. **The tilt is saved the moment you release** and stays with
that section. **Restore original tilt** (`r`) puts it back.

Rotation is a **viewing aid and nothing else**. Every stored coordinate stays in
the unrotated frame, so all three exports are identical whether you turned the
section or not. The angle rides along in `roi_plates.csv` as `view_rotation_deg`
for provenance.

```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```

# Per-section decisions

| Button | Key | Meaning |
|---|---|---|
| **Favourite** | `f` | This section is in the subset you will quantify. Orthogonal to everything else — a section can be worth quantifying before anyone has landmarked it |
| **No ROI here** | — | This section carries no region of interest |
| **Exclude** | `x` | Reject the section. A judgement in its own right, and exported as one |
| **DAPI** | — | Show or hide the blue counterstain, leaving the marker channel alone |

# Reading the strip

![Section thumbnails, colour-coded by what has been decided about them](img/06_strip.png)

| Appearance | State |
|---|---|
| Purple border | Registered — 3 or more landmarks |
| Blue border | Plate assigned only |
| Gold inner edge | Favourite |
| Red border, greyed | Excluded |
| Faded | Marked "no ROI" |

`↑` / `↓` move between sections; **the plate stays put**, which
is what makes working through a run of neighbouring sections quick.

# The sidebar

![Section identity, plate slider, landmark residuals and the warped-region summary](img/05_sidebar.png)

The **LANDMARKS** card lists each pair with its residual, so a mis-clicked pair
shows up as a large error instead of quietly dragging the whole fit. The
**REGIONS WARPED** card names the regions the current plate will contribute.

```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```

# Keyboard shortcuts

| Key | Action | | Key | Action |
|---|---|---|---|---|
| `←` `→` | Previous / next plate | | `a` | Assign plate |
| `↑` `↓` | Previous / next section | | `f` | Favourite |
| `g` | Guided mode on/off | | `x` | Exclude section |
| `s` | Skip the current seed | | `z` | Undo point |
| `r` | Restore original tilt | | `shift` | Fine rotation while dragging |

# Saving

Your work is written to browser storage **on every change** — there is no save
button and nothing is waiting on a timer.

On top of that, once a minute the tool writes a **rolling snapshot** under a
second key, and shows `saved HH:MM:SS` in the header. That snapshot is a recovery
point: if the live state goes wrong, `roiRestoreBackup()` in the browser console
rolls back to it, confirming the timestamp and section count first. It is
deliberately not a button, because it replaces everything currently in the tool.

Two things to know:

- Storage is **per browser and per machine**. Clearing site data takes both copies.
- The snapshot is at most a minute old. **Export is what commits your work to
  disk**; autosave is a safety net under it, not a replacement.

```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```

# What Export writes

Three files, because there are three different decisions and collapsing them
loses one.

## `roi_plates.csv` — one row per decided section

`scene_uid, animal, marker, subset, section_order, plate_set, plate_id,
plate_index, plate_has_seeds, n_landmarks, transform, status, favorite,
view_rotation_deg, excluded`

A section appears here if anything was decided about it — assigned, favourited or
excluded — even with no landmarks.

## `roi_landmarks.csv` — one row per pair

`scene_uid, animal, marker, section_order, plate_set, plate_id, pair, sec_x,
sec_y, sec_r, plate_x, plate_y, residual_px, seed_n, seed_region`

`seed_n` and `seed_region` say whether the landmark was placed against a numbered
atlas seed, and which one. **Blank means it was free-clicked.**

## `roi_regions.csv` — one row per warped seed

`scene_uid, animal, marker, plate_set, plate_id, region, region_ambiguous,
ambiguity_group, region_uncertain_in_atlas, sec_x, sec_y, n_landmarks,
transform, mean_residual_px`

All coordinates are in **canonical reformatted-frame pixels** (the 256 grid), the
same frame the masks and every other reformatted product live in — regardless of
what resolution was on screen.

# Things worth knowing

## A guided landmark is an assertion, not a measurement

When you place a landmark against a seed, you are stating where that region is.
The warp then reproduces your statement at that point exactly — a thin-plate
spline interpolates its landmarks with zero residual by construction — so **the
residual is not an independent check on a guided pair**.

Seeds you did *not* click are still atlas-derived, interpolated from the ones you
did, and those are the rows the atlas is actually doing work for. This is why
every landmark records the seed it came from: which method produced a number
stays recoverable instead of being lost in the mean.

## Two different kinds of uncertainty

All 356 atlas seeds carry a region name; none are blank. **The overwhelming
majority name a distinct place and are not qualified by anything** — Dl and Dm in
particular are separate regions in separate locations, and nothing in the tool
treats them as interchangeable.

Two groups *are* qualified, for two different reasons:

| | Seeds | Why |
|---|---|---|
| `region_ambiguous` | 42 | **Vd / Vv / POA** cannot be told apart without knowing the section's rostrocaudal level, so the group is shown rather than a name the data cannot support. Drawn in gold |
| `region_uncertain_in_atlas` | 8 | The **atlas itself** labels these `"Rm (Raphe) ??"`. Shown with a trailing `?` |

A seed can carry either, both, or neither, and they are exported in separate
columns. The specific region name is always kept alongside.

Everything outside those two groups — **Dl, Dm, Vl, Vs, Vc, the tuberal
regions** — is reported as itself, with `region_ambiguous = 0`. In the sidebar
only the ambiguous entry is drawn in gold, so the caveat applies to the one entry
it names and not to the list around it.

## Free correspondence is still available

With Guided off, the original two-click flow works as before: click a point on
the section, then the matching point on the plate. Those landmarks carry no seed
number and no region — they are arbitrary correspondence points, which is exactly
what you want when the useful matching feature is not a region centre.

---

*Generated from the live tool. Screenshots are of animal LS105, section 53,
matched to `plate_011`.*
