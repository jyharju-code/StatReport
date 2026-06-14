#!/bin/bash
# Double-click launcher for a source checkout: runs the GUI from this folder.
cd "$(dirname "$0")"
exec python3 -m statreport.cli web
