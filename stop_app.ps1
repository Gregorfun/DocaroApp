# Docaro Stop-Skript
# Stoppt alle laufenden Docaro-Instanzen

$APP_PORT = 5001

Write-Host "Stoppe Docaro..." -ForegroundColor Yellow

# 1) Stoppe alle Prozesse, die auf Port lauschen
try {
	$listeners = Get-NetTCPConnection -LocalPort $APP_PORT -State Listen -ErrorAction SilentlyContinue
	if ($listeners) {
		foreach ($l in $listeners) {
			if ($l.OwningProcess) {
				Write-Host "Stoppe Prozess auf Port $APP_PORT (PID $($l.OwningProcess))..." -ForegroundColor Yellow
				Stop-Process -Id $l.OwningProcess -Force -ErrorAction Continue
			}
		}
		Start-Sleep -Seconds 2
	} else {
		Write-Host "Keine Prozesse auf Port $APP_PORT gefunden." -ForegroundColor DarkGray
	}
} catch {
	Write-Host "Fehler beim Stoppen: $_" -ForegroundColor Red
}

# 2) Zusätzlich: laufende Python-Prozesse mit app\app.py beenden
try {
	$existing = Get-CimInstance Win32_Process | Where-Object {
		$_.Name -in @('python.exe','python3.exe','python3.11.exe') -and
		$_.CommandLine -and ($_.CommandLine -like '*\app\app.py*')
	}
	if ($existing) {
		foreach ($p in $existing) {
			Write-Host "Stoppe Docaro-Prozess (PID $($p.ProcessId))..." -ForegroundColor Yellow
			Stop-Process -Id $p.ProcessId -Force -ErrorAction Continue
		}
	}
} catch {}

# Überprüfen ob erfolgreich
Start-Sleep -Seconds 1
$check = Get-NetTCPConnection -LocalPort $APP_PORT -State Listen -ErrorAction SilentlyContinue
if ($check) {
	Write-Host "WARNUNG: Port $APP_PORT ist noch belegt!" -ForegroundColor Yellow
} else {
	Write-Host "Docaro erfolgreich gestoppt." -ForegroundColor Green
}
