# Marker-POSITIVE nuclei per ROI, by treatment - one point per SAMPLE.
#
# Switched from all DAPI nuclei to the positive subset at the operator's request
# on 2026-09-07, matching plot_roi_figures.R. `n_nuclei` and `cells_per_mm2` are
# still in the sheet; switching back is two column names.
#
# THE CUT IS PER SECTION, set from that section's own background discs, and the
# rate is NOT absolute - there is no no-primary control and no tERK channel in
# this dataset, so what these figures support is the comparison between arms,
# where the non-specific component is shared. The subtitle says so on the figure
# rather than only here.
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

# Output names are suffixed for any marker other than the pERK default, so a
# PCNA run writes beside these rather than over them. load_sheet has already
# filtered the sheet to MARKER.
out <- function(name) file.path(
  results, if (MARKER == "AF568") name else paste0(name, "_", MARKER))


# The requested figure: raw counts.
plot_by_roi(df, "n_positive",
            bquote(.(marker_label())*"-positive nuclei counted"),
            paste(sprintf("%s-positive nuclei per ROI by treatment - one point per sample.",
                          marker_label()),
                  "\nRaw counts: not corrected for how much tissue was measured.",
                  "\nCut per section from its own background discs; not an absolute rate."),
            out("plot_positive_count_by_sample"))

# The same figure on a comparable scale. A raw count rises with the number of
# discs and sections that happen to have been measured for that animal, and
# those differ several-fold here; density divides that out. Both are written so
# the difference between them can be seen rather than argued about.
plot_by_roi(df, "positive_cells_per_mm2",
            bquote(.(marker_label())*"-positive"~(cells~per~mm^2)),
            paste(sprintf("%s-positive density per ROI by treatment - one point per sample.",
                          marker_label()),
                  "\nAbercrombie-corrected, area-normalised: the comparable one.",
                  "\nCut per section from its own background discs; not an absolute rate."),
            out("plot_positive_density_by_sample"))
