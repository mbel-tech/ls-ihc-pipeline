# The models behind the figure labels.
#
# Kept out of the plotting file because this is the part worth reading on its
# own: what is being tested, on which unit, and what happens when it cannot be.
#
# ONE MODEL FAMILY, fitted on SLIDE-level rows:
#
#     lmer(value ~ <fixed> + (1 | animal))
#
# The animal is the experimental unit - slides from one fish are not independent
# replicates of a treatment - but the slides carry real information about
# within-animal variability. A random intercept per animal uses that without
# claiming 33 fish. Fitting a plain aov() on slides instead would roughly treble
# the apparent sample size and every p value with it.
#
# CORRECTED AND RAW ARE NEVER COMPARED. They are the same animals measured two
# ways, so each gets its own fit and its own letters.
#
# WHEN A FIT FAILS IT SAYS SO. Cells here are 3/2/3/3 animals, singular fits are
# expected, and a ROI can have a group with no slides at all - in which case the
# interaction is inestimable. Every fit is wrapped, and the failure becomes the
# label. A caption that quietly disappears looks like a figure nobody tested.

suppressPackageStartupMessages({
  have <- vapply(c("lme4", "lmerTest", "emmeans", "multcomp", "multcompView"),
                 requireNamespace, logical(1), quietly = TRUE)
})
if (!all(have)) {
  stop("needs: ", paste(names(have)[!have], collapse = ", "),
       "\n  install.packages(c(\"lme4\",\"lmerTest\",\"emmeans\",\"multcomp\",\"multcompView\"))")
}
suppressPackageStartupMessages({
  library(lmerTest)
  library(emmeans)
  library(multcomp)
})
# emmeans warns about the estimability of unbalanced cells on every call; the
# imbalance is the design, not news, and the letters already encode it.
emm_options(msg.interaction = FALSE, msg.nesting = FALSE)

# Which model the data shape actually supports.
#
# A random intercept per animal needs animals with MORE THAN ONE slide - with
# exactly one row per animal the animal effect and the residual are the same
# thing and lmer cannot separate them, so the fit fails outright. Five of the
# ten ROIs here are in that position: Vc, Vd, Vl, Vs and Vv were placed on one
# slide per fish.
#
# For those a plain lm IS the correct model, not a fallback with an asterisk:
# one observation per animal means ordinary least squares is already operating
# on the experimental unit, and it is exactly the ANOVA that was asked for.
# Reporting "could not be fitted" and drawing no test would have thrown away
# five real comparisons to protect against a problem those data do not have.
#
# The caption says which was used, because it changes how the df read.
needs_mixed <- function(d) {
  per <- table(d$sample)
  length(per) > 1 && max(per) > 1
}

fit_model <- function(form_fixed, d) {
  mixed <- needs_mixed(d)
  f <- if (mixed) stats::update(form_fixed, . ~ . + (1 | sample)) else form_fixed
  fit <- tryCatch(
    suppressMessages(suppressWarnings(
      if (mixed) lmerTest::lmer(f, data = d) else stats::lm(f, data = d))),
    error = function(e) NULL)
  list(fit = fit, mixed = mixed)
}

# anova() shapes differ between lm and lmer, so the F line is read from whichever
# came back rather than assuming lmerTest's column names.
fmt_p <- function(p) {
  if (!is.finite(p)) return("p = n/a")
  if (p < 0.001) "p < 0.001" else sprintf("p = %.3f", p)
}

# A one-line F test from a fitted lmer, for a named fixed term.
#
# Denominator df comes from Satterthwaite (lmerTest's default) and is worth
# looking at: it should land near the number of ANIMALS. If it reports the
# number of SLIDES, the random effect is not doing its job and the result is
# pseudoreplicated.
term_line <- function(fit, term, label = term) {
  a <- tryCatch(anova(fit), error = function(e) NULL)
  if (is.null(a) || !term %in% rownames(a)) {
    return(sprintf("%s: not estimable", label))
  }
  row <- a[term, ]
  # Degrees of freedom go in a SUBSCRIPT with no brackets - F<sub>1,6.0</sub> -
  # which is the convention in print and is what ggtext's element_markdown()
  # renders. Everything downstream that shows a caption has to use
  # element_markdown, or these tags appear as literal text.
  if ("DenDF" %in% colnames(a)) {          # lmerTest
    dfd <- row[["DenDF"]]
    out <- sprintf("%s: F<sub>%.0f,%.1f</sub> = %.2f, %s", label,
                   row[["NumDF"]], dfd, row[["F value"]],
                   fmt_p(row[["Pr(>F)"]]))
  } else {                                  # lm
    dfd <- a["Residuals", "Df"]
    out <- sprintf("%s: F<sub>%.0f,%.0f</sub> = %.2f, %s", label,
                   row[["Df"]], dfd, row[["F value"]],
                   fmt_p(row[["Pr(>F)"]]))
  }
  # Flag a p value nobody should act on. Vc raw came back F(1,1) = 915,
  # p = 0.021 while the corrected measure on the SAME animals gave p = 0.120 -
  # on one residual degree of freedom the estimate is essentially unconstrained
  # and a small p means almost nothing. Printing it without this reads as a
  # finding.
  if (is.finite(dfd) && dfd < 3) out <- paste(out, "(df too low to interpret)")
  out
}

# --------------------------------------------------------------- series 1
# density ~ treatment, one caption line per measure.
stat_treatment <- function(d) {
  n_an <- length(unique(d$sample))
  if (n_an < 3 || length(unique(d$treatment)) < 2) {
    return(sprintf("no test: %d animal%s in %d treatment group%s",
                   n_an, if (n_an == 1) "" else "s",
                   length(unique(d$treatment)),
                   if (length(unique(d$treatment)) == 1) "" else "s"))
  }
  m <- fit_model(value ~ treatment, d)
  if (is.null(m$fit)) return("no test: the model could not be fitted")
  paste0(term_line(m$fit, "treatment", "treatment"), "<br>",
         if (m$mixed) "mixed model, animal as a random effect"
         else "one slide per animal, plain ANOVA")
}

# --------------------------------------------------------------- series 2
# density ~ treatment * environment, plus Tukey letters over the four groups.
#
# Returns a list: $caption (three F lines) and $letters (a data.frame of
# group -> letter), or $letters = NULL when the model would not fit.
stat_group4 <- function(d) {
  cells <- table(droplevels(d$group4))
  present <- sum(cells > 0)
  n_an <- length(unique(d$sample))
  if (present < 2 || n_an < 4) {
    return(list(caption = sprintf("no test: %d of 4 groups present, %d animals",
                                  present, n_an),
                letters = NULL))
  }

  full <- length(unique(d$treatment)) > 1 && length(unique(d$environment)) > 1
  m <- fit_model(if (full) value ~ treatment * environment else value ~ group4, d)
  fit <- m$fit
  if (is.null(fit)) {
    return(list(caption = "no test: the model could not be fitted", letters = NULL))
  }

  # One term per line. Three F tests joined by pipes ran off the right edge of
  # the figure and had to be rescued by widening it; as lines they simply fit.
  cap <- if (full) {
    paste(term_line(fit, "treatment", "treatment"),
          term_line(fit, "environment", "environment"),
          # The first argument is the row name anova() actually uses; only the
          # second is the label shown. Changing the lookup to a prettier string
          # makes every interaction line read "not estimable".
          term_line(fit, "treatment:environment", "interaction"),
          sep = "<br>")
  } else {
    term_line(fit, "group4", "group")
  }
  # A singular fit means the animal variance collapsed to zero. The letters are
  # still computed - the fixed effects are fine - but it is said out loud,
  # because it is the model telling you the design is thin.
  cap <- paste0(cap, "<br>", if (m$mixed) "mixed model, animal as a random effect"
                             else "one slide per animal, plain ANOVA")
  if (m$mixed && isTRUE(lme4::isSingular(fit))) cap <- paste(cap, "(singular fit)")

  # THE LETTERS COME FROM THE ONE-WAY PARAMETERISATION, and that is not a second
  # analysis. `~ treatment * environment` and `~ group4` span the identical
  # design space - four cells, four parameters - so it is the same fit written
  # two ways. Comparing a single 4-level factor makes the six pairwise contrasts
  # unambiguously ONE family, which is the condition Tukey is defined for.
  #
  # emmeans prints "adjust = tukey was changed to sidak" here and it is easy to
  # misread as the letters being downgraded. They are not. The full output says
  #
  #     Conf-level adjustment: sidak method for 4 estimates
  #     P value adjustment:    tukey method for comparing a family of 4 estimates
  #
  # - Sidak applies to the confidence intervals cld also reports, which nothing
  # here uses, and the PAIRWISE p values that decide the letters are Tukey.
  lets <- tryCatch({
    fit1 <- if (full) fit_model(value ~ group4, d)$fit else fit
    em <- emmeans(fit1, ~ group4)
    cl <- as.data.frame(multcomp::cld(em, alpha = 0.05, Letters = letters,
                                      adjust = "tukey"))
    data.frame(group4 = as.character(cl$group4),
               letter = trimws(cl$.group),
               emmean = cl$emmean,
               stringsAsFactors = FALSE)
  }, error = function(e) NULL)

  if (is.null(lets)) cap <- paste(cap, "- letters unavailable")
  list(caption = cap, letters = lets)
}
