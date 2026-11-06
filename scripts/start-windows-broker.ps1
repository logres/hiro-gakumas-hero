#requires -Version 7.0
param([switch]$Worker)
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $repo
if (-not $Worker) {
    # A successful authenticated health check reuses the current broker.
    & .venv/Scripts/python.exe -m hiro.platforms.windows.broker status 2>$null
    if ($LASTEXITCODE -eq 0) { exit 0 }
    $statePath = Join-Path $repo 'reports/windows-broker/session.json'
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if (Get-Process -Id $state.pid -ErrorAction SilentlyContinue) {
            throw 'Existing broker PID is still alive but health check failed. Inspect it before starting another.'
        }
        Remove-Item -LiteralPath $statePath
    }
    $arguments = '-NoProfile -File "{0}" -Worker' -f $PSCommandPath
    $process = Start-Process -FilePath (Get-Command pwsh.exe).Source -Verb RunAs -WindowStyle Hidden -ArgumentList $arguments -PassThru
    Write-Host "Broker launcher PID: $($process.Id). Waiting for authenticated readiness..."
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        & .venv/Scripts/python.exe -m hiro.platforms.windows.broker status 2>$null
        if ($LASTEXITCODE -eq 0) { exit 0 }
        if ($process.HasExited) { throw 'Broker exited; inspect reports/windows-broker-start.log' }
    }
    throw 'Broker readiness timed out. Inspect its process and log before restarting.'
}
$null = New-Item -ItemType Directory -Path 'reports' -Force
& .venv/Scripts/python.exe -m hiro.platforms.windows.broker_server *> reports/windows-broker-start.log
exit $LASTEXITCODE
