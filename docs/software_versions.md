| Software | Version | What it does here |
|---|---|---|
| Python | 3.13.15 | the interpreter every stage runs under |
| pylibCZIrw | 6.1.0 | reads every CZI pixel whose value reaches a result |
| czifile | 2026.8.16 | raw per-tile pixels, for instrument characterisation only |
| imagecodecs | 2026.8.16 | JPEG-XR decoding, required by czifile |
| NumPy | 2.5.2 | arrays, the affine algebra, the mask lookups |
| SciPy | 1.18.1 | rotation, filtering, optimal assignment |
| pandas | 3.0.5 | tabular joins in the dataset stages |
| Pillow | 12.3.0 | image resizing in the reformat and its inverse |
| scikit-image | 0.26.0 | per-object measurement (regionprops) |
| StarDist | 0.9.2 | nucleus segmentation |
| csbdeep | 0.8.2 | percentile intensity normalisation before segmentation |
| TensorFlow | 2.21.0 | the neural-network backend StarDist runs on |
| Keras | 3.15.1 | model API above TensorFlow |
| PyMuPDF | 1.28.2 | atlas plate and region-seed extraction from the PDF |
| itk-elastix | 0.25.4 | affine and B-spline registration (assessed, QC only) |
| OpenCV | 5.0.0.93 | connected components and morphology |
| tifffile | 2026.8.23 | TIFF interchange with Fiji |
| matplotlib | 3.11.1 | QC figures and the workflow diagram |
| openpyxl | 3.1.5 | the output workbooks |
| PySide6 | 6.11.2 | the desktop application shell |
| R | 4.6.0 | the statistics and figure layer |
| ggplot2 (R) | 4.0.3 | the figures |
| ggtext (R) | 0.1.2 | rich-text axis and panel labels |
| lme4 (R) | 2.0.1 | mixed models where an animal contributes more than one row |
| lmerTest (R) | 3.2.1 | degrees of freedom and p-values for those models |
| emmeans (R) | 2.0.3 | estimated marginal means and contrasts |
| multcomp (R) | 1.4.30 | multiplicity adjustment across contrasts |
| officer (R) | 0.7.4 | writing the figure deck |
| readxl (R) | 1.4.5 | reading the workbooks back in |
