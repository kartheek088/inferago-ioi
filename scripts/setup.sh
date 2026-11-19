#!/usr/bin/env bash
# One-time install: backend deps (uv), database migrations, frontend deps.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/.env" ] || cp "$ROOT/.env.example" "$ROOT/.env"
(cd "$ROOT/backend" && uv sync && uv run alembic upgrade head)
(cd "$ROOT/frontend" && npm install)
echo "Setup complete. Run scripts/dev.sh"
