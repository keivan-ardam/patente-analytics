#!/usr/bin/env bash
#
# First-time setup on the Raspberry Pi.
# Run from the repo root on the Pi:  bash scripts/setup_pi.sh
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="patente-analytics"

echo "==> Setting up Patente Analytics in $REPO_DIR"

# 1. Python virtual environment
if [ ! -d "$REPO_DIR/.venv" ]; then
  echo "==> Creating virtualenv"
  python3 -m venv "$REPO_DIR/.venv"
fi
echo "==> Installing dependencies"
"$REPO_DIR/.venv/bin/pip" install --upgrade pip -q
"$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"

# 2. .env file
if [ ! -f "$REPO_DIR/.env" ]; then
  echo "==> Creating .env from template (EDIT IT with your secrets!)"
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
  echo "    A random ANALYTICS_SECRET has been generated for you:"
  SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  sed -i "s#^ANALYTICS_SECRET=.*#ANALYTICS_SECRET=${SECRET}#" "$REPO_DIR/.env"
  echo "    ANALYTICS_SECRET=${SECRET}"
  echo "    >>> Now edit $REPO_DIR/.env to add TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ALLOWED_ORIGINS"
fi

# 3. systemd service
echo "==> Installing systemd service (requires sudo)"
sudo cp "$REPO_DIR/systemd/${SERVICE_NAME}.service" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo ""
echo "==> Done. Service status:"
sudo systemctl status "${SERVICE_NAME}" --no-pager -l | head -12 || true
echo ""
echo "Useful commands:"
echo "  sudo systemctl status ${SERVICE_NAME}      # check status"
echo "  sudo journalctl -u ${SERVICE_NAME} -f      # live logs"
echo "  curl http://127.0.0.1:8000/health          # test locally"
echo ""
echo "Next: set up the Cloudflare Tunnel (see README)."
