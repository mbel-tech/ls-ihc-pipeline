# Per-ROI density figures, with statistics, plus a PowerPoint of the lot.
#
# Writes two series into results/ROI_plots/, one PNG per ROI in each:
#
#   treatment/    control vs exercise
#   environment/  brackish control | brackish exercise, sea control | sea exercise
#
# Both series: two panels (per sample, per slide), colour by treatment, and two
# scatters per group - fully opaque is Abercrombie-corrected, 50% is raw counts
# over area. The panels share a y axis because it is the same quantity in the
# same units, and the axis includes zero because these are densities.
#
# READ THE CORRECTED LAYER. Sections are consecutive at 14 um, so a nucleus cut
# by the boundary appears in both, and both datasets pool across sections - the
# raw layer counts those twice. It is drawn so the size of the correction is
# visible per region, not because it is the answer.
#
# Statistics live in roi_stats.R: a mixed model on slide-level rows with the
# animal as a random effect. Series 1 gets an F test as a caption; series 2 gets
# that plus Tukey compact-letter display above the scatters.
#
# Finally every PNG is packed into results/ROI_figures.pptx, one per slide.
#
# Run:  Rscript analysis/plot_roi_figures.R
#       Rscript analysis/plot_roi_figures.R D:/LS-analysis/results

args <- commandArgs(trailingOnly = TRUE)
here <- dirname(sub("^--file=", "",
                    grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(here, "roi_plots.R"))
source(file.path(here, "roi_stats.R"))

results <- if (length(args) >= 1) args[1] else RESULTS_DEFAULT
outdir <- file.path(results, "ROI_plots")
dirs <- list(treatment = file.path(outdir, "treatment"),
             environment = file.path(outdir, "environment"))
PPTX <- file.path(results, "ROI_figures.pptx")

CORRECTED <- "cells_per_mm2"
RAW       <- "profiles_per_mm2"
MEASURES  <- c("Abercrombie-corrected", "raw counts / area")

# All 8 Rm seeds are flagged uncertain in the atlas itself (LOGS.md), so a
# figure of it would look exactly like the others and mean less. Dropped from
# the FIGURES AND STATISTICS only - the spreadsheets keep it, because they are
# the record of what was measured.
DROP_ROIS <- c("Rm")

# Nudge the two measures apart inside each group as well as separating them by
# opacity: two clouds of one hue at 1.0 and 0.5 alpha are hard to tell apart
# where the correction is small. Set to 0 to stack them exactly.
DODGE <- 0.34

message(sprintf("reading %s", results))
samp <- load_sheet(file.path(results, "roi_dataset.xlsx"), "by_roi")
slide <- load_sheet(file.path(results, "roi_dataset_by_slide.xlsx"), "by_slide")

drop_rois <- function(df, what) {
  n <- sum(as.character(df$ROI) %in% DROP_ROIS)
  if (n) message(sprintf("  dropped %d %s row%s: %s",
                         n, what, if (n == 1) "" else "s",
                         paste(DROP_ROIS, collapse = ", ")))
  df <- df[!as.character(df$ROI) %in% DROP_ROIS, ]
  # Drop the LEVEL too, not just the rows. Left in, Rm kept appearing in the
  # per-panel summary as "0 control, 0 exercise" with a warning that it had too
  # few points - which reads as though it were still being considered.
  df$ROI <- droplevels(df$ROI)
  df
}
samp <- drop_rois(samp, "per-sample")
slide <- drop_rois(slide, "per-slide")

# environment arrived with 06c/06d; without it the four-group series cannot be
# built and saying so beats drawing an empty one.
if (!"environment" %in% names(samp) || all(is.na(samp$environment) | samp$environment == "")) {
  stop("no environment column - rebuild the datasets:\n",
       "  python scripts/06c_excel_dataset.py && python scripts/06d_excel_by_slide.py")
}

# Brackish pair first, then sea, reading left to right from the y axis.
GROUP_LEVELS <- c("brackish control", "brackish exercise",
                  "sea control", "sea exercise")
add_keys <- function(df) {
  df$environment <- factor(trimws(df$environment), levels = c("brackish", "sea"))
  df$group4 <- factor(paste(df$environment, df$treatment), levels = GROUP_LEVELS)
  df
}
samp <- add_keys(samp); slide <- add_keys(slide)

message(sprintf("  per sample: %d rows, %d samples", nrow(samp),
                length(unique(samp$sample))))
message(sprintf("  per slide : %d rows, %d slides", nrow(slide),
                length(unique(slide$slide))))

# One long frame per level, with both measures stacked.
stack_level <- function(df, level) {
  keep <- c("ROI", "treatment", "environment", "group4", "sample")
  do.call(rbind, lapply(
    list(c(CORRECTED, MEASURES[1]), c(RAW, MEASURES[2])),
    function(m) {
      out <- df[, keep]
      out$ROI <- as.character(out$ROI)
      out$level <- level
      out$measure <- m[2]
      out$value <- suppressWarnings(as.numeric(df[[m[1]]]))
      out
    }))
}
long <- rbind(stack_level(samp, "per sample"), stack_level(slide, "per slide"))
long <- long[is.finite(long$value), ]
long$level <- factor(long$level, levels = c("per sample", "per slide"))
long$measure <- factor(long$measure, levels = MEASURES)

report_n(samp, "one point = one sample")

# "Overwrite the past set" means the SET: a region that stops appearing would
# otherwise leave a stale figure looking current. The PNGs go, not the folders -
# deleting a directory open in Explorer fails on Windows.
for (d in dirs) dir.create(d, showWarnings = FALSE, recursive = TRUE)
old <- unlist(lapply(dirs, list.files, pattern = "\\.png$", full.names = TRUE))
if (length(old)) {
  file.remove(old)
  message(sprintf("\n  cleared %d old figure%s", length(old),
                  if (length(old) == 1) "" else "s"))
}

safe_name <- function(x) gsub("^_+|_+$", "", gsub("[^A-Za-z0-9]+", "_", x))
rois <- levels(droplevels(factor(long$ROI, levels = levels(samp$ROI))))

base_theme <- theme_minimal(base_size = 11) +
  theme(legend.position = "top", legend.box = "horizontal",
        panel.grid.minor = element_blank(),
        plot.title = element_text(face = "bold"),
        plot.caption = element_text(hjust = 0, size = 7.6, colour = "grey25"),
        strip.text = element_text(face = "bold"))

alpha_scale <- scale_alpha_manual(
  values = setNames(c(1, 0.5), MEASURES), drop = FALSE,
  guide = guide_legend(order = 2, override.aes = list(size = 3.2)))

message(sprintf("\n  writing %d ROIs x 2 series", length(rois)))

for (roi in rois) {
  d <- long[long$ROI == roi, ]
  if (!nrow(d)) next
  d_slide <- d[d$level == "per slide", ]

  # ---- series 1: treatment ------------------------------------------------
  caps <- vapply(MEASURES, function(m)
    sprintf("%s - %s", m, stat_treatment(d_slide[d_slide$measure == m, ])),
    character(1))

  p1 <- ggplot(d, aes(x = treatment, y = value,
                      colour = treatment, alpha = measure, group = measure)) +
    geom_point(position = position_jitterdodge(jitter.width = 0.12,
                                               dodge.width = DODGE, seed = 1),
               size = 2.6) +
    facet_wrap(~ level) +
    scale_colour_manual(values = TREATMENT_COLOURS, drop = FALSE,
                        guide = guide_legend(order = 1)) +
    alpha_scale + expand_limits(y = 0) +
    labs(title = roi, x = NULL, y = expression(density~(per~mm^2)),
         colour = NULL, alpha = NULL,
         subtitle = "opaque is Abercrombie-corrected",
         # The footer states what does NOT vary. Which model was used varies by
         # ROI - five of the ten have one slide per animal and get a plain
         # ANOVA - and is already named on each line, so asserting "mixed
         # model" here contradicted the line above it on half the figures.
         caption = paste(c(paste(caps, collapse = "\n"),
                           "the animal is the experimental unit; the model used is named on each line"),
                         collapse = "\n")) +
    base_theme
  ggsave(file.path(dirs$treatment, paste0(safe_name(roi), ".png")), p1,
         width = 7.6, height = 5.2, dpi = 200)

  # ---- series 2: the four groups -----------------------------------------
  st4 <- lapply(setNames(MEASURES, MEASURES),
                function(m) stat_group4(d_slide[d_slide$measure == m, ]))

  # Letters sit above the slide panel, the one the model was fitted on. Placed
  # at a fixed fraction above the tallest point in the whole figure so they
  # never collide with the data or with each other.
  top <- max(d$value, na.rm = TRUE)
  lab <- do.call(rbind, lapply(MEASURES, function(m) {
    L <- st4[[m]]$letters
    if (is.null(L) || !nrow(L)) return(NULL)
    L$measure <- factor(m, levels = MEASURES)
    L$level <- factor("per slide", levels = levels(d$level))
    L$group4 <- factor(L$group4, levels = GROUP_LEVELS)
    L$treatment <- sub("^\\S+ ", "", as.character(L$group4))
    L$y <- top * (if (m == MEASURES[1]) 1.10 else 1.19)
    L
  }))

  p2 <- ggplot(d, aes(x = group4, y = value,
                      colour = treatment, alpha = measure, group = measure)) +
    geom_point(position = position_jitterdodge(jitter.width = 0.12,
                                               dodge.width = DODGE, seed = 1),
               size = 2.4) +
    facet_wrap(~ level) +
    scale_colour_manual(values = TREATMENT_COLOURS, drop = FALSE,
                        guide = guide_legend(order = 1)) +
    alpha_scale +
    scale_x_discrete(drop = FALSE,
                     labels = function(x) sub(" ", "\n", x)) +
    expand_limits(y = 0) +
    labs(title = roi, x = NULL, y = expression(density~(per~mm^2)),
         colour = NULL, alpha = NULL,
         subtitle = "opaque is Abercrombie-corrected; letters share = not different (Tukey)",
         caption = paste(c(
           paste(sprintf("%s - %s", MEASURES,
                         vapply(st4, `[[`, character(1), "caption")),
                 collapse = "\n"),
           "the animal is the experimental unit; the model used is named on each line. Letters describe the four groups",
           "environment is confounded with timepoint here: brackish = tp1, sea = tp2"),
           collapse = "\n")) +
    base_theme +
    theme(axis.text.x = element_text(size = 8.5))

  if (!is.null(lab) && nrow(lab)) {
    p2 <- p2 + geom_text(data = lab,
                         aes(x = group4, y = y, label = letter,
                             colour = treatment, alpha = measure),
                         inherit.aes = FALSE, size = 3.4, fontface = "bold",
                         position = position_dodge(width = DODGE),
                         show.legend = FALSE) +
      expand_limits(y = top * 1.26)
  }
  ggsave(file.path(dirs$environment, paste0(safe_name(roi), ".png")), p2,
         width = 11.0, height = 5.8, dpi = 200)
}

pngs <- unlist(lapply(dirs, list.files, pattern = "\\.png$", full.names = TRUE))
message(sprintf("  %d PNGs written", length(pngs)))

# ---- PowerPoint --------------------------------------------------------------
# Rebuilt from scratch every run, like the PNGs, so it can never carry a slide
# whose figure no longer exists.
if (!requireNamespace("officer", quietly = TRUE)) {
  message("  officer not installed - skipping the pptx")
} else {
  library(officer)
  doc <- read_pptx()
  for (f in sort(pngs)) {
    series <- basename(dirname(f))
    title <- sprintf("%s - %s", sub("\\.png$", "", basename(f)), series)
    doc <- add_slide(doc, layout = "Title Only", master = "Office Theme")
    doc <- ph_with(doc, value = title, location = ph_location_type(type = "title"))
    doc <- ph_with(doc, value = external_img(f, width = 9.2, height = 6.1),
                   location = ph_location(left = 0.4, top = 1.35,
                                          width = 9.2, height = 6.1))
  }
  print(doc, target = PPTX)
  message(sprintf("  %d slides -> %s", length(pngs), PPTX))
}
