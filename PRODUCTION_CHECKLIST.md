# Produktions-Checkliste - Docaro

## Muss vor Go-Live erledigt sein

- Auth erzwungen: DOCARO_AUTH_REQUIRED=1
- Selbstregistrierung deaktiviert: DOCARO_ALLOW_SELF_REGISTER=0
- Seed-Admin mit individuellem Passwort angelegt
- TLS ueber Reverse Proxy aktiviert
- Rate Limits und CSRF-Haertung aktiviert
- Metrics nur mit Token oder intern erreichbar
- RQ Dashboard nur bei Bedarf aktiv und abgesichert
- Grafana-Admin-Passwort individuell gesetzt
- Backup- und Restore-Test dokumentiert
- Logging, Monitoring und Alarmierung aktiviert
- Support- und Eskalationskontakt dokumentiert: OPERATIONS_CONTACTS_TEMPLATE.md ausfuellen
- EULA, Datenschutzdokumente und AVV-Vorlage geprueft

## Automatischer Gate-Check

Technischer Produktions-Check:

```bash
python tools/production_readiness_check.py --env-file /etc/docaro/docaro.env
```

Strenger Gate-Check inklusive Warnungen:

```bash
python tools/production_readiness_check.py --env-file /etc/docaro/docaro.env --fail-on-warnings
```

## Release-Gate

- Test-Suite gruener Status
- Lint-Suite gruener Status
- Security-Workflow gruener Status
- Abhaengigkeiten fuer alle verwendeten requirements-Dateien auditiert
- Smoke-Test von Login, Upload, Review, Export und Worker abgeschlossen

## Betriebsfreigabe

- Change-Log erstellt
- Rollback-Pfad dokumentiert
- Verantwortlichkeiten fuer Betrieb und Incident Response benannt