#!/usr/bin/env pwsh
# archiGuard launcher (PowerShell). Finds a Python 3.9+ interpreter and runs the
# deterministic engine in ../python/archiguard.py with all arguments.
#
# Interpreter search order:
#   1. $env:ARCHIGUARD_PYTHON
#   2. python / python3 on PATH (Windows Store alias stubs are skipped), then the py launcher
#   3. the Python inside the uv tool environment of specify-cli
#   4. uv run --no-project python
#
# Arguments are passed through unchanged, e.g.:  archiguard.ps1 run plan b --json

$ErrorActionPreference = 'Stop'

$engine = Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) 'python') 'archiguard.py'
if (-not (Test-Path -LiteralPath $engine -PathType Leaf)) {
    [Console]::Error.WriteLine("archiGuard: ERROR: engine not found at $engine")
    exit 2
}

function Test-Python {
    param([string]$Exe, [string[]]$Prefix = @())
    try {
        $null = & $Exe @Prefix -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$exe = $null
$prefix = @()

if ($env:ARCHIGUARD_PYTHON) {
    if (-not (Test-Python -Exe $env:ARCHIGUARD_PYTHON)) {
        [Console]::Error.WriteLine("archiGuard: ERROR: ARCHIGUARD_PYTHON='$($env:ARCHIGUARD_PYTHON)' is not a working Python 3.9+ interpreter.")
        exit 2
    }
    $exe = $env:ARCHIGUARD_PYTHON
} else {
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd -and (Test-Python -Exe $cmd.Source)) { $exe = $cmd.Source; break }
    }
    if (-not $exe) {
        $launcher = Get-Command 'py' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($launcher -and (Test-Python -Exe $launcher.Source -Prefix @('-3'))) { $exe = $launcher.Source; $prefix = @('-3') }
    }
    if (-not $exe) {
        $uv = Get-Command 'uv' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($uv) {
            $toolDir = (& $uv.Source tool dir 2>$null | Select-Object -First 1)
            if ($toolDir) {
                foreach ($candidate in @(
                        (Join-Path $toolDir 'specify-cli\Scripts\python.exe'),
                        (Join-Path $toolDir 'specify-cli/bin/python'))) {
                    if ((Test-Path -LiteralPath $candidate) -and (Test-Python -Exe $candidate)) { $exe = $candidate; break }
                }
            }
            if (-not $exe) { $exe = $uv.Source; $prefix = @('run', '--no-project', '--quiet', 'python') }
        }
    }
}

if (-not $exe) {
    [Console]::Error.WriteLine('archiGuard: ERROR: no Python 3.9+ interpreter found. Install Python or uv, or set ARCHIGUARD_PYTHON.')
    exit 2
}

try {
    & $exe @prefix $engine @args
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine("archiGuard: ERROR: could not run $exe : $($_.Exception.Message)")
    exit 2
}
