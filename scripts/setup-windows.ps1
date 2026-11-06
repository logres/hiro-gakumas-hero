#requires -Version 7.0
<#!
.SYNOPSIS
Install the Windows development/OCR environment; does not launch or control a game.
#>
[CmdletBinding()]
param([switch]$Regen)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
if (-not $IsWindows) { throw 'Run this script in PowerShell 7 on Windows.' }

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program exited with code $LASTEXITCODE" }
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$kaaRoot = Join-Path $repoRoot 'vendor/kaa'
$python = Join-Path $repoRoot '.venv/Scripts/python.exe'
foreach ($command in @('git', 'uv')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Required command missing: $command" }
}
Push-Location $repoRoot
try {
    Invoke-Checked -Program git -Arguments @('submodule', 'update', '--init', 'vendor/kaa')
    if (-not (Test-Path -LiteralPath $python)) {
        Invoke-Checked -Program uv -Arguments @('venv', '--python', '3.10', (Join-Path $repoRoot '.venv'))
    }
    Invoke-Checked -Program $python -Arguments @('-c', 'import sys; assert sys.version_info[:2] == (3, 10), "Existing .venv must use Python 3.10; select another environment explicitly instead of overwriting it"')

    # uv pip does not resolve [tool.uv.sources]; pass the fixed local submodule explicitly.
    Invoke-Checked -Program uv -Arguments @('pip', 'install', '--python', $python, '-e', $kaaRoot, '-e', "${repoRoot}[dev]")

    $generatedCode = Join-Path $kaaRoot 'kaa/tasks/R.py'
    if ($Regen -or -not (Test-Path -LiteralPath $generatedCode)) {
        Push-Location $kaaRoot
        try {
            # Upstream deletes OUTPUT_IMG_DIR recursively. Verify exact constants,
            # resolved paths (including junctions), and ignored/untracked outputs first.
            $validate = @'
import ast
from pathlib import Path
import subprocess
root = Path.cwd().resolve()
script = root / 'tools/make_resources.py'
tree = ast.parse(script.read_text(encoding='utf-8'))
constants = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id in {'ROOT_SCAN_PATH', 'OUTPUT_IMG_DIR', 'OUTPUT_CODE_FILE'}}
expected = {'ROOT_SCAN_PATH': './kotonebot-resource/sprites/jp', 'OUTPUT_IMG_DIR': './kaa/sprites', 'OUTPUT_CODE_FILE': './kaa/tasks/R.py'}
assert constants == expected, 'Upstream resource paths changed; review before regeneration'
for key, relative in expected.items():
    target = (root / relative).resolve()
    assert target.is_relative_to(root) and target != root, f'Unsafe resolved path: {target}'
    print(f'{key}: {target}')
    if key != 'ROOT_SCAN_PATH':
        subprocess.run(['git', 'check-ignore', '--quiet', relative], check=True)
        tracked = subprocess.check_output(['git', 'ls-files', '--', relative], text=True)
        assert not tracked.strip(), f'Refusing to overwrite tracked output: {relative}'
assert (root / expected['ROOT_SCAN_PATH']).is_dir(), 'Resource source directory missing'
'@
            Invoke-Checked -Program $python -Arguments @('-c', $validate)
            Invoke-Checked -Program $python -Arguments @('tools/make_resources.py')
        } finally { Pop-Location }
    } else {
        Write-Host 'Existing kaa/tasks/R.py retained. After changing KAA versions, rerun with -Regen.'
    }
    Invoke-Checked -Program $python -Arguments @('-c', 'import hiro; from kaa.tasks import R; print("Host and generated KAA resources import successfully")')
    Write-Host 'Environment setup finished. Game data and a validated window backend are still required for full play; no game was launched or controlled.'
} finally { Pop-Location }
