# Docaro Diagnose-Tool
# Prueft Systemvoraussetzungen und App-Gesundheit

Write-Host "`nDOCAR DIAGNOSE-TOOL`n" -ForegroundColor Cyan

$REPO_ROOT = Split-Path $PSScriptRoot -Parent
$checks_passed = 0
$checks_failed = 0

function Check-Item {
    param([string]$Name, [scriptblock]$TestBlock, [string]$HelpUrl = "")
    
    try {
        $result = & $TestBlock
        if ($result) {
            Write-Host "[OK]   $Name" -ForegroundColor Green
            $script:checks_passed++
        } else {
            Write-Host "[FAIL] $Name" -ForegroundColor Red
            if ($HelpUrl) { Write-Host "       -> $HelpUrl" -ForegroundColor DarkGray }
            $script:checks_failed++
        }
    } catch {
        Write-Host "[FAIL] $Name (Error: $_)" -ForegroundColor Red
        $script:checks_failed++
    }
}

Write-Host "SYSTEM-ANFORDERUNGEN" -ForegroundColor Yellow
Check-Item "Python 3.9+" { 
    $v = python --version 2>&1
    $v -match "Python 3\.(9|1[0-9])" 
}

Check-Item "Virtual Environment" {
    Test-Path "$REPO_ROOT\.venv\Scripts\python.exe"
}

Check-Item "Tesseract OCR" {
    Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe"
} "https://github.com/UB-Mannheim/tesseract/wiki"

Check-Item "Tesseract German" {
    Test-Path "C:\Program Files\Tesseract-OCR\tessdata\deu.traineddata"
} "Download deu.traineddata"

Check-Item "Poppler" {
    Test-Path "$REPO_ROOT\poppler\Library\bin\pdftoppm.exe"
}

Write-Host "`nDIREKTORIES" -ForegroundColor Yellow
Check-Item "data/eingang" { Test-Path "$REPO_ROOT\data\eingang" }
Check-Item "data/fertig" { Test-Path "$REPO_ROOT\data\fertig" }
Check-Item "data/quarantaene" { Test-Path "$REPO_ROOT\data\quarantaene" }
Check-Item "data/logs" { Test-Path "$REPO_ROOT\data\logs" }

Write-Host "`nPYTHON DEPENDENCIES" -ForegroundColor Yellow
$venv_python = "$REPO_ROOT\.venv\Scripts\python.exe"

if (Test-Path $venv_python) {
    Check-Item "Flask" { & $venv_python -c "import flask" 2>$null; $LASTEXITCODE -eq 0 }
    Check-Item "pdf2image" { & $venv_python -c "import pdf2image" 2>$null; $LASTEXITCODE -eq 0 }
    Check-Item "pytesseract" { & $venv_python -c "import pytesseract" 2>$null; $LASTEXITCODE -eq 0 }
    Check-Item "Pillow" { & $venv_python -c "import PIL" 2>$null; $LASTEXITCODE -eq 0 }
} else {
    Write-Host "[SKIP] venv not found" -ForegroundColor Yellow
}

Write-Host "`nAPP HEALTH" -ForegroundColor Yellow
Check-Item "App running (Port 5001)" {
    Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

Write-Host "`nCONFIGURATIONS" -ForegroundColor Yellow
Check-Item "config.py" { Test-Path "$REPO_ROOT\config.py" }
Check-Item "data/settings.json" { Test-Path "$REPO_ROOT\data\settings.json" }

$total = $checks_passed + $checks_failed
if ($total -gt 0) {
    $percentage = [math]::Round(($checks_passed / $total) * 100)
} else {
    $percentage = 0
}

Write-Host "`nSUMMARY" -ForegroundColor Cyan
Write-Host "Passed: $checks_passed/$total ($percentage%)" -ForegroundColor Green
Write-Host "Failed: $checks_failed/$total" -ForegroundColor $(if ($checks_failed -eq 0) { 'Green' } else { 'Red' })

if ($checks_failed -eq 0) {
    Write-Host "`nOK - Ready to start app`n" -ForegroundColor Green
} else {
    Write-Host "`nWARNING - Fix issues above`n" -ForegroundColor Yellow
}

exit $checks_failed
