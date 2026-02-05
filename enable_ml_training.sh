#!/bin/bash
# ML Auto-Training aktivieren

set -e

echo "🤖 ML Auto-Training Setup"
echo "========================================"

# 1. Environment-Variablen setzen
echo ""
echo "1. Config aktualisieren..."
cat >> /etc/docaro/docaro.env <<'EOF'

# ML Training Configuration
DOCARO_ML_ENABLED=1
DOCARO_MLFLOW_URI=http://localhost:5000
DOCARO_ML_MIN_SAMPLES=10
DOCARO_ML_RETRAIN_TIME=02:00
EOF

echo "   ✅ ML-Config hinzugefügt"

# 2. Systemd Service für Scheduler erstellen
echo ""
echo "2. Training-Scheduler Service erstellen..."
cat > /etc/systemd/system/docaro-ml-scheduler.service <<'EOF'
[Unit]
Description=Docaro ML Retrain Scheduler
After=network.target redis-server.service

[Service]
Type=simple
User=docaro
Group=docaro
WorkingDirectory=/opt/Docaro
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/etc/docaro/docaro.env
ExecStart=/opt/Docaro/.venv/bin/python -m ml.retrain_scheduler
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
EOF

echo "   ✅ Service-Datei erstellt"

# 3. Service aktivieren & starten
echo ""
echo "3. Service aktivieren..."
systemctl daemon-reload
systemctl enable docaro-ml-scheduler.service

echo ""
echo "========================================"
echo "✅ ML Auto-Training konfiguriert!"
echo ""
echo "Hinweise:"
echo "  - Scheduler läuft täglich um 02:00 Uhr"
echo "  - Benötigt mind. 10 Ground Truth Samples"
echo "  - Aktuell: $(wc -l < /opt/Docaro/data/ml/ground_truth.jsonl) Samples"
echo ""
echo "Befehle:"
echo "  Service starten:  systemctl start docaro-ml-scheduler"
echo "  Status prüfen:    systemctl status docaro-ml-scheduler"
echo "  Logs ansehen:     journalctl -u docaro-ml-scheduler -f"
echo "  Test-Training:    sudo -u docaro /opt/Docaro/.venv/bin/python /opt/Docaro/ml/retrain_scheduler.py"
echo ""
echo "⚠️  WICHTIG:"
echo "  Der Scheduler-Code ist aktuell ein Skeleton!"
echo "  Training-Logik muss noch implementiert werden (siehe TODO in retrain_scheduler.py)"
echo ""
