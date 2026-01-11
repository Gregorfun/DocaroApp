# Sicherheitshinweise für Docaro

Dieses Dokument beschreibt Sicherheitsaspekte und Best Practices für den Betrieb von Docaro.

## Übersicht

Docaro verarbeitet PDF-Dokumente, die sensible Geschäftsinformationen enthalten können (Rechnungen, Lieferscheine). Eine sichere Konfiguration ist daher wichtig.

## Sicherheits-Checkliste

### Vor der Produktionsnutzung

- [ ] **Secret Key setzen**: Generieren Sie einen sicheren `DOCARO_SECRET_KEY`
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
  Tragen Sie diesen in die `.env` Datei ein.

- [ ] **Debug-Modus deaktivieren**: `DOCARO_DEBUG=0` in Produktion
- [ ] **Debug-Extraktion deaktivieren**: `DOCARO_DEBUG_EXTRACT=0` in Produktion
- [ ] **Sichere Dateiberechtigungen**: 
  ```bash
  chmod 600 .env
  chmod 700 data/
  ```

- [ ] **HTTPS verwenden**: In Produktion sollte Docaro hinter einem Reverse Proxy (z.B. nginx) mit HTTPS laufen

### Netzwerk-Sicherheit

#### Zugriffsbeschränkung

Docaro bindet standardmäßig an `127.0.0.1` (localhost), was nur lokale Verbindungen erlaubt. Für Netzwerkzugriff:

```bash
# NUR für vertrauenswürdige Netzwerke!
DOCARO_SERVER_HOST=0.0.0.0
```

**Empfehlung**: Verwenden Sie einen Reverse Proxy wie nginx oder Apache, der:
- HTTPS/TLS bereitstellt
- Authentifizierung implementiert
- Rate Limiting bietet
- Zugriff auf vertrauenswürdige IPs beschränkt

#### Beispiel nginx-Konfiguration

```nginx
server {
    listen 443 ssl http2;
    server_name docaro.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # Nur aus internem Netzwerk
    allow 10.0.0.0/8;
    deny all;
    
    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Upload-Größenlimit
        client_max_body_size 50M;
    }
}
```

### Datei-Sicherheit

#### Erlaubte Dateitypen

Docaro akzeptiert nur PDF-Dateien. Dies wird über `ALLOWED_EXTENSIONS` in `app/app.py` gesteuert.

#### Dateinamen-Sanitisierung

Alle Dateinamen werden durch `secure_filename()` von Werkzeug bereinigt, um Path-Traversal-Angriffe zu verhindern.

#### Dateispeicherung

- PDFs werden in konfigurierten Verzeichnissen gespeichert (`data/eingang/`, `data/fertig/`)
- Zugriff auf Dateien außerhalb dieser Verzeichnisse wird blockiert
- Temporäre Dateien werden in `data/tmp/` gespeichert und sollten regelmäßig bereinigt werden

### Eingabe-Validierung

Alle Benutzereingaben werden validiert:

- **Lieferantennamen**: Durch `_normalize_supplier_input()` bereinigt
- **Datumsangaben**: Nur vordefinierte Formate akzeptiert
- **Dateinamen**: Durch `secure_filename()` validiert

### Session-Management

- Sessions verwenden Flask's sichere Cookie-Implementierung
- Ein sicherer `SECRET_KEY` ist erforderlich für Session-Verschlüsselung
- Sessions laufen nach Inaktivität ab

### Logging

- Logs werden in `data/logs/` gespeichert
- Sensitive Daten (wie Secret Keys) werden nicht geloggt
- Logs sollten regelmäßig rotiert und archiviert werden
- Standard-Aufbewahrungszeit: 30 Tage (konfigurierbar via `DOCARO_LOG_RETENTION_DAYS`)

### Dependency-Management

#### Regelmäßige Updates

```bash
# Python-Pakete aktualisieren
pip install --upgrade -r requirements.txt

# Sicherheitslücken prüfen
pip install safety
safety check
```

#### Bekannte Abhängigkeiten

- **Flask**: Web-Framework
- **Pillow**: Bildverarbeitung
- **PyTesseract**: OCR-Wrapper
- **pdf2image**: PDF-Konvertierung
- **Werkzeug**: Utilities (Teil von Flask)

### Externe Tools

#### Tesseract OCR

Stellen Sie sicher, dass Tesseract aus vertrauenswürdigen Quellen installiert ist:
- **Windows**: Offizielle Installer verwenden
- **Linux**: Aus Distributions-Repositories (`apt`, `yum`, etc.)
- **macOS**: Via Homebrew

#### Poppler

Gleiche Empfehlung wie für Tesseract.

### Betriebssystem-Härtung

- **Benutzerrechte**: Docaro sollte unter einem dedizierten Benutzer ohne Root-Rechte laufen
- **Firewall**: Nur benötigte Ports öffnen
- **Updates**: Betriebssystem und Pakete aktuell halten
- **SELinux/AppArmor**: Erwägen Sie Mandatory Access Control auf Linux

### Backup und Wiederherstellung

#### Was sollte gesichert werden?

- `data/suppliers.json` - Lieferanten-Datenbank
- `data/history.jsonl` - Änderungshistorie
- `data/fertig/` - Verarbeitete PDFs
- `.env` - Konfiguration (sicher aufbewahren!)

#### Was muss NICHT gesichert werden?

- `data/tmp/` - Temporäre Dateien
- `data/logs/` - Log-Dateien (optional)
- `data/eingang/` - Eingangsdateien (nach Verarbeitung)

### Überwachung

#### Was sollte überwacht werden?

- **Fehlgeschlagene Uploads**: Könnte auf Angriffe hindeuten
- **Ungewöhnliche Dateimuster**: Viele große Dateien, ungewöhnliche Namen
- **Hohe Last**: CPU/RAM-Nutzung durch OCR
- **Log-Einträge**: Fehler und Warnungen in `data/logs/docaro.log`

#### Beispiel-Monitoring

```bash
# Überwache Fehler im Log
tail -f data/logs/docaro.log | grep ERROR

# Prüfe Speicherplatz
df -h data/

# Überwache CPU/RAM
top -p $(pgrep -f "python.*app.py")
```

## Sicherheitsvorfälle

### Bei Verdacht auf Kompromittierung

1. **Sofort**: Docaro stoppen und vom Netzwerk trennen
2. **Analyse**: Logs in `data/logs/` überprüfen
3. **Secret Key erneuern**: Neuen `DOCARO_SECRET_KEY` generieren
4. **Abhängigkeiten prüfen**: `safety check` ausführen
5. **System prüfen**: Auf Malware/Rootkits scannen
6. **Neustart**: Nach Behebung mit neuer Konfiguration starten

### Meldung von Sicherheitslücken

Wenn Sie eine Sicherheitslücke in Docaro finden, erstellen Sie bitte ein privates Security Advisory im GitHub-Repository statt ein öffentliches Issue.

## Best Practices Zusammenfassung

✅ **DO**:
- Sicheren SECRET_KEY verwenden
- HTTPS in Produktion nutzen
- Zugriff beschränken (Firewall, nginx)
- Regelmäßig Updates einspielen
- Logs überwachen
- Backups erstellen

❌ **DON'T**:
- DEBUG-Modus in Produktion
- Secrets im Code oder Git
- Direkten Internet-Zugriff ohne Schutz
- Root-Rechte für Docaro
- Unbekannte Abhängigkeiten installieren

## Weitere Ressourcen

- [OWASP Web Security Testing Guide](https://owasp.org/www-project-web-security-testing-guide/)
- [Flask Security Best Practices](https://flask.palletsprojects.com/en/latest/security/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)

---

**Letzte Aktualisierung**: 2026-01-11
