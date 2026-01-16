# Docaro Startskript mit Tesseract-Konfiguration
# HINWEIS: Tesseract muss mit deutschen Sprachdaten (deu.traineddata) installiert sein
# Download: https://github.com/tesseract-ocr/tessdata/raw/main/deu.traineddata
# Speichern unter: C:\Program Files\Tesseract-OCR\tessdata\deu.traineddata

# Setze Tesseract-Pfade
$env:DOCARO_TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
$env:TESSDATA_PREFIX = "C:\Program Files\Tesseract-OCR\tessdata"

# Konsistente Umlaute im Terminal
try {
	[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
	$OutputEncoding = [Console]::OutputEncoding
} catch {}

# Optional: Debug-Modi aktivieren (auskommentieren bei Bedarf)
# $env:DOCARO_DEBUG = "1"
# $env:DOCARO_DEBUG_EXTRACT = "1"

Write-Host "Tesseract konfiguriert: $env:DOCARO_TESSERACT_CMD" -ForegroundColor Green
Write-Host "Starte Docaro App..." -ForegroundColor Cyan

# Hinweis: Wir starten als Background-Process, damit das Terminal nutzbar bleibt.
$logDir = Join-Path $PSScriptRoot "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLogPath = Join-Path $logDir "flask_stdout.log"
$errLogPath = Join-Path $logDir "flask_stderr.log"

# Stale-Statusdateien nach Neustart entfernen (sonst bleibt "Verarbeitung läuft" hängen)
try {
	$tmpDir = Join-Path $PSScriptRoot "data\tmp"
	$flagPath = Join-Path $tmpDir "processing.flag"
	$progressPath = Join-Path $tmpDir "progress.json"
	if (Test-Path $flagPath) { Remove-Item -Force $flagPath -ErrorAction SilentlyContinue }
	if (Test-Path $progressPath) { Remove-Item -Force $progressPath -ErrorAction SilentlyContinue }
} catch {}

# Wenn bereits eine Instanz läuft, beenden (damit neue Änderungen aktiv sind)
# 1) Alles beenden, was auf Port 5001 lauscht
try {
	$listeners = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue
	foreach ($l in $listeners) {
		if ($l.OwningProcess) {
			Write-Host "Stoppe Prozess auf Port 5001 (PID $($l.OwningProcess))..." -ForegroundColor Yellow
			Stop-Process -Id $l.OwningProcess -Force -ErrorAction Continue
		}
	}
} catch {}

# Sicherstellen, dass der Port wirklich frei ist (sonst läuft evtl. eine andere Python-Instanz weiter)
try {
	$deadline = (Get-Date).AddSeconds(5)
	while ((Get-Date) -lt $deadline) {
		$still = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue
		if (-not $still) { break }
		Start-Sleep -Milliseconds 200
	}
	$still = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
	if ($still -and $still.OwningProcess) {
		$pid = $still.OwningProcess
		$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pid" -ErrorAction SilentlyContinue
		Write-Host "FEHLER: Port 5001 ist weiterhin belegt (PID $pid, Name $($proc.Name))." -ForegroundColor Red
		Write-Host "CommandLine: $($proc.CommandLine)" -ForegroundColor DarkGray
		Write-Host "Bitte Prozess beenden oder Port wechseln." -ForegroundColor Red
		return
	}
} catch {}

# 2) Zusätzlich: laufende Python-Prozesse mit app\app.py beenden (python.exe UND python3*.exe)
try {
	$existing = Get-CimInstance Win32_Process | Where-Object {
		$_.Name -in @('python.exe','python3.exe','python3.11.exe') -and
		$_.CommandLine -and ($_.CommandLine -like '*\app\app.py*')
	}
	foreach ($p in $existing) {
		Write-Host "Stoppe laufende Docaro-Instanz (PID $($p.ProcessId))..." -ForegroundColor Yellow
		Stop-Process -Id $p.ProcessId -Force -ErrorAction Continue
	}
} catch {}

# Starte Flask-App mit Python aus der venv (detach)
Start-Process -FilePath (Join-Path $PSScriptRoot ".venv\Scripts\python.exe") `
	-WorkingDirectory $PSScriptRoot `
	-ArgumentList @(".\app\app.py") `
	-RedirectStandardOutput $outLogPath `
	-RedirectStandardError $errLogPath `
	-WindowStyle Hidden

Write-Host "Docaro läuft (wenn keine Fehler): http://127.0.0.1:5001" -ForegroundColor Green
Write-Host "Logs: $outLogPath / $errLogPath" -ForegroundColor DarkGray
