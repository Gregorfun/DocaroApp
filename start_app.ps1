# Docaro Startskript mit Tesseract-Konfiguration
# Bevorzugt das mitgelieferte Windows-Tesseract im Repository.
# Falls bereits explizite ENV-Werte gesetzt sind, werden diese respektiert.

# Konfiguration
$APP_PORT = 5001
$env:DOCARO_SERVER_PORT = $APP_PORT
if (-not $env:DOCARO_AUTH_REQUIRED) {
	$env:DOCARO_AUTH_REQUIRED = "0"
}
if (-not $env:DOCARO_ALLOW_SELF_REGISTER) {
	$env:DOCARO_ALLOW_SELF_REGISTER = "0"
}

# Setze Tesseract-Pfade
$bundledTesseractDir = Join-Path $PSScriptRoot "Tesseract OCR Windows installer"
$bundledTesseractExe = Join-Path $bundledTesseractDir "tesseract.exe"
$bundledTessdataDir = Join-Path $bundledTesseractDir "tessdata"
$systemTesseractExe = "C:\Program Files\Tesseract-OCR\tesseract.exe"
$systemTessdataDir = "C:\Program Files\Tesseract-OCR\tessdata"

if (-not $env:DOCARO_TESSERACT_CMD -or -not (Test-Path $env:DOCARO_TESSERACT_CMD)) {
	if (Test-Path $bundledTesseractExe) {
		$env:DOCARO_TESSERACT_CMD = $bundledTesseractExe
	} else {
		$env:DOCARO_TESSERACT_CMD = $systemTesseractExe
	}
}

if (-not $env:TESSDATA_PREFIX -or -not (Test-Path $env:TESSDATA_PREFIX)) {
	if ($env:DOCARO_TESSERACT_CMD -eq $bundledTesseractExe -and (Test-Path $bundledTessdataDir)) {
		$env:TESSDATA_PREFIX = $bundledTessdataDir
	} else {
		$env:TESSDATA_PREFIX = $systemTessdataDir
	}
}

# Konsistente Umlaute im Terminal
try {
	[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
	$OutputEncoding = [Console]::OutputEncoding
} catch {}

# Optional: Debug-Modi aktivieren (auskommentieren bei Bedarf)
# $env:DOCARO_DEBUG = "1"
# $env:DOCARO_DEBUG_EXTRACT = "1"

Write-Host "Tesseract konfiguriert: $env:DOCARO_TESSERACT_CMD" -ForegroundColor Green
if (-not (Test-Path $env:DOCARO_TESSERACT_CMD)) {
    Write-Host "WARNUNG: Tesseract nicht gefunden - OCR wird nicht funktionieren!" -ForegroundColor Yellow
} elseif (-not (Test-Path $env:TESSDATA_PREFIX)) {
	Write-Host "WARNUNG: Tesseract-Sprachdaten nicht gefunden unter: $env:TESSDATA_PREFIX" -ForegroundColor Yellow
}

try {
	$redisReachable = Test-NetConnection -ComputerName "127.0.0.1" -Port 6379 -WarningAction SilentlyContinue -InformationLevel Quiet
	if (-not $redisReachable) {
		Write-Host "HINWEIS: Redis auf 127.0.0.1:6379 ist nicht erreichbar. Uploads werden im direkten Fallback verarbeitet und koennen laenger dauern." -ForegroundColor Yellow
	}
} catch {}

# Pruefe ob Python venv existiert
$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Host "FEHLER: Python venv nicht gefunden unter: $pythonExe" -ForegroundColor Red
	Write-Host "Bitte zuerst 'python -m venv .venv' und 'pip install -r requirements.txt' ausfuehren" -ForegroundColor Yellow
    return
}

Write-Host "Starte Docaro App..." -ForegroundColor Cyan

# Hinweis: Wir starten als Background-Process, damit das Terminal nutzbar bleibt.
$logDir = Join-Path $PSScriptRoot "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLogPath = Join-Path $logDir "flask_stdout.log"
$errLogPath = Join-Path $logDir "flask_stderr.log"

# Log-Rotation: Alte Logs archivieren wenn zu gross (>10 MB)
foreach ($logFile in @($outLogPath, $errLogPath)) {
	if (Test-Path $logFile) {
		$size = (Get-Item $logFile).Length / 1MB
		if ($size -gt 10) {
			Move-Item $logFile "$logFile.old" -Force -ErrorAction SilentlyContinue
		}
	}
}

# Stale-Statusdateien nach Neustart entfernen (sonst bleibt "Verarbeitung laeuft" haengen)
try {
	$tmpDir = Join-Path $PSScriptRoot "data\tmp"
	$flagPath = Join-Path $tmpDir "processing.flag"
	$progressPath = Join-Path $tmpDir "progress.json"
	if (Test-Path $flagPath) { Remove-Item -Force $flagPath -ErrorAction SilentlyContinue }
	if (Test-Path $progressPath) { Remove-Item -Force $progressPath -ErrorAction SilentlyContinue }
} catch {}

# Wenn bereits eine Instanz laeuft, beenden (damit neue Aenderungen aktiv sind)
# 1) Alles beenden, was auf Port $APP_PORT lauscht
try {
	$listeners = Get-NetTCPConnection -LocalPort $APP_PORT -State Listen -ErrorAction SilentlyContinue
	foreach ($l in $listeners) {
		if ($l.OwningProcess) {
			Write-Host "Stoppe Prozess auf Port $APP_PORT (PID $($l.OwningProcess))..." -ForegroundColor Yellow
			Stop-Process -Id $l.OwningProcess -Force -ErrorAction Continue
		}
	}
} catch {}

# Sicherstellen, dass der Port wirklich frei ist (sonst laeuft evtl. eine andere Python-Instanz weiter)
try {
	Write-Host "Warte auf Port-Freigabe..." -ForegroundColor Yellow
	$deadline = (Get-Date).AddSeconds(10)
	while ((Get-Date) -lt $deadline) {
		$still = Get-NetTCPConnection -LocalPort $APP_PORT -State Listen -ErrorAction SilentlyContinue
		if (-not $still) { break }
		Start-Sleep -Milliseconds 200
	}
	$still = Get-NetTCPConnection -LocalPort $APP_PORT -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
	if ($still -and $still.OwningProcess) {
		$processId = $still.OwningProcess
		$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
		Write-Host "FEHLER: Port $APP_PORT ist weiterhin belegt (PID $processId, Name $($proc.Name))." -ForegroundColor Red
		Write-Host "CommandLine: $($proc.CommandLine)" -ForegroundColor DarkGray
		Write-Host "Bitte Prozess beenden oder Port wechseln." -ForegroundColor Red
		return
	}
} catch {}

# 2) Zusaetzlich: laufende Python-Prozesse mit app\app.py beenden (python.exe UND python3*.exe)
try {
	$existing = Get-CimInstance Win32_Process | Where-Object {
		$_.Name -in @('python.exe','python3.exe','python3.11.exe') -and
		$_.CommandLine -and ($_.CommandLine -like '*\app\app.py*' -or $_.CommandLine -like '*-m app.app*')
	}
	foreach ($p in $existing) {
		Write-Host "Stoppe laufende Docaro-Instanz (PID $($p.ProcessId))..." -ForegroundColor Yellow
		Stop-Process -Id $p.ProcessId -Force -ErrorAction Continue
	}
} catch {}

# Starte Flask-App mit Python aus der venv (detach)
Start-Process -FilePath $pythonExe `
	-WorkingDirectory $PSScriptRoot `
	-ArgumentList @("-m", "app.app") `
	-RedirectStandardOutput $outLogPath `
	-RedirectStandardError $errLogPath `
	-WindowStyle Hidden

# Warte kurz und pruefe ob App wirklich laeuft
Write-Host "Warte auf App-Start..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
$check = Get-NetTCPConnection -LocalPort $APP_PORT -State Listen -ErrorAction SilentlyContinue
if ($check) {
	Write-Host "Docaro erfolgreich gestartet: http://127.0.0.1:$APP_PORT" -ForegroundColor Green
} else {
	Write-Host "App konnte nicht gestartet werden - siehe Logs fuer Details" -ForegroundColor Yellow
	Write-Host "Logs: $outLogPath" -ForegroundColor DarkGray
	return
}

Write-Host "Logs: $outLogPath / $errLogPath" -ForegroundColor DarkGray

