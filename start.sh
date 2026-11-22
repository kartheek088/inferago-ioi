#!/usr/bin/env bash
# Start Inferago IOI: checks requirements, installs what's missing, applies database migrations,
# builds the web app if needed, and starts IOI in the background. Open the printed address in a browser.
# Stop it with ./stop.sh. Logs: backend/data/ioi.log
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DATA="$ROOT/backend/data"
PIDFILE="$DATA/ioi.pid"
LOG="$DATA/ioi.log"
mkdir -p "$DATA"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mProblem:\033[0m %s\n' "$*" >&2; exit 1; }

# --- settings file -------------------------------------------------------------------------------
if [ ! -f "$ROOT/.env" ]; then cp "$ROOT/.env.example" "$ROOT/.env"; say "Created .env from .env.example"; fi
envval() { grep -E "^$1=" "$ROOT/.env" | tail -1 | cut -d= -f2- | tr -d '"' || true; }
PORT="$(envval IOI_PORT)"; PORT="${PORT:-8000}"
HOST="$(envval IOI_HOST)"; HOST="${HOST:-127.0.0.1}"
URL="http://127.0.0.1:$PORT"

# --- already running? ----------------------------------------------------------------------------
if curl -sf "$URL/api/v3/status" >/dev/null 2>&1 || curl -s -o /dev/null -w '%{http_code}' "$URL/api/v3/status" 2>/dev/null | grep -q 401; then
  say "IOI is already running: $URL"
  if command -v systemctl >/dev/null && systemctl --user is-active --quiet ioi 2>/dev/null; then echo "(as the background service 'ioi')"; fi
  exit 0
fi
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then fail "IOI is starting or stuck (pid $(cat "$PIDFILE")). Run ./stop.sh, then ./start.sh"; fi
if (command -v ss >/dev/null && ss -ltn | grep -qE "[:.]$PORT\b"); then fail "Port $PORT is used by another program. Change IOI_PORT in .env"; fi

# --- requirements --------------------------------------------------------------------------------
command -v python3 >/dev/null || fail "Python 3.11+ is not installed. Install it from https://www.python.org/downloads/ (or: sudo apt install python3 python3-venv)"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || fail "Python 3.11 or newer is needed (found $(python3 --version))"
command -v node >/dev/null && command -v npm >/dev/null || fail "Node.js 18+ is not installed. Install it from https://nodejs.org/"
[ "$(node -p 'process.versions.node.split(".")[0]')" -ge 18 ] || fail "Node.js 18 or newer is needed (found $(node --version))"

# --- backend dependencies ------------------------------------------------------------------------
cd "$ROOT/backend"
if command -v uv >/dev/null; then
  if [ ! -d .venv ] || [ uv.lock -nt .venv/.ioi-installed ] || [ pyproject.toml -nt .venv/.ioi-installed ]; then
    say "Installing backend packages (uv)…"; uv sync --quiet && touch .venv/.ioi-installed
  fi
  PY=(.venv/bin/python)
else
  if [ ! -x .venv/bin/python ]; then say "Creating Python environment…"; python3 -m venv .venv || fail "Could not create a virtual environment (Ubuntu: sudo apt install python3-venv)"; fi
  if [ ! -f .venv/.ioi-installed ] || [ pyproject.toml -nt .venv/.ioi-installed ]; then
    say "Installing backend packages (pip)…"
    .venv/bin/python - <<'PYEOF' > .venv/requirements.txt
import tomllib; print("\n".join(tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]))
PYEOF
    .venv/bin/pip install --quiet --upgrade pip && .venv/bin/pip install --quiet -r .venv/requirements.txt && touch .venv/.ioi-installed
  fi
  PY=(.venv/bin/python)
fi

# --- web app -------------------------------------------------------------------------------------
cd "$ROOT/frontend"
if [ ! -d node_modules ] || [ package-lock.json -nt node_modules/.package-lock.json ]; then say "Installing web app packages…"; npm ci --no-audit --no-fund --loglevel=error; fi
if [ ! -f dist/index.html ] || [ -n "$(find src index.html package.json -newer dist/index.html -print -quit 2>/dev/null)" ]; then
  say "Building the web app…"; npm run --silent build >/dev/null
fi

# --- start ---------------------------------------------------------------------------------------
cd "$ROOT/backend"
say "Starting IOI (applies database updates automatically)…"
nohup "${PY[@]}" -m app.main >>"$LOG" 2>&1 &
echo $! >"$PIDFILE"
for _ in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "$URL/api/v3/status" 2>/dev/null || true)"
  if [ "$code" = "200" ] || [ "$code" = "401" ]; then
    say "IOI is running."
    echo "  Open: $URL"
    [ "$HOST" != "127.0.0.1" ] && [ "$HOST" != "localhost" ] && echo "  (Also reachable from your network; other devices need the access token from .env)"
    echo "  Stop: ./stop.sh    Logs: $LOG"
    exit 0
  fi
  kill -0 "$(cat "$PIDFILE")" 2>/dev/null || { rm -f "$PIDFILE"; tail -n 20 "$LOG" >&2; fail "IOI stopped while starting (see the log above)."; }
  sleep 1
done
fail "IOI did not respond within 60 seconds. See $LOG"
