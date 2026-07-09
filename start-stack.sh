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

# Stable public URL for Telegram Web App.
export TELEGRAM_WEB_APP_URL="${TELEGRAM_WEB_APP_URL:-https://promptform-dave.loca.lt}"
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

# Start the tunnel using Cloudflare Tunnel (no account required).
# The `trycloudflare.com` URL is HTTPS and suitable for Telegram Web Apps.
"$HOME/.local/bin/cloudflared" tunnel --url "http://127.0.0.1:$WEBAPP_PORT" --no-autoupdate >/tmp/telegram-prompt-form-tunnel.log 2>&1 &
TUNNEL_PID=$!

# Give the tunnel a moment to come up and then print the public URL if available.
sleep 6
if grep -Eq 'https://[^ ]+\.trycloudflare\.com' /tmp/telegram-prompt-form-tunnel.log; then
  URL=$(grep -Eo 'https://[^ ]+\.trycloudflare\.com' /tmp/telegram-prompt-form-tunnel.log | tail -n 1)
  echo "Web App URL: $URL"
fi

# Start the bot with the same env.
python bot.py
