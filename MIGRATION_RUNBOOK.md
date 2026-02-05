# 🚚 Docaro Server-Migration: Verlustfreies Runbook

**Ziel**: Docaro vom **Quellserver** (alt) auf den **Zielserver** (neu, `/opt`) umziehen – ohne Datenverlust, mit Rollback-Option.

**Status**: ✅ Git-Repo bereits auf Ziel-Server geklont (`/opt/Docaro`), SSH-Key konfiguriert.

---

## 📋 Überblick: Was wird migriert?

| Komponente | Pfad (alt) | Pfad (neu) | Methode |
|------------|------------|------------|---------|
| **Code** | (Git) | `/opt/Docaro` | ✅ Git `pull` (bereits geklont) |
| **Daten** | `/opt/docaro/data/` | `/opt/Docaro/data/` | rsync (unidirektional, Backup vorher) |
| **Config** | `/etc/docaro/docaro.env` | `/etc/docaro/docaro.env` | rsync/scp + manueller Check |
| **systemd Units** | `/etc/systemd/system/docaro*.service` | `/etc/systemd/system/docaro*.service` | rsync/scp + `daemon-reload` |
| **Services** | Redis, optional Docker (Qdrant, Label Studio, MLflow) | Redis + Docker Compose | Neuinstall + Daten-Import |
| **Nginx** (optional) | `/etc/nginx/sites-enabled/docaro` | `/etc/nginx/sites-enabled/docaro` | rsync/scp + Test |

---

## ⚠️ Kritische Datenpfade (niemals über Git!)

Folgende Verzeichnisse/Dateien liegen in `.gitignore` und **müssen** per `rsync` migriert werden:

```
data/tmp/              # Temporäre Dateien (kann ggf. leer sein)
data/eingang/          # 📥 Eingehende Dokumente (KRITISCH)
data/fertig/           # ✅ Verarbeitete Dokumente (KRITISCH)
data/uploads/          # ☁️  Web-Uploads (KRITISCH)
data/quarantaene/      # ⚠️  Problematische Dokumente (KRITISCH)
data/logs/             # 📝 Anwendungs-Logs
data/ml/               # 🤖 ML-Modelle, Trainingsdaten
data/arbeitsordner/    # 🔧 Temporäre Arbeitskopien
data/session_files.json   # User-Sessions
data/settings.json        # App-Einstellungen
```

**Docker-Volumes** (falls Services laufen):
```
docker/qdrant_storage/       # Qdrant Vektor-DB
docker/label_studio_data/    # Label Studio Projekte
docker/label_studio_media/   # Label Studio Uploads
docker/mlflow_data/          # MLflow Experimente
```

---

## 🎯 Migrations-Strategie (Zero Data Loss)

### Phase 1: **Vorbereitung & Backup** (Quellserver läuft)
### Phase 2: **Zielserver Setup** (parallel, Quellserver läuft)
### Phase 3: **Cutover** (kurze Downtime ~2-5 min)
### Phase 4: **Verifikation**
### Phase 5: **Rollback-Bereitschaft** (Quellserver 24h+ live halten)

---

## 📦 Phase 1: Backup auf Quellserver (PFLICHT!)

**Ausführen auf**: QUELLSERVER (alter Server)

```bash
# ─────────────────────────────────────────────────────────────
# 1.1 Vollständiges Backup der Daten (außerhalb /opt/docaro)
# ─────────────────────────────────────────────────────────────
BACKUP_DIR="/backup/docaro_migration_$(date +%Y%m%d_%H%M%S)"
sudo mkdir -p "$BACKUP_DIR"

# Daten sichern
sudo rsync -aH --info=progress2 /opt/docaro/data/ "$BACKUP_DIR/data/"

# Config sichern
sudo rsync -aH /etc/docaro/ "$BACKUP_DIR/etc_docaro/
sudo rsync -aH /etc/systemd/system/docaro*.service "$BACKUP_DIR/systemd/"

# Nginx (falls vorhanden)
sudo rsync -aH /etc/nginx/sites-available/docaro* "$BACKUP_DIR/nginx/" || true

# Docker-Volumes (falls genutzt)
if [ -d /opt/docaro/docker/qdrant_storage ]; then
  sudo rsync -aH /opt/docaro/docker/qdrant_storage/ "$BACKUP_DIR/docker/qdrant_storage/
fi
if [ -d /opt/docaro/docker/label_studio_data ]; then
  sudo rsync -aH /opt/docaro/docker/label_studio_data/ "$BACKUP_DIR/docker/label_studio_data/
fi
if [ -d /opt/docaro/docker/mlflow_data ]; then
  sudo rsync -aH /opt/docaro/docker/mlflow_data/ "$BACKUP_DIR/docker/mlflow_data/
fi

echo "✅ Backup abgeschlossen: $BACKUP_DIR"
ls -lh "$BACKUP_DIR"

# Optional: Backup komprimieren für schnelleren Transfer
cd /backup
sudo tar czf docaro_backup_$(date +%Y%m%d).tar.gz docaro_migration_*
```

**Warum?** Falls etwas schief geht, können wir alles 1:1 wiederherstellen.

---

## 🖥️ Phase 2: Zielserver vorbereiten

**Ausführen auf**: ZIELSERVER (neu, `/opt`)

### 2.1 System-Dependencies installieren

```bash
# ─────────────────────────────────────────────────────────────
# Basis-Pakete (Debian/Ubuntu)
# ─────────────────────────────────────────────────────────────
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip python3-dev build-essential \
  tesseract-ocr tesseract-ocr-deu \
  poppler-utils \
  redis-server \
  nginx \
  rsync \
  ca-certificates

# Optional: Zusätzliche Bild-Libraries (für ML/Pillow)
sudo apt-get install -y libjpeg-dev zlib1g-dev libfreetype6-dev libopenjp2-7-dev libtiff5-dev

# Redis aktivieren
sudo systemctl enable --now redis-server
sudo systemctl status redis-server
```

### 2.2 User `docaro` anlegen (falls nicht vorhanden)

```bash
# User anlegen (systemd erwartet User=docaro)
sudo adduser --system --group --home /opt/Docaro docaro

# Repo-Besitz anpassen (Git-Clone wurde bereits als root durchgeführt)
sudo chown -R docaro:docaro /opt/Docaro
```

### 2.3 Python venv + Dependencies installieren

```bash
cd /opt/Docaro

# Virtual Environment erstellen
sudo -u docaro -H python3 -m venv .venv

# Pip upgraden
sudo -u docaro -H /opt/Docaro/.venv/bin/python -m pip install --upgrade pip

# Runtime-Dependencies installieren
sudo -u docaro -H /opt/Docaro/.venv/bin/pip install -r requirements.txt

# Optional: Pipeline/ML-Dependencies (falls genutzt)
# sudo -u docaro -H /opt/Docaro/.venv/bin/pip install -r requirements-pipeline.txt
# sudo -u docaro -H /opt/Docaro/.venv/bin/pip install -r requirements-ml.txt

# Prestart-Check (optional, testet Abhängigkeiten)
sudo -u docaro -H /opt/Docaro/.venv/bin/python /opt/Docaro/tools/prestart_check.py | head -n 30
```

### 2.4 Environment-Datei vorbereiten (noch LEER, wird später synced)

```bash
# Verzeichnis anlegen
sudo mkdir -p /etc/docaro

# TEMPORÄRE Test-Config (wird später überschrieben!)
sudo cp /opt/Docaro/deploy/docaro.env.example /etc/docaro/docaro.env
sudo chown root:root /etc/docaro/docaro.env
sudo chmod 640 /etc/docaro/docaro.env

# Optional: Variablen prüfen (wird später aus Quellserver übernommen)
cat /etc/docaro/docaro.env
```

### 2.5 Systemd Units vorbereiten (noch NICHT starten!)

```bash
# Units aus Repo kopieren
sudo cp /opt/Docaro/deploy/systemd/docaro.service /etc/systemd/system/docaro.service
sudo cp /opt/Docaro/deploy/systemd/docaro-worker.service /etc/systemd/system/docaro-worker.service
sudo systemctl daemon-reload

# NICHT aktivieren/starten (noch keine echten Daten!)
echo "✅ systemd Units installiert, aber inaktiv (warten auf Datenmigration)"
```

---

## 🔄 Phase 3: Cutover (Downtime 2-5 min)

**Timing**: Wartungsfenster (z.B. nachts oder Wochenende)

### 3.1 Quellserver stoppen (Downtime beginnt!)

**Ausführen auf**: QUELLSERVER

```bash
# ─────────────────────────────────────────────────────────────
# Services stoppen (verhindert neue Änderungen)
# ─────────────────────────────────────────────────────────────
sudo systemctl stop docaro docaro-worker
sudo systemctl status docaro docaro-worker

# Optional: Nginx deaktivieren (falls Traffic vom Internet kommt)
# sudo systemctl stop nginx

echo "⏸️  Downtime: Quellserver gestoppt"
```

### 3.2 Finaler Daten-Sync (Quellserver → Zielserver)

**Ausführen auf**: ZIELSERVER (pull vom Quellserver)

```bash
# ─────────────────────────────────────────────────────────────
# ACHTUNG: <QUELLSERVER_IP> durch echte IP/Hostname ersetzen!
# ─────────────────────────────────────────────────────────────
QUELLSERVER="root@<QUELLSERVER_IP>"  # z.B. root@192.168.1.100 oder root@alt.example.com

# 3.2.1 Daten synchronisieren (Hauptpfad: data/)
sudo rsync -aH --numeric-ids --info=progress2 \
  "$QUELLSERVER:/opt/docaro/data/" \
  /opt/Docaro/data/

# Besitz auf docaro-User anpassen
sudo chown -R docaro:docaro /opt/Docaro/data

# 3.2.2 Config übernehmen (inkl. Secrets!)
sudo rsync -aH "$QUELLSERVER:/etc/docaro/docaro.env" /etc/docaro/docaro.env
sudo chown root:root /etc/docaro/docaro.env
sudo chmod 640 /etc/docaro/docaro.env

# 3.2.3 Systemd-Units synchronisieren (falls auf Quellserver angepasst)
sudo rsync -aH "$QUELLSERVER:/etc/systemd/system/docaro*.service" /etc/systemd/system/
sudo systemctl daemon-reload

# 3.2.4 Docker-Volumes (falls Services genutzt werden)
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

# 3.2.5 Nginx-Config (falls vorhanden)
sudo rsync -aH "$QUELLSERVER:/etc/nginx/sites-available/docaro*" /etc/nginx/sites-available/ || true
sudo ln -sf /etc/nginx/sites-available/docaro /etc/nginx/sites-enabled/docaro || true

echo "✅ Finaler Sync abgeschlossen"
```

### 3.3 Zielserver starten (Services aktivieren)

**Ausführen auf**: ZIELSERVER

```bash
# ─────────────────────────────────────────────────────────────
# Services starten
# ─────────────────────────────────────────────────────────────
sudo systemctl enable --now docaro docaro-worker
sudo systemctl status docaro docaro-worker

# Logs live beobachten (in separatem Terminal)
# sudo journalctl -u docaro -u docaro-worker -f

# Optional: Docker-Services starten
if [ -f /opt/Docaro/docker/docker-compose.yml ]; then
  cd /opt/Docaro/docker
  docker-compose up -d
  docker-compose ps
fi

# Nginx neustarten (falls Config geändert)
sudo nginx -t
sudo systemctl reload nginx

# SSL/HTTPS einrichten (empfohlen für www.docaro.de)
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d www.docaro.de -d docaro.de

echo "✅ Zielserver läuft!"
```

### 3.4 DNS/Loadbalancer umstellen (falls öffentlich erreichbar)

**Wenn Docaro über Domain erreichbar ist:**

1. **TTL vorher auf 60s senken** (24h vor Migration) bei deinem DNS-Provider
2. **DNS A-Record auf neue IP ändern** (im DNS-Provider für `www.docaro.de` und `docaro.de`)
3. **Warten**: `dig www.docaro.de +short` → sollte neue IP zeigen
4. **Health-Check**: `curl -I http://www.docaro.de`
5. **SSL einrichten**:
   ```bash
   sudo apt-get install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d www.docaro.de -d docaro.de
   # Certbot konfiguriert automatisch HTTPS-Redirect
   ```

**Wenn interner Zugriff (z.B. VPN/LAN):**
- Clients müssen `/etc/hosts` oder interne DNS-Einträge aktualisieren

---

## ✅ Phase 4: Verifikation (kritisch!)

**Ausführen auf**: ZIELSERVER

```bash
# ─────────────────────────────────────────────────────────────
# 4.1 Services laufen?
# ─────────────────────────────────────────────────────────────
sudo systemctl is-active docaro docaro-worker redis-server
# Erwartet: active active active

# ─────────────────────────────────────────────────────────────
# 4.2 HTTP-Endpoint antwortet?
# ─────────────────────────────────────────────────────────────
curl -sS http://127.0.0.1:5001/ | head -n 20
# Erwartet: HTML oder JSON (kein 502/504)

# ─────────────────────────────────────────────────────────────
# 4.3 Daten vorhanden?
# ─────────────────────────────────────────────────────────────
ls -lh /opt/Docaro/data/eingang | head
ls -lh /opt/Docaro/data/fertig | head
ls -lh /opt/Docaro/data/uploads | head

# Anzahl Dateien vergleichen (mit Quellserver)
find /opt/Docaro/data/eingang -type f | wc -l
find /opt/Docaro/data/fertig -type f | wc -l

# ─────────────────────────────────────────────────────────────
# 4.4 Settings/Session intakt?
# ─────────────────────────────────────────────────────────────
if [ -f /opt/Docaro/data/settings.json ]; then
  jq '.' /opt/Docaro/data/settings.json | head -n 20  # Syntax-Check
fi

# ─────────────────────────────────────────────────────────────
# 4.5 Redis erreichbar?
# ─────────────────────────────────────────────────────────────
redis-cli ping
# Erwartet: PONG

# ─────────────────────────────────────────────────────────────
# 4.6 Docker-Services (falls genutzt)
# ─────────────────────────────────────────────────────────────
cd /opt/Docaro/docker
docker-compose ps
# Erwartet: qdrant, label-studio, mlflow → Up

# Qdrant Dashboard testen
curl -s http://localhost:6333/collections || echo "Qdrant nicht erreichbar"

# ─────────────────────────────────────────────────────────────
# 4.7 Logs prüfen (keine Fehler?)
# ─────────────────────────────────────────────────────────────
sudo journalctl -u docaro --since "5 minutes ago" --no-pager | tail -n 50
sudo journalctl -u docaro-worker --since "5 minutes ago" --no-pager | tail -n 50

# Erwartung: Keine ERROR/CRITICAL, nur INFO/DEBUG

# ─────────────────────────────────────────────────────────────
# 4.8 Funktionaler Smoke-Test (Web-UI)
# ─────────────────────────────────────────────────────────────
# 1. Browser öffnen: http://<NEUE_IP>:5001  (oder https://docaro.example.com)
# 2. Login möglich?
# 3. Bisherige Dokumente sichtbar?
# 4. Upload-Test: Neues Dokument hochladen → Verarbeitung läuft?
```

**Checkliste (alle ✅ = Migration erfolgreich):**

- [ ] systemd Services `active`
- [ ] HTTP-Endpoint antwortet
- [ ] Anzahl Dateien in `data/` stimmt mit Quellserver überein
- [ ] `settings.json` / `session_files.json` vorhanden & valide
- [ ] Redis läuft (`PONG`)
- [ ] Docker-Services laufen (falls genutzt)
- [ ] Logs zeigen keine Fehler
- [ ] Web-UI: Login + Dokumentenliste korrekt
- [ ] Test-Upload/Processing funktioniert

---

## 🔙 Phase 5: Rollback (falls etwas schief geht)

**Nur ausführen, wenn Zielserver NICHT funktioniert!**

### Rollback auf Quellserver

**Ausführen auf**: QUELLSERVER

```bash
# ─────────────────────────────────────────────────────────────
# Services wieder starten
# ─────────────────────────────────────────────────────────────
sudo systemctl start docaro docaro-worker
sudo systemctl status docaro docaro-worker

# Nginx (falls gestoppt)
sudo systemctl start nginx

echo "✅ Quellserver wieder aktiv (Rollback)"
```

**DNS zurückschalten** (falls bereits umgestellt):
- A-Record auf alte IP ändern
- Warten: `dig docaro.example.com +short`

**Wichtig**: Quellserver **mindestens 24-48h** nach Migration aktiv lassen (für Notfall-Rollback).

---

## 🧹 Phase 6: Cleanup (nach erfolgreicher Migration, +24h)

**Nur ausführen, wenn Zielserver seit 24+ Stunden stabil läuft!**

### Quellserver stilllegen

**Ausführen auf**: QUELLSERVER

```bash
# ─────────────────────────────────────────────────────────────
# 1. Finale Bestätigung: Zielserver läuft perfekt?
# ─────────────────────────────────────────────────────────────
# JA → weitermachen
# NEIN → NICHT stilllegen!

# ─────────────────────────────────────────────────────────────
# 2. Services dauerhaft deaktivieren
# ─────────────────────────────────────────────────────────────
sudo systemctl stop docaro docaro-worker
sudo systemctl disable docaro docaro-worker

# ─────────────────────────────────────────────────────────────
# 3. Optional: Daten archivieren (statt löschen)
# ─────────────────────────────────────────────────────────────
cd /opt
sudo tar czf docaro_archiv_$(date +%Y%m%d).tar.gz docaro/

# Archiv auf externen Storage verschieben (z.B. S3, NAS)
# aws s3 cp docaro_archiv_*.tar.gz s3://backup-bucket/
# rsync -aH docaro_archiv_*.tar.gz backup-server:/archives/

# ─────────────────────────────────────────────────────────────
# 4. Optional: /opt/docaro löschen (erst nach Archiv-Bestätigung!)
# ─────────────────────────────────────────────────────────────
# sudo rm -rf /opt/docaro  # VORSICHT: unwiderruflich!

echo "✅ Quellserver stillgelegt"
```

---

## 📊 Downtime-Übersicht

| Phase | Quellserver | Zielserver | Downtime | Dauer |
|-------|-------------|------------|----------|-------|
| 1. Backup | ✅ läuft | - | ❌ Nein | 5-30 min |
| 2. Setup Ziel | ✅ läuft | 🔧 Installation | ❌ Nein | 15-45 min |
| **3. Cutover** | ⏸️ **STOP** | 🔄 Sync + Start | ⚠️ **JA** | **2-5 min** |
| 4. Verifikation | ⏸️ idle | ✅ läuft | ❌ Nein (Ziel live) | 10-20 min |
| 5. Rollback (nur Notfall) | ✅ restart | ⏸️ stop | ⚠️ JA | 2 min |

**Minimale Downtime**: ~2-5 Minuten (Phase 3.1 bis 3.3)

---

## 🛠️ Troubleshooting

### Problem: `rsync` schlägt fehl (Permission Denied)

```bash
# SSH-Key für root@Quellserver hinterlegen
ssh-copy-id root@<QUELLSERVER_IP>

# Alternativ: mit Passwort (bei Prompt eingeben)
rsync -aH -e "ssh -o PreferredAuthentications=password" ...
```

### Problem: systemd Unit startet nicht (`ExecStartPre failed`)

```bash
# Prestart-Check manuell ausführen
sudo -u docaro -H /opt/Docaro/.venv/bin/python /opt/Docaro/tools/prestart_check.py

# Fehlende Dependencies nachinstallieren
sudo -u docaro -H /opt/Docaro/.venv/bin/pip install -r /opt/Docaro/requirements.txt
```

### Problem: Redis nicht erreichbar (`Connection refused`)

```bash
# Redis neu starten
sudo systemctl restart redis-server
sudo systemctl status redis-server

# Port-Check
sudo netstat -tlnp | grep 6379
```

### Problem: Nginx 502 Bad Gateway

```bash
# Gunicorn läuft?
sudo systemctl status docaro

# Bind-Adresse prüfen (muss 127.0.0.1:5001 sein)
sudo netstat -tlnp | grep 5001

# Nginx-Logs prüfen
sudo tail -n 50 /var/log/nginx/error.log
```

### Problem: Docker-Services starten nicht

```bash
cd /opt/Docaro/docker

# Logs prüfen
docker-compose logs -f qdrant
docker-compose logs -f label-studio

# Volumes-Permissions
sudo chown -R 1000:1000 qdrant_storage label_studio_data mlflow_data
```

---

## 📞 Support-Kontakte (intern)

- **Docaro Docs**: [DEPLOYMENT_LINUX.md](DEPLOYMENT_LINUX.md), [QUICKSTART.md](QUICKSTART.md)
- **systemd Units**: `/opt/Docaro/deploy/systemd/`
- **Logs**: `sudo journalctl -u docaro -u docaro-worker -f`

---

## ✅ Migration Complete Checklist

Nach Abschluss:

- [ ] Zielserver läuft seit 24+ Stunden stabil
- [ ] Backups vom Quellserver extern gesichert
- [ ] DNS zeigt auf neuen Server (und TTL wieder hoch)
- [ ] Quellserver stillgelegt (Services disabled)
- [ ] Monitoring/Alerting auf neue IP umgestellt
- [ ] Dokumentation aktualisiert (IP, Hostname, etc.)

**🎉 Migration abgeschlossen!**
