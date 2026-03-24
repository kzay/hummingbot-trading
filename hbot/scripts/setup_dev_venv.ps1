#Requires -Version 5.1
<#
.SYNOPSIS
  Recreate a local venv with Python 3.12.x and install kzay-capital-desk + dev extras.

.DESCRIPTION
  Run from the repository ROOT (parent of hbot/):
    powershell -ExecutionPolicy Bypass -File hbot/scripts/setup_dev_venv.ps1

  If .venv is locked (IDE/terminal), automatically uses .venv-work instead.
#>
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$env:PIP_DEFAULT_TIMEOUT = "120"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

Write-Host "Repo root: $RepoRoot"

if (Get-Command pyenv -ErrorAction SilentlyContinue) {
    pyenv local 3.12.3
    Write-Host "pyenv local 3.12.3"
}
else {
    Write-Warning "pyenv not on PATH; ensure python --version is 3.12.x"
}

$pyVersion = python --version 2>&1
Write-Host $pyVersion
if ($pyVersion -notmatch "3\.12\.") {
    throw "Need Python 3.12.x on PATH (install pyenv-win 3.12.3 or use python.org 3.12)."
}

$VenvName = ".venv"
$venvPath = Join-Path $RepoRoot $VenvName

if (Test-Path $venvPath) {
    Write-Host "Removing $VenvName ..."
    try {
        Remove-Item -Recurse -Force $venvPath -ErrorAction Stop
    }
    catch {
        Write-Warning "Could not remove $VenvName (folder in use). Trying .venv-work ..."
        $VenvName = ".venv-work"
        $venvPath = Join-Path $RepoRoot $VenvName
        if (Test-Path $venvPath) {
            Remove-Item -Recurse -Force $venvPath -ErrorAction Stop
        }
    }
}

Write-Host "Creating $VenvName with --upgrade-deps ..."
python -m venv $venvPath --upgrade-deps

$venvPy = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    throw "$VenvName\Scripts\python.exe missing after venv create."
}

$pipExe = Join-Path $venvPath "Scripts\pip.exe"
if (-not (Test-Path $pipExe)) {
    Write-Host "pip missing; trying ensurepip ..."
    & $venvPy -m ensurepip --upgrade 2>&1 | Out-Host
    if (-not (Test-Path $pipExe)) {
        Write-Host "ensurepip did not add pip.exe; running get-pip.py ..."
        $gp = Join-Path $env:TEMP "get-pip-bootstrap.py"
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $gp -UseBasicParsing
        & $venvPy $gp
        Remove-Item -Force $gp -ErrorAction SilentlyContinue
    }
}

& $venvPy -m pip install -U pip setuptools wheel

$HbotDir = Join-Path $RepoRoot "hbot"
Push-Location $HbotDir
try {
    & $venvPy -m pip install -e ".[dev]"
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done. Virtual env: $VenvName"
Write-Host "Activate:"
Write-Host "  .\$VenvName\Scripts\Activate.ps1"
Write-Host "  `$env:PYTHONPATH = 'hbot'"
