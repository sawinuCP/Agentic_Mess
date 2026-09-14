# Runs the same quality gates as CI, locally, from the repo root.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\check.ps1
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Virtualenv not found at $python. See DEVELOPMENT.md setup steps."
}

& $python -m ruff check (Join-Path $root "services/api")
& $python -m ruff format --check (Join-Path $root "services/api")

Push-Location (Join-Path $root "services/api")
try {
    & $python -m mypy
    & $python -m pytest -q
}
finally {
    Pop-Location
}
