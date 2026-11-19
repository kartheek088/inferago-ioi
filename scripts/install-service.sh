#!/usr/bin/env bash
# Install IOI as a systemd *user* service (no sudo). Rebuilds the UI first.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv)"
(cd "$ROOT/frontend" && npm run build >/dev/null)
mkdir -p "$HOME/.config/systemd/user"
sed -e "s#__ROOT__#$ROOT#g" -e "s#__UV__#$UV#g" "$ROOT/scripts/ioi.service" > "$HOME/.config/systemd/user/ioi.service"
systemctl --user daemon-reload
systemctl --user enable --now ioi.service
systemctl --user restart ioi.service
echo "IOI service running: http://127.0.0.1:8000  (logs: journalctl --user -u ioi -f)"
