# Changelog

Alle wichtigen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefügt
- README.md (Setup/ENV/Tools)
- .env.example Vorlage für Umgebungsvariablen
- CONTRIBUTING.md Entwicklerhandbuch
- SECURITY.md Sicherheitshinweise
- requirements-dev.txt für Entwicklungs-Abhängigkeiten
- GitHub Actions CI-Workflow für automatische Tests

### Behoben
- MANUAL_DATE_FORMATS Konstante war nicht definiert (Bug)
- DEEP_SCAN Konfigurationsvariable fehlte in config.py
- Fehlende Dokumentation für Entwickler

### Verbessert
- Bessere Strukturierung der Projektdateien
- Erweiterte Dokumentation für Installation und Verwendung

## Frühere Versionen

### Version vor Verbesserungen
- Grundlegende OCR-Funktionalität mit Tesseract
- Flask Web-Interface
- Automatische PDF-Umbenennung
- Lieferanten-Datenbank mit Alias-Unterstützung
- Manuelle Korrekturmöglichkeiten
- PaddleOCR-Integration (experimental)
