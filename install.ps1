# StatReport one-line installer for Windows (PowerShell).
#   irm https://raw.githubusercontent.com/jyharju-code/StatReport/main/install.ps1 | iex
#
# Uses `uv` to fetch a managed Python and all dependencies (one time).
# Optional rich engine: install R + Quarto for gtsummary/modelsummary/report + Quarto PDF/DOCX.

$ErrorActionPreference = "Stop"
$RepoTarball = "https://github.com/jyharju-code/StatReport/archive/refs/heads/main.tar.gz"
$AppDir = "$HOME\.statreport-app"
$Launcher = "$HOME\Desktop\StatReport.cmd"
$PyVer = "3.12"

Write-Host "Installing StatReport..."

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "  Installing uv (one-time)..."
  irm https://astral.sh/uv/install.ps1 | iex
}
$env:Path = "$HOME\.local\bin;$HOME\.cargo\bin;$env:Path"

if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
uv venv --python $PyVer "$AppDir\.venv"
$Py = "$AppDir\.venv\Scripts\python.exe"

Write-Host "  Installing dependencies (one time)..."
uv pip install --python $Py "statreport[desktop] @ $RepoTarball"

@"
@echo off
"$Py" -m statreport.cli web
"@ | Set-Content -Encoding ASCII $Launcher

# Optional rich R engine. Set STATREPORT_WITH_R=1 to auto-install R (via winget) + R packages.
if ($env:STATREPORT_WITH_R -eq "1") {
  Write-Host "  Setting up the rich R engine (STATREPORT_WITH_R=1)..."
  if (-not (Get-Command Rscript -ErrorAction SilentlyContinue) -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    winget install --silent --accept-package-agreements --accept-source-agreements RProject.R
    winget install --silent --accept-package-agreements --accept-source-agreements JohnMacFarlane.Pandoc
  }
  if (Get-Command Rscript -ErrorAction SilentlyContinue) {
    & $Py -m statreport.cli setup-r
    Write-Host "  (For polished PDF/DOCX, also install Quarto: https://quarto.org)"
  } else {
    Write-Host "  R not found. Install it from https://cloud.r-project.org, then run: statreport setup-r"
  }
}

Write-Host ""
Write-Host "Installed. Double-click 'StatReport.cmd' on your Desktop to start."
Write-Host "Add a free Gemini API key in the app (Settings). https://aistudio.google.com/apikey"
Write-Host ""

if ($env:STATREPORT_NO_LAUNCH -ne "1") {
  & $Py -m statreport.cli web
}
