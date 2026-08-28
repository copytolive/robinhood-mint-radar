#!/bin/sh
set -eu
cd "$(dirname "$0")"
PYTHON_BIN=${PYTHON_BIN:-$(command -v python3 || true)}
if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: python3 not found" >&2
  exit 2
fi
PORT=${RADAR_DASHBOARD_PORT:-4173}
echo "Dashboard: http://127.0.0.1:$PORT/"
cd public
exec "$PYTHON_BIN" -m http.server "$PORT" --bind 127.0.0.1
