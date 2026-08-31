# One figure per ROI: density by treatment, at both levels, corrected and raw.
#
# Reads both workbooks and writes results/ROI_plots/<ROI>.png, one per region.
#
# Each figure has two panels - per SAMPLE and per SLIDE - and inside each panel
# every treatment carries two scatters:
#
#   fully opaque   cells_per_mm2      Abercrombie-corrected
#   50% opacity    profiles_per_mm2   raw counts / area
#
# The two panels share a y axis on purpose. It is the same quantity in the same
# units, and a fixed scale is what makes "the slide points scatter wider than
# the sample points" legible at all; free scales would hide the one comparison
# the two panels exist to show.
#
# Read the corrected layer. Sections here are consecutive at 14 um, so a nucleus
# cut by the section boundary appears in both, and both datasets pool across
# sections - the raw layer counts those twice. It is drawn because the size of
# the correction is worth seeing per region, not because it is the answer.
#
# Run:  Rscript analysis/plot_roi_figures.R
#       Rscript analysis/plot_roi_figures.R D:/LS-analysis/results

args <- commandArgs(trailingOnly = TRUE)
here <- dirname(sub("^--file=", "",
                    grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(here, "roi_plots.R"))

results <- if (length(args) >= 1) args[1] else RESULTS_DEFAULT
outdir <- file.path(results, "ROI_plots")

CORRECTED <- "cells_per_mm2"      # Abercrombie applied
RAW       <- "profiles_per_mm2"   # counts / area

# Nudge the two measures apart inside each treatment slot as well as separating
# them by opacity. Two clouds of one hue at 1.0 and 0.5 alpha are genuinely hard
# to tell apart where the correction is small; the x position still means the
# treatment. Set to 0 to stack them exactly.
DODGE <- 0.34

message(sprintf("reading %s", results))
samp <- load_sheet(file.path(results, "roi_dataset.xlsx"), "by_roi")
slide <- load_sheet(file.path(results, "roi_dataset_by_slide.xlsx"), "by_slide")
message(sprintf("  per sample: %d rows, %d samples", nrow(samp),
                length(unique(samp$sample))))
message(sprintf("  per slide : %d rows, %d slides", nrow(slide),
                length(unique(slide$slide))))

# One long frame: level x measure. Built by rbind rather than pivoting, because
# the two sheets have different key columns and only these five are wanted.
stack_level <- function(df, level) {
  do.call(rbind, lapply(
    list(c(CORRECTED, "Abercrombie-corrected"), c(RAW, "raw counts / area")),
    function(m) data.frame(
      ROI = as.character(df$ROI), treatment = df$treatment,
      level = level, measure = m[2], value = suppressWarnings(as.numeric(df[[m[1]]])),
      stringsAsFactors = FALSE)))
}
long <- rbind(stack_level(samp, "per sample"), stack_level(slide, "per slide"))
long <- long[is.finite(long$value), ]
long$level <- factor(long$level, levels = c("per sample", "per slide"))
long$measure <- factor(long$measure,
                       levels = c("Abercrombie-corrected", "raw counts / area"))

report_n(samp, "one point = one sample")

# "Overwrite the past set" means the SET. A region that stops appearing between
# runs would otherwise leave a stale figure sitting there looking current. The
# PNGs go, not the directory - deleting a folder someone has open in Explorer
# fails on Windows.
dir.create(outdir, showWarnings = FALSE, recursive = TRUE)
old <- list.files(outdir, pattern = "\\.png$", full.names = TRUE)
if (length(old)) {
  file.remove(old)
  message(sprintf("\n  cleared %d old figure%s from %s",
                  length(old), if (length(old) == 1) "" else "s", outdir))
}

# Dl is fine as a filename; "Anterior tuberal nucleus" is not.
safe_name <- function(x) gsub("^_+|_+$", "", gsub("[^A-Za-z0-9]+", "_", x))

rois <- levels(droplevels(factor(long$ROI, levels = levels(samp$ROI))))
message(sprintf("\n  writing %d figures to %s", length(rois), outdir))

for (roi in rois) {
  d <- long[long$ROI == roi, ]
  if (!nrow(d)) next

  n_samp <- sum(d$level == "per sample" & d$measure == "Abercrombie-corrected")
  n_slide <- sum(d$level == "per slide" & d$measure == "Abercrombie-corrected")

  p <- ggplot(d, aes(x = treatment, y = value,
                     colour = treatment, alpha = measure, group = measure)) +
    geom_point(position = position_jitterdodge(jitter.width = 0.12,
                                               dodge.width = DODGE,
                                               seed = 1),
               size = 2.6) +
    facet_wrap(~ level) +
    scale_colour_manual(values = TREATMENT_COLOURS, drop = FALSE,
                        guide = guide_legend(order = 1)) +
    scale_alpha_manual(values = c("Abercrombie-corrected" = 1,
                                  "raw counts / area" = 0.5),
                       drop = FALSE,
                       guide = guide_legend(order = 2,
                                            override.aes = list(size = 3.2))) +
    expand_limits(y = 0) +
    labs(title = roi, x = NULL, y = expression(density~(per~mm^2)),
         colour = NULL, alpha = NULL,
         subtitle = sprintf("%d sample%s, %d slide%s - opaque is corrected",
                            n_samp, if (n_samp == 1) "" else "s",
                            n_slide, if (n_slide == 1) "" else "s")) +
    theme_minimal(base_size = 11) +
    theme(legend.position = "top", legend.box = "horizontal",
          panel.grid.minor = element_blank(),
          plot.title = element_text(face = "bold"),
          strip.text = element_text(face = "bold"))

  ggsave(file.path(outdir, paste0(safe_name(roi), ".png")), p,
         width = 7.5, height = 4.6, dpi = 200)
}

message(sprintf("  done - %d PNG%s in %s",
                length(list.files(outdir, pattern = "\\.png$")),
                if (length(rois) == 1) "" else "s", outdir))
