#!/bin/sh
set -eu
cd "$(dirname "$0")"

# Optional read-only local configuration. Never place wallet secrets here.
if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

PYTHON_BIN=${PYTHON_BIN:-$(command -v python3 || true)}
if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: python3 not found. Install Python 3.10+ first." >&2
  exit 2
fi

mkdir -p data public logs
export PYTHONUNBUFFERED=1
exec "$PYTHON_BIN" -m radar --db "${RADAR_DB:-data/radar.sqlite}" --status "${RADAR_STATUS_PATH:-public/status.json}" --interval "${RADAR_SCAN_INTERVAL:-15}"
