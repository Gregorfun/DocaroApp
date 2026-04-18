# Datenschutz und Sicherheitskonzept - Docaro

Dieses Dokument beschreibt die datenschutzrelevanten Punkte fuer den
produktiven Einsatz von Docaro. Es ist als technische Grundlage gedacht und
ersetzt keine juristische Pruefung.

## Verarbeitete Daten

- Hochgeladene PDF-Dokumente
- Extrahierte Metadaten wie Lieferant, Datum, Dokumenttyp und Dokumentnummer
- Betriebsdaten wie Audit-Logs, Fehlerprotokolle und Queue-Metadaten
- Benutzerkonten fuer Authentifizierung und Rollenzuordnung

## Zweck der Verarbeitung

- OCR und Dokumentanalyse
- Klassifikation und Extraktion strukturierter Dokumentdaten
- Review- und Korrekturprozesse
- Betrieb, Sicherheit, Nachvollziehbarkeit und Fehleranalyse

## Technische und organisatorische Massnahmen

- Login-Pflicht standardmaessig aktiviert
- Selbstregistrierung standardmaessig deaktiviert
- Passwort-Hashes via Argon2
- Rate Limits und CSRF-Schutz fuer mutierende Requests
- Session-Cookies auf HttpOnly und SameSite gesetzt
- Optionen fuer Sentry, strukturiertes Logging und Audit-Logging
- Mandanten- bzw. benutzerspezifische Laufzeitverzeichnisse
- Systemd-Haertung fuer Web- und Worker-Service

## Betriebshinweise

- TLS muss ueber Reverse Proxy oder vorgeschaltete Infrastruktur erzwungen werden.
- Logging darf keine unnoetigen personen- oder geheimnisbezogenen Inhalte enthalten.
- Aufbewahrungsfristen fuer Logs und Dokumente muessen kundenspezifisch definiert werden.
- Backups muessen verschluesselt und mit Restore-Test betrieben werden.

## Rollen und Verantwortlichkeiten

- Hersteller/Lieferant: Produktpflege, Security-Fixes, Release-Hinweise
- Betreiber/Kunde: Rechtsgrundlage, Nutzerverwaltung, Betrieb, Backup, Zugriffskontrolle

## Offene Punkte vor Verkaufsstart

- TOMs finalisieren
- Loesch- und Aufbewahrungskonzept vertraglich definieren
- AVV/DPA mit Kunden abstimmen
- Drittlandtransfer- und Monitoring-Konzept pruefen, falls externe Dienste aktiviert werden