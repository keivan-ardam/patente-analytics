#!/usr/bin/env bash
#
# Update deployment on the Pi after pulling new code.
# Run from the repo root on the Pi:  bash scripts/deploy.sh
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="patente-analytics"

echo "==> Pulling latest code"
git -C "$REPO_DIR" pull --ff-only

echo "==> Updating dependencies"
"$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"

echo "==> Restarting service"
sudo systemctl restart "${SERVICE_NAME}"

echo "==> Status:"
sudo systemctl status "${SERVICE_NAME}" --no-pager -l | head -8 || true
