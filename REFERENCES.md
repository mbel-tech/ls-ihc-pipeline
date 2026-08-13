# References

Prior work consulted for this pipeline, what was taken from each, and what could not be.

The recurring constraint: **every existing tool targets the mouse Allen CCF.** No digital atlas
exists for a salmonid, so their *registration targets* are unusable here while their *methods*
transfer directly. Each entry below separates the two.

---

## AnNoBrainer

> Peter R, Hrobar P, Navratil J, Vagenknecht M, Soukup J, Tsuji K, Barrezueta NX, Stoll AC,
> Gentzel RC, Sugam JA, Marcus J, Bitton DA (2024). **AnNoBrainer, An Automated Annotation of
> Mouse Brain Images using Deep Learning.** *Neuroinformatics* 22(4):719–730.
> doi:[10.1007/s12021-024-09679-1](https://doi.org/10.1007/s12021-024-09679-1) ·
> [github.com/Merck/AnNoBrainer](https://github.com/Merck/AnNoBrainer) (MIT)

The closest match to this project's problem: it is explicitly built for slides carrying **many
brains that each need separate annotation**.

**Adopted / convergent**
- **Hungarian assignment** to link detected brains to an experimental metadata grid. This
  pipeline independently arrived at the same tool (`scipy.optimize.linear_sum_assignment`) for
  cross-marker section pairing in `02_pair_passes.py` — convergence worth noting.
- **Multi-brain detection on one slide** via mask R-CNN, including a class for handwritten notes
  so slide annotations are rejected rather than measured. Directly applicable to the
  multi-section scenes found here.
- **Deep classifier for atlas-layer matching**, benchmarked at 59% exact / 86% ±1 / 94% ±2
  (EfficientNet-B0, beating ResNet-34). Sets a realistic target: **exact-match is not the
  standard; ±1–2 layers is.**
- **Affine then elastic registration with a landmark regularisation term**, where landmark
  disagreement locally relaxes the smoothness penalty. Solves the specific problem of sections
  cut off-perpendicular, which produces hemispheres that cannot both align under uniform
  regularisation.

**Directly validates two findings here**
- *"Certain IHC staining techniques such as **DAPI are unlikely to result in high quality
  registration due to data sparsity or poor morphological correspondence with the H&E staining**
  used in the Allen brain atlas."* This is exactly the DAPI-section → Nissl-plate mismatch
  measured in `04b_atlas_match.py`, where silhouette IoU tops out near 0.51. The limitation is
  documented in the literature, not a defect in this implementation.
- Expert-versus-expert agreement on annotation quality gave **Kappa 0.17** ("slight"), rising to
  only 0.38 when collapsed to useful/not-useful. Two trained neuroscientists disagree about brain
  annotation. That is the strongest available argument for the propose-then-adjudicate design
  used here, and for not treating any single expert pass as ground truth.

**Not usable:** Allen CCF templates and the layer classifier, both mouse-only. Their classifier
is also restricted to the z-range it was trained on (CP region).

---

## DeepSlice

> Carey H, Pegios M, Martin L, Saleeba C, Turner AJ, Everett NA, Bjerke IE, Puchades MA,
> Bjaalie JG, McMullan S (2023). **DeepSlice: rapid fully automatic registration of mouse brain
> imaging to a volumetric atlas.** *Nature Communications* 14:5884.
> doi:[10.1038/s41467-023-41645-4](https://doi.org/10.1038/s41467-023-41645-4) ·
> [github.com/PolarBean/DeepSlice](https://github.com/PolarBean/DeepSlice) · DeepSlice.org

**Adopted**
- **Synthetic training data generated from the template itself.** They rendered ~920k virtual
  sections through the Allen volumes at real and stochastically sampled cutting angles, with
  added noise, pixel drop-out and warping. This is the answer to having only 101 salmon atlas
  plates and no labelled sections: augment the plates into a training set rather than hand-label
  thousands of reals.
- **Training-set decontamination by loss.** They ran the whole training set through a prototype
  model, sorted by MSE, and cut at the inflection point where error grew exponentially —
  discovering that many "ground truth" alignments were themselves wrong.
- **Wisdom-of-the-crowd ground truth**: seven operators of varying experience, averaged. Given
  the Kappa of 0.17 above, a single annotator's pass is not ground truth.
- **Ordering as post-processing**, which this pipeline implements as the monotonic dynamic
  program in `04b_atlas_match.py`.

**Validates a finding here:** DeepSlice *"tends to underperform on tissue in which
neuroanatomical landmarks are obscured (e.g. low background staining, very high or very low
signal contrast)."* That describes the AF568 channel measured here — contrast inverted on 93% of
2,572 sections.

**Not usable:** the trained model regresses Allen CCF anchoring vectors. Mouse-only, and no
retraining path without a volumetric salmonid atlas.

---

## BrainJ

> Hammond L. **Automated Imaging and BrainJ Analysis Pipeline** (guide v9.3). Cellular Imaging
> Platform. ImageJ/Fiji plugin.

The most transferable of the three, because its early steps are atlas-independent and it runs in
Fiji, which is already installed here.

**Adopted**
- **Section reformatting before anything else**: each section *centred and rotated horizontal in
  the frame, with surrounding tissue and debris removed*. This pipeline's silhouette matching
  compares raw scan regions, which is why an orientation search was needed at all. Normalising
  first is the better fix and should improve matching materially.
- **Montage and stack preview to check section integrity, ordering and orientation** before
  analysis — the same role as the contact sheets here, confirming the design.
- **Explicit section-flipper step**: *"if sections have been floating during immunolabelling then
  some may require flipping horizontally."* Free-floating IHC sections land either face up or
  face down. This pipeline's dihedral search assumed one global orientation; per-section flips
  are a real and separate phenomenon.
- **DAPI accepted as a counterstain channel** for reconstruction, alongside NeuroTrace and NeuN —
  a useful counterpoint to AnNoBrainer's DAPI caveat, which concerned registration *to an H&E
  atlas* specifically.
- **Elastix** for registration and **Ilastik** for pixel-classification-based cell detection.
  Elastix is a stronger candidate than bUnwarpJ: scriptable, standard, and used by both BrainJ
  and (via AirLab equivalents) AnNoBrainer. Ilastik matters here because there is no local CUDA.

**Not usable:** the atlas analysis stages target the Allen CCF. BrainJ also requires
*consecutive intact sections* for 3D reconstruction, which this dataset does not guarantee.

---

## Automated FISH and IHC image analysis (review)

> Theodosiou Z, Kasampalidis IN, Livanos G, Zervakis M, Pitas I, Lyroudia K (2007).
> **Automated analysis of FISH and immunohistochemistry images: A review.**
> *Cytometry Part A* 71A(7):439–450.

Background and framing rather than method. Its conclusion is the governing principle of the
curation design used here: automated analysis is increasingly capable, but **"manual intervention
is still necessary in order to resolve particularly challenging or ambiguous cases"**, and
large-scale validation is required before such systems can be trusted unsupervised.

Also relevant: its account of how subjective manual IHC scoring is, which is the reason this
pipeline keeps every judgement auditable and every threshold explicit rather than per-image.

---

## Immunofluorescence normalisation — UniFORM

> Wang K, Ait-Ahmad K, Kupp S, Sims Z, Cramer E, Sayar Z, Yu J, Wong MH, Mills GB, Eksi SE,
> Chang YH (2025). **Toward universal immunofluorescence normalization for multiplex tissue
> imaging with UniFORM.** *Cell Reports Methods* 5(9):101172.
> https://doi.org/10.1016/j.crmeth.2025.101172 ·
> [github.com/kunlunW/UniFORM](https://github.com/kunlunW/UniFORM)

Normalises marker intensity by **aligning the negative population** — the leftmost mode of the
log-intensity histogram, inferred without any phenotyping — across samples, by maximum
cross-correlation. Non-parametric, works at feature and pixel level, Python, open source.

**Directly relevant to the hardest open problem here.** This project has no tERK channel and no
negative control, so the plan falls back on DAPI density and a reference region. UniFORM supplies a
third internal reference and a better-founded one: **the non-expressing population within each
image is the control**. Its critique of the alternatives lands on this dataset specifically —
mean division "relies on the arithmetic mean, which can be unstable in right-skewed, heterogeneous
marker distributions", and Z score / ComBat assume symmetry that fluorescence does not have.

Its consequence also matches a principle already in the plan: once distributions are aligned, **one
uniform gating threshold works across the whole dataset**, removing the per-sample thresholds this
pipeline has refused to use since Stage 1.

**Two reasons it cannot simply be run here.**

*It corrects a multiplicative factor, and the problem measured on AF568 is not multiplicative.*
UniFORM applies linear normalisation factors — a shift in log space — and its own limitations
section notes this suits IF but not chromogenic assays. Testing the AF568 batch split here on
**clip-free sections only**, the two apparent groups turn out to be nearly identical: background
10,844 vs 12,300, tissue 5,542 vs 5,494, tissue/background 0.52 vs 0.50. The 1.86x gap seen across
all sections is an artefact of **ceiling clipping**, not a gain difference. There is no
multiplicative factor to remove.

*It needs raw intensities.* The overviews here are 8-bit with per-section display ranging applied,
which destroys exactly the cross-section comparability UniFORM operates on. It belongs at Stage 5/6
on 16-bit data, not on the overview PNGs.

**Adopted as method, deferred as software:** normalise by aligning the negative population rather
than dividing by a mean, and apply it to raw per-object intensities once detection exists.

---

## Immunofluorescence artifact QC — QUALIFAI

> Andhari MD, Rinaldi G, Nazari P, Vets J, Shankar G, Dubroja N, Ostyn T, Vanmechelen M,
> Decraene B, Arnould A, Mestdagh W, De Moor B, De Smet F, Bosisio F, Antoranz A (2024).
> **Quality control of immunofluorescence images using artificial intelligence.**
> *Cell Reports Physical Science* 5(10):102220. https://doi.org/10.1016/j.xcrp.2024.102220
> [github.com/TCWO/QualIFAI](https://github.com/TCWO/QualIFAI) — code and pretrained models

**The closest match to this dataset of anything evaluated here**, and the reason is one line of
their Table 1: the MILAN training set was acquired on a **Zeiss Axioscan Z1 at 0.65 µm/px**. That
is this study's acquisition — same instrument class, same pixel size, same modality. Every other
tool assessed either targets brightfield or targets the mouse Allen CCF.

Five artifact classes, each a separate binary model: **out-of-focus areas, air bubbles, tissue
folds, external artifacts** (dust, hair, fibres) **and antibody aggregates**. Two-tier — classify
the tile, then segment it with U-Net if positive. >90% classification accuracy; segmentation IoU
0.65–0.82 across platforms. 512 px tiles, 20 px overlap, q99 normalisation, ImageNet-pretrained
backbones with the last four layers unfrozen, 7,508 tiles annotated by active learning.

**Two design choices worth copying regardless of whether the tool is run.**

*Channel-agnostic vs channel-specific.* Bubbles, folds, external artifacts and OOF were annotated
**on DAPI only**, because they affect every channel identically. Antibody aggregates were annotated
per affected channel, because they do not. That is the correct split for this project too: the
curation here is deliberately done on DAPI, blinded to marker, and aggregates are the one class
that cannot be.

*Binary models over one multiclass model*, because the classes have genuinely different character —
external artifacts are easy on intensity alone, OOF is subjective and magnification-dependent.
The same reasoning applies to `04f_exclusion_candidates.py` keeping `no_tissue` and `out_of_focus`
as separate rules rather than one exclusion score.

**Contradicts Jurgas et al. on generalisation.** Jurgas report their model *"does not generalize
well to a new dataset"*; QUALIFAI reports consistent accuracy and IoU **across three technologies
at 0.22, 0.37 and 0.65 µm/px**. Their stated caveat is narrower: *"acquisition technologies not
included in our study might require fine-tuning"* — and this acquisition is effectively one of the
included ones. The unaddressed risk is species: all three datasets are human, though brain is
among the tissues.

**The result that bears on the analysis plan, not just the QC.** On a 10-core DLBCL TMA, removing
artifacts changed the cytotoxic-T-cell fraction by **46.28%** in an affected core, against a
maximum of 10.12% in unaffected ones. More importantly, **cells outside the artifact areas changed
label too** — artifact-inflated intensities skew normalisation, which shifts the expression space,
which shifts clustering. This project's primary readouts are DAPI-normalised and reference-region
metrics; those are precisely the machinery an artifact corrupts *globally* rather than locally. It
is an argument for masking artifacts before normalising, not after.

**Measured on this dataset before deciding:** in a random sample of 250 sections, **91% carry at
least one bright, compact, texture-free object** inside the tissue — median 3 per section, up to
15, median 0.028 mm² total. Present at 68–100% in all twelve animals, so not obviously a
group-specific confound, but that must be re-checked at unblinding. These sit *inside* otherwise
good tissue, so the geometric rules in `04f` cannot touch them; they are a detection-stage quality
mask problem, not a section-exclusion one.

**Cost of actually running it:** Keras/TensorFlow, which this stack does not have, and roughly
730,000 tiles of 512 px at 0.65 µm/px for 1,381 sections. Infeasible on this CPU; a Colab GPU job,
which is what Stage 5b already earmarks Colab for.

---

## Slice-to-atlas registration tools

Three tools aimed at the problem this project has not solved: assigning each section an atlas level
and propagating regions onto it. **None can be run against the salmon atlas**, and one of them was
tested here and fails on this data for a measurable reason.

### SHARCQ — Lauridsen et al. 2022

> Lauridsen K, Ly A, Prévost ED, McNulty C, McGovern DJ, Tay JW, Dragavon J, Root DH (2022).
> **A semi-automated workflow for brain slice histology alignment, registration, and cell
> quantification (SHARCQ).** *eNeuro* 9(2):ENEURO.0483-21.2022.
> [github.com/wildrootlab/SHARCQ](https://github.com/wildrootlab/SHARCQ)

MATLAB GUI derived from SHARP-Track. Allen Brain Atlas or the digitised Franklin-Paxinos atlas.

**The important thing about it is what it does *not* automate.** The user "must scroll to the
correct AP coordinate and DV/ML tilt" by eye, then press `t` and click **numbered corresponding
points** between the Slice Viewer and the Atlas Viewer; points can be added or deleted until the
overlay looks right. What SHARCQ automates is the landmark **registration**, the warping of the
cell-location matrix through the same transform (`Warp_ROI.m`), and the per-region cell counts.

So the published, peer-reviewed tool for exactly this task **selects the matching atlas slice
manually**. That is worth stating plainly: automatic level assignment is not the standard here, and
this project's failure to achieve it is not unusual.

**Adoptable:** the workflow shape - assign the plate, place a few corresponding landmarks, warp the
atlas regions onto the section, count within them. Not the code: MATLAB, and bound to a 3D rodent
atlas we do not have an equivalent of.

### giRAff — Piluso et al. 2024

> Piluso S, Souedet N, Jan C, Hérard A-S, et al. (2024). **giRAff: an automated atlas segmentation
> tool adapted to single histological slices.** *Frontiers in Neuroscience* 17:1230814.

Estimates a single slice's z-position in the atlas volume by registering it against every candidate
template slice with **linear registration by Block Matching using a cross-correlation similarity**
metric, then taking the optimum. Explicitly designed for single slices without anatomical context -
our situation - and runs in about a minute per slice.

**Tested on this data, and it does not work.** giRAff differs from `04c` in scoring *registered
image intensity* rather than silhouette overlap, so it was the one real untested idea. Built a
regional cell-density map per section (rim eroded, interior re-stretched, smoothed to suppress
pixel noise) and per plate, scored by normalised cross-correlation, and measured the same rank
correlation between serial order and best-matching plate that condemned `04c`:

| animal | n | direct | inverted |
|---|---|---|---|
| LS45 | 87 | −0.18 | −0.06 |
| LS120 | 68 | 0.00 | −0.11 |
| LS22 | 60 | −0.02 | 0.09 |

Against `04c`'s silhouette figures of −0.05, 0.00, 0.17, −0.04. **No improvement, in either
polarity.** Interior intensity carries no more level information here than shape does.

Two reasons, both visible in `qc/atlasmatch/interior_structure.png`: the interior *does* carry real
architecture - the periventricular cell layer is clear - but it is contaminated by the **uncorrected
tile mosaic grid**, a strong periodic pattern identical in every section; and DAPI at 5.20 µm/px
does not resolve the lamination the Nissl plates show. Making giRAff's approach viable would need
the tile flat-field fixed (unresolved since Stage 1) and re-extraction at 0.65-1.3 µm/px.

### DeepSlice — already assessed

See below. A CNN trained on ~920k virtual mouse sections rendered from a **volumetric** template.
There is no salmon volume to render from - the atlas here is 101 discrete plates from a book - so
there is no training set to build, before considering that the network is mouse-specific.

---

## Brain symmetry-axis detection

Three papers, all aimed at finding the mid-sagittal / midline axis. **Only the shape-based idea
survived measurement on this dataset**, and the reason is a property of the data worth recording.

### Wu et al. 2013 — SIFT-pair matching and Hough voting

> Wu H, Wang D, Shi L, Wen Z, Ming Z (2013). **Fast and robust symmetry detection for brain images
> based on parallel scale-invariant feature transform matching and voting.**
> *International Journal of Imaging Systems and Technology* 23(4):314–326.
> https://doi.org/10.1002/ima.22066

SIFT keypoints are detected in a single image and matched *against each other* using a symmetric
similarity metric that combines relative scale, mirrored orientation (a reflection about a line at
angle α maps a gradient at φ to 2α − φ) and the **flipped descriptor**. Each accepted pair votes in
a Hough space for the perpendicular bisector of the segment joining it; the accumulator peak is the
axis. Reported accuracy on MRI: polar angle error within 0.69°.

**Implemented in full here** — including the 128-bin reindexing that mirrors a SIFT descriptor
(4×4 spatial cells → column-flipped, 8 orientation bins → negated). Measured against synthetic
ground truth on 24 sections: **median error 24.1°, 12% of sections within 5°.** Unusable.

**Why it fails, which is not an implementation detail.** The method assumes local image features
have genuine mirror counterparts. In MRI they do. In DAPI fluorescence at 5.20 µm/px the internal
texture is nuclear speckle — an individual nucleus on the left has no mirror twin on the right,
because cellular detail is not bilaterally symmetric even though the anatomy is. There is nothing
to match.

Confirmed independently by scoring the *same* candidate axes two ways: intensity normalised
cross-correlation put 59% of sections within 2°, shape overlap put 91%. **Bilateral symmetry in
this data lives in shape and gross anatomy, not in local image features.**

### Wu et al. 2021 — 2-channel CNN patch similarity

> Wu H, Chen X, Li P, Wen Z (2021). **Automatic symmetry detection from brain MRI based on a
> 2-channel convolutional neural network.** *IEEE Transactions on Cybernetics.*

Replaces the hand-designed similarity metric with a CNN trained to judge whether two brain patches
(Poisson-sampled from the slice) are mirror images, then scores and ranks candidate axes. Evaluated
on 2,166 synthetic and real MR slices.

**Not attempted, and the reason is the measurement above rather than the cost.** It is a better
similarity metric for patch pairs — but the 2013 result shows the mirrored-patch signal is not
present in this data, so a better metric has nothing to measure. It would also need a GPU (none
here) and salmonid training data (none exists).

### Willemse et al. 2020 — local symmetry in FIJI

> Willemse J, van der Vaart M, Yang W, Briegel A (2020). **Mathematical mirroring for
> identification of local symmetry centers in microscopic images: local symmetry detection in
> FIJI.** *Microscopy and Microanalysis* 26(5):978–987.

An interactive FIJI plugin that assigns a **local** symmetry score to every pixel, so the
*symmetry centres of small objects* can be thresholded out — demonstrated on bacterial
chemoreceptor arrays and vesicle trafficking. The authors note it is the first such method easily
usable from ImageJ/FIJI.

**Different problem.** This is point symmetry of many small structures, not one global reflection
axis per section. Its transferable trick — combining the reflection axes of a square (0/45/90/135°)
for cheap coverage in all directions — is unnecessary once the search is restricted to a narrow
residual range around an existing estimate.

**What was implemented instead** (`04h_symmetry_axis.py`): direct reflective symmetry of the tissue
*shape*. For each candidate angle, rotate so that angle would be vertical, mirror left-right, slide
the mirror over a range of offsets, keep the best overlap. Restricted to ±30° because `04a` has
already put the midline approximately vertical — searching the full 180° produced ~90° failures on
a third of sections, since a roughly elliptical section is also near-symmetric about its long axis.
Held-out synthetic validation over three samples of 28 sections: **median error 0.20–0.45°, 86–96%
within 5°.**

---

## Artifact-detection codebases assessed

### DIAGNijmegen / pathology-artifact-detection

> [github.com/DIAGNijmegen/pathology-artifact-detection](https://github.com/DIAGNijmegen/pathology-artifact-detection)
> Radboud UMC Diagnostic Image Analysis Group.

Multi-class semantic segmentation of six artifact types — tissue folds, ink, dust, air bubbles,
marker, out-of-focus — with DeepLabV3+ and an EfficientNet-B2 encoder. 142 slides, 3,278
annotations, four scanner manufacturers.

**Adopted: the working resolution.** It runs at **4.0 µm/px** in 1024 px tiles with 256 px overlap.
That is the single most useful fact in the repository, because this project's overviews are already
at **5.20 µm/px** — essentially the same scale. Artifact detection does not need full resolution,
so `04g_artifact_mask.py` runs on PNGs that already exist rather than re-reading ~730,000 tiles
from the CZIs. That is the difference between a Colab job and a ten-minute local run.

**Not adopted: the model.** Trained on brightfield H&E and chromogenic IHC (CD3, CD45RO, CD8, PAS,
CK20), and it requires an 11 GB GPU, 2 CPUs and 48 GB RAM. This dataset is fluorescence and this
machine has 11.8 GB of system RAM and no CUDA.

### IAWG-CSBC-PSON / hack2022-01-artifacts

> [github.com/IAWG-CSBC-PSON/hack2022-01-artifacts](https://github.com/IAWG-CSBC-PSON/hack2022-01-artifacts)
> Hackathon challenge, CyCIF multiplex immunofluorescence, 40 channels over 8 rounds.

**A challenge repository, not a method** — it ships `roc.py` and `pr.py` for scoring submissions
and reports no results. So there is nothing to implement from it, and it should not be cited as a
technique.

Two things are still worth taking. Its artifact vocabulary is the only one of the three that names
**"uneven immunolabeling"** and **"fluorescence aberration"** as classes in their own right — and
the AF568 contrast inversion measured across all twelve animals here is precisely an
uneven-immunolabelling problem, not a bubble or a fold. It belongs in the methods as a named
artifact rather than an unexplained oddity.

Second, it scores artifacts **per detected cell**, from features already computed for other
purposes — integrated intensity, nuclear morphology, position — rather than from a separate
pixel-level model. That is the cheap route for Stage 5: once cells are detected, an artifact score
per object costs almost nothing.

---

## Whole-slide-image artifact QC

> Jurgas A, Wodzinski M, D'Amato M, van der Laak J, Atzori M, Müller H (2024).
> **Improving quality control of whole slide images by explicit artifact augmentation.**
> *Scientific Reports* 14:17847. https://doi.org/10.1038/s41598-024-68667-2
> [github.com/Jarartur/HistopathologyAugmentationResearch](https://github.com/Jarartur/HistopathologyAugmentationResearch)

**Adopted: the artifact taxonomy, not the method.** The paper's six standard WSI artifact classes
are *air* (bubbles), *dust* (debris), *tissue* (folds), *ink*, *marker*, and *focus*. Four of the
six exist in this dataset; ink and marker do not, because those are chromogenic/brightfield
problems and these are fluorescence scans.

Reading that list is what prompted checking **focus** as an exclusion class separate from tissue
amount — `04f_exclusion_candidates.py` had only a "not enough tissue" rule. The check found **51
sections, up to 54 mm² of tissue each, with no resolvable nuclear detail**, every one of which the
area rule was keeping and would have sent to cell counting. The taxonomy earned its place by
naming a failure mode that was being missed.

**Not adopted: the augmentation pipeline or the released weights.** Three reasons, in order of
weight:

1. **Modality.** The method blends annotated artifacts into H&E and chromogenic IHC — RGB
   brightfield. Reinhard colour normalisation for ink transfer, stain-invariant segmentation and
   a ResNet50 over colour patches all assume colour. This dataset is 16-bit fluorescence, one
   channel at a time, on black.
2. **Their own generalisation result.** Table 3 reports that the model *"does not generalize well
   to a new dataset"*, with the lack of significance confirmed by Wilcoxon tests. Taking the
   released weights and running them on salmonid fluorescence would be a much larger domain shift
   than the one that already failed.
3. **Cost against benefit.** Reported gains are 0.01–0.10 AUROC, they used A100s, and this machine
   has no CUDA. The geometric rules here already flag 154 of 1,381 sections with a montage that
   can be checked in minutes.

**Corroborates a method already in use.** Synthesising training data by transforming a small
annotated set is the same principle taken from DeepSlice for the atlas-plate variant bank in
`04c_atlas_match.py`. Two independent groups reaching for it is worth noting in the methods.

---

## Other tools named in the above, not yet evaluated

| | |
|---|---|
| **QUINT / QuickNII / VisuAlign** | Yates et al. (2019) *Front Neuroinform* 13:75. Mature rodent workflow for quantification and spatial analysis; VisuAlign provides user-guided non-linear refinement — the same propose-then-adjudicate shape used here. |
| **Spatial landmark detection** | Ekvall M (2024) *Nature Methods*. Higher precision, lower throughput than DeepSlice. |
| **AirLab** | Sandkühler et al. (2020). PyTorch registration library with GPU support, used by AnNoBrainer. |
| **Neural Best-Buddies** | Aberman et al. (2018) *ACM ToG* 37(4). Sparse cross-domain correspondence — finds semantically matching points **across imaging modalities**, which is precisely the DAPI-to-Nissl problem here. |
| **Allen Mouse Brain Atlas** | Lein et al. (2007) *Nature* 445:168–176. |
