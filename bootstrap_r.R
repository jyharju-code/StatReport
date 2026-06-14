#!/usr/bin/env Rscript
# bootstrap_r.R — install the R packages StatReport's rich engine uses.
#
#   Rscript bootstrap_r.R          # or, equivalently:  statreport setup-r
#
# Required for the R engine at all : jsonlite, ggplot2
# Ready report tooling (optional)  : gtsummary, modelsummary, report, janitor
# Extra data formats (optional)    : readxl, arrow, DBI, RSQLite
# Anything not installed is simply skipped at runtime — the engine degrades gracefully.

pkgs <- c("jsonlite", "ggplot2",
          "gtsummary", "modelsummary", "report", "janitor",
          "readxl", "arrow", "DBI", "RSQLite")

missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) {
  cat("Installing:", paste(missing, collapse = ", "), "\n")
  install.packages(missing, repos = "https://cloud.r-project.org")
} else {
  cat("All StatReport R packages already installed.\n")
}
for (p in pkgs) cat(sprintf("%-12s %s\n", p, requireNamespace(p, quietly = TRUE)))
