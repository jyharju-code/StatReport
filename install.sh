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
"$UV" pip install --python "$PY" "statreport @ $REPO_TARBALL"

cat > "$LAUNCHER" <<EOF
#!/bin/bash
exec "$PY" -m statreport.cli web
EOF
chmod +x "$LAUNCHER"

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
