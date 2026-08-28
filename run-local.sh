#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p data public
exec python3 -m radar --db data/radar.sqlite --status public/status.json --interval "${RADAR_SCAN_INTERVAL:-15}"
