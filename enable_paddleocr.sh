#!/bin/bash
# PaddleOCR für Docaro aktivieren
# Schnelle Aktivierung in 3 Schritten

set -e

echo "🔧 Aktiviere PaddleOCR-Fallback für Docaro..."

# Schritt 1: Environment-Variable setzen
export DOCARO_USE_PADDLEOCR=1
export DOCARO_PADDLEOCR_FALLBACK_THRESHOLD=400

# Schritt 2: Services neustarten
echo "📍 Starte Services neu..."
sudo systemctl restart docaro docaro-worker

# Schritt 3: Warten bis ready
echo "⏳ Warte auf Service-Start..."
sleep 5

# Überprüfen
STATUS=$(curl -s http://localhost:5001/health)
if echo "$STATUS" | grep -q "ok"; then
    echo "✅ PaddleOCR aktiviert und Service läuft!"
    echo ""
    echo "📊 Einstellungen:"
    echo "  - Fallback Schwelle: 400 (anpassbar via DOCARO_PADDLEOCR_FALLBACK_THRESHOLD)"
    echo "  - Sprache: Deutsch"
    echo ""
    echo "💡 Nächste Schritte:"
    echo "  1. Upload ein Test-PDF"
    echo "  2. Logs überprüfen: tail -f /opt/Docaro/data/logs/docaro.log | grep -i paddle"
    echo "  3. Siehe PADDLEOCR_INTEGRATION.md für Konfiguration"
else
    echo "❌ Service-Start fehlgeschlagen!"
    sudo systemctl status docaro docaro-worker
    exit 1
fi
