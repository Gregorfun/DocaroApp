#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/docaro"
VENV_PIP="/opt/docaro/.venv/bin/pip"

cd "$REPO_DIR"

echo "[docaro-update] git pull"
git pull --ff-only

echo "[docaro-update] pip install -r requirements.txt"
"$VENV_PIP" install -r requirements.txt

echo "[docaro-update] restart services"
systemctl restart docaro docaro-worker

echo "[docaro-update] done"
