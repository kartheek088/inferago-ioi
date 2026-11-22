#!/usr/bin/env bash
# Stop Inferago IOI started with ./start.sh (or the 'ioi' background service). Running discovery
# jobs stop gracefully; completed work is already saved.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$ROOT/backend/data/ioi.pid"
stopped=0
if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE")"
  if kill -0 "$PID" 2>/dev/null; then
    kill -TERM "$PID"
    for _ in $(seq 1 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
    kill -0 "$PID" 2>/dev/null && { echo "Still running; forcing stop."; kill -KILL "$PID"; }
    stopped=1
  fi
  rm -f "$PIDFILE"
fi
if command -v systemctl >/dev/null && systemctl --user is-active --quiet ioi 2>/dev/null; then
  systemctl --user stop ioi && stopped=1
  echo "Stopped the 'ioi' background service (it starts again at login unless you run: systemctl --user disable ioi)."
fi
[ "$stopped" = 1 ] && echo "IOI stopped." || echo "IOI was not running."
