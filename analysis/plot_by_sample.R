# Number of nuclei per ROI, by treatment - one point per SAMPLE.
#
# Reads results/roi_dataset.xlsx (sheet by_roi), written by
# scripts/06c_excel_dataset.py. One row there is one ROI in one animal, pooled
# over every section of that animal, so each point below is an animal.
#
# That is the unit the treatment comparison is actually made on: sections within
# an animal are not independent, so a figure with one point per section would
# show a sample size the design does not have.
#
# Run:  Rscript analysis/plot_by_sample.R
#       Rscript analysis/plot_by_sample.R D:/LS-analysis/results

args <- commandArgs(trailingOnly = TRUE)
here <- dirname(sub("^--file=", "",
                    grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(here, "roi_plots.R"))

results <- if (length(args) >= 1) args[1] else RESULTS_DEFAULT
xlsx <- file.path(results, "roi_dataset.xlsx")

message(sprintf("reading %s [by_roi]", xlsx))
df <- load_sheet(xlsx, "by_roi")
message(sprintf("  %d rows, %d ROIs, %d samples",
                nrow(df), nlevels(droplevels(df$ROI)), length(unique(df$sample))))
report_n(df, "one point = one sample")

# The requested figure: raw counts.
plot_by_roi(df, "n_nuclei", "nuclei counted",
            paste("Nuclei per ROI by treatment - one point per sample.",
                  "\nRaw counts: not corrected for how much tissue was measured."),
            file.path(results, "plot_nuclei_by_sample"))

# The same figure on a comparable scale. A raw count rises with the number of
# discs and sections that happen to have been measured for that animal, and
# those differ several-fold here; density divides that out. Both are written so
# the difference between them can be seen rather than argued about.
plot_by_roi(df, "cells_per_mm2", expression(cells~per~mm^2),
            paste("Density per ROI by treatment - one point per sample.",
                  "\nAbercrombie-corrected, area-normalised: the comparable one."),
            file.path(results, "plot_density_by_sample"))
