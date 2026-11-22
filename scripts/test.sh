#!/usr/bin/env bash
# Full verification: backend tests (incl. migrations), drift check, frontend type check, unit tests, build,
# and the browser end-to-end acceptance test (only if Google Chrome is installed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "== backend tests" && (cd "$ROOT/backend" && uv run pytest -q -p no:warnings)
TMPDB="sqlite:///$(mktemp -d)/check.db"
echo "== alembic upgrade + drift check" && (cd "$ROOT/backend" && IOI_DATABASE_URL="$TMPDB" uv run alembic upgrade head >/dev/null 2>&1 && IOI_DATABASE_URL="$TMPDB" uv run alembic check)
echo "== frontend typecheck" && (cd "$ROOT/frontend" && npm run typecheck)
echo "== frontend unit tests" && (cd "$ROOT/frontend" && npx vitest run --reporter=dot)
echo "== frontend build" && (cd "$ROOT/frontend" && npm run build)
if command -v google-chrome >/dev/null || command -v google-chrome-stable >/dev/null; then
  echo "== end-to-end (separate test server + throwaway database)" && (cd "$ROOT/frontend" && npx playwright test)
else
  echo "== end-to-end skipped (Google Chrome not installed)"
fi
echo "ALL CHECKS PASSED"
