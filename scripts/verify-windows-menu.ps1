#requires -Version 7.0
param(
    [switch]$Elevate,
    [switch]$CloseExisting,
    [ValidateSet('windows_native','windows_sendinput')]
    [string]$Backend = 'windows_sendinput'
)
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$log = Join-Path $repo 'reports/windows-probe/menu-verification.log'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$admin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($Elevate -and -not $admin) {
    # Use the normal Windows consent flow, not a policy change or silent broker.
    $childArgs = '-NoProfile -File "{0}" -Backend {1}' -f $PSCommandPath, $Backend
    if ($CloseExisting) { $childArgs += ' -CloseExisting' }
    $child = Start-Process -FilePath (Get-Command pwsh.exe).Source -Verb RunAs -WindowStyle Hidden -ArgumentList $childArgs -PassThru
    $child.WaitForExit()
    if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log }
    exit $child.ExitCode
}
$null = New-Item -ItemType Directory -Path (Split-Path $log) -Force
Push-Location -LiteralPath $repo
try {
    $checkArgs = @('tools/check_dmm_menu.py', '--backend', $Backend)
    if ($CloseExisting) { $checkArgs += '--close-existing' }
    "Input backend: $Backend; administrator: $admin; close-existing: $CloseExisting" | Set-Content -LiteralPath $log -Encoding utf8
    & .venv/Scripts/python.exe @checkArgs *>> $log
    $result = $LASTEXITCODE
    Add-Content -LiteralPath $log -Value "EXIT_CODE=$result" -Encoding utf8
    Get-Content -LiteralPath $log
    exit $result
} finally { Pop-Location }
