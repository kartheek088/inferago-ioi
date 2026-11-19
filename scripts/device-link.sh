#!/usr/bin/env bash
# Print a one-time setup link (and QR code) for a phone/laptop on your tailnet.
# The token travels in the URL #fragment (never sent to the server); the app stores it and hides it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOKEN="$(grep -E '^IOI_API_TOKEN=' "$ROOT/.env" | cut -d= -f2-)"
[ -n "$TOKEN" ] || { echo "IOI_API_TOKEN missing in .env"; exit 1; }
HOST="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
URL="https://$HOST/#token=$TOKEN"
echo "Open this once on each device (keep it private — it grants access):"
echo "$URL"
echo
cd "$ROOT/backend" && uv run --quiet --with segno python -c "import segno,sys; segno.make(sys.argv[1], error='m').terminal(compact=True)" "$URL" || true
