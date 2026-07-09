#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Load local overrides if present.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN in the environment or .env}"

# Private Web App URL for Telegram. This should point at a tailnet-only HTTPS endpoint.
export TELEGRAM_WEB_APP_URL="${TELEGRAM_WEB_APP_URL:-https://brsvr.tail5967a1.ts.net}"
export WEBAPP_PORT="${WEBAPP_PORT:-8000}"

# Activate project environment.
source .venv/bin/activate

# Start the local Web App backend.
python webapp.py >/tmp/telegram-prompt-form-webapp.log 2>&1 &
WEBAPP_PID=$!

cleanup() {
  kill "$TUNNEL_PID" 2>/dev/null || true
  kill "$WEBAPP_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Expose the local Web App only to the tailnet using Tailscale Serve.
# This is private: only authenticated devices on the tailnet can reach it.
tailscale serve reset >/tmp/telegram-prompt-form-tailscale.log 2>&1 || true
tailscale serve --yes --bg --https=443 "http://127.0.0.1:$WEBAPP_PORT" >/tmp/telegram-prompt-form-tailscale.log 2>&1

# Give the local web app a moment to come up.
sleep 3

# Start the bot with the same env.
python bot.py
