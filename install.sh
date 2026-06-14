#!/usr/bin/env bash
#
# StatReport one-line installer for macOS.
#   curl -fsSL https://raw.githubusercontent.com/jyharju-code/StatReport/main/install.sh | bash
#
# Uses `uv` to fetch a managed Python and all dependencies (one time).
# No Xcode tools or pre-installed Python required. Creates a double-click launcher
# on your Desktop. Set STATREPORT_NO_LAUNCH=1 to install without launching.
#
# Optional rich engine: install R + Quarto to get gtsummary / modelsummary / easystats
# `report` tables and Quarto PDF/DOCX. Without them, StatReport uses its built-in
# Python engine (pandas / matplotlib / statsmodels) and renders self-contained HTML.

set -euo pipefail

REPO_TARBALL="https://github.com/jyharju-code/StatReport/archive/refs/heads/main.tar.gz"
APP_DIR="$HOME/.statreport-app"
LAUNCHER="$HOME/Desktop/StatReport.command"
PYVER="3.12"

echo "▶  Installing StatReport…"

if ! command -v uv >/dev/null 2>&1; then
  echo "   Installing uv (one-time, ~15 MB)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
UV="$(command -v uv)"

echo "   Creating environment in $APP_DIR…"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
"$UV" venv --python "$PYVER" "$APP_DIR/.venv" >/dev/null
PY="$APP_DIR/.venv/bin/python"

echo "   Downloading and installing dependencies (one time)…"
"$UV" pip install --python "$PY" "statreport[desktop] @ $REPO_TARBALL"

cat > "$LAUNCHER" <<EOF
#!/bin/bash
exec "$PY" -m statreport.cli web
EOF
chmod +x "$LAUNCHER"

# Optional rich R engine. Set STATREPORT_WITH_R=1 to auto-install R + pandoc (via Homebrew)
# and the R packages (gtsummary, modelsummary, easystats `report`, ggplot2, …).
if [ "${STATREPORT_WITH_R:-}" = "1" ]; then
  echo "   Setting up the rich R engine (STATREPORT_WITH_R=1)…"
  if ! command -v Rscript >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
    echo "   Installing R + pandoc via Homebrew…"
    brew install r pandoc || true
  fi
  if command -v Rscript >/dev/null 2>&1; then
    "$PY" -m statreport.cli setup-r || true
    echo "   (For polished PDF/DOCX, also install Quarto: brew install --cask quarto)"
  else
    echo "   R not found and Homebrew unavailable. Install R from https://cloud.r-project.org,"
    echo "   then run:  statreport setup-r"
  fi
fi

echo ""
echo "✓  Installed."
echo "   → Double-click 'StatReport.command' on your Desktop to start it."
echo "   → It opens in your browser. Add a free Gemini API key in the app"
echo "     (Settings panel). Get one at https://aistudio.google.com/apikey"
echo "   → Optional: install R + Quarto for the rich R report engine."
echo ""

if [ "${STATREPORT_NO_LAUNCH:-}" != "1" ]; then
  echo "Launching StatReport now…"
  exec "$PY" -m statreport.cli web
fi
