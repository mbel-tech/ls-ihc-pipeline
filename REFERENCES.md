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

## Other tools named in the above, not yet evaluated

| | |
|---|---|
| **QUINT / QuickNII / VisuAlign** | Yates et al. (2019) *Front Neuroinform* 13:75. Mature rodent workflow for quantification and spatial analysis; VisuAlign provides user-guided non-linear refinement — the same propose-then-adjudicate shape used here. |
| **Spatial landmark detection** | Ekvall M (2024) *Nature Methods*. Higher precision, lower throughput than DeepSlice. |
| **AirLab** | Sandkühler et al. (2020). PyTorch registration library with GPU support, used by AnNoBrainer. |
| **Neural Best-Buddies** | Aberman et al. (2018) *ACM ToG* 37(4). Sparse cross-domain correspondence — finds semantically matching points **across imaging modalities**, which is precisely the DAPI-to-Nissl problem here. |
| **Allen Mouse Brain Atlas** | Lein et al. (2007) *Nature* 445:168–176. |
