#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${1:-/opt/docaro}"

cd "$REPO_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

echo "OK: venv ready at $REPO_DIR/.venv"
