"""
rcode.py — generate the R compute script (the rich engine, used when R is present).

This is the second deterministic executor (pyengine.py is the always-available
fallback). It writes a standalone R script that:

  * reads the data with base R / readxl / arrow / RSQLite (whatever is present),
  * runs each section's analysis with ggplot2 + the broad R stats ecosystem,
    preferring the *ready report tooling* when installed (gtsummary, modelsummary,
    easystats `report`, janitor) and falling back to base R otherwise,
  * saves every figure as assets/<id>.png and every table as markdown,
  * writes results.json in the SAME shape pyengine.compute() returns,

so rengine.py, the assembler and qa.py treat both engines identically. Every
section is wrapped in tryCatch, so one failing analysis never kills the report.
"""

from __future__ import annotations

import json
from typing import List

from .recipe import ReportRecipe


def _slim_plan(recipe: ReportRecipe) -> list:
    plan = []
    for sec in recipe.sections:
        a = sec.analysis
        plan.append({
            "id": sec.id, "heading": sec.heading, "method": a.method,
            "variables": list(a.variables), "group_by": a.group_by,
            "time_var": a.time_var, "options": a.options or {},
        })
    return plan


# The fixed R helper + method library, shared by every generated script.
_R_LIBRARY = r"""
options(warn = -1)
suppressMessages({ library(jsonlite); library(ggplot2) })

has <- function(pkg) requireNamespace(pkg, quietly = TRUE)
n4  <- function(x) { x <- suppressWarnings(as.numeric(x)); ifelse(is.finite(x), round(x, 4), NA) }

save_gg <- function(p, id) {
  fp <- file.path(ASSETS_DIR, paste0(id, ".png"))
  suppressMessages(ggsave(fp, p, width = 6.8, height = 3.8, dpi = 120))
  file.path("assets", paste0(id, ".png"))
}

df_to_md <- function(d, rowname = "") {
  d <- as.data.frame(d)
  cols <- colnames(d)
  rn <- rownames(d)
  has_rn <- !is.null(rn) && !identical(rn, as.character(seq_len(nrow(d))))
  fmtcell <- function(x) if (is.numeric(x)) formatC(x, format = "g", digits = 5) else as.character(x)
  header <- if (has_rn) c(rowname, cols) else cols
  sep <- rep("---", length(header))
  lines <- c(paste0("| ", paste(header, collapse = " | "), " |"),
             paste0("| ", paste(sep, collapse = " | "), " |"))
  for (i in seq_len(nrow(d))) {
    cells <- vapply(seq_along(cols), function(j) fmtcell(d[i, j]), character(1))
    if (has_rn) cells <- c(rn[i], cells)
    lines <- c(lines, paste0("| ", paste(cells, collapse = " | "), " |"))
  }
  paste(lines, collapse = "\n")
}

numcols <- function(df, vars) {
  nums <- names(df)[vapply(df, is.numeric, logical(1))]
  pref <- intersect(vars, nums)
  if (length(pref)) pref else nums
}

m_descriptive <- function(df, vars, grp, tvar, opt, id) {
  nums <- numcols(df, vars)
  numbers <- list(rows = nrow(df), columns = ncol(df),
                  missing_cells = sum(is.na(df)))
  tbl_md <- NA
  if (length(nums)) {
    stat <- data.frame(
      mean   = sapply(df[nums], function(x) n4(mean(x, na.rm = TRUE))),
      sd     = sapply(df[nums], function(x) n4(sd(x, na.rm = TRUE))),
      min    = sapply(df[nums], function(x) n4(min(x, na.rm = TRUE))),
      median = sapply(df[nums], function(x) n4(median(x, na.rm = TRUE))),
      max    = sapply(df[nums], function(x) n4(max(x, na.rm = TRUE))))
    tbl_md <- df_to_md(stat, "variable")
    for (c in nums) {
      numbers[[paste0(c, "_mean")]]   <- n4(mean(df[[c]], na.rm = TRUE))
      numbers[[paste0(c, "_median")]] <- n4(median(df[[c]], na.rm = TRUE))
    }
  }
  list(figure = NULL, table_markdown = tbl_md, numbers = numbers,
       summary = sprintf("%d rows, %d columns, %d missing cells.",
                         nrow(df), ncol(df), sum(is.na(df))))
}

m_distribution <- function(df, vars, grp, tvar, opt, id) {
  v <- numcols(df, vars)[1]; x <- df[[v]]
  p <- ggplot(data.frame(x = x), aes(x)) +
       geom_histogram(bins = 30, fill = "#6f8cff", alpha = .85) +
       labs(title = paste("Distribution of", v), x = v, y = "count")
  fig <- save_gg(p, id)
  sk <- mean((x - mean(x, na.rm = TRUE))^3, na.rm = TRUE) / sd(x, na.rm = TRUE)^3
  numbers <- setNames(list(n4(mean(x, na.rm = TRUE)), n4(sd(x, na.rm = TRUE)),
                           n4(min(x, na.rm = TRUE)), n4(max(x, na.rm = TRUE)), n4(sk)),
                      paste0(v, c("_mean", "_std", "_min", "_max", "_skew")))
  list(figure = fig, table_markdown = NA, numbers = numbers,
       summary = sprintf("%s: mean %s, std %s.", v, numbers[[paste0(v,"_mean")]],
                         numbers[[paste0(v,"_std")]]))
}

m_correlation <- function(df, vars, grp, tvar, opt, id) {
  nums <- numcols(df, vars)
  cm <- cor(df[nums], use = "pairwise.complete.obs")
  long <- expand.grid(a = rownames(cm), b = colnames(cm))
  long$r <- as.vector(cm)
  p <- ggplot(long, aes(a, b, fill = r)) + geom_tile() +
       scale_fill_gradient2(low = "#6f8cff", mid = "white", high = "#ff9d3c", limits = c(-1, 1)) +
       labs(title = "Correlation matrix", x = NULL, y = NULL) +
       theme(axis.text.x = element_text(angle = 45, hjust = 1))
  fig <- save_gg(p, id)
  numbers <- list(); pairs <- list()
  for (i in seq_along(nums)) for (j in seq_along(nums)) if (j > i) {
    pairs[[length(pairs) + 1]] <- list(a = nums[i], b = nums[j], r = n4(cm[i, j]))
  }
  pairs <- pairs[order(-abs(sapply(pairs, function(p) p$r)))]
  for (p2 in head(pairs, 6)) numbers[[paste0("corr_", p2$a, "_", p2$b)]] <- p2$r
  top <- if (length(pairs)) pairs[[1]] else NULL
  list(figure = fig, table_markdown = df_to_md(round(cm, 2), "variable"), numbers = numbers,
       summary = if (!is.null(top)) sprintf("Strongest correlation: %s vs %s = %s.",
                                            top$a, top$b, top$r) else "")
}

m_comparison <- function(df, vars, grp, tvar, opt, id) {
  v <- vars[[1]]
  agg <- aggregate(df[[v]], list(group = df[[grp]]),
                   function(x) c(mean = mean(x, na.rm = TRUE), n = length(x)))
  res <- data.frame(group = agg$group, mean = n4(agg$x[, "mean"]), n = agg$x[, "n"])
  res <- res[order(-res$mean), ]
  p <- ggplot(res, aes(reorder(group, -mean), mean)) +
       geom_col(fill = "#ff9d3c") +
       labs(title = paste("Mean", v, "by", grp), x = grp, y = paste("mean", v)) +
       theme(axis.text.x = element_text(angle = 45, hjust = 1))
  fig <- save_gg(p, id)
  numbers <- setNames(as.list(res$mean), paste0(v, "_mean_", res$group))
  list(figure = fig, table_markdown = df_to_md(res), numbers = numbers,
       summary = sprintf("Highest mean %s: %s (%s); lowest: %s (%s).",
                         v, res$group[1], res$mean[1],
                         res$group[nrow(res)], res$mean[nrow(res)]))
}

m_trend <- function(df, vars, grp, tvar, opt, id) {
  v <- numcols(df, vars)[1]
  d <- df
  if (!is.null(tvar)) { d[[tvar]] <- as.Date(as.character(d[[tvar]])); d <- d[order(d[[tvar]]), ] ; x <- d[[tvar]] }
  else x <- seq_len(nrow(d))
  y <- d[[v]]
  p <- ggplot(data.frame(x = x, y = y), aes(x, y)) + geom_line(color = "#3fd6b0") +
       labs(title = paste(v, "over time"), x = NULL, y = v)
  fig <- save_gg(p, id)
  first <- n4(y[1]); last <- n4(y[length(y)])
  pct <- if (!is.na(first) && first != 0) n4((last - first) / first * 100) else NA
  numbers <- setNames(list(first, last, n4(last - first), pct),
                      paste0(v, c("_first", "_last", "_change", "_pct_change")))
  list(figure = fig, table_markdown = NA, numbers = numbers,
       summary = sprintf("%s moved from %s to %s (%s%% change).", v, first, last, pct))
}

m_crosstab <- function(df, vars, grp, tvar, opt, id) {
  cols <- unique(c(unlist(vars), if (!is.null(grp)) grp))
  ct <- table(df[[cols[1]]], df[[cols[2]]])
  m <- as.data.frame.matrix(ct)
  long <- expand.grid(a = rownames(m), b = colnames(m)); long$n <- as.vector(as.matrix(m))
  p <- ggplot(long, aes(b, a, fill = n)) + geom_tile() +
       scale_fill_gradient(low = "white", high = "#6f8cff") +
       labs(title = paste(cols[1], "x", cols[2]), x = cols[2], y = cols[1])
  fig <- save_gg(p, id)
  list(figure = fig, table_markdown = df_to_md(m, cols[1]),
       numbers = list(total = sum(ct)),
       summary = sprintf("Cross-tabulation of %s and %s.", cols[1], cols[2]))
}

m_regression <- function(df, vars, grp, tvar, opt, id) {
  nums <- numcols(df, vars)
  y <- nums[1]; xs <- if (length(vars) >= 2) nums[-1] else setdiff(nums, y)
  f <- as.formula(paste0("`", y, "` ~ ", paste0("`", xs, "`", collapse = " + ")))
  fit <- lm(f, data = df)
  s <- summary(fit)
  coef <- data.frame(coef = n4(coef(fit)), p_value = n4(s$coefficients[, 4]))
  summ <- sprintf("OLS on %s: R^2 = %s (n = %d).", y, n4(s$r.squared), length(fit$fitted.values))
  if (has("report")) summ <- tryCatch(paste(as.character(report::report(fit)), collapse = " "),
                                       error = function(e) summ)
  tbl <- df_to_md(coef, "term")
  if (has("modelsummary")) tbl <- tryCatch(
    modelsummary::modelsummary(fit, output = "markdown", gof_map = c("r.squared", "nobs")),
    error = function(e) tbl)
  p <- ggplot(data.frame(pred = fit$fitted.values, act = fit$model[[1]]), aes(pred, act)) +
       geom_point(color = "#6f8cff", alpha = .6) +
       geom_abline(color = "#ff9d3c") + labs(title = paste("OLS:", y), x = "predicted", y = "actual")
  fig <- save_gg(p, id)
  numbers <- list(r_squared = n4(s$r.squared), adj_r_squared = n4(s$adj.r.squared),
                  n_obs = length(fit$fitted.values))
  for (nm in names(coef(fit))) numbers[[paste0("coef_", nm)]] <- n4(coef(fit)[[nm]])
  list(figure = fig, table_markdown = as.character(tbl), numbers = numbers, summary = summ)
}

m_timeseries_forecast <- function(df, vars, grp, tvar, opt, id) {
  v <- numcols(df, vars)[1]
  d <- df
  if (!is.null(tvar)) { d[[tvar]] <- as.Date(as.character(d[[tvar]])); d <- d[order(d[[tvar]]), ] }
  y <- as.numeric(d[[v]]); y <- y[!is.na(y)]
  h <- tryCatch(as.integer(opt$horizon), error = function(e) 6L); if (is.na(h)) h <- 6L
  idx <- seq_along(y); fit <- lm(y ~ idx)
  fut <- (length(y) + 1):(length(y) + h)
  fc <- as.numeric(predict(fit, newdata = data.frame(idx = fut)))
  p <- ggplot() +
       geom_line(aes(idx, y), color = "#3fd6b0") +
       geom_line(aes(fut, fc), color = "#ff9d3c", linetype = "dashed") +
       labs(title = sprintf("%s: linear-trend forecast (+%d)", v, h), x = NULL, y = v)
  fig <- save_gg(p, id)
  numbers <- list(trend_slope = n4(coef(fit)[["idx"]]), horizon = h,
                  forecast_last = n4(tail(fc, 1)), current_last = n4(tail(y, 1)))
  list(figure = fig, table_markdown = NA, numbers = numbers,
       summary = sprintf("Linear-trend forecast for %s: %s now -> %s in %d periods.",
                         v, numbers$current_last, numbers$forecast_last, h))
}

DISPATCH <- list(descriptive = m_descriptive, distribution = m_distribution,
                 correlation = m_correlation, comparison = m_comparison, trend = m_trend,
                 crosstab = m_crosstab, regression = m_regression,
                 timeseries_forecast = m_timeseries_forecast)

read_data <- function(path) {
  ext <- tolower(tools::file_ext(path))
  if (ext == "csv") return(read.csv(path, check.names = FALSE, stringsAsFactors = FALSE))
  if (ext %in% c("tsv", "txt")) return(read.delim(path, check.names = FALSE, stringsAsFactors = FALSE))
  if (ext %in% c("xlsx", "xls")) { if (!has("readxl")) stop("readxl not installed"); return(as.data.frame(readxl::read_excel(path))) }
  if (ext == "parquet") { if (!has("arrow")) stop("arrow not installed"); return(as.data.frame(arrow::read_parquet(path))) }
  if (ext == "json") return(as.data.frame(jsonlite::fromJSON(path)))
  if (ext %in% c("sqlite", "db", "sqlite3")) {
    if (!has("DBI") || !has("RSQLite")) stop("DBI/RSQLite not installed")
    con <- DBI::dbConnect(RSQLite::SQLite(), path); on.exit(DBI::dbDisconnect(con))
    t <- DBI::dbListTables(con)[1]; return(DBI::dbReadTable(con, t))
  }
  stop(paste("unsupported:", ext))
}
"""

_R_RUNNER = r"""
df <- read_data(DATA_PATH)
results <- list(engine = "r",
                dataset = list(rows = nrow(df), cols = ncol(df), columns = as.list(names(df))),
                sections = list())
plan <- fromJSON(PLAN_JSON, simplifyVector = FALSE)
for (sec in plan) {
  fn <- DISPATCH[[sec$method]]; if (is.null(fn)) fn <- m_descriptive
  res <- tryCatch({
      r <- fn(df, sec$variables, sec$group_by, sec$time_var, sec$options, sec$id)
      r$ok <- TRUE; r$error <- NULL; r
    }, error = function(e) list(ok = FALSE, error = substr(conditionMessage(e), 1, 300),
                                figure = NULL, table_markdown = NA, numbers = list(), summary = ""))
  res$method <- sec$method; res$heading <- sec$heading
  results$sections[[sec$id]] <- res
}
write_json(results, RESULTS_PATH, auto_unbox = TRUE, na = "null", null = "null", pretty = TRUE)
cat("STATREPORT_OK\n")
"""


def _r_str(s: str) -> str:
    return json.dumps(s)  # valid R string literal too (double-quoted, escaped)


def build_compute_r(recipe: ReportRecipe, data_path: str, assets_dir: str,
                    results_path: str) -> str:
    plan_json = json.dumps(_slim_plan(recipe))
    header = (
        f"ASSETS_DIR <- {_r_str(assets_dir)}\n"
        f"dir.create(ASSETS_DIR, showWarnings = FALSE, recursive = TRUE)\n"
        f"DATA_PATH <- {_r_str(data_path)}\n"
        f"RESULTS_PATH <- {_r_str(results_path)}\n"
        f"PLAN_JSON <- {_r_str(plan_json)}\n"
    )
    return header + _R_LIBRARY + _R_RUNNER


# packages the rich path *uses if present* (none are hard requirements beyond the first two)
RECOMMENDED_R_PACKAGES: List[str] = [
    "jsonlite", "ggplot2",          # required for the R engine at all
    "gtsummary", "modelsummary", "report", "janitor",  # ready report tooling, optional
    "readxl", "arrow", "DBI", "RSQLite",               # extra data formats, optional
]
