#!/usr/bin/env bash
# Publish IOI on a public HTTPS address through a Cloudflare Tunnel. No sudo and no open ports are
# needed: cloudflared makes an outbound connection, and the app keeps listening on this laptop.
#
#   scripts/public-tunnel.sh            install cloudflared (checksum-verified), start the tunnel service, print the link
#   scripts/public-tunnel.sh link       print the current link + QR again
#   scripts/public-tunnel.sh stop       stop and disable the tunnel
#
# Quick-tunnel mode (default, no Cloudflare account): the address is https://<random>.trycloudflare.com
# and CHANGES whenever the tunnel restarts (reboot, network change). Re-run `link` to get the new one.
# For a permanent address, see docs/DEPLOY.md → "Public link (Cloudflare Tunnel)".
#
# Security: requests through the tunnel are proxied, so IOI_API_TOKEN is ALWAYS required (the server
# refuses proxied requests without it). The token goes in the URL #fragment, which is never sent over
# the network to Cloudflare or the server. Treat the link like a password.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HOME/.local/bin/cloudflared"
VERSION="2026.10.0"
UNIT="$HOME/.config/systemd/user/ioi-tunnel.service"
PORT="$(grep -E '^IOI_PORT=' "$ROOT/.env" 2>/dev/null | cut -d= -f2- || true)"; PORT="${PORT:-8000}"
TOKEN="$(grep -E '^IOI_API_TOKEN=' "$ROOT/.env" | cut -d= -f2- || true)"

link() {
  local url=""
  for _ in $(seq 1 30); do
    url="$(journalctl --user -u ioi-tunnel --since "-15min" --no-pager -o cat 2>/dev/null | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)"
    [ -n "$url" ] && break
    sleep 1
  done
  [ -n "$url" ] || { echo "Tunnel address not found yet. Check: journalctl --user -u ioi-tunnel -n 50"; exit 1; }
  echo "Public address: $url"
  echo "Open this once on each device (keep it private — it grants access):"
  echo "$url/#token=$TOKEN"
  echo
  cd "$ROOT/backend" && uv run --quiet --with segno python -c "import segno,sys; segno.make(sys.argv[1], error='m').terminal(compact=True)" "$url/#token=$TOKEN" || true
}

case "${1:-start}" in
  link) link; exit 0 ;;
  stop) systemctl --user disable --now ioi-tunnel.service || true; echo "Tunnel stopped."; exit 0 ;;
  start) ;;
  *) echo "usage: $0 [start|link|stop]"; exit 2 ;;
esac

[ -n "$TOKEN" ] || { echo "IOI_API_TOKEN missing in .env — refusing to publish without a token."; exit 1; }
systemctl --user is-active --quiet ioi || { echo "IOI service not running. Run scripts/install-service.sh first."; exit 1; }

if [ ! -x "$BIN" ] || ! "$BIN" --version 2>/dev/null | grep -q "$VERSION"; then
  ARCH="$(uname -m)"; case "$ARCH" in x86_64) A=amd64 ;; aarch64|arm64) A=arm64 ;; *) echo "Unsupported arch $ARCH"; exit 1 ;; esac
  TMP="$(mktemp -d)"
  echo "Downloading cloudflared $VERSION ($A) from the official GitHub release…"
  curl -fsSL -o "$TMP/cloudflared" "https://github.com/cloudflare/cloudflared/releases/download/$VERSION/cloudflared-linux-$A"
  # The release notes publish SHA256 sums; verify against them.
  curl -fsSL "https://api.github.com/repos/cloudflare/cloudflared/releases/tags/$VERSION" -o "$TMP/release.json"
  WANT="$(python3 -c "import json,re,sys; b=json.load(open(sys.argv[1]))['body']; m=re.search(r'cloudflared-linux-$A:\s*([0-9a-f]{64})', b); print(m.group(1) if m else '')" "$TMP/release.json")"
  GOT="$(sha256sum "$TMP/cloudflared" | cut -d' ' -f1)"
  if [ -z "$WANT" ] || [ "$WANT" != "$GOT" ]; then
    echo "Checksum verification FAILED (expected '${WANT:-not published}', got $GOT). Not installing."; rm -rf "$TMP"; exit 1
  fi
  mkdir -p "$(dirname "$BIN")"; install -m 755 "$TMP/cloudflared" "$BIN"; rm -rf "$TMP"
  echo "cloudflared installed: $("$BIN" --version)"
fi

mkdir -p "$(dirname "$UNIT")"
cat > "$UNIT" <<EOF
# Cloudflare quick tunnel → IOI on 127.0.0.1:$PORT. Installed by scripts/public-tunnel.sh
[Unit]
Description=Inferago IOI public tunnel (Cloudflare)
After=network-online.target ioi.service
Wants=ioi.service

[Service]
ExecStart=$BIN tunnel --no-autoupdate --url http://127.0.0.1:$PORT
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now ioi-tunnel.service
systemctl --user restart ioi-tunnel.service
# Keep user services running after logout / without an open session (may ask for your password).
loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes || loginctl enable-linger "$USER" 2>/dev/null || \
  echo "Note: run 'sudo loginctl enable-linger $USER' so IOI keeps running when you are logged out."
link
