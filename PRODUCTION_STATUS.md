# 🎉 Docaro Production System - Finales Setup (Feb 2026)

## ✅ **Was ist AKTIV & funktioniert perfekt**

```
┌─────────────────────────────────────────────────────────┐
│  🌐 DOCARO PRODUCTION (www.docaro.de)                   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  📄 PDF-Upload via Web-UI                              │
│    ↓                                                    │
│  🔍 OCR-Pipeline:                                       │
│    ├─ Tesseract (Primary, schnell ~400ms)              │
│    └─ PaddleOCR (Fallback bei Score < 400, ~1.8s)      │
│    ↓                                                    │
│  📊 Extraktion:                                         │
│    ├─ Lieferant (TF-IDF Klassifikator)                 │
│    ├─ Datum (Regex + Heuristik)                        │
│    └─ Dokumenttyp (Pattern-Matching)                   │
│    ↓                                                    │
│  ✅ Review-Queue:                                       │
│    ├─ Benutzer sieht Extraction                        │
│    ├─ Kann korrigieren (wenn falsch)                   │
│    └─ Speichert Korrektur → ground_truth.jsonl         │
│    ↓                                                    │
│  🌙 Nightly Training (02:00 Uhr):                      │
│    ├─ Sammelt alle Korrektionen                        │
│    ├─ Trainiert TF-IDF + LogisticRegression            │
│    └─ Speichert neues Modell                           │
│    ↓                                                    │
│  📈 System LERNT automatisch!                           │
│    └─ Nächster Scan → bessere Erkennung               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## 🎯 **Performance-Charakteristiken**

| Metrik | Wert | Anmerkung |
|--------|------|----------|
| **Website-Latenz** | < 100ms | HTTPS via Nginx |
| **PDF-Verarbeitung** | 400-2000ms | Abhängig von OCR-Fallback |
| **Tesseract OCR** | ~400ms | Primary, zuverlässig |
| **PaddleOCR OCR** | ~1800ms | Nur bei schlechtem Score |
| **Extraktion** | ~200ms | TF-IDF + Regex |
| **ML-Training** | ~1s | Nightly um 02:00 Uhr |
| **System RAM** | 180-200MB | Steady-state |
| **Disk Usage** | ~250GB | Platz für mehr als 10.000 PDFs |

## 📦 **Installierte Komponenten**

### **Core (Obligatorisch)**
- ✅ **Python 3.13**
- ✅ **Tesseract OCR** (Deutsch)
- ✅ **Poppler** (pdfinfo, pdftoppm)
- ✅ **pdf2image** (PDF → Images)
- ✅ **Flask** (Web-Framework)
- ✅ **Gunicorn** (WSGI-Server, 2 Worker × 4 Threads)
- ✅ **Redis** (Queue-Backend)
- ✅ **RQ** (Job-Queue für PDF-Verarbeitung)

### **ML/OCR (Aktiviert)**
- ✅ **PaddleOCR 3.4.0** (Fallback-OCR)
- ✅ **PaddlePaddle 3.3.0** (ML-Backend)
- ✅ **scikit-learn** (TF-IDF + LogisticRegression)
- ✅ **MLflow 3.9.0** (Experiment-Tracking lokal)
- ✅ **libGL1** (OpenCV-Dependency für PaddleOCR)

### **Optional (Entfernt - nicht genutzt)**
- ❌ **Docling** (zu groß, nie installiert)
- ❌ **Label Studio** (redundant mit Review-UI)
- ❌ **Qdrant** (zu früh für Skalierung)

## 🛠️ **Systemd Services**

```bash
# Hauptservices
sudo systemctl status docaro              # Flask/Gunicorn Web-App
sudo systemctl status docaro-worker       # RQ Worker für PDF-Queue
sudo systemctl status docaro-ml-scheduler # Nightly ML-Training um 02:00

# Infrastruktur
sudo systemctl status redis-server        # Queue-Backend
sudo systemctl status nginx               # Reverse-Proxy → HTTPS

# Alle starten
sudo systemctl start docaro docaro-worker docaro-ml-scheduler redis-server nginx
```

## 📊 **Monitoring & Logs**

### **Web-App Logs**
```bash
# Echtzeit-Monitoring
tail -f /opt/Docaro/data/logs/docaro.log

# Nach PaddleOCR-Aktivität suchen
grep -i "paddle\|upgrade\|rescue" /opt/Docaro/data/logs/docaro.log
```

### **ML-Training Logs**
```bash
# Letzte Training-Ausführung
journalctl -u docaro-ml-scheduler -n 50

# Training-Metriken
sqlite3 /opt/Docaro/data/ml/mlflow.db "SELECT * FROM metrics LIMIT 5;"
```

### **System Health**
```bash
# RAM/CPU
free -h && top -bn1 | head -5

# Disk
df -h /opt/Docaro

# Services
systemctl list-units | grep docaro
```

## 🔐 **SSL/HTTPS Setup**

- ✅ **Domain:** www.docaro.de
- ✅ **Zertifikat:** Let's Encrypt (automatisch erneuert)
- ✅ **Reverse-Proxy:** Nginx (Port 80/443 → 127.0.0.1:5001)
- ✅ **Firewall:** UFW (SSH, HTTP, HTTPS offen)

```bash
# Zertifikat Check
sudo certbot certificates

# Erneuern (manuell)
sudo certbot renew
```

## 🚀 **Deployment & Updates**

### **Code-Updates (aus GitHub)**
```bash
cd /opt/Docaro
git pull origin main
sudo systemctl restart docaro docaro-worker
```

### **Dependencies Updaten**
```bash
# Neue Versionen installieren
cd /opt/Docaro
/opt/Docaro/.venv/bin/pip install --upgrade -r requirements.txt

# Services neustarten
sudo systemctl restart docaro docaro-worker
```

### **ML-Modell Backup**
```bash
# Modell sichern vor Update
cp /opt/Docaro/data/ml/supplier_model.pkl /opt/Docaro/data/ml/supplier_model.pkl.backup

# MLflow-DB sichern
cp /opt/Docaro/data/ml/mlflow.db /opt/Docaro/data/ml/mlflow.db.backup
```

## 💡 **Best Practices für ML-Verbesserungen**

### **1. Korrektionen sammeln**
- Mindestens **50-100 Korrektionen** pro Lieferant für gutes Training
- Review-UI nutzen (einfach, schnell)

### **2. Training-Qualität überprüfen**
```bash
# Nach 02:00 Uhr-Training:
tail -20 /opt/Docaro/data/logs/extract_debug.log | grep -i training

# Modell-Verbesserung sehen
ls -lh /opt/Docaro/data/ml/supplier_model.pkl
```

### **3. Bei schlechten Ergebnissen**
```bash
# Korrektionen anschauen
head -5 /opt/Docaro/data/ml/ground_truth.jsonl

# Neue Lieferanten hinzufügen (wenn Pattern unbekannt)
# → System lernt automatisch nächste Nacht

# Fallback-Threshold anpassen (wenn zu viele False-Negatives)
export DOCARO_PADDLEOCR_FALLBACK_THRESHOLD=350  # Aggressiver
```

## 📈 **Skalierungspfad (Zukunft)**

| Meilenstein | Aktion | Grund |
|-------------|--------|-------|
| **100 Scans/Tag** | ← JETZT | TF-IDF reicht aus |
| **500 Scans/Tag** | Monitor RAM/CPU | ggf. Worker erhöhen |
| **1000+ Scans/Tag** | Elasticsearch für Text-Suche | Schnellere Dedup |
| **10.000+ Scans** | Qdrant Vector-DB | Semantische Suche |
| **50.000+ Scans** | Docling (größer Server) | Layout-Verstehen |
| **100.000+ Scans** | Distributed Training | BERT-Modelle |

## ✅ **Checkliste für Produktion**

- ✅ HTTPS aktiv (Let's Encrypt)
- ✅ SSL-Zertifikat gültig (auto-renew)
- ✅ Firewall konfiguriert (SSH, HTTP, HTTPS)
- ✅ Backups laufen? (GitHub für Code, MLflow für Modelle)
- ✅ Monitoring aktiv? (Logs zugänglich)
- ✅ OCR-System gut? (Tesseract + PaddleOCR)
- ✅ ML-Training aktiv? (02:00 Uhr Nightly)
- ✅ Performance okay? (< 2s pro PDF)
- ✅ Speicherplatz ausreichend? (251GB insgesamt, ~234GB frei)

## 🎯 **Nächste Schritte**

1. **Testphase:** 2-4 Wochen mit echten Dokumenten
   - Sammle Korrektionen
   - Beobachte ML-Training
   
2. **Optimierung:** Basierend auf Feedback
   - Fallback-Threshold anpassen
   - Lieferanten-Liste erweitern
   
3. **Skalierung:** Wenn Volumen > 1000/Tag
   - Überlege Elasticsearch/Qdrant
   - Erhöhe Worker-Count

---

## 📞 **Support**

**System läuft gut?** → Keep it as is! 
- `supervisor` hätte zu viel Overhead
- Aktuelle systemd-Setup ist ausreichend

**Probleme?** → Check diese Dateien:
1. `/opt/Docaro/data/logs/docaro.log` (Web-App)
2. `journalctl -u docaro-ml-scheduler` (ML-Training)
3. `/opt/Docaro/PADDLEOCR_INTEGRATION.md` (OCR-Hilfe)
4. `/opt/Docaro/ML_TRAINING.md` (ML-Erklärung)

---

**Docaro ist produktionsreif! 🚀**

Stand: 6. Februar 2026
