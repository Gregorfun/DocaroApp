# ✅ Zielserver Setup abgeschlossen – Cutover-Ready

**Datum**: 5. Februar 2026  
**Server**: `/opt/Docaro` (Zielserver)  
**Status**: ✅ Alle Dependencies installiert, bereit für Datenmigration

---

## 📦 Was wurde installiert?

### System-Dependencies ✅
- **Python**: 3.13.5
- **Tesseract OCR**: 5.5.0 (mit Deutsch-Support)
- **Poppler**: 25.03.0 (pdfinfo, pdftoppm)
- **Redis**: 8.0.2 (enabled, active)
- **Nginx**: 1.26.3 (Config vorbereitet, aber noch inaktiv)
- **Docker**: 29.2.1 + Docker Compose Plugin (enabled, active)
- **Build-Tools**: gcc, make, libjpeg-dev, zlib1g-dev, etc.

### Python Virtual Environment ✅
- **Pfad**: `/opt/Docaro/.venv`
- **Pip**: 25.1.1
- **Packages**: Flask 3.1.2, Gunicorn 25.0.1, Redis 7.1.0, Pillow 12.1.0, pytesseract 0.3.13, pdf2image 1.17.0, PyMuPDF 1.26.7, pdfplumber 0.11.9, PyPDF2 3.0.1, RQ 2.6.1, PyYAML 6.0.3

### User & Permissions ✅
- **User**: `docaro` (uid=102, gid=104)
- **Home**: `/opt/Docaro`
- **Besitzer**: `/opt/Docaro` → `docaro:docaro`

### systemd Units ✅
- `/etc/systemd/system/docaro.service` (Web/Gunicorn)
- `/etc/systemd/system/docaro-worker.service` (RQ Worker)
- **Status**: installiert, daemon-reload ausgeführt, **noch NICHT gestartet**

### Config ✅
- **Environment**: `/etc/docaro/docaro.env` (Template, wird per rsync vom Quellserver überschrieben)
- **Nginx**: `/etc/nginx/sites-available/docaro` (vorbereitet, aber noch NICHT aktiviert)

### Verzeichnisse ✅
```
/opt/Docaro/data/
├── arbeitsordner/    (leer, wird per rsync befüllt)
├── eingang/          (leer, wird per rsync befüllt)
├── fertig/           (leer, wird per rsync befüllt)
├── logs/             (leer, wird per rsync befüllt)
├── ml/               (leer, wird per rsync befüllt)
├── quarantaene/      (leer, wird per rsync befüllt)
├── tmp/              (leer, wird per rsync befüllt)
└── uploads/          (leer, wird per rsync befüllt)
```

### Prestart-Check ✅
```json
{"ok": true, "checks": [
  {"ok": true, "name": "py:flask"},
  {"ok": true, "name": "py:gunicorn"},
  {"ok": true, "name": "py:pytesseract"},
  {"ok": true, "name": "cmd:tesseract", "detail": "/usr/bin/tesseract"},
  {"ok": true, "name": "cmd:pdfinfo", "detail": "/usr/bin/pdfinfo"},
  {"ok": true, "name": "cmd:pdftoppm", "detail": "/usr/bin/pdftoppm"},
  {"ok": true, "name": "tesseract:langs", "detail": "has deu"},
  {"ok": true, "name": "fs:/opt/Docaro/data/eingang"}
]}
```

---

## 🚀 Nächster Schritt: CUTOVER (Phase 3)

**Voraussetzung**: Backup auf Quellserver abgeschlossen ✅

### Cutover-Ablauf (2-5 Minuten Downtime)

#### 1️⃣ Quellserver stoppen

```bash
# AUF QUELLSERVER ausführen:
ssh root@<QUELLSERVER_IP>

sudo systemctl stop docaro docaro-worker
sudo systemctl status docaro docaro-worker
# Erwartet: inactive (dead)

# Optional: Nginx stoppen (falls öffentlich erreichbar)
# sudo systemctl stop nginx
```

#### 2️⃣ Finaler Daten-Sync (Quellserver → Zielserver)

**AUF ZIELSERVER ausführen** (dieser Server):

```bash
# ─────────────────────────────────────────────────────────────
# WICHTIG: <QUELLSERVER_IP> durch echte IP ersetzen!
# ─────────────────────────────────────────────────────────────
QUELLSERVER="root@<QUELLSERVER_IP>"

# Daten synchronisieren
sudo rsync -aH --numeric-ids --info=progress2 \
  "$QUELLSERVER:/opt/docaro/data/" \
  /opt/Docaro/data/

sudo chown -R docaro:docaro /opt/Docaro/data

# Config synchronisieren (inkl. Secrets!)
sudo rsync -aH "$QUELLSERVER:/etc/docaro/docaro.env" /etc/docaro/docaro.env
sudo chown root:root /etc/docaro/docaro.env
sudo chmod 640 /etc/docaro/docaro.env

# Systemd-Units (falls auf Quellserver angepasst)
sudo rsync -aH "$QUELLSERVER:/etc/systemd/system/docaro*.service" /etc/systemd/system/
sudo systemctl daemon-reload

# Docker-Volumes (optional, falls Services genutzt werden)
if ssh "$QUELLSERVER" "[ -d /opt/docaro/docker/qdrant_storage ]"; then
  sudo rsync -aH --numeric-ids \
    "$QUELLSERVER:/opt/docaro/docker/qdrant_storage/" \
    /opt/Docaro/docker/qdrant_storage/
fi

if ssh "$QUELLSERVER" "[ -d /opt/docaro/docker/label_studio_data ]"; then
  sudo rsync -aH --numeric-ids \
    "$QUELLSERVER:/opt/docaro/docker/label_studio_data/" \
    /opt/Docaro/docker/label_studio_data/
fi

if ssh "$QUELLSERVER" "[ -d /opt/docaro/docker/mlflow_data ]"; then
  sudo rsync -aH --numeric-ids \
    "$QUELLSERVER:/opt/docaro/docker/mlflow_data/" \
    /opt/Docaro/docker/mlflow_data/
fi

# Nginx-Config (falls vorhanden)
sudo rsync -aH "$QUELLSERVER:/etc/nginx/sites-available/docaro*" /etc/nginx/sites-available/ || true
```

#### 3️⃣ Services starten

```bash
# Services aktivieren und starten
sudo systemctl enable --now docaro docaro-worker
sudo systemctl status docaro docaro-worker

# Logs live beobachten (separates Terminal)
sudo journalctl -u docaro -u docaro-worker -f

# Docker-Services (optional)
cd /opt/Docaro/docker
docker compose up -d
docker compose ps

# Nginx aktivieren
sudo ln -sf /etc/nginx/sites-available/docaro /etc/nginx/sites-enabled/docaro
sudo nginx -t
sudo systemctl reload nginx
```

#### 4️⃣ Health-Check

```bash
# Services laufen?
sudo systemctl is-active docaro docaro-worker redis-server

# HTTP-Endpoint antwortet?
curl -sS http://127.0.0.1:5001/ | head -n 20

# Daten vorhanden?
ls -lh /opt/Docaro/data/eingang | head
ls -lh /opt/Docaro/data/fertig | head

# Anzahl Dateien (mit Quellserver vergleichen)
find /opt/Docaro/data/eingang -type f | wc -l
find /opt/Docaro/data/fertig -type f | wc -l

# Redis erreichbar?
redis-cli ping

# Logs ohne Fehler?
sudo journalctl -u docaro --since "5 minutes ago" --no-pager | tail -n 50
```

---

## 🛠️ Schnell-Befehle für Cutover

**Kopiere diese Befehle in ein Skript `cutover.sh`:**

```bash
#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# CUTOVER-SCRIPT: Daten vom Quellserver holen & Services starten
# ─────────────────────────────────────────────────────────────

QUELLSERVER="${1:-root@QUELLSERVER_IP_HIER_EINTRAGEN}"

echo "════════════════════════════════════════════════════════════"
echo "🚚 Docaro Cutover: $QUELLSERVER → $(hostname)"
echo "════════════════════════════════════════════════════════════"
echo ""

read -p "⚠️  Ist Quellserver GESTOPPT? (docaro/docaro-worker inactive?) [y/N]: " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
  echo "❌ Abbruch: Quellserver muss zuerst gestoppt werden!"
  exit 1
fi

echo ""
echo "📦 Schritt 1/4: Daten synchronisieren..."
sudo rsync -aH --numeric-ids --info=progress2 \
  "$QUELLSERVER:/opt/docaro/data/" \
  /opt/Docaro/data/
sudo chown -R docaro:docaro /opt/Docaro/data
echo "✅ Daten synchronisiert"

echo ""
echo "⚙️  Schritt 2/4: Config + systemd Units synchronisieren..."
sudo rsync -aH "$QUELLSERVER:/etc/docaro/docaro.env" /etc/docaro/docaro.env
sudo chown root:root /etc/docaro/docaro.env
sudo chmod 640 /etc/docaro/docaro.env
sudo rsync -aH "$QUELLSERVER:/etc/systemd/system/docaro*.service" /etc/systemd/system/ || true
sudo systemctl daemon-reload
echo "✅ Config synchronisiert"

echo ""
echo "🚀 Schritt 3/4: Services starten..."
sudo systemctl enable --now docaro docaro-worker
sleep 3
sudo systemctl status docaro docaro-worker --no-pager
echo "✅ Services gestartet"

echo ""
echo "🔍 Schritt 4/4: Health-Check..."
if sudo systemctl is-active --quiet docaro docaro-worker; then
  echo "✅ Services: active"
else
  echo "❌ Services: NICHT active!"
  exit 1
fi

if redis-cli ping > /dev/null 2>&1; then
  echo "✅ Redis: PONG"
else
  echo "❌ Redis: nicht erreichbar!"
  exit 1
fi

if curl -sS -m 5 http://127.0.0.1:5001/ > /dev/null 2>&1; then
  echo "✅ HTTP: antwortet"
else
  echo "⚠️  HTTP: noch nicht erreichbar (Service startet gerade?)"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "🎉 Cutover abgeschlossen!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "📊 Nächste Schritte:"
echo "  1. Logs prüfen:         sudo journalctl -u docaro -f"
echo "  2. Nginx aktivieren:    sudo ln -s /etc/nginx/sites-available/docaro /etc/nginx/sites-enabled/docaro"
echo "  3.                      sudo nginx -t && sudo systemctl reload nginx"
echo "  4. Web-UI testen:       http://$(hostname -I | awk '{print $1}'):5001"
echo "  5. Docker-Services:     cd /opt/Docaro/docker && docker compose up -d"
echo ""
```

**Skript ausführbar machen:**
```bash
chmod +x cutover.sh
```

**Cutover durchführen:**
```bash
./cutover.sh root@<QUELLSERVER_IP>
```

---

## 📞 Bei Problemen

### Service startet nicht
```bash
sudo journalctl -u docaro -n 100 --no-pager
sudo -u docaro -H /opt/Docaro/.venv/bin/python /opt/Docaro/tools/prestart_check.py
```

### Rollback (falls kritischer Fehler)
```bash
# AUF QUELLSERVER:
sudo systemctl start docaro docaro-worker
sudo systemctl start nginx

# DNS zurückschalten (falls bereits umgestellt)
```

---

## ✅ Checkliste vor Cutover

- [ ] Backup auf Quellserver abgeschlossen
- [ ] Quellserver kann per SSH erreicht werden (`ssh root@<QUELLSERVER_IP>`)
- [ ] Wartungsfenster kommuniziert (2-5 Minuten Downtime)
- [ ] Rollback-Plan verstanden
- [ ] Alle Befehle getestet (rsync dry-run: `--dry-run`)

---

**Ready! 🚀**

Wenn du bereit bist, führe **Phase 3 (Cutover)** aus (siehe `MIGRATION_RUNBOOK.md` oder `cutover.sh`).
