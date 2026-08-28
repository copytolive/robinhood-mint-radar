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
INSTALL_SERVICES_STOPPED=0
INSTALL_COMPLETE=0
PYTHON_BIN=""

restore_background_services() {
  [ "${RADAR_INSTALL_DRY_RUN:-0}" = "1" ] && return 0
  [ -n "${PYTHON_BIN:-}" ] || return 0
  if [ -f "$INSTALL_DIR/macos/install-launchagent.sh" ]; then PYTHON_BIN="$PYTHON_BIN" sh "$INSTALL_DIR/macos/install-launchagent.sh" >/dev/null 2>&1 || true; fi
  if [ -f "$INSTALL_DIR/macos/install-dashboard-launchagent.sh" ]; then PYTHON_BIN="$PYTHON_BIN" sh "$INSTALL_DIR/macos/install-dashboard-launchagent.sh" >/dev/null 2>&1 || true; fi
}

cleanup() {
  RC=$?
  rm -rf "$TMP_DIR" >/dev/null 2>&1 || true
  if [ "${INSTALL_SERVICES_STOPPED:-0}" = "1" ] && [ "${INSTALL_COMPLETE:-0}" != "1" ]; then
    echo "Restoring background services after interrupted/failed install..." >&2
    restore_background_services
  fi
  exit "$RC"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

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

curl_download() {
  URL="$1"; OUT="$2"
  if curl --proto '=https' --tlsv1.2 -fL --retry 4 --retry-delay 2 --connect-timeout 20 "$URL" -o "$OUT"; then return 0; fi
  echo "Retrying download with macOS default TLS trust..."
  env -u SSL_CERT_FILE curl --proto '=https' --tlsv1.2 -fL --retry 4 --retry-delay 2 --connect-timeout 20 "$URL" -o "$OUT"
}

[ "$(uname -s)" = "Darwin" ] || fail "macOS is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v unzip >/dev/null 2>&1 || fail "unzip is required"

echo "=== $APP_NAME ==="
echo "Installing read-only scanner. Wallet execution remains manual."

curl_download "$ZIP_URL" "$TMP_DIR/radar.zip" || fail "could not download application"
unzip -q "$TMP_DIR/radar.zip" -d "$TMP_DIR" || fail "could not unpack application"
SRC_DIR="$TMP_DIR/robinhood-mint-radar-main"
[ -d "$SRC_DIR/radar" ] || fail "downloaded package is incomplete"

mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/data" "$INSTALL_DIR/logs" "$INSTALL_DIR/public"
if [ -f "$INSTALL_DIR/.env" ]; then cp "$INSTALL_DIR/.env" "$TMP_DIR/existing.env"; fi
cp -R "$SRC_DIR/." "$INSTALL_DIR/"
if [ -f "$TMP_DIR/existing.env" ]; then
  cp "$TMP_DIR/existing.env" "$INSTALL_DIR/.env"
elif [ ! -f "$INSTALL_DIR/.env" ]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
fi
chmod +x "$INSTALL_DIR"/*.sh "$INSTALL_DIR"/*.command "$INSTALL_DIR"/macos/*.sh 2>/dev/null || true

valid_python() { [ -n "${1:-}" ] && "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1; }

install_managed_python() {
  echo "Installing private Python runtime..."
  mkdir -p "$RUNTIME_DIR/uv" "$RUNTIME_DIR/python"
  curl_download "$UV_INSTALLER" "$TMP_DIR/uv-install.sh" || fail "could not download Python runtime installer"
  env UV_UNMANAGED_INSTALL="$RUNTIME_DIR/uv" UV_NO_MODIFY_PATH=1 sh "$TMP_DIR/uv-install.sh" >/dev/null || fail "could not install runtime manager"
  UV_BIN="$RUNTIME_DIR/uv/uv"
  [ -x "$UV_BIN" ] || fail "runtime manager was not installed"
  env UV_PYTHON_INSTALL_DIR="$RUNTIME_DIR/python" "$UV_BIN" python install 3.12 >/dev/null || fail "could not install Python 3.12"
  PYTHON_BIN=$(env UV_PYTHON_INSTALL_DIR="$RUNTIME_DIR/python" "$UV_BIN" python find 3.12 2>/dev/null || true)
}

tls_probe() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import os, socket, ssl
host='rpc.mainnet.chain.robinhood.com'; cafile=os.environ.get('SSL_CERT_FILE')
ctx=ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
with socket.create_connection((host,443),timeout=10) as raw:
    with ctx.wrap_socket(raw,server_hostname=host) as tls:
        if not tls.getpeercert(): raise RuntimeError('no peer certificate')
PY
}

validate_status_file() {
  "$PYTHON_BIN" - "$1" <<'PY' >/dev/null 2>&1
import json,sys,time
s=json.load(open(sys.argv[1])); scan=s.get('scan',{})
assert s.get('mode')=='READ_ONLY'
assert s.get('wallet_execution')=='MANUAL_ONLY'
assert s.get('live_ready')=='READY'
assert s.get('chain',{}).get('chain_id')==4663
assert time.time()-float(s.get('generated_at',0)) < 180
assert int(scan.get('lag_blocks',10**9)) <= 2000
assert int(scan.get('lag_seconds',10**9)) <= 60
assert float(scan.get('analysis_age_seconds',10**9)) <= 60
PY
}

status_progress() {
  "$PYTHON_BIN" - "public/status.json" <<'PY' 2>/dev/null || true
import json,sys
try:s=json.load(open(sys.argv[1]))
except Exception:raise SystemExit(0)
sc=s.get('scan') or {}
print('[PROGRESS] service status:',s.get('live_ready'),'lag=',sc.get('lag_seconds'),'s /',sc.get('lag_blocks'),'blocks','analysis=',sc.get('analysis_age_seconds'),'s')
PY
}

launchagent_running() { launchctl print "$1" 2>/dev/null | grep -q 'state = running'; }

stop_existing_launchagents() {
  DOMAIN="gui/$(id -u)"
  for LABEL in com.copytolive.robinhood-mint-radar-dashboard com.copytolive.robinhood-mint-radar; do
    PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
    if [ -f "$PLIST" ]; then
      launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    else
      launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    fi
  done
}

PYTHON_BIN=$(command -v python3 || true)
if [ "${RADAR_FORCE_MANAGED_PYTHON:-0}" = "1" ]; then PYTHON_BIN=""; fi
if ! valid_python "$PYTHON_BIN"; then install_managed_python; fi
valid_python "$PYTHON_BIN" || fail "Python 3.10+ is unavailable"
echo "Runtime: $($PYTHON_BIN --version 2>&1)"

if [ "${RADAR_TEST_BROKEN_PYTHON_CA:-0}" = "1" ]; then SSL_CERT_FILE="/tmp/definitely-missing-robinhood-python-ca.pem"; export SSL_CERT_FILE; fi
if ! tls_probe; then
  echo "Repairing Python TLS trust store..."
  FOUND_CA=""
  for CA in /etc/ssl/cert.pem /private/etc/ssl/cert.pem /opt/homebrew/etc/ca-certificates/cert.pem /usr/local/etc/ca-certificates/cert.pem /opt/homebrew/etc/openssl@3/cert.pem /usr/local/etc/openssl@3/cert.pem; do
    if [ -s "$CA" ]; then SSL_CERT_FILE="$CA"; export SSL_CERT_FILE; if tls_probe; then FOUND_CA="$CA"; break; fi; fi
  done
  if [ -z "$FOUND_CA" ]; then
    CA_BUNDLE="$INSTALL_DIR/data/macos-ca.pem"; : > "$CA_BUNDLE"
    if [ -x /usr/bin/security ]; then
      /usr/bin/security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain >> "$CA_BUNDLE" 2>/dev/null || true
      /usr/bin/security find-certificate -a -p /Library/Keychains/System.keychain >> "$CA_BUNDLE" 2>/dev/null || true
      USER_KEYCHAIN=$(/usr/bin/security default-keychain -d user 2>/dev/null | tr -d '"' || true)
      if [ -n "$USER_KEYCHAIN" ] && [ -f "$USER_KEYCHAIN" ]; then /usr/bin/security find-certificate -a -p "$USER_KEYCHAIN" >> "$CA_BUNDLE" 2>/dev/null || true; fi
    fi
    if [ -s "$CA_BUNDLE" ]; then SSL_CERT_FILE="$CA_BUNDLE"; export SSL_CERT_FILE; if tls_probe; then FOUND_CA="$CA_BUNDLE"; fi; fi
  fi
  if [ -z "$FOUND_CA" ]; then
    echo "System Python TLS is unhealthy; switching to private Python runtime..."
    install_managed_python; valid_python "$PYTHON_BIN" || fail "private Python runtime is unavailable"; unset SSL_CERT_FILE || true
    if ! tls_probe; then CA_BUNDLE="$INSTALL_DIR/data/macos-ca.pem"; if [ -s "$CA_BUNDLE" ]; then SSL_CERT_FILE="$CA_BUNDLE"; export SSL_CERT_FILE; fi; fi
    tls_probe || fail "verified TLS connection to Robinhood Chain could not be established"
  else
    echo "TLS CA: $FOUND_CA"
  fi
fi

cd "$INSTALL_DIR"
PYTHON_BIN="$PYTHON_BIN" sh macos/doctor.sh || fail "live doctor did not pass"

if [ "${RADAR_INSTALL_DRY_RUN:-0}" != "1" ]; then
  echo "Stopping previous scanner/dashboard instance..."
  stop_existing_launchagents
  INSTALL_SERVICES_STOPPED=1
fi

if [ -f ./.env ]; then set -a; . ./.env; set +a; fi
DB_PATH="${RADAR_DB:-data/radar.sqlite}"

# Preserve old data and explicitly record any unrecovered historical gap if a
# stale cursor is too far behind for an interactive installer.
"$PYTHON_BIN" - "$DB_PATH" <<'PY'
import os, sys, time
from radar import config
from radar.db import RadarDB
from radar.rpc import RPCClient
path=sys.argv[1]
if not os.path.exists(path):
    print('[PASS] live cursor: fresh database');raise SystemExit(0)
db=RadarDB(path)
try:
    last=db.last_block()
    if last is None:print('[PASS] live cursor: no prior checkpoint');raise SystemExit(0)
    rpc=RPCClient(config.DEFAULT_RPC_URL,timeout=5,retries=1)
    tip=rpc.block_number();safe=max(0,tip-config.CONFIRMATION_BLOCKS);lag=max(0,safe-last);threshold=max(5000,config.MAX_CATCHUP_BLOCKS)
    if lag<=threshold:print(f'[PASS] live cursor backlog: {lag} blocks');raise SystemExit(0)
    backup_dir=os.path.join(os.path.dirname(path) or '.','recovery-backups');backup=db.backup(backup_dir=backup_dir,keep=10)
    new_cursor=max(0,safe-config.INITIAL_LOOKBACK_BLOCKS);bh=(rpc.block(new_cursor) or {}).get('hash')
    if not bh:raise RuntimeError(f'cannot obtain recovery cursor hash for block {new_cursor}')
    gap_from=last+1;gap_to=max(gap_from-1,new_cursor-1)
    db.set_meta('recovery_backup',backup);db.set_meta('historical_gap_from',gap_from);db.set_meta('historical_gap_to',gap_to);db.set_meta('historical_gap_recorded_at',int(time.time()));db.set_meta('last_block',new_cursor);db.set_meta('last_block_hash',bh)
    print(f'[RECOVERY] stale live cursor: {lag} blocks behind');print(f'[RECOVERY] database backup: {backup}');print(f'[RECOVERY] historical gap recorded: {gap_from}-{gap_to}');print(f'[RECOVERY] live cursor rebased to: {new_cursor}')
finally:db.close()
PY

# Fast durable bootstrap only. Candidate enrichment belongs to the real
# background service and is no longer duplicated synchronously by the installer.
echo "Bootstrapping durable live checkpoint..."
"$PYTHON_BIN" - "$DB_PATH" <<'PY'
import sys
from radar import config
from radar.live_scanner import LiveRadarScanner
path=sys.argv[1];s=LiveRadarScanner(path)
try:
    tip=s.rpc.block_number();safe=max(0,tip-config.CONFIRMATION_BLOCKS);start=max(0,safe-2)
    added=s._scan_range_or_raise(start,safe);s._checkpoint(safe)
    print(f'[PASS] durable live bootstrap: {start}-{safe} / {added} observations')
finally:s.close()
PY

if [ "${RADAR_INSTALL_DRY_RUN:-0}" = "1" ]; then
  PYTHON_BIN="$PYTHON_BIN" sh -n macos/install-launchagent.sh
  PYTHON_BIN="$PYTHON_BIN" sh -n macos/install-dashboard-launchagent.sh
  echo "ONE_DOWNLOAD_DRY_RUN=PASS"
  INSTALL_COMPLETE=1
  exit 0
fi

rm -f public/status.json
PYTHON_BIN="$PYTHON_BIN" sh macos/install-launchagent.sh || fail "scanner LaunchAgent install failed"
PYTHON_BIN="$PYTHON_BIN" sh macos/install-dashboard-launchagent.sh || fail "dashboard LaunchAgent install failed"

UID_NOW=$(id -u);SCANNER_SERVICE="gui/$UID_NOW/com.copytolive.robinhood-mint-radar";DASHBOARD_SERVICE="gui/$UID_NOW/com.copytolive.robinhood-mint-radar-dashboard"
OK=0;I=0
while [ "$I" -lt 30 ]; do
  if launchagent_running "$SCANNER_SERVICE" && launchagent_running "$DASHBOARD_SERVICE"; then OK=1;break;fi
  I=$((I+1));sleep 1
done
[ "$OK" -eq 1 ] || fail "LaunchAgents were loaded but did not stay running"
echo "[PASS] scanner LaunchAgent running"
echo "[PASS] dashboard LaunchAgent running"

# Wait for the real service, not a duplicate foreground scan. Keep the user
# informed and keep services running while transient RPC errors self-recover.
echo "Waiting for background scanner READY..."
OK=0;I=0
while [ "$I" -lt 180 ]; do
  if [ -f public/status.json ] && validate_status_file public/status.json; then OK=1;break;fi
  I=$((I+1))
  if [ $((I % 15)) -eq 0 ]; then status_progress; fi
  sleep 1
done
if [ "$OK" -ne 1 ]; then
  status_progress
  fail "background scanner did not reach READY within 180s"
fi

echo "[PASS] background scanner READY"
if ! curl -fsS --max-time 3 "http://127.0.0.1:$PORT/status.json" >/dev/null 2>&1; then fail "local dashboard did not serve status";fi
echo "[PASS] local dashboard serving healthy status"

PYTHON_BIN="$PYTHON_BIN" "$PYTHON_BIN" -m radar.audit >/dev/null || fail "final readiness audit failed"
URL="http://127.0.0.1:$PORT/";open "$URL" >/dev/null 2>&1 || true
INSTALL_COMPLETE=1

echo ""
echo "========================================"
echo "INSTALLATION PASS"
echo "Scanner: LIVE / READ_ONLY"
echo "Wallet: MANUAL_ONLY"
echo "Dashboard: $URL"
echo "Installed at: $INSTALL_DIR"
echo "========================================"
