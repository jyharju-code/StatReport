#!/bin/bash
# Double-click launcher for a source checkout: opens the native window via the local
# venv if present, else the system Python. For a real Launchpad/Spotlight app, run
# ./make_app.sh instead (builds ~/Applications/StatReport.app).
cd "$(dirname "$0")"
if [ -x ".venv/bin/statreport" ]; then
  exec ./.venv/bin/statreport web
fi
exec python3 -m statreport.cli web
