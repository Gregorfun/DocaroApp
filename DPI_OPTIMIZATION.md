#!/bin/bash
# DPI Optimization & Supplier Detection Verbesserungen

## Durchgeführte Änderungen (5. Februar 2026)

### 1. DPI auf 300 erhöht
**Problem:** 
- Lieferant "Förch" wurde nicht erkannt
- "Franz Bracht" aus Lieferanschrift wurde fälschlicherweise als Lieferant erkannt

**Ursache:**
- Standardmäßig DPI 200 für OCR/PDF-Rendering
- Bei niedrigem DPI werden kleine Schriften oder komplexe Zeichen (ö, ü) unscharf/falsch erkannt

**Lösung:**
```bash
echo "DOCARO_RENDER_DPI=300" >> /etc/docaro/docaro.env
systemctl restart docaro docaro-worker
```

**Details:**
- Code: `/opt/Docaro/core/extractor.py` Zeile 89-99
- Funktion: `_render_dpi()` liest `DOCARO_RENDER_DPI` env variable
- Standardwert: 200 DPI (Balance zwischen Qualität und RAM-Nutzung)
- Maximalwert: 300 DPI (hardcoded Limit)
- Höherer DPI = schärfere Bilder = bessere OCR-Genauigkeit

### 2. Recipient-Detection bereits konfiguriert
Die Text-Segmentierung erkennt Lieferanschriften automatisch via Keywords:
- "lieferanschrift", "versandanschrift", "ship to", etc.
- Code: `/opt/Docaro/core/text_segments.py` Zeile 8-21
- Recipient-Segment erhält Confidence-Penalty: 0.20 (statt 1.0 für Header)
- Sollte verhindern, dass Empfänger als Lieferant erkannt wird

### 3. Förch-Aliase bereits vorhanden
Supplier-Canonicalizer kennt Förch-Varianten:
```yaml
FOERCH:
  canonical: "Foerch"
  aliases:
    - "FÖRCH"
    - "FOERCH"  
    - "Förch GmbH"
    - "(?i)foerch"
  domain_hints: ["foerch.de"]
```
Config: `/opt/Docaro/config/supplier_aliases.yaml`

### 4. Test-Script erstellt
```bash
# Test mit einem Lieferschein:
cd /opt/Docaro
sudo -u docaro .venv/bin/python test_supplier_detection.py data/eingang/scan.pdf
```

Das Script zeigt:
- Erkannten Lieferant + Confidence
- Top 5 Kandidaten mit Segment (header/body/recipient)
- Erste 15 Zeilen OCR-Text

### Erwartetes Verhalten nach DPI-Erhöhung:
1. **Bessere OCR-Qualität:**
   - "Förch" wird klarer erkannt (kein "Forch" oder "Foreh")
   - Umlaute (ö, ü, ä) werden korrekt gelesen

2. **Korrekte Segmentierung:**
   - "Förch" im Briefkopf/Header → Segment: header, Confidence: ~0.95-0.99
   - "Franz Bracht" unter "Lieferanschrift:" → Segment: recipient, Confidence: ~0.20
   - Winner: Förch (höhere Confidence durch Segment-Multiplikator)

3. **Fallback-Strategie:**
   - Falls mehrere Kandidaten gleich stark: Höchste Confidence gewinnt
   - Falls kein Match: "Unbekannt"

### Troubleshooting

**Problem bleibt nach DPI-Erhöhung:**
1. OCR-Text prüfen:
   ```bash
   cd /opt/Docaro
   sudo -u docaro .venv/bin/python test_supplier_detection.py <PDF> | grep "OCR Text"
   ```
   
2. Steht "Förch" im Header (erste ~40 Zeilen)?
   - Ja → Sollte erkannt werden
   - Nein → PDF-Layout ungewöhnlich, Segmentierung anpassen

3. Steht "Franz Bracht" unter Keyword "Lieferanschrift"?
   - Ja → Sollte als recipient ignoriert werden
   - Nein → Keyword fehlt, manuell zu `_RECIPIENT_KEYWORDS` hinzufügen

**Weitere DPI-Optimierung:**
DPI ist jetzt auf Maximum (300). Höhere Werte bringen keine Verbesserung, erhöhen aber:
- RAM-Verbrauch (große PDFs können OOM verursachen)
- Verarbeitungszeit

**Alternative: Tesseract-Config tunen:**
Falls OCR immer noch ungenau:
```python
# In extractor.py, Funktion _ocr_image()
# Aktuell: config="--psm 3" (automatic page segmentation)
# Alternativ für Lieferscheine:
config="--psm 6"  # Assume uniform block of text
config="--psm 11" # Sparse text, no order
```

### Monitoring nach Änderung:
```bash
# Services aktiv?
systemctl status docaro docaro-worker

# DPI-Wert prüfen:
grep DOCARO_RENDER_DPI /etc/docaro/docaro.env

# Test mit echtem Lieferschein:
sudo -u docaro /opt/Docaro/.venv/bin/python /opt/Docaro/test_supplier_detection.py <PDF>
```

### Rollback (falls nötig):
```bash
sed -i '/DOCARO_RENDER_DPI/d' /etc/docaro/docaro.env
systemctl restart docaro docaro-worker
```

---
**Nächste Schritte:**
1. Teste mit dem problematischen Lieferschein (scan.pdf)
2. Wenn Förch immer noch nicht erkannt wird: OCR-Text analysieren
3. Falls Layout-Problem: `header_max_lines` von 40 auf 50-60 erhöhen
4. Falls persistent: Manuelle Förch-Regex in `detect_supplier_detailed()` hinzufügen

