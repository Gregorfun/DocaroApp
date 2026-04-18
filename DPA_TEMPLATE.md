# Vorlage Auftragsverarbeitungsvertrag (AVV / DPA) - Docaro

Diese Datei ist eine technische Vertragsvorlage und muss vor Verwendung durch
eine Rechtsberatung oder die zustaendige interne Rechtsabteilung geprueft und
angepasst werden.

## 1. Gegenstand und Dauer

Verarbeitung von Dokumenten und Metadaten mittels Docaro im Rahmen eines
On-Premises- oder Hosted-Betriebs.

## 2. Art und Zweck der Verarbeitung

- OCR und Dokumentklassifikation
- Extraktion strukturierter Daten
- Review, Korrektur und Nachbearbeitung
- Betriebs- und Sicherheitslogging

## 3. Kategorien betroffener Personen und Daten

- Ansprechpartner, Lieferanten, Mitarbeitende, sonstige Dokumentenbeteiligte
- Dokumentinhalte, Rechnungsdaten, Lieferscheindaten, Metadaten und Nutzerkonten

## 4. Technische und organisatorische Massnahmen

- Zugriff nur fuer autorisierte Nutzer
- Passwort-Hashing mit Argon2
- TLS ueber Reverse Proxy
- Logging, Auditierung und rollenbasierte Zugriffssteuerung
- Backup- und Restore-Verfahren

## 5. Unterauftragsverhaeltnisse

Externe Dienste duerfen nur eingesetzt werden, wenn sie vertraglich vereinbart,
dokumentiert und datenschutzrechtlich zulaessig sind.

## 6. Kontrollrechte und Mitwirkungspflichten

Kunde und Anbieter definieren Audits, Ansprechpartner und Eskalationswege
gesondert im Hauptvertrag.