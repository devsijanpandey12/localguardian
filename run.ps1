<#
.SYNOPSIS
    Zero-setup PowerShell launcher for LocalGuardian (works even if conda is not on PATH).
.EXAMPLE
    .\run.ps1 --doctor
    .\run.ps1 --models
    .\run.ps1 --text
    .\run.ps1 --voice
    .\run.ps1 --once "go to Chrome and type Elon Musk"
#>

$ErrorActionPreference = "Stop"

$candidates = @(
    "$env:USERPROFILE\anaconda3\envs\localguardian\Scripts\localguardian.exe",
    "$env:USERPROFILE\miniconda3\envs\localguardian\Scripts\localguardian.exe",
    "C:\ProgramData\anaconda3\envs\localguardian\Scripts\localguardian.exe"
)

$lg = $null
foreach ($p in $candidates) {
    if (Test-Path $p) {
        $lg = $p
        break
    }
}

if (-not $lg) {
    $cmd = Get-Command localguardian -ErrorAction SilentlyContinue
    if ($cmd) {
        $lg = $cmd.Source
    }
}

if (-not $lg) {
    Write-Error "Could not find localguardian.exe. Activate your conda env or run: pip install -e ."
    exit 1
}

& $lg @args
exit $LASTEXITCODE
