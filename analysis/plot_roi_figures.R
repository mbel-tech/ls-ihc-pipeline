# Per-ROI figures, with statistics, plus a PowerPoint of the lot.
#
# Writes TWO series into results/ROI_plots/, one PNG per ROI in each - two
# grouping series over ONE measure:
#
#   positive_treatment/          pERK-positive, control vs exercise
#   positive_production_phase/   pERK-positive, the four groups
#
# The grouping factor is still called `environment` in the data - renaming that
# column would ripple through 06b, 06c, 06d and every model formula - but every
# label a reader sees says PRODUCTION PHASE.
#
# ONE MEASURE, ONE LEVEL. `positive_cells_per_mm2` is the subset of DAPI nuclei
# over the per-section cut, Abercrombie-corrected, from 06a via 06c, one point
# per ANIMAL.
#
# THE ALL-NUCLEI DENSITY SERIES WAS DROPPED at the operator's request on
# 2026-09-07. It used to be drawn alongside this one, and the reason it was is
# still live: there is no no-primary control and no tERK channel in this
# dataset, so an ABSOLUTE positivity rate is not a claim these data support.
# What is supported is the comparison BETWEEN ARMS at matched levels, because
# the non-specific component is shared. With density gone the positivity figure
# no longer has a companion to be read against, so the false-positive rate the
# background discs measured - printed in the caption of every figure here -
# carries that caveat on its own. `cells_per_mm2` is still in the workbook and
# in plot_by_sample.R / plot_by_slide.R; restoring the series is re-adding the
# list entry below.
#
# The raw counts/area layer was dropped: two scatters of one hue at different
# opacity, doubled across two panels, was four clouds per group to read before
# the reader got to the statistics.
#
# Sections are consecutive at 14 um, so a nucleus cut by the boundary appears in
# both and pooling raw counts across sections counts it twice. The correction is
# not optional here, which is why the raw layer went rather than the corrected
# one.
#
# THE POINT IS THE ANIMAL. One mark per fish per region. The animal is the
# experimental unit, so a figure whose points were sections drew 130 marks for a
# comparison that has twelve fish in it, and the reader took the sample size off
# the size of the cloud. What each mark carries is 06c's pooled value - that
# animal's nuclei over that animal's measured disc area - so an animal measured
# on nine discs is not outvoted by one measured on two. The within-animal spread
# has not been thrown away; plot_by_slide.R draws it, and says there what it is.
#
# SHAPE IS STILL THE ANIMAL even though each now appears once per scatter. It is
# what lets a reader follow one fish from Dm to Vv and between the two series,
# and it names the outlier instead of leaving it anonymous. The filled pch set
# is used so they stay solid at size.
#
# Statistics live in roi_stats.R: one row per animal means ordinary least
# squares is already operating on the experimental unit, so it is a plain ANOVA
# - nothing to cluster, no random effect to fit and no singular fits to explain.
# Series 1 gets an F test; series 2 adds Tukey compact-letter display above the
# scatters.
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

results <- results_dir(args)
outdir <- file.path(results, "ROI_plots")
PPTX_FOR <- function(m) file.path(
  results, sprintf("ROI_figures%s.pptx", marker_suffix(m)))

# TWO MEASURES, each drawn as the same two series. Density is every DAPI
# nucleus; positivity is the subset over the per-section cut, pooled to the
# animal.
#
# Positivity is added ALONGSIDE density, never in place of it. There is no
# no-primary control and no tERK channel in this dataset, so an absolute
# positivity rate is not a claim these data support - what is supported is the
# comparison between arms at matched levels, because the non-specific component
# is shared. The density figures stand unchanged.
# Output folders are suffixed for any marker other than the pERK default, so a
# PCNA run writes beside the pERK figures rather than over them - the same
# reason 05a's box files are per marker. The existing folder names are kept for
# the first declared marker so nothing already cited moves; marker_suffix in
# roi_plots.R is the one place that decides which marker that is.
sfx <- marker_suffix()
series_dir <- function(name) file.path(outdir, paste0(name, sfx))

MEASURES <- list(
  list(key = "positive", value = "positive_cells_per_mm2",
       # The label names the marker, so a PCNA figure cannot read as a pERK one.
       ylab = bquote(.(marker_label())*"-positive"~(cells~per~mm^2)),
       treatment = series_dir("positive_treatment"),
       phase = series_dir("positive_production_phase"),
       note = "Abercrombie-corrected",
       cap = "positivity cut per section from its own background discs, then pooled to the animal")
)
dirs <- unlist(lapply(MEASURES, function(m) c(m$treatment, m$phase)))

# The false-positive rate the background discs measured, quoted on every
# positivity figure. Without it a positivity number reads as absolute, which is
# exactly the reading these data do not support. Median over sections.
SPEC <- file.path(results, "detector_specificity.csv")
fp_note <- ""
if (file.exists(SPEC)) {
  sp <- utils::read.csv(SPEC, stringsAsFactors = FALSE)
  # THIS MARKER'S SECTIONS ONLY. detector_specificity.csv carries a marker
  # column and is read here rather than through load_sheet, so it did not
  # inherit the sheet filter - and pooling it would caption every pERK figure
  # with PCNA's sections mixed in. It is the one number on the figure that must
  # not be pooled, since it is what stops the positivity being read as absolute.
  sp <- filter_marker(sp, "detector_specificity.csv")
  fr <- suppressWarnings(as.numeric(sp$false_positive_rate))
  fr <- fr[is.finite(fr)]
  if (length(fr)) fp_note <- sprintf(
    "detector false-positives on background discs: median %.1f%% (range %.1f-%.1f%%, n=%d)",
    100 * median(fr), 100 * min(fr), 100 * max(fr), length(fr))
} else {
  message("  no detector_specificity.csv - run 06a_roi_dataset.py; ",
          "positivity figures will carry no false-positive rate")
}

# ONE SHAPE FOR EVERY POINT: 16, the solid circle. Operator's call, 2026-09-07.
#
# What this gives up is stated plainly because it is not recoverable from the
# figure: an animal is no longer identifiable by its mark, so a reader cannot
# follow one fish across ROIs or spot which fish is carrying a group. Twelve
# per-animal shapes used to do that (21-25 bordered, 15-18 solid, then 8, 14 and
# 11), and the animal legend went with them.
#
# The ARMS are still separated, by colour - shape 16 takes `colour`, not `fill`,
# which is why colour = treatment is mapped alongside fill and the figures do
# not come out monochrome.
PT_SHAPE <- 16

BASE <- 18                        # everything is sized off this
PT   <- 4.6

message(sprintf("reading %s", results))
# ANIMALS, not sections. 06c's `by_roi` is already keyed one row per
# (animal, marker, ROI): that animal's nuclei summed over its discs, Abercrombie-
# corrected, over the area those discs covered. Pooling there rather than
# averaging section values here is the deliberate half of the choice - it
# weights by tissue actually measured, so an animal carrying two usable discs
# does not get the same say as one carrying nine.
#
# The section-level table is still built and still drawn, by plot_by_slide.R.
# What moved is which level carries the test: the figures in the deck now show
# the unit the comparison is made on, so the number of marks in a scatter, the
# N printed under it and the df in the caption are one number. They were three.
animal <- load_sheet(file.path(results, "roi_dataset.xlsx"), "by_roi")

# by_roi is keyed by (animal, marker, ROI) and load_sheet has already cut it to
# one marker, so a repeated pair here means the sheet is not what this script
# believes it is. Worth stopping for rather than drawing: a duplicated animal
# would double its weight in the mean bar and add a degree of freedom the design
# does not have, and nothing on the figure would look wrong.
dup <- paste(animal$sample, animal$ROI)
if (anyDuplicated(dup)) {
  d <- unique(dup[duplicated(dup)])
  stop(sprintf("by_roi has %d animal x ROI pair%s appearing twice (%s) - rebuild:\n%s",
               length(d), if (length(d) == 1) "" else "s",
               paste(utils::head(d, 4), collapse = ", "),
               "  python scripts/06a_roi_dataset.py && python scripts/06c_excel_dataset.py"))
}

# Rm is already gone: load_sheet drops DROP_ROIS for every figure in the
# analysis folder, and its ROI levels are built from what survives.

if (!"environment" %in% names(animal) ||
    all(is.na(animal$environment) | animal$environment == "")) {
  stop("no environment column - rebuild the dataset:\n",
       "  python scripts/06c_excel_dataset.py")
}

GROUP_LEVELS <- c("brackish control", "brackish exercise",
                  "sea control", "sea exercise")
animal$environment <- factor(trimws(animal$environment), levels = c("brackish", "sea"))
animal$group4 <- factor(paste(animal$environment, animal$treatment), levels = GROUP_LEVELS)
animal$sample <- factor(animal$sample,
                        levels = unique(animal$sample[order(
                          as.numeric(sub("^LS", "", animal$sample)))]))
for (m in MEASURES) {
  if (!m$value %in% names(animal)) {
    stop(sprintf("no column '%s' in by_roi - rebuild the dataset:\n%s",
                 m$value,
                 "  python scripts/06a_roi_dataset.py && python scripts/06c_excel_dataset.py"))
  }
}

message(sprintf("  %d animal x ROI rows, %d animals, %d ROIs", nrow(animal),
                nlevels(droplevels(animal$sample)), nlevels(animal$ROI)))

for (d in dirs) dir.create(d, showWarnings = FALSE, recursive = TRUE)
# Sweep the PARENT too, not just the series folders. An earlier layout wrote
# the figures straight into ROI_plots/, and eleven of them - Rm among them - sat
# there untouched through every rebuild after the subfolders arrived, because
# the clear only ever looked one level down. Anything stale enough to survive a
# layout change is exactly what "overwrite the past set" is meant to catch.
#
# RETIRED FOLDERS ARE SWEPT BY NAME. Dropping the density measure on 2026-09-07
# took `treatment/` and `production_phase/` out of `dirs`, and a sweep that only
# looks at `dirs` would have left their last set of density PNGs on disk forever
# - out of the deck, since the pptx is built from `dirs`, but sitting in
# results/ROI_plots/ looking current. That is the same failure the paragraph
# above describes, one layout change later.
#
# Named rather than swept recursively ON PURPOSE: a recursive clear of outdir
# would delete the OTHER marker's figures, which the `sfx` suffix exists to
# keep apart. These are this marker's own retired folders and nothing else.
RETIRED <- c(series_dir("treatment"), series_dir("production_phase"))
old <- c(list.files(outdir, pattern = "\\.png$", full.names = TRUE),
         unlist(lapply(c(dirs, RETIRED), list.files,
                       pattern = "\\.png$", full.names = TRUE)))
if (length(old)) {
  file.remove(old)
  message(sprintf("\n  cleared %d old figure%s", length(old),
                  if (length(old) == 1) "" else "s"))
}
# THE EMPTINESS CHECK IS THE GUARD, not the unlink flag. unlink() refuses a
# directory outright unless recursive = TRUE - empty or not - so the first
# version of this left both folders standing. With recursive = TRUE the call
# would happily take a full one, which is why nothing but an already-empty
# folder ever reaches it. all.files/no.. so a stray dotfile still counts as
# content.
for (r in RETIRED) {
  if (dir.exists(r) && !length(list.files(r, all.files = TRUE, no.. = TRUE)))
    unlink(r, recursive = TRUE)
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

message(sprintf("\n  writing %d ROIs x 2 series x %d measures",
                nlevels(animal$ROI), length(MEASURES)))

# The measure loop is OUTSIDE the ROI loop, so `value` is set once per measure
# and every figure in a series is drawn from the same column. Rows with no value
# for that measure drop HERE and not globally: 06c leaves positivity blank for
# an animal unless EVERY disc behind it carried a cut, and an animal with a
# density but no positivity must still appear in the density figures.
for (M in MEASURES) {
  animal_m <- animal
  animal_m$value <- suppressWarnings(as.numeric(animal_m[[M$value]]))
  animal_m <- animal_m[is.finite(animal_m$value), ]
  if (!nrow(animal_m)) {
    message(sprintf("  %s: no rows carry a value, series skipped", M$key))
    next
  }
  message(sprintf("  %s: %d animal x ROI rows", M$key, nrow(animal_m)))
  report_n(animal_m, sprintf("one point = one animal (%s)", M$key))

  for (roi in levels(animal_m$ROI)) {
    d <- animal_m[animal_m$ROI == roi, ]
    if (!nrow(d)) next
    d$environment <- droplevels(d$environment)
    # sample keeps ALL its levels so the shape scale stays identical across
    # figures; drop = TRUE on the scale keeps absent animals out of the legend.
    top <- max(d$value, na.rm = TRUE)

    # Mean and SEM, drawn AFTER the points so they read on top of them. The SEM
    # is over the POINTS SHOWN, which are animals - so the bar and the caption
    # now describe the same scatter at the same level. They did not before: the
    # bar summarised sections while the p value came from a model that clustered
    # them, and the reader had no way to see that from the figure.
    # ONE crossbar and ONE error bar per scatter.
    #
    # `aes(group = ...)` is not decoration here, and it stays even though shape
    # is now constant. Any discrete aesthetic mapped in the parent ggplot() sets
    # the grouping stat_summary inherits, so without an explicit group the mean
    # is computed per subgroup - which drew three or four stacked horizontal bars
    # inside a single scatter and looked like a rendering fault. The group has to
    # be the x variable, which is what "per scatter" means.
    #
    # The two must also read as different objects: the mean is a SHORT THICK bar,
    # the SEM a NARROWER THINNER one.
    # `middle.linewidth` rather than the deprecated `fatten` (ggplot2 4.0).
    summary_layers <- function(xvar) list(
      stat_summary(aes(group = .data[[xvar]]), fun.data = mean_se,
                   geom = "errorbar", width = 0.10, linewidth = 0.6,
                   colour = "black"),
      # The mean is drawn as an errorbar with ymin = ymax = mean, which collapses
      # to a single horizontal segment. geom_crossbar was the obvious choice and
      # the wrong one: with a zero-height box it draws its outline AND its middle
      # line in the same place, so the two thicknesses stack into a heavy black
      # slab that covered the points behind it.
      stat_summary(aes(group = .data[[xvar]]),
                   fun = mean, fun.min = mean, fun.max = mean,
                   geom = "errorbar", width = 0.28, linewidth = 1.7,
                   colour = "black"))

    common <- list(
      scale_colour_manual(values = TREATMENT_COLOURS, drop = FALSE, name = NULL,
                          guide = guide_legend(order = 1,
                                               override.aes = list(size = 4.4, shape = 16))),
      scale_fill_manual(values = TREATMENT_COLOURS, drop = FALSE, guide = "none"),
      expand_limits(y = 0),
      # clip="off" lets the (N=x) annotation sit outside the panel, between the
      # axis line and the group name.
      coord_cartesian(clip = "off"),
      labs(x = NULL, y = M$ylab,
           # The headline set's panels are titled by ROI alone, as they
           # were before a second marker existed; every other marker says
           # which one it is, so two panels cannot be confused.
           title = if (identical(MARKER, PRIMARY)) roi
                   else sprintf("%s - %s", roi, marker_label())),
      base_theme)

    # The false-positive rate belongs on the positivity figures and nowhere else.
    # The subtitle is ONE unwrapped line and ggplot will not break it - a long
    # one is silently clipped at the panel edge, which is how the false-positive
    # rate disappeared off the right of every positivity figure the first time.
    # Anything longer than a clause goes in the caption, which is markdown and
    # breaks on <br>.
    sub_note <- paste0(M$note, "; one point per animal, pooled over its sections")
    # Two SEPARATE caption lines, not one joined string. element_markdown wraps
    # on <br> and on nothing else, so a single line carrying both notes came to
    # ~96 characters and ran off the right of the panel - the same clipping that
    # hid this note when it lived in the subtitle. Each line stays under ~90.
    cap_note <- if (is.null(M$cap)) NULL else c(M$cap, fp_note)

    # ---- series 1: treatment ------------------------------------------------
    st1 <- stat_treatment(d)
    p1 <- ggplot(d, aes(x = treatment, y = value, colour = treatment,
                        fill = treatment)) +
      geom_jitter(width = 0.16, height = 0, size = PT, stroke = 1.1,
                  shape = PT_SHAPE) +
      summary_layers("treatment") +
      geom_text(data = n_labels(d, "treatment", top),
                aes(x = x, y = y, label = sprintf("(N=%d)", n)),
                inherit.aes = FALSE, vjust = 1, size = BASE * 0.30,
                colour = "grey25") +
      scale_x_discrete(labels = axis_labeller) +
      common +
      labs(subtitle = sub_note,
           caption = paste(c(st1$caption, cap_note), collapse = "<br>"))
    # Two scatters, so a letter pair would only ever read "a / b" - which says
    # nothing a single mark does not. The asterisk goes on the HIGHER group.
    p1 <- p1 + star_layer(d, "treatment", st1$p, top)
    ggsave(file.path(M$treatment, paste0(safe_name(roi), ".png")), p1,
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
                        fill = treatment)) +
      geom_jitter(width = 0.16, height = 0, size = PT, stroke = 1.1,
                  shape = PT_SHAPE) +
      summary_layers("group4") +
      geom_text(data = n_labels(d, "group4", top),
                aes(x = x, y = y, label = sprintf("(N=%d)", n)),
                inherit.aes = FALSE, vjust = 1, size = BASE * 0.30,
                colour = "grey25") +
      scale_x_discrete(drop = FALSE, labels = axis_labeller) +
      common +
      labs(subtitle = paste0(
             sub_note,
             if (letters_shown) "; letters share = not different (Tukey)" else ""),
           caption = paste(c(st4$caption, tukey_note, cap_note,
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
    ggsave(file.path(M$phase, paste0(safe_name(roi), ".png")), p2,
           width = 12.0, height = 8.4, dpi = 200, bg = "white")
  }   # per ROI
}   # per measure

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
  pptx <- PPTX_FOR(MARKER)
  print(doc, target = pptx)
  message(sprintf("  %d slides -> %s", length(pngs), pptx))
}
