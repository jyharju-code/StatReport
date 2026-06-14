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
uv pip install --python $Py "statreport @ $RepoTarball"

@"
@echo off
"$Py" -m statreport.cli web
"@ | Set-Content -Encoding ASCII $Launcher

Write-Host ""
Write-Host "Installed. Double-click 'StatReport.cmd' on your Desktop to start."
Write-Host "Add a free Gemini API key in the app (Settings). https://aistudio.google.com/apikey"
Write-Host ""

if ($env:STATREPORT_NO_LAUNCH -ne "1") {
  & $Py -m statreport.cli web
}
