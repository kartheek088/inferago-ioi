#!/usr/bin/env bash
# One-time Tailscale setup for private access from phone + laptop. Needs sudo and a browser login.
set -euo pipefail
if ! command -v tailscale >/dev/null; then
  echo "== Installing Tailscale (official installer, needs sudo)"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
echo "== Connecting this laptop to your Tailscale account (open the printed link to log in)"
sudo tailscale up --operator="$USER"
echo "== Keep IOI available while you are logged in, even without an open terminal session"
sudo loginctl enable-linger "$USER" || true
echo "== Publishing IOI privately to your tailnet over HTTPS"
echo "   (if asked, open the link to enable HTTPS certificates for your tailnet, then re-run this script)"
tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale serve status
echo
echo "Done. Now run: scripts/device-link.sh"
