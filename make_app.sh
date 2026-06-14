#!/usr/bin/env bash
#
# make_app.sh (macOS) — build a double-clickable StatReport.app that opens the local
# venv app in a NATIVE window (pywebview), shows in Launchpad/Spotlight/the app switcher,
# and quits when the window is closed. Also drops a `statreport` CLI shim into ~/.local/bin.
#
# Run from a source checkout whose .venv has statreport installed:
#   python3 -m venv .venv && source .venv/bin/activate && pip install -e .
#   ./make_app.sh
#
# (On Windows, use the PyInstaller build from a GitHub release instead.)

set -euo pipefail
[ "$(uname)" = "Darwin" ] || { echo "macOS only. On Windows use the PyInstaller release build."; exit 1; }

REPO="$(cd "$(dirname "$0")" && pwd)"
VENV_BIN="$REPO/.venv/bin/statreport"
if [ ! -x "$VENV_BIN" ]; then
  echo "No venv app at $VENV_BIN"
  echo "Set it up first:  python3 -m venv .venv && source .venv/bin/activate && pip install -e ."
  exit 1
fi

DEST="${1:-$HOME/Applications/StatReport.app}"
mkdir -p "$(dirname "$DEST")"

# A foreground-running applet: the launched Python inherits the applet's GUI (aqua)
# session — required for the native WKWebView window. macOS 11+ blocks plain
# shell-script .app main executables, so we compile a proper applet via osacompile.
SCRIPT="$(mktemp /tmp/statreport_launcher.XXXXXX).applescript"
cat > "$SCRIPT" <<APPLESCRIPT
do shell script "export PATH=/opt/homebrew/bin:/usr/local/bin:\$PATH; export PYTHONUNBUFFERED=1; '$VENV_BIN' web > /tmp/statreport_gui.log 2>&1"
APPLESCRIPT

rm -rf "$DEST"
osacompile -o "$DEST" "$SCRIPT"
rm -f "$SCRIPT"

# CLI shim so `statreport` works from any terminal (if ~/.local/bin is on PATH).
mkdir -p "$HOME/.local/bin"
ln -sf "$VENV_BIN" "$HOME/.local/bin/statreport"
ln -sf "$REPO/.venv/bin/statreport-web" "$HOME/.local/bin/statreport-web" 2>/dev/null || true

echo "✓ Built $DEST"
echo "  Double-click it (or:  open '$DEST'). Closing the window quits the app."
echo "✓ Linked 'statreport' into ~/.local/bin (CLI from any terminal, if that's on your PATH)."
echo "  (The branded icon ships with the PyInstaller release build; this app uses the default icon.)"
