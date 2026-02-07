# Run Distro Rating Bot (PowerShell)
# Usage: .\run.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Use python from PATH; if you use venv, activate it first
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "Python not found. Install Python and add it to PATH, or activate your venv."
    exit 1
}

Write-Host "Installing dependencies..."
& $python.Source -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Starting bot..."
& $python.Source bot.py
