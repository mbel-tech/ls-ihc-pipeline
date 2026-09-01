# Number of nuclei per ROI, by treatment - one point per SLIDE.
#
# Reads results/roi_dataset_by_slide.xlsx (sheet by_slide), written by
# scripts/06d_excel_by_slide.py. One row there is one ROI on one slide, so an
# animal contributes several points per region and the within-animal spread is
# visible instead of averaged away.
#
# Read it as a picture of variability, NOT as a bigger sample. Slides from one
# animal are not independent replicates of the treatment - the animal is the
# experimental unit - so the extra points sharpen the description without adding
# a single degree of freedom to the comparison. plot_by_sample.R draws the unit
# the contrast is actually made on.
#
# Run:  Rscript analysis/plot_by_slide.R
#       Rscript analysis/plot_by_slide.R D:/LS-analysis/results

args <- commandArgs(trailingOnly = TRUE)
here <- dirname(sub("^--file=", "",
                    grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(here, "roi_plots.R"))

results <- if (length(args) >= 1) args[1] else RESULTS_DEFAULT
xlsx <- file.path(results, "roi_dataset_by_slide.xlsx")

message(sprintf("reading %s [by_slide]", xlsx))
df <- load_sheet(xlsx, "by_slide")
message(sprintf("  %d rows, %d ROIs, %d slides from %d samples",
                nrow(df), nlevels(droplevels(df$ROI)),
                length(unique(df$slide)), length(unique(df$sample))))
report_n(df, "one point = one slide")

# Output names are suffixed for any marker other than the pERK default, so a
# PCNA run writes beside these rather than over them. load_sheet has already
# filtered the sheet to MARKER.
out <- function(name) file.path(
  results, if (MARKER == "AF568") name else paste0(name, "_", MARKER))


plot_by_roi(df, "n_nuclei", "nuclei counted",
            paste("Nuclei per ROI by treatment - one point per slide.",
                  "\nRaw counts: not corrected for how much tissue was measured."),
            out("plot_nuclei_by_slide"), point_size = 2.1)

plot_by_roi(df, "cells_per_mm2", expression(cells~per~mm^2),
            paste("Density per ROI by treatment - one point per slide.",
                  "\nAbercrombie-corrected, area-normalised: the comparable one."),
            out("plot_density_by_slide"), point_size = 2.1)
