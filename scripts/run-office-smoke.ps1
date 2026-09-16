# Starts the API stack, then runs the Phase-9 office UI smoke end to end.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\run-office-smoke.ps1
$ErrorActionPreference = "Continue"
$env:HARNESS_TEMPORAL_ENABLED = "true"
$root = Split-Path -Parent $PSScriptRoot

$w = Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
    -ArgumentList '-u', '-m', 'app.durable.worker' `
    -WorkingDirectory "$root\services\api" -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$root\tmp-w.log" -RedirectStandardError "$root\tmp-we.log"
$a = Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', '8000' `
    -WorkingDirectory "$root\services\api" -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$root\tmp-a.log" -RedirectStandardError "$root\tmp-ae.log"
Start-Sleep -Seconds 15

& "$root\.venv\Scripts\python.exe" "$root\scripts\smoke_office.py"
$exit = $LASTEXITCODE

Stop-Process -Id $w.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $a.Id -Force -ErrorAction SilentlyContinue
Remove-Item "$root\tmp-*.log" -ErrorAction SilentlyContinue
Write-Host "office smoke exit: $exit"
