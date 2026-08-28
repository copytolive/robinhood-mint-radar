#!/bin/sh
set -eu
cd "$(dirname "$0")";echo 'Robinhood Mint Radar — Mac install';sh macos/doctor.sh
if [ "${RADAR_INSTALL_DRY_RUN:-0}" = "1" ];then sh -n macos/install-launchagent.sh;sh -n macos/install-dashboard-launchagent.sh;sh -n macos/uninstall-stack.sh;echo 'MAC_INSTALL_DRY_RUN=PASS';exit 0;fi
sh macos/install-launchagent.sh;sh macos/install-dashboard-launchagent.sh;sleep 2;python3 -m radar.audit || true;URL="http://127.0.0.1:${RADAR_DASHBOARD_PORT:-4173}/";command -v open >/dev/null 2>&1 && open "$URL" || true;echo "READY: $URL"
