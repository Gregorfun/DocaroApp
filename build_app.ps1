param(
    [switch]$RunSmokeTest
)

# DocaroApp Desktop – Build-Skript
# Erzeugt eine standalone .exe unter dist\DocaroApp\DocaroApp.exe
#
# Voraussetzungen (einmalig):
#   .venv\Scripts\pip install pywebview pyinstaller fakeredis ocrmypdf
#
# Ausführen:
#   powershell -ExecutionPolicy Bypass -File build_app.ps1
#   powershell -ExecutionPolicy Bypass -File build_app.ps1 -RunSmokeTest

Set-Location $PSScriptRoot

$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pyinstallerExe = Join-Path $PSScriptRoot ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Host "FEHLER: Python venv nicht gefunden ($pythonExe)" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $pyinstallerExe)) {
    Write-Host "Installiere PyInstaller..." -ForegroundColor Yellow
    & $pythonExe -m pip install pyinstaller pywebview fakeredis ocrmypdf --quiet
}

$requiredModules = @('ocrmypdf', 'pikepdf', 'img2pdf')
foreach ($module in $requiredModules) {
    & $pythonExe -c "import $module" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installiere fehlendes Build-Modul: $module" -ForegroundColor Yellow
        & $pythonExe -m pip install $module --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Installation von $module fehlgeschlagen" -ForegroundColor Red
            exit $LASTEXITCODE
        }
    }
}

# Alte Build-Artefakte entfernen
Write-Host "Bereinige alte Builds..." -ForegroundColor Cyan
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist\DocaroApp") { Remove-Item -Recurse -Force "dist\DocaroApp" }

# Build
Write-Host "Baue DocaroApp Desktop..." -ForegroundColor Cyan
& $pyinstallerExe DocaroApp.spec --noconfirm

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build fehlgeschlagen (Exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

$exePath = Join-Path $PSScriptRoot "dist\DocaroApp\DocaroApp.exe"
if (Test-Path $exePath) {
    $sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Build erfolgreich!" -ForegroundColor Green
    Write-Host "  Pfad : dist\DocaroApp\DocaroApp.exe" -ForegroundColor White
    Write-Host "  Groesse: $sizeMB MB" -ForegroundColor White
    Write-Host ""
    Write-Host "Starten: .\dist\DocaroApp\DocaroApp.exe" -ForegroundColor Cyan

    if ($RunSmokeTest) {
        Write-Host "Starte Desktop-EXE-Smoke-Test..." -ForegroundColor Cyan
        & $pythonExe .\tools\smoke_test_desktop_exe.py --exe $exePath
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Desktop-Smoke-Test fehlgeschlagen (Exit $LASTEXITCODE)" -ForegroundColor Red
            exit $LASTEXITCODE
        }
    }
} else {
    Write-Host "EXE nicht gefunden - Build fehlgeschlagen?" -ForegroundColor Red
    exit 1
}
