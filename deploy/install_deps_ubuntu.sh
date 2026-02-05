#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip python3-dev build-essential \
  tesseract-ocr tesseract-ocr-deu \
  poppler-utils \
  redis-server

echo "OK: base system deps installed"
