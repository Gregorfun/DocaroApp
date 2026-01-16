# DIFF: core/supplier_fingerprint.py
+++ Supplier-Fingerprinting mit OCR-Fehlertoleranz
+ SupplierFingerprint dataclass
+ SupplierMatcher mit 5 Strategien:
+   - Exakte Übereinstimmung
+   - Fuzzy-Match (Levenshtein)
+   - Keyword-basiert
+   - Pattern-basiert (Regex)
+   - Character-Signature (n-gram)

# DIFF: core/date_scorer.py
+++ Multi-Kandidaten Datum-Extraktion
+ DateCandidate dataclass mit Metadaten
+ DateScorer mit Kontext-Analyse:
+   - Mehrere Kandidaten finden
+   - Label-Keywords erkennen
+   - Plausibilität prüfen
+   - Best-Pick mit Confidence + Erklärung

# DIFF: core/doctype_classifier.py
+++ Dokumenttyp-Klassifikation
+ DoctypeClassifier regel-basiert
+ Typen: Rechnung, Lieferschein, Gutschrift, Servicebericht, Angebot, Auftrag, Unklar
+ Keyword-basierte Regeln mit negative Keywords

# DIFF: core/audit_logger.py
+++ Audit-Logging für Erklärbarkeit
+ FieldExtraction: Feld + Confidence + Seite + Text + BBox + Gründe
+ AuditEntry: Kompletter Audit-Trail pro Dokument
+ AuditLogger: JSONL-basiertes Logging
+ Korrekturen-Tracking für Training

# DIFF: core/quarantine_manager.py
+++ Quarantäne-Verwaltung
+ QuarantineEntry dataclass
+ QuarantineManager:
+   - add_to_quarantine()
+   - list_quarantine()
+   - mark_reviewed()
+   - release_from_quarantine()

# DIFF: pipelines/document_pipeline.py
+++ Integration Audit-Logging + Quarantäne
+ from core.audit_logger import AuditLogger, FieldExtraction
+ Audit-Logging für alle Extraktionen (Supplier, Date, Doctype)
+ Quarantäne-Verschiebung bei low confidence
+ Audit-Eintrag speichern vor Ergebnis-Rückgabe

# DIFF: pipelines/ml_analyzer.py
+++ Integration neue Core-Module
+ _predict_supplier() nutzt SupplierMatcher (Fingerprinting)
+ _extract_date() nutzt DateScorer (Multi-Kandidaten)
+ _predict_document_type() nutzt DoctypeClassifier
+ Erweiterte Metadaten für Audit-Trail

# DIFF: app/review_routes.py
+++ Web-UI Review-Endpunkte
+ Blueprint 'review'
+ /review/quarantine - Liste
+ /review/document/<path> - Detailansicht
+ /review/submit - Korrekturen speichern
+ /review/stats - Statistiken

# DIFF: app/templates/quarantine.html
+++ Quarantäne-Listen-UI
+ Tabelle mit Dokumenten
+ Confidence-Anzeige
+ Review-Button

# DIFF: app/templates/review_document.html
+++ Review-Formular
+ PDF-Vorschau
+ Korrektur-Formular (Supplier, Date, Doctype)
+ AJAX-Submit zu /review/submit
+ Audit-Details (collapsible)

# DIFF: app/app.py
+++ Blueprint-Registrierung
+ from app.review_routes import review_bp
+ app.register_blueprint(review_bp)

# DIFF: ml/retrain_scheduler.py
+++ Automatischer Retrain-Scheduler
+ RetrainScheduler mit Nachtjob (02:00 Uhr)
+ collect_training_data() aus Audit-Log
+ train_supplier_model() mit MLflow
+ run_scheduled() für Daemon-Betrieb

# DIFF: ml/training/training_data_exporter.py
+++ Trainingsdaten-Export
+ TrainingDataExporter
+ export_for_sklearn() - JSON-Format
+ export_for_label_studio() - Tasks-Format
