#!/bin/bash
# SSL/HTTPS für www.docaro.de einrichten
# Dieses Skript installiert Let's Encrypt Certbot und richtet HTTPS ein

set -euo pipefail

echo "════════════════════════════════════════════════════════════"
echo "🔒 SSL/HTTPS Setup für www.docaro.de"
echo "════════════════════════════════════════════════════════════"
echo ""

# 1. Certbot installieren
echo "📦 Installiere Certbot..."
apt-get update -qq
apt-get install -y certbot python3-certbot-nginx

# 2. Sicherstellen, dass Nginx läuft und Port 80 erreichbar ist
echo ""
echo "🔍 Prüfe Nginx-Status..."
if ! systemctl is-active --quiet nginx; then
    echo "⚠️  Nginx läuft nicht, starte..."
    systemctl start nginx
fi

if ! systemctl is-enabled --quiet nginx; then
    systemctl enable nginx
fi

# 3. Prüfe, ob docaro-Config aktiviert ist
if [ ! -L /etc/nginx/sites-enabled/docaro ]; then
    echo "⚠️  Docaro Nginx-Config nicht aktiviert, aktiviere..."
    ln -sf /etc/nginx/sites-available/docaro /etc/nginx/sites-enabled/docaro
    nginx -t && systemctl reload nginx
fi

# 4. Bestätigung
echo ""
echo "⚠️  WICHTIG:"
echo "   - DNS muss auf diesen Server zeigen:"
echo "     www.docaro.de → $(hostname -I | awk '{print $1}')"
echo "     docaro.de → $(hostname -I | awk '{print $1}')"
echo ""
echo "   - Port 80 muss von außen erreichbar sein (Firewall!)"
echo ""

read -p "✅ DNS zeigt auf diesen Server & Port 80 ist offen? [y/N]: " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
  echo "❌ Abbruch: Erst DNS + Firewall konfigurieren!"
  echo ""
  echo "DNS prüfen:"
  echo "  dig www.docaro.de +short"
  echo "  dig docaro.de +short"
  echo ""
  echo "Port 80 Test:"
  echo "  curl -I http://www.docaro.de"
  exit 1
fi

# 5. Zertifikat beantragen
echo ""
echo "🔐 Beantrage Let's Encrypt Zertifikat..."
echo "   (automatischer HTTPS-Redirect wird konfiguriert)"
echo ""

certbot --nginx \
  -d www.docaro.de \
  -d docaro.de \
  --non-interactive \
  --agree-tos \
  --redirect \
  --email admin@docaro.de

# 6. Auto-Renewal prüfen
echo ""
echo "🔄 Prüfe Auto-Renewal..."
systemctl status certbot.timer --no-pager

# 7. Test
echo ""
echo "✅ SSL eingerichtet!"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "🎉 HTTPS ist aktiv!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  🌐 https://www.docaro.de"
echo "  🌐 https://docaro.de"
echo ""
echo "Zertifikat:"
echo "  Pfad: /etc/letsencrypt/live/www.docaro.de/"
echo "  Gültig: 90 Tage (automatische Erneuerung via certbot.timer)"
echo ""
echo "Renewal testen:"
echo "  sudo certbot renew --dry-run"
echo ""
echo "════════════════════════════════════════════════════════════"
