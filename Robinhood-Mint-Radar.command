#!/bin/sh
set -eu

APP_NAME="Robinhood Mint Radar"
INSTALL_DIR="$HOME/Library/Application Support/RobinhoodMintRadar"
RUNTIME_DIR="$HOME/Library/Application Support/RobinhoodMintRadarRuntime"
ZIP_URL="https://github.com/copytolive/robinhood-mint-radar/archive/refs/heads/main.zip"
UV_VERSION="0.11.15"
UV_INSTALLER="https://astral.sh/uv/${UV_VERSION}/install.sh"
PORT="${RADAR_DASHBOARD_PORT:-4173}"
TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/robinhood-mint-radar.XXXXXX")
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

fail() {
  echo ""
  echo "INSTALL FAILED: $*" >&2
  if [ -f "$INSTALL_DIR/logs/radar.err.log" ]; then
    echo "--- scanner log ---" >&2
    tail -n 40 "$INSTALL_DIR/logs/radar.err.log" >&2 || true
  fi
  if [ -f "$INSTALL_DIR/logs/dashboard.err.log" ]; then
    echo "--- dashboard log ---" >&2
    tail -n 20 "$INSTALL_DIR/logs/dashboard.err.log" >&2 || true
  fi
  exit 2
}

[ "$(uname -s)" = "Darwin" ] || fail "macOS is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v unzip >/dev/null 2>&1 || fail "unzip is required"

echo "=== $APP_NAME ==="
echo "Installing read-only scanner. Wallet execution remains manual."

# 1) Download/update the application without requiring git.
curl --proto '=https' --tlsv1.2 -fL --retry 4 --retry-delay 2 --connect-timeout 20 \
  "$ZIP_URL" -o "$TMP_DIR/radar.zip" || fail "could not download application"
unzip -q "$TMP_DIR/radar.zip" -d "$TMP_DIR" || fail "could not unpack application"
SRC_DIR="$TMP_DIR/robinhood-mint-radar-main"
[ -d "$SRC_DIR/radar" ] || fail "downloaded package is incomplete"

mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/data" "$INSTALL_DIR/logs" "$INSTALL_DIR/public"
if [ -f "$INSTALL_DIR/.env" ]; then
  cp "$INSTALL_DIR/.env" "$TMP_DIR/existing.env"
fi
cp -R "$SRC_DIR/." "$INSTALL_DIR/"
if [ -f "$TMP_DIR/existing.env" ]; then
  cp "$TMP_DIR/existing.env" "$INSTALL_DIR/.env"
elif [ ! -f "$INSTALL_DIR/.env" ]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
fi
chmod +x "$INSTALL_DIR"/*.sh "$INSTALL_DIR"/*.command "$INSTALL_DIR"/macos/*.sh 2>/dev/null || true

# 2) Resolve Python 3.10+. If macOS has none, install a private managed Python.
valid_python() {
  [ -n "${1:-}" ] && "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1
}
PYTHON_BIN=$(command -v python3 || true)
if [ "${RADAR_FORCE_MANAGED_PYTHON:-0}" = "1" ]; then PYTHON_BIN=""; fi
if ! valid_python "$PYTHON_BIN"; then
  echo "Installing private Python runtime..."
  mkdir -p "$RUNTIME_DIR/uv" "$RUNTIME_DIR/python"
  curl --proto '=https' --tlsv1.2 -fL --retry 4 --retry-delay 2 --connect-timeout 20 \
    "$UV_INSTALLER" -o "$TMP_DIR/uv-install.sh" || fail "could not download Python runtime installer"
  env UV_UNMANAGED_INSTALL="$RUNTIME_DIR/uv" UV_NO_MODIFY_PATH=1 sh "$TMP_DIR/uv-install.sh" >/dev/null \
    || fail "could not install runtime manager"
  UV_BIN="$RUNTIME_DIR/uv/uv"
  [ -x "$UV_BIN" ] || fail "runtime manager was not installed"
  env UV_PYTHON_INSTALL_DIR="$RUNTIME_DIR/python" "$UV_BIN" python install 3.12 >/dev/null \
    || fail "could not install Python 3.12"
  PYTHON_BIN=$(env UV_PYTHON_INSTALL_DIR="$RUNTIME_DIR/python" "$UV_BIN" python find 3.12 2>/dev/null || true)
fi
valid_python "$PYTHON_BIN" || fail "Python 3.10+ is unavailable"
echo "Runtime: $($PYTHON_BIN --version 2>&1)"

# 3) Full live doctor before background installation.
cd "$INSTALL_DIR"
PYTHON_BIN="$PYTHON_BIN" sh macos/doctor.sh || fail "live doctor did not pass"

if [ "${RADAR_INSTALL_DRY_RUN:-0}" = "1" ]; then
  PYTHON_BIN="$PYTHON_BIN" sh -n macos/install-launchagent.sh
  PYTHON_BIN="$PYTHON_BIN" sh -n macos/install-dashboard-launchagent.sh
  echo "ONE_DOWNLOAD_DRY_RUN=PASS"
  exit 0
fi

# Remove cloud snapshot so final checks prove the local scanner wrote a fresh one.
rm -f public/status.json

# 4) Install scanner + dashboard as user LaunchAgents.
PYTHON_BIN="$PYTHON_BIN" sh macos/install-launchagent.sh || fail "scanner LaunchAgent install failed"
PYTHON_BIN="$PYTHON_BIN" sh macos/install-dashboard-launchagent.sh || fail "dashboard LaunchAgent install failed"

# 5) Prove both services are running and the local status is fresh/read-only.
UID_NOW=$(id -u)
launchctl print "gui/$UID_NOW/com.copytolive.robinhood-mint-radar" >/dev/null 2>&1 || fail "scanner service is not loaded"
launchctl print "gui/$UID_NOW/com.copytolive.robinhood-mint-radar-dashboard" >/dev/null 2>&1 || fail "dashboard service is not loaded"

OK=0
I=0
while [ "$I" -lt 90 ]; do
  if [ -f public/status.json ] && curl -fsS --max-time 2 "http://127.0.0.1:$PORT/status.json" >/dev/null 2>&1; then
    if "$PYTHON_BIN" - "public/status.json" <<'PY' >/dev/null 2>&1
import json,sys,time
s=json.load(open(sys.argv[1]))
assert s.get('mode')=='READ_ONLY'
assert s.get('wallet_execution')=='MANUAL_ONLY'
assert s.get('live_ready')=='READY'
assert s.get('chain',{}).get('chain_id')==4663
assert time.time()-float(s.get('generated_at',0)) < 180
PY
    then OK=1; break; fi
  fi
  I=$((I+1))
  sleep 1
done
[ "$OK" -eq 1 ] || fail "local scanner/dashboard did not become healthy"

PYTHON_BIN="$PYTHON_BIN" "$PYTHON_BIN" -m radar.audit >/dev/null || fail "final readiness audit failed"

URL="http://127.0.0.1:$PORT/"
open "$URL" >/dev/null 2>&1 || true

echo ""
echo "========================================"
echo "INSTALLATION PASS"
echo "Scanner: LIVE / READ_ONLY"
echo "Wallet: MANUAL_ONLY"
echo "Dashboard: $URL"
echo "Installed at: $INSTALL_DIR"
echo "========================================"
