# Docaro Developer Tools
# Hilfsskript für Common Tasks

param(
    [Parameter(Mandatory=$false)]
    [string]$Task = "help"
)

# Bestimme Python Executable (bevorzuge venv)
$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
    Write-Host "[Dev] Nutze venv Python: $PythonExe" -ForegroundColor DarkGray
} else {
    $PythonExe = "python"
    Write-Host "[Dev] Nutze System Python" -ForegroundColor DarkGray
}

function Show-Help {
    Write-Host "Verfügbare Tasks:" -ForegroundColor Cyan
    Write-Host "  test      - Führt alle Tests aus"
    Write-Host "  lint      - Prüft Code-Style (Black/Flake8)"
    Write-Host "  format    - Formatiert Code (Black)"
    Write-Host "  clean     - Bereinigt temporäre Dateien"
    Write-Host "  seed      - Erstellt den Seed-User (nutzt .env oder Defaults)"
    Write-Host "  diagnose  - Prüft Systemvoraussetzungen und App-Gesundheit"
    Write-Host "  logs      - Analysiert App-Logs"
}

if ($Task -eq "test") {
    Write-Host "Starte Tests..." -ForegroundColor Green
    & $PythonExe -m pytest
}
elseif ($Task -eq "lint") {
    Write-Host "Prüfe Code..." -ForegroundColor Green
    & $PythonExe -m flake8 app core tests tools
    & $PythonExe -m black --check app core tests tools
}
elseif ($Task -eq "format") {
    Write-Host "Formatiere Code..." -ForegroundColor Green
    & $PythonExe -m black app core tests tools
}
elseif ($Task -eq "clean") {
    Write-Host "Bereinige..." -ForegroundColor Green
    Get-ChildItem -Path . -Include "__pycache__", "*.pyc", "*.pyo" -Recurse | Remove-Item -Force -Recurse
    Write-Host "Fertig."
}
elseif ($Task -eq "seed") {
    Write-Host "Erstelle Seed-User..." -ForegroundColor Green
    & $PythonExe tools/seed_user.py --email $env:DOCARO_SEED_EMAIL --reset-password
}
elseif ($Task -eq "diagnose") {
    Write-Host "Starte Diagnose..." -ForegroundColor Green
    & $PSScriptRoot\tools\diagnose.ps1
}
elseif ($Task -eq "logs") {
    Write-Host "Analysiere Logs..." -ForegroundColor Green
    & $PythonExe tools/analyze_logs.py
}
else {
    Show-Help
}
