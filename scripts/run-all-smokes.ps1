# Runs the API stack once, then the full smoke battery across all phases.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\run-all-smokes.ps1
# Self-contained smokes spawn their own Vite instances on test ports; only
# smoke_office.py uses the shared dev server started here (:5173).
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
$a = Start-Process -FilePath $py -ArgumentList '-m', 'uvicorn', 'app.main:app', '--port', '8000' `
    -WorkingDirectory "$root\services\api" -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$root\tmp-a.log" -RedirectStandardError "$root\tmp-ae.log"
$v = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev -- --port 5173 --strictPort" `
    -WorkingDirectory "$root\apps\web-ui" -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$root\tmp-v.log" -RedirectStandardError "$root\tmp-ve.log"
Start-Sleep -Seconds 25

$failed = 0
$smokes = @('editor', 'durable', 'recovery', 'scheduler', 'runtime', 'integrations',
    'oversight', 'office', 'agent_office', 'command_center', 'command_palette',
    'design_tokens', 'graph', 'history', 'intelligence', 'panel_retention',
    'project_picker', 'shell_status', 'task_controls')
foreach ($name in $smokes) {
    Write-Host "=== $name ==="
    & $py "$root\scripts\smoke_$name.py" 2>&1 | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { $failed++ }
}

Stop-Process -Id $w.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $a.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $v.Id -Force -ErrorAction SilentlyContinue
Remove-Item "$root\tmp-*.log" -ErrorAction SilentlyContinue
Write-Host "smoke battery: $failed failed"
exit $failed
