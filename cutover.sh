#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# DOCARO CUTOVER: Daten vom Quellserver holen & Services starten
# ═══════════════════════════════════════════════════════════════

QUELLSERVER="${1:-}"

if [ -z "$QUELLSERVER" ]; then
  echo "❌ Fehler: Quellserver-Adresse fehlt!"
  echo ""
  echo "Verwendung:"
  echo "  $0 root@<QUELLSERVER_IP>"
  echo ""
  echo "Beispiel:"
  echo "  $0 root@192.168.1.100"
  echo "  $0 root@alt.example.com"
  exit 1
fi

echo "════════════════════════════════════════════════════════════"
echo "🚚 Docaro Cutover"
echo "════════════════════════════════════════════════════════════"
echo "  Quelle:  $QUELLSERVER:/opt/docaro/"
echo "  Ziel:    $(hostname):/opt/Docaro/"
echo "════════════════════════════════════════════════════════════"
echo ""

# ─────────────────────────────────────────────────────────────
# BESTÄTIGUNG: Quellserver gestoppt?
# ─────────────────────────────────────────────────────────────
echo "⚠️  WICHTIG: Quellserver MUSS gestoppt sein!"
echo ""
echo "   Auf Quellserver ausführen:"
echo "   $ sudo systemctl stop docaro docaro-worker"
echo "   $ sudo systemctl status docaro docaro-worker"
echo "   → Erwartet: inactive (dead)"
echo ""

read -p "✅ Ist Quellserver GESTOPPT? [y/N]: " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
  echo "❌ Abbruch: Quellserver muss zuerst gestoppt werden!"
  exit 1
fi

# ─────────────────────────────────────────────────────────────
# SCHRITT 1: SSH-Verbindung testen
# ─────────────────────────────────────────────────────────────
echo ""
echo "🔍 Teste SSH-Verbindung zu $QUELLSERVER..."
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$QUELLSERVER" "echo ok" > /dev/null 2>&1; then
  echo "❌ SSH-Verbindung fehlgeschlagen!"
  echo "   Prüfen:"
  echo "   - Ist die IP/Hostname korrekt?"
  echo "   - SSH-Key hinterlegt? (ssh-copy-id $QUELLSERVER)"
  exit 1
fi
echo "✅ SSH-Verbindung OK"

# ─────────────────────────────────────────────────────────────
# SCHRITT 2: Daten synchronisieren
# ─────────────────────────────────────────────────────────────
echo ""
echo "📦 Schritt 1/4: Daten synchronisieren (data/)..."
sudo rsync -aH --numeric-ids --info=progress2 \
  "$QUELLSERVER:/opt/docaro/data/" \
  /opt/Docaro/data/

sudo chown -R docaro:docaro /opt/Docaro/data
echo "✅ Daten synchronisiert"

# ─────────────────────────────────────────────────────────────
# SCHRITT 3: Config + systemd Units synchronisieren
# ─────────────────────────────────────────────────────────────
echo ""
echo "⚙️  Schritt 2/4: Config + systemd Units synchronisieren..."

# Environment-Datei (inkl. Secrets!)
sudo rsync -aH "$QUELLSERVER:/etc/docaro/docaro.env" /etc/docaro/docaro.env
sudo chown root:root /etc/docaro/docaro.env
sudo chmod 640 /etc/docaro/docaro.env

# systemd Units (falls auf Quellserver angepasst)
sudo rsync -aH "$QUELLSERVER:/etc/systemd/system/docaro*.service" /etc/systemd/system/ || true
sudo systemctl daemon-reload

# Nginx-Config (optional, falls vorhanden)
sudo rsync -aH "$QUELLSERVER:/etc/nginx/sites-available/docaro*" /etc/nginx/sites-available/ 2>/dev/null || true

echo "✅ Config synchronisiert"

# ─────────────────────────────────────────────────────────────
# SCHRITT 4: Docker-Volumes synchronisieren (optional)
# ─────────────────────────────────────────────────────────────
echo ""
echo "🐳 Optional: Docker-Volumes synchronisieren..."

if ssh "$QUELLSERVER" "[ -d /opt/docaro/docker/qdrant_storage ]" 2>/dev/null; then
  echo "  → Qdrant Storage..."
  sudo rsync -aH --numeric-ids \
    "$QUELLSERVER:/opt/docaro/docker/qdrant_storage/" \
    /opt/Docaro/docker/qdrant_storage/
  echo "  ✅ Qdrant"
fi

if ssh "$QUELLSERVER" "[ -d /opt/docaro/docker/label_studio_data ]" 2>/dev/null; then
  echo "  → Label Studio Data..."
  sudo rsync -aH --numeric-ids \
    "$QUELLSERVER:/opt/docaro/docker/label_studio_data/" \
    /opt/Docaro/docker/label_studio_data/
  echo "  ✅ Label Studio"
fi

if ssh "$QUELLSERVER" "[ -d /opt/docaro/docker/mlflow_data ]" 2>/dev/null; then
  echo "  → MLflow Data..."
  sudo rsync -aH --numeric-ids \
    "$QUELLSERVER:/opt/docaro/docker/mlflow_data/" \
    /opt/Docaro/docker/mlflow_data/
  echo "  ✅ MLflow"
fi

echo "✅ Docker-Volumes synchronisiert (falls vorhanden)"

# ─────────────────────────────────────────────────────────────
# SCHRITT 5: Services starten
# ─────────────────────────────────────────────────────────────
echo ""
echo "🚀 Schritt 3/4: Services starten..."
sudo systemctl enable --now docaro docaro-worker
sleep 3
sudo systemctl status docaro docaro-worker --no-pager -l
echo "✅ Services gestartet"

# ─────────────────────────────────────────────────────────────
# SCHRITT 6: Health-Check
# ─────────────────────────────────────────────────────────────
echo ""
echo "🔍 Schritt 4/4: Health-Check..."

# Services aktiv?
if sudo systemctl is-active --quiet docaro && sudo systemctl is-active --quiet docaro-worker; then
  echo "✅ Services: active"
else
  echo "❌ Services: NICHT active!"
  sudo systemctl status docaro docaro-worker --no-pager -l
  exit 1
fi

# Redis erreichbar?
if redis-cli ping > /dev/null 2>&1; then
  echo "✅ Redis: PONG"
else
  echo "❌ Redis: nicht erreichbar!"
  exit 1
fi

# HTTP antwortet?
sleep 2
if curl -sS -m 10 http://127.0.0.1:5001/ > /dev/null 2>&1; then
  echo "✅ HTTP: antwortet (http://127.0.0.1:5001)"
else
  echo "⚠️  HTTP: noch nicht erreichbar (Service startet noch?)"
  echo "   Logs prüfen: sudo journalctl -u docaro -n 50"
fi

# Daten vorhanden?
eingang_count=$(find /opt/Docaro/data/eingang -type f 2>/dev/null | wc -l)
fertig_count=$(find /opt/Docaro/data/fertig -type f 2>/dev/null | wc -l)
echo "✅ Daten: ${eingang_count} Dateien in eingang/, ${fertig_count} in fertig/"

# ─────────────────────────────────────────────────────────────
# FERTIG
# ─────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo "🎉 Cutover abgeschlossen!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "📊 Nächste Schritte:"
echo ""
echo "  1️⃣  Logs live beobachten:"
echo "      sudo journalctl -u docaro -u docaro-worker -f"
echo ""
echo "  2️⃣  Nginx aktivieren (falls noch nicht geschehen):"
echo "      sudo ln -sf /etc/nginx/sites-available/docaro /etc/nginx/sites-enabled/docaro"
echo "      sudo nginx -t && sudo systemctl reload nginx"
echo ""
echo "  3️⃣  Web-UI testen:"
echo "      http://www.docaro.de  (oder http://$(hostname -I | awk '{print $1}'):5001)"
echo ""
echo "  4️⃣  SSL/HTTPS einrichten (empfohlen):"
echo "      sudo apt-get install -y certbot python3-certbot-nginx"
echo "      sudo certbot --nginx -d www.docaro.de -d docaro.de"
echo ""
echo "  5️⃣  Docker-Services starten (optional):"
echo "      cd /opt/Docaro/docker && docker compose up -d"
echo ""
echo "  6️⃣  Verifikation (siehe MIGRATION_RUNBOOK.md Phase 4):"
echo "      - Web-UI: Login + Dokumentenliste korrekt?"
echo "      - Test-Upload/Processing funktioniert?"
echo ""
echo "════════════════════════════════════════════════════════════"
