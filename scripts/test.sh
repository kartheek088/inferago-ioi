#!/usr/bin/env bash
# Full verification: backend tests (incl. migrations), frontend type check and production build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "== backend tests" && (cd "$ROOT/backend" && uv run pytest -q -p no:warnings)
TMPDB="sqlite:///$(mktemp -d)/check.db"
echo "== alembic upgrade + drift check" && (cd "$ROOT/backend" && IOI_DATABASE_URL="$TMPDB" uv run alembic upgrade head >/dev/null 2>&1 && IOI_DATABASE_URL="$TMPDB" uv run alembic check)
echo "== frontend typecheck" && (cd "$ROOT/frontend" && npm run typecheck)
echo "== frontend build" && (cd "$ROOT/frontend" && npm run build)
echo "ALL CHECKS PASSED"
