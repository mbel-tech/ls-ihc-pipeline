# Marker-POSITIVE nuclei per ROI, by treatment - one point per SLIDE.
#
# Switched from all DAPI nuclei to the positive subset at the operator's request
# on 2026-09-07, matching plot_by_sample.R and plot_roi_figures.R. The same
# caveat applies and is printed on the figure: the cut is per section, from that
# section's own background discs, and the rate is not absolute.
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

results <- results_dir(args)
xlsx <- file.path(results, "roi_dataset_by_slide.xlsx")

message(sprintf("reading %s [by_slide]", xlsx))
df <- load_sheet(xlsx, "by_slide")
message(sprintf("  %d rows, %d ROIs, %d slides from %d samples",
                nrow(df), nlevels(droplevels(df$ROI)),
                length(unique(df$slide)), length(unique(df$sample))))
report_n(df, "one point = one slide")

# Output names are suffixed for any marker but the first declared one, so a
# second marker's run writes beside these rather than over them. load_sheet
# has already filtered the sheet to MARKER; marker_suffix is in roi_plots.R.
out <- function(name) file.path(results, paste0(name, marker_suffix()))


plot_by_roi(df, "n_positive",
            bquote(.(marker_label())*"-positive nuclei counted"),
            paste(sprintf("%s-positive nuclei per ROI by treatment - one point per slide.",
                          marker_label()),
                  "\nRaw counts: not corrected for how much tissue was measured.",
                  "\nCut per section from its own background discs; not an absolute rate."),
            out("plot_positive_count_by_slide"), point_size = 2.1)

plot_by_roi(df, "positive_cells_per_mm2",
            bquote(.(marker_label())*"-positive"~(cells~per~mm^2)),
            paste(sprintf("%s-positive density per ROI by treatment - one point per slide.",
                          marker_label()),
                  "\nAbercrombie-corrected, area-normalised: the comparable one.",
                  "\nCut per section from its own background discs; not an absolute rate."),
            out("plot_positive_density_by_slide"), point_size = 2.1)
