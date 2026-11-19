#!/usr/bin/env bash
# Start backend (127.0.0.1:8000) and frontend dev server (127.0.0.1:5173). Ctrl+C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend" && uv run python -m app.main &
BACK=$!
trap 'kill $BACK 2>/dev/null; wait $BACK 2>/dev/null' EXIT INT TERM
cd "$ROOT/frontend" && npm run dev
