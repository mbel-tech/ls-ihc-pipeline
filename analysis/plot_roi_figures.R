# Per-ROI density figures, with statistics, plus a PowerPoint of the lot.
#
# Writes two series into results/ROI_plots/, one PNG per ROI in each:
#
#   treatment/         control vs exercise
#   production_phase/  brackish control | brackish exercise,
#                      sea control | sea exercise
#
# The grouping factor is still called `environment` in the data - renaming that
# column would ripple through 06b, 06c, 06d and every model formula - but every
# label a reader sees says PRODUCTION PHASE.
#
# ONE measure and ONE level. The y value is `cells_per_mm2` - Abercrombie
# corrected - and every point is a SLIDE. The raw counts/area layer and the
# per-sample panel were both dropped: two scatters of one hue at different
# opacity, doubled across two panels, was four clouds per group to read before
# the reader got to the statistics.
#
# Sections are consecutive at 14 um, so a nucleus cut by the boundary appears in
# both and pooling raw counts across sections counts it twice. The correction is
# not optional here, which is why the raw layer went rather than the corrected
# one.
#
# SHAPE IS THE ANIMAL. Points are slides and an animal contributes several, so
# without the shape a cluster of five points reads as five fish. The filled pch
# set is used so they stay solid at size.
#
# Statistics live in roi_stats.R: a mixed model on slides with the animal as a
# random effect, or a plain ANOVA where each animal has only one slide. Series 1
# gets an F test; series 2 adds Tukey compact-letter display above the scatters.
#
# Every PNG is packed into results/ROI_figures.pptx, one per slide.
#
# Run:  Rscript analysis/plot_roi_figures.R
#       Rscript analysis/plot_roi_figures.R D:/LS-analysis/results

args <- commandArgs(trailingOnly = TRUE)
here <- dirname(sub("^--file=", "",
                    grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(here, "roi_plots.R"))
source(file.path(here, "roi_stats.R"))

if (!requireNamespace("ggtext", quietly = TRUE)) {
  stop("needs ggtext for the subscripted df and the two-line axis labels:\n",
       "  install.packages(\"ggtext\")")
}
library(ggtext)

results <- if (length(args) >= 1) args[1] else RESULTS_DEFAULT
outdir <- file.path(results, "ROI_plots")
dirs <- list(treatment = file.path(outdir, "treatment"),
             phase = file.path(outdir, "production_phase"))
PPTX <- file.path(results, "ROI_figures.pptx")

VALUE <- "cells_per_mm2"          # Abercrombie-corrected density

# All 8 Rm seeds are flagged uncertain in the atlas itself (LOGS.md), so a
# figure of it would look exactly like the others and mean less. Dropped from
# the FIGURES AND STATISTICS only - the spreadsheets keep it.
DROP_ROIS <- c("Rm")

# Eleven animals need eleven marks that can be told apart at a glance, and R
# only has five filled FORMS - circle, square, diamond, triangle up, triangle
# down - in two styles each. The first nine are those: 21-25 filled with a
# border, then 15-18 solid.
#
# 19 and 20 used to fill the last two slots and both are plain circles, so
# LS87, LS136 and LS138 came out as three circles distinguishable only by a
# border and a couple of pixels of radius. A star and a square-with-triangle
# are not "full" shapes, but being able to tell two animals apart matters more
# than the fill.
SHAPES <- c(21, 22, 23, 24, 25, 15, 16, 17, 18, 8, 14)

# An animal keeps ITS OWN shape in every figure. Assigning shapes per ROI from
# whichever animals happen to be present looked fine on any single plot and made
# LS37 a circle in one figure and a square in the next - which, in a twenty-slide
# deck someone reads in order, is worse than no shapes at all. The mapping is
# built once from the full animal list and reused.
animal_shapes <- function(levels_all) setNames(
  rep_len(SHAPES, length(levels_all)), levels_all)

BASE <- 18                        # everything is sized off this
PT   <- 4.6

message(sprintf("reading %s", results))
# SECTIONS, not slides. A slide carries 1 to 9 sections, so keying the points by
# slide threw most of the data away before it was drawn: Dm's sea-control group
# was a single point, and half the ROIs had groups of one or two. By section the
# same ROI is 5, 15, 21 and 33.
#
# This does not change the statistical claim. The animal is still the
# experimental unit and the model still carries (1 | sample); more rows per
# animal give the random effect more to work with, they do not become more fish.
slide <- load_sheet(file.path(results, "roi_dataset_by_slide.xlsx"), "by_section")

n0 <- sum(as.character(slide$ROI) %in% DROP_ROIS)
if (n0) message(sprintf("  dropped %d row%s: %s", n0, if (n0 == 1) "" else "s",
                        paste(DROP_ROIS, collapse = ", ")))
slide <- slide[!as.character(slide$ROI) %in% DROP_ROIS, ]
slide$ROI <- droplevels(slide$ROI)

if (!"environment" %in% names(slide) ||
    all(is.na(slide$environment) | slide$environment == "")) {
  stop("no environment column - rebuild the datasets:\n",
       "  python scripts/06c_excel_dataset.py && python scripts/06d_excel_by_slide.py")
}

GROUP_LEVELS <- c("brackish control", "brackish exercise",
                  "sea control", "sea exercise")
slide$environment <- factor(trimws(slide$environment), levels = c("brackish", "sea"))
slide$group4 <- factor(paste(slide$environment, slide$treatment), levels = GROUP_LEVELS)
slide$sample <- factor(slide$sample,
                       levels = unique(slide$sample[order(
                         as.numeric(sub("^LS", "", slide$sample)))]))
slide$value <- suppressWarnings(as.numeric(slide[[VALUE]]))
slide <- slide[is.finite(slide$value), ]

message(sprintf("  %d sections, %d animals, %d ROIs", nrow(slide),
                nlevels(droplevels(slide$sample)), nlevels(slide$ROI)))
report_n(slide, "one point = one section")

for (d in dirs) dir.create(d, showWarnings = FALSE, recursive = TRUE)
# Sweep the PARENT too, not just the two series folders. An earlier layout wrote
# the figures straight into ROI_plots/, and eleven of them - Rm among them - sat
# there untouched through every rebuild after the subfolders arrived, because
# the clear only ever looked one level down. Anything stale enough to survive a
# layout change is exactly what "overwrite the past set" is meant to catch.
old <- c(list.files(outdir, pattern = "\\.png$", full.names = TRUE),
         unlist(lapply(dirs, list.files, pattern = "\\.png$", full.names = TRUE)))
if (length(old)) {
  file.remove(old)
  message(sprintf("\n  cleared %d old figure%s", length(old),
                  if (length(old) == 1) "" else "s"))
}

safe_name <- function(x) gsub("^_+|_+$", "", gsub("[^A-Za-z0-9]+", "_", x))

# The group name, one word per line. Bold comes from the theme.
axis_labeller <- function(x) gsub(" ", "\n", x)

# A single asterisk on the HIGHER group, when a two-group comparison is
# significant.
#
# With exactly two scatters, compact letters can only ever come back "a" and "b",
# which is the same information as one mark and costs the reader a legend. The
# mark goes on the higher group so the direction is readable without comparing
# the clouds by eye.
#
# Returns an empty list rather than NULL when there is nothing to draw: ggplot
# accepts a list of layers, and NULL in a `+` chain is a silent no-op that is
# easy to mistake for "the test said nothing".
star_layer <- function(d, col, p, top, alpha_level = 0.05) {
  if (!isTRUE(is.finite(p)) || p >= alpha_level) return(list())
  m <- tapply(d$value, droplevels(d[[col]]), mean, na.rm = TRUE)
  hi <- names(m)[which.max(m)]
  list(geom_text(data = data.frame(x = factor(hi, levels = levels(d[[col]])),
                                   y = top * 1.10),
                 aes(x = x, y = y), label = "*", inherit.aes = FALSE,
                 size = BASE * 0.95, fontface = "bold", colour = "black",
                 vjust = 0.75),
       expand_limits(y = top * 1.20))
}

# (N=x) is drawn as an ANNOTATION below the axis line, not folded into the axis
# label, so it sits above the group name with real padding and the name alone
# carries the bold.
#
# It cannot be part of the label: with ggplot2 4.0.3 and ggtext 0.1.2,
# element_markdown() renders on plot.caption but NOT on axis.text.x - ggplot2
# 4.0's axis code does not dispatch to it, and the tags print literally. Checked
# on a two-point toy plot before changing anything here.
n_labels <- function(d, col, top) {
  lv <- levels(droplevels(d[[col]]))
  data.frame(x = factor(lv, levels = levels(d[[col]])),
             n = vapply(lv, function(g) sum(as.character(d[[col]]) == g), integer(1)),
             y = -0.055 * top, row.names = NULL)
}

base_theme <- theme_minimal(base_size = BASE) +
  theme(legend.position = "top", legend.box = "horizontal",
        legend.text = element_text(size = BASE * 0.8),
        panel.grid.minor = element_blank(),
        panel.grid.major.x = element_blank(),
        plot.title = element_text(face = "bold", size = BASE * 1.5),
        plot.subtitle = element_text(size = BASE * 0.85, colour = "grey30"),
        # Every caption carries <sub> tags from roi_stats.R, so it MUST be
        # markdown - element_text would print the tags literally.
        plot.caption = element_markdown(hjust = 0, size = BASE * 0.78,
                                        colour = "grey15", lineheight = 1.45),
        axis.text.x = element_text(size = BASE * 0.92, colour = "black",
                                   face = "bold", lineheight = 1.05,
                                   margin = margin(t = 26)),
        axis.text.y = element_text(size = BASE * 0.92, colour = "black"),
        axis.title.y = element_text(size = BASE, margin = margin(r = 10)),
        axis.line = element_line(colour = "black", linewidth = 1.1),
        axis.ticks = element_line(colour = "black", linewidth = 1.1),
        axis.ticks.length = unit(5, "pt"),
        plot.margin = margin(14, 22, 12, 14))

SHAPE_MAP <- animal_shapes(levels(slide$sample))
shape_scale <- scale_shape_manual(
  values = SHAPE_MAP, drop = TRUE, name = NULL,
  guide = guide_legend(order = 2, nrow = 2,
                       override.aes = list(size = 3.6, colour = "grey20",
                                           fill = "grey60")))

message(sprintf("\n  writing %d ROIs x 2 series", nlevels(slide$ROI)))

for (roi in levels(slide$ROI)) {
  d <- slide[slide$ROI == roi, ]
  if (!nrow(d)) next
  d$environment <- droplevels(d$environment)
  # sample keeps ALL its levels so the shape scale stays identical across
  # figures; drop = TRUE on the scale keeps absent animals out of the legend.
  top <- max(d$value, na.rm = TRUE)

  # Mean and SEM, drawn AFTER the points so they read on top of them. The SEM
  # is over the POINTS SHOWN, which are slides - it describes the scatter, and
  # is deliberately NOT the standard error the model reports, which accounts for
  # animal clustering and is what the p values come from. The bar is a
  # description of the picture; the caption is the test.
  # ONE crossbar and ONE error bar per scatter.
  #
  # `aes(group = ...)` is not decoration here. shape is mapped to the animal, so
  # without an explicit group stat_summary inherits that grouping and computes a
  # mean per ANIMAL - which drew three or four stacked horizontal bars inside a
  # single scatter and looked like a rendering fault. The group has to be the x
  # variable, which is what "per scatter" means.
  #
  # The two must also read as different objects: the mean is a SHORT THICK bar,
  # the SEM a NARROWER THINNER one.
  # `shape = NULL` drops the inherited shape aesthetic. Without it the summary
  # layers still carry shape = sample, and a summary has no single animal, so
  # the shape resolves to NA - which put a phantom "NA" entry in the animal
  # legend of every figure. The bars themselves never used shape.
  #
  # `middle.linewidth` rather than the deprecated `fatten` (ggplot2 4.0).
  summary_layers <- function(xvar) list(
    stat_summary(aes(group = .data[[xvar]], shape = NULL), fun.data = mean_se,
                 geom = "errorbar", width = 0.10, linewidth = 0.6,
                 colour = "black"),
    # The mean is drawn as an errorbar with ymin = ymax = mean, which collapses
    # to a single horizontal segment. geom_crossbar was the obvious choice and
    # the wrong one: with a zero-height box it draws its outline AND its middle
    # line in the same place, so the two thicknesses stack into a heavy black
    # slab that covered the points behind it.
    stat_summary(aes(group = .data[[xvar]], shape = NULL),
                 fun = mean, fun.min = mean, fun.max = mean,
                 geom = "errorbar", width = 0.28, linewidth = 1.7,
                 colour = "black"))

  common <- list(
    scale_colour_manual(values = TREATMENT_COLOURS, drop = FALSE, name = NULL,
                        guide = guide_legend(order = 1,
                                             override.aes = list(size = 4.4, shape = 16))),
    scale_fill_manual(values = TREATMENT_COLOURS, drop = FALSE, guide = "none"),
    shape_scale,
    expand_limits(y = 0),
    # clip="off" lets the (N=x) annotation sit outside the panel, between the
    # axis line and the group name.
    coord_cartesian(clip = "off"),
    labs(x = NULL, y = expression(density~(cells~per~mm^2)), title = roi),
    base_theme)

  # ---- series 1: treatment ------------------------------------------------
  st1 <- stat_treatment(d)
  p1 <- ggplot(d, aes(x = treatment, y = value, colour = treatment,
                      fill = treatment, shape = sample)) +
    geom_jitter(width = 0.16, height = 0, size = PT, stroke = 1.1) +
    summary_layers("treatment") +
    geom_text(data = n_labels(d, "treatment", top),
              aes(x = x, y = y, label = sprintf("(N=%d)", n)),
              inherit.aes = FALSE, vjust = 1, size = BASE * 0.30,
              colour = "grey25") +
    scale_x_discrete(labels = axis_labeller) +
    common +
    labs(subtitle = "Abercrombie-corrected; one point per section, shape = animal",
         caption = st1$caption)
  # Two scatters, so a letter pair would only ever read "a / b" - which says
  # nothing a single mark does not. The asterisk goes on the HIGHER group.
  p1 <- p1 + star_layer(d, "treatment", st1$p, top)
  ggsave(file.path(dirs$treatment, paste0(safe_name(roi), ".png")), p1,
         width = 9.5, height = 8.0, dpi = 200, bg = "white")

  # ---- series 2: the four groups -----------------------------------------
  st4 <- stat_group4(d)

  # LETTERS ONLY WHEN THEY SEPARATE SOMETHING. If Tukey puts every group in the
  # same class the display is four identical "a"s, which is a legend, a
  # subtitle and four glyphs spent saying nothing - and worse, it reads at a
  # glance like a result.
  #
  # But an absent label must not be ambiguous with an untested one, so when they
  # are suppressed the caption says Tukey ran and separated nothing. Silence
  # would leave the reader unable to tell "no difference" from "no test".
  L <- st4$letters
  letters_shown <- !is.null(L) && nrow(L) > 0 && length(unique(L$letter)) > 1
  tukey_note <- if (!is.null(L) && nrow(L) && !letters_shown) {
    "Tukey: no pair of groups differs, so no letters are drawn"
  } else NULL

  p2 <- ggplot(d, aes(x = group4, y = value, colour = treatment,
                      fill = treatment, shape = sample)) +
    geom_jitter(width = 0.16, height = 0, size = PT, stroke = 1.1) +
    summary_layers("group4") +
    geom_text(data = n_labels(d, "group4", top),
              aes(x = x, y = y, label = sprintf("(N=%d)", n)),
              inherit.aes = FALSE, vjust = 1, size = BASE * 0.30,
              colour = "grey25") +
    scale_x_discrete(drop = FALSE, labels = axis_labeller) +
    common +
    labs(subtitle = paste0(
           "Abercrombie-corrected; one point per section, shape = animal",
           if (letters_shown) "; letters share = not different (Tukey)" else ""),
         caption = paste(c(st4$caption, tukey_note,
                           "production phase is confounded with timepoint: brackish = tp1, sea = tp2"),
                         collapse = "<br>"))

  # Letters when they separate something; a single asterisk when only two groups
  # are present, for the same reason as series 1.
  if (isTRUE(st4$n_groups == 2)) {
    p2 <- p2 + star_layer(d, "group4", st4$p, top)
  } else if (letters_shown) {
    L$group4 <- factor(L$group4, levels = GROUP_LEVELS)
    L$y <- top * 1.10
    p2 <- p2 + geom_text(data = L, aes(x = group4, y = y, label = letter),
                         inherit.aes = FALSE, size = BASE * 0.42,
                         fontface = "bold", colour = "black") +
      expand_limits(y = top * 1.18)
  }
  ggsave(file.path(dirs$phase, paste0(safe_name(roi), ".png")), p2,
         width = 12.0, height = 8.4, dpi = 200, bg = "white")
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
    doc <- ph_with(doc, value = external_img(f, width = 9.6, height = 6.4),
                   location = ph_location(left = 0.2, top = 1.2,
                                          width = 9.6, height = 6.4))
  }
  print(doc, target = PPTX)
  message(sprintf("  %d slides -> %s", length(pngs), PPTX))
}
