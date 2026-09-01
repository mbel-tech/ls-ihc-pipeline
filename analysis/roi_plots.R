# Shared plotting for the ROI datasets.
#
# Sourced by plot_by_sample.R and plot_by_slide.R, which differ only in which
# workbook they open and what one row means. Keeping the plotting here means the
# two figures are drawn by the same code and stay comparable; the alternative
# was two near-identical scripts that drift the first time one is edited.
#
# Needs: readxl, ggplot2. Both were present in R 4.6.0 on this machine.

suppressPackageStartupMessages({
  ok <- requireNamespace("readxl", quietly = TRUE) &&
        requireNamespace("ggplot2", quietly = TRUE)
})
if (!ok) {
  stop("needs readxl and ggplot2:\n  install.packages(c(\"readxl\", \"ggplot2\"))")
}
library(readxl)
library(ggplot2)

RESULTS_DEFAULT <- "D:/LS-analysis/results"

# WHICH MARKER THESE FIGURES ARE ABOUT.
#
# The sheets carry one row per (sample|slide, MARKER, ROI). A figure that does
# not filter would draw AF568 and AF488 points into the same panel as if they
# were replicates of one measure - two different antibodies sharing a mean bar,
# an SEM bar and a significance test - and roi_stats.R would silently flip from
# lm to lmer for the ROIs that currently have one row per animal, because a
# second marker looks exactly like a second slide to `needs_mixed()`.
#
# Nothing would error. So the filter is applied centrally, in load_sheet, where
# all three entry points pass through, rather than left to each of them.
#
# Override with LS_MARKER=AF488 in the environment.
MARKER <- Sys.getenv("LS_MARKER", "AF568")
MARKER_LABEL <- c(AF568 = "pERK", AF488 = "PCNA")

marker_label <- function(m = MARKER) {
  # Single brackets and is.na, NOT [[ ]]: double-bracket lookup of an unknown
  # name on a named character vector THROWS rather than returning NULL, so the
  # fallback below was unreachable and an unrecognised marker would have failed
  # with "subscript out of bounds" instead of printing its own id.
  lbl <- MARKER_LABEL[m]
  if (is.na(lbl)) m else unname(lbl)
}

# Filter any per-section table to the marker in play.
#
# Shared because `detector_specificity.csv` needs exactly what the sheets need
# and got it wrong by being a separate read: it is not a sheet, so it did not
# pass through load_sheet, and the false-positive rate printed on every pERK
# positivity figure would have had PCNA's sections folded into it.
filter_marker <- function(df, what, require_rows = FALSE) {
  if (!"marker" %in% names(df)) {
    # A file written before the marker column existed is all AF568. Saying so
    # is fine when AF568 is what was asked for; handing it back for AF488 would
    # caption a PCNA figure with pERK data, which is the whole failure mode.
    if (MARKER != "AF568") {
      stop(sprintf(paste0("%s has no marker column, so it is all AF568 - ",
                          "cannot serve %s.\n  Rebuild with 06c/06d."),
                   what, MARKER))
    }
    message(sprintf("  %s has no marker column - treating it as AF568 (pERK)", what))
    return(df)
  }
  have <- sort(unique(df$marker[!is.na(df$marker)]))
  out <- df[!is.na(df$marker) & df$marker == MARKER, , drop = FALSE]
  if (require_rows && !nrow(out)) {
    stop(sprintf("no %s rows in %s (it has: %s).\n  Set LS_MARKER to one of them.",
                 MARKER, what, paste(have, collapse = ", ")))
  }
  if (length(have) > 1) {
    message(sprintf("  marker %s (%s) - %s also present and excluded",
                    MARKER, marker_label(),
                    paste(setdiff(have, MARKER), collapse = ", ")))
  }
  out
}

# Colour-blind safe, and deliberately not red/green.
TREATMENT_COLOURS <- c(control = "#4C72B0", exercise = "#DD8452")

load_sheet <- function(path, sheet) {
  if (!file.exists(path)) {
    stop(sprintf("no dataset at %s\n  build it with: python scripts/%s",
                 path,
                 if (grepl("by_slide", path)) "06d_excel_by_slide.py"
                 else "06c_excel_dataset.py"))
  }
  df <- as.data.frame(readxl::read_excel(path, sheet = sheet))
  # ONE marker per figure, via the shared rule - this used to reimplement it
  # inline with different messages, which is two versions of one decision.
  df <- filter_marker(df, basename(path), require_rows = TRUE)

  df <- df[!is.na(df$treatment) & df$treatment != "", ]
  df$treatment <- factor(df$treatment, levels = names(TREATMENT_COLOURS))
  # Longest region names first would reorder the panels arbitrarily; sort by how
  # much data each region has, so the well-covered ones are read first.
  n_by_roi <- sort(table(df$ROI), decreasing = TRUE)
  df$ROI <- factor(df$ROI, levels = names(n_by_roi))
  df
}

# One panel per ROI, one point per row, coloured by treatment.
#
# The point is the unit the dataset is keyed by - a sample in one file, a slide
# in the other - so the two figures answer different questions with the same
# picture: how far apart the arms are, and how much of that is spread within an
# animal.
plot_by_roi <- function(df, value, ylab, subtitle, outfile, point_size = 2.6) {
  if (!value %in% names(df)) stop(sprintf("no column '%s' in the sheet", value))
  df <- df[is.finite(df[[value]]), ]
  if (!nrow(df)) stop("nothing to plot - is the detection run still empty?")

  p <- ggplot(df, aes(x = treatment, y = .data[[value]], colour = treatment)) +
    # A mean line behind the points, so a panel with three points either side is
    # readable without squinting. Drawn first so points sit on top of it.
    stat_summary(fun = mean, geom = "crossbar", width = 0.5,
                 linewidth = 0.35, colour = "grey35", alpha = 0.9) +
    geom_jitter(width = 0.14, height = 0, size = point_size, alpha = 0.85) +
    facet_wrap(~ ROI, scales = "free_y") +
    scale_colour_manual(values = TREATMENT_COLOURS, drop = FALSE) +
    # Counts start at zero and the reader will compare heights, so the axis has
    # to include it - a free y-axis that starts at the smallest point would
    # exaggerate every difference in the figure.
    expand_limits(y = 0) +
    labs(x = NULL, y = ylab, colour = NULL, subtitle = subtitle) +
    theme_minimal(base_size = 11) +
    theme(legend.position = "top",
          panel.grid.minor = element_blank(),
          strip.text = element_text(face = "bold", size = 9))

  ggsave(paste0(outfile, ".png"), p, width = 10, height = 7, dpi = 200)
  ggsave(paste0(outfile, ".pdf"), p, width = 10, height = 7)
  message(sprintf("  wrote %s.png and .pdf", outfile))
  invisible(p)
}

# What is actually in each panel. Printed rather than assumed, because with a
# partial detection run a panel can hold one point per arm and still look like
# a comparison.
report_n <- function(df, unit) {
  message(sprintf("\n  points per panel (%s):", unit))
  tab <- table(df$ROI, df$treatment)
  w <- max(nchar(rownames(tab)))
  message(sprintf("    %-*s %s", w, "ROI",
                  paste(sprintf("%9s", colnames(tab)), collapse = "")))
  for (r in rownames(tab)) {
    message(sprintf("    %-*s %s", w, r,
                    paste(sprintf("%9d", tab[r, ]), collapse = "")))
  }
  thin <- rownames(tab)[apply(tab, 1, function(x) any(x < 2))]
  if (length(thin)) {
    message(sprintf("\n  NOTE: %s %s fewer than 2 points in an arm - ",
                    paste(thin, collapse = ", "),
                    if (length(thin) == 1) "has" else "have"),
            "the panel is drawn but there is nothing to compare yet.")
  }
}
