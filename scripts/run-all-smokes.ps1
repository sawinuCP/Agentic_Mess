# Runs the API stack once, then the full smoke battery across all phases.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\run-all-smokes.ps1
$ErrorActionPreference = "Continue"
$env:HARNESS_TEMPORAL_ENABLED = "true"
# Local-dev SSRF opt-in (docs/OPERATIONS.md §2.5): the integrations smoke
# fetches localhost/healthz as its research target.
$env:HARNESS_RESEARCH_PRIVATE_HOSTS_ALLOWED = "true"
$root = Split-Path -Parent $PSScriptRoot
$py = "$root\.venv\Scripts\python.exe"

$w = Start-Process -FilePath $py -ArgumentList '-u', '-m', 'app.durable.worker' `
    -WorkingDirectory "$root\services\api" -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$root\tmp-w.log" -RedirectStandardError "$root\tmp-we.log"
$a = Start-Process -FilePath $py -ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', '8000' `
    -WorkingDirectory "$root\services\api" -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$root\tmp-a.log" -RedirectStandardError "$root\tmp-ae.log"
Start-Sleep -Seconds 15

$failed = 0
foreach ($name in @('editor', 'durable', 'recovery', 'scheduler', 'runtime', 'integrations', 'oversight', 'office')) {
    Write-Host "=== $name ==="
    & $py "$root\scripts\smoke_$name.py" 2>&1 | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { $failed++ }
}

Stop-Process -Id $w.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $a.Id -Force -ErrorAction SilentlyContinue
Remove-Item "$root\tmp-*.log" -ErrorAction SilentlyContinue
Write-Host "smoke battery: $failed failed"
