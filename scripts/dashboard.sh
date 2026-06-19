#!/usr/bin/env bash
# Start the FDK pipeline monitor and open the dashboard in the default
# browser. Idempotent: if the monitor is already running on port 7777,
# only opens the browser.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${FDK_MONITOR_PORT:-7777}"
URL="http://localhost:${PORT}"
PIDFILE="${ROOT}/.run-logs/monitor.pid"
LOGFILE="${ROOT}/.run-logs/monitor.log"
mkdir -p "${ROOT}/.run-logs"

is_running() {
  if [[ -f "$PIDFILE" ]]; then
    local pid
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  # Also check the port (in case PID file is stale but a monitor instance is alive)
  if curl -sfo /dev/null "${URL}/state.json" 2>/dev/null; then
    return 0
  fi
  return 1
}

if is_running; then
  echo "monitor already running on ${URL}"
else
  echo "starting monitor on ${URL} (logs: ${LOGFILE})"
  cd "$ROOT"
  nohup python3 scripts/monitor.py > "$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"
  # wait briefly for the server to come up
  for _ in 1 2 3 4 5; do
    if curl -sfo /dev/null "${URL}/state.json" 2>/dev/null; then break; fi
    sleep 0.5
  done
fi

# Open in default browser (macOS / Linux / Windows fallback)
if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 &
elif command -v start >/dev/null 2>&1; then
  start "$URL"
else
  echo "open ${URL} manually in your browser"
fi
