$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Missing clean project interpreter at .venv\Scripts\python.exe"
}

$env:PYTHONPATH = "hbot"
$env:VIRTUAL_ENV = Join-Path $repoRoot ".venv"
$env:Path = "$(Join-Path $repoRoot '.venv\Scripts');$env:Path"

Write-Host "Project Python ready"
Write-Host "Python: $venvPython"
& $venvPython --version

