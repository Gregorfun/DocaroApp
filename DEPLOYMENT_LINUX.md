# Linux/VPS Deployment (Production)

Ziel: Auf einem neuen Server nach `git pull` sauber installieren, starten und betreiben – ohne dass `data/` über Git übertragen werden muss.

## 1) Verzeichnis- und User-Layout (empfohlen)

- Code: `/opt/docaro` (Git-Repo)
- Daten: `/opt/docaro/data` (liegt zwar im Repo-Pfad, ist aber **nicht** in Git)
- Service-User: `docaro`

User anlegen:

```bash
sudo adduser --system --group --home /opt/docaro docaro
```

Repo klonen (oder `git pull`, wenn bereits vorhanden):

```bash
sudo -u docaro -H git clone <DEIN_GIT_URL> /opt/docaro
```

Wenn das bisherige Remote-Repo nicht mehr existiert und du ein neues GitHub-Repo erstellt hast, siehe:

- [NEW_GITHUB_REPO_SETUP.md](NEW_GITHUB_REPO_SETUP.md)

## 2) System-Abhängigkeiten installieren

Siehe vollständige Liste in [DEPENDENCIES.md](DEPENDENCIES.md).

Schnellstart (Debian/Ubuntu):

```bash
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip python3-dev build-essential \
  tesseract-ocr tesseract-ocr-deu \
  poppler-utils \
  redis-server
```

Alternativ (Script):

```bash
cd /opt/docaro
chmod +x deploy/install_deps_ubuntu.sh
./deploy/install_deps_ubuntu.sh
```

Optional (wenn Pip Pakete aus Source bauen):

```bash
sudo apt-get install -y libjpeg-dev zlib1g-dev libfreetype6-dev libopenjp2-7-dev libtiff5-dev
```

## 3) Python venv + Runtime-Requirements

```bash
cd /opt/docaro
sudo -u docaro -H python3 -m venv .venv
sudo -u docaro -H /opt/docaro/.venv/bin/python -m pip install --upgrade pip
sudo -u docaro -H /opt/docaro/.venv/bin/pip install -r requirements.txt
```

Alternativ (Script):

```bash
cd /opt/docaro
chmod +x deploy/bootstrap_venv.sh
sudo -u docaro -H ./deploy/bootstrap_venv.sh /opt/docaro
```

Quick-Check (optional, aber hilfreich):

```bash
sudo -u docaro -H /opt/docaro/.venv/bin/python /opt/docaro/tools/prestart_check.py | head
```

## 4) Environment-Datei `/etc/docaro/docaro.env`

Die systemd Units erwarten:

- EnvironmentFile: `/etc/docaro/docaro.env`

Beispiel kopieren:

```bash
sudo mkdir -p /etc/docaro
sudo cp /opt/docaro/deploy/docaro.env.example /etc/docaro/docaro.env
sudo chown -R root:root /etc/docaro
sudo chmod 640 /etc/docaro/docaro.env
```

Wichtigste Variablen:

- `REDIS_URL` (default: `redis://localhost:6379`)
- `DOCARO_DEBUG=0|1`
- `DOCARO_AUTH_REQUIRED=1`
- `DOCARO_ALLOW_SELF_REGISTER=0`
- `DOCARO_SESSION_COOKIE_SECURE=1`
- optional: `DOCARO_RENDER_DPI`, `DOCARO_FOLDER_TIMEOUT`
- optional Observability: `DOCARO_METRICS_ENABLED=1`, `DOCARO_WORKER_METRICS_PORT=9108`
- empfohlen fuer Metrics-Schutz: `DOCARO_METRICS_TOKEN=<secret>`
- optional Sentry: `DOCARO_SENTRY_DSN`, `DOCARO_SENTRY_ENVIRONMENT`, `DOCARO_RELEASE`
- optional RQ Dashboard: `DOCARO_RQ_DASHBOARD_ENABLED=0|1`, `DOCARO_RQ_DASHBOARD_URL_PREFIX=/rq`
- optional Logging-Format: `DOCARO_LOG_FORMAT=json`
- optional Queue/OCR-Worker-Limits: `DOCARO_QUEUE_MAX_DEPTH`, `DOCARO_PROCESS_MAX_WORKERS`, `DOCARO_PROCESS_ADAPTIVE_WORKERS`
- optional Model-Gates: `DOCARO_MODEL_MIN_ACCURACY`, `DOCARO_MODEL_MIN_F1_WEIGHTED`

## 5) systemd Units installieren

Units liegen in:

- `deploy/systemd/`

Installation:

```bash
sudo cp /opt/docaro/deploy/systemd/docaro.service /etc/systemd/system/docaro.service
sudo cp /opt/docaro/deploy/systemd/docaro-worker.service /etc/systemd/system/docaro-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now redis-server
sudo systemctl enable --now docaro docaro-worker
```

Logs prüfen:

```bash
sudo journalctl -u docaro -f
sudo journalctl -u docaro-worker -f
```

## 6) Reverse Proxy (Nginx, optional aber üblich)

Gunicorn bindet standardmäßig an `127.0.0.1:5001`. Nginx kann TLS/öffentlichen Zugriff übernehmen.

Beispiel-Konfig:

- `deploy/nginx-docaro.conf`

## 7) Daten-Migration (ohne Git)

`data/` ist absichtlich in `.gitignore`.

Empfohlener Weg: `rsync` vom alten Server auf den neuen.

Beispiel:

```bash
# Auf dem NEUEN Server ausführen (pull vom alten Server)
sudo rsync -aH --numeric-ids --delete \
  <ALT_SERVER>:/opt/docaro/data/ /opt/docaro/data/
sudo chown -R docaro:docaro /opt/docaro/data
```

Falls du **nichts löschen** möchtest, lass `--delete` weg.

## 8) Smoke Test

- Web startet? `sudo systemctl status docaro`
- Worker läuft? `sudo systemctl status docaro-worker`
- HTTP lokal:

```bash
curl -sS http://127.0.0.1:5001/ | head
```

## 9) Update-Strategie

Empfohlen:

```bash
cd /opt/docaro
sudo -u docaro -H git pull
sudo -u docaro -H /opt/docaro/.venv/bin/pip install -r requirements.txt
sudo systemctl restart docaro docaro-worker
```

Optional gibt es eine Unit/Script-Schablone für automatische Updates:

- `deploy/systemd/docaro-update.service`
- `deploy/docaro-update.sh`

Wenn du das nutzt:

```bash
sudo install -m 0755 /opt/docaro/deploy/docaro-update.sh /usr/local/bin/docaro-update.sh
```

## 10) Optional: Monitoring Stack (Prometheus/Grafana)

Docaro exportiert Worker-Metriken auf `:9108` (default, via `DOCARO_WORKER_METRICS_PORT` anpassbar).

Stack starten:

```bash
cd /opt/docaro
docker compose -f docker/docker-compose.yml up -d prometheus grafana redis-exporter
```

Zugriff:

- Prometheus: `http://<server>:9090`
- Grafana: `http://<server>:3000` (Admin-Passwort ueber `DOCARO_GRAFANA_ADMIN_PASSWORD` setzen)

Hinweis: Die Compose-Datei bindet Prometheus, Grafana und Redis Exporter standardmaessig nur an `127.0.0.1`, damit diese Oberflaechen nicht ungeschuetzt oeffentlich erreichbar sind.
