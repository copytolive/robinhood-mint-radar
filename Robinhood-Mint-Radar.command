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

curl_download() {
  URL="$1"; OUT="$2"
  if curl --proto '=https' --tlsv1.2 -fL --retry 4 --retry-delay 2 --connect-timeout 20 "$URL" -o "$OUT"; then
    return 0
  fi
  # A broken inherited SSL_CERT_FILE can also break curl. Retry with curl's
  # normal macOS trust configuration; certificate verification stays enabled.
  echo "Retrying download with macOS default TLS trust..."
  env -u SSL_CERT_FILE curl --proto '=https' --tlsv1.2 -fL --retry 4 --retry-delay 2 --connect-timeout 20 "$URL" -o "$OUT"
}

[ "$(uname -s)" = "Darwin" ] || fail "macOS is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v unzip >/dev/null 2>&1 || fail "unzip is required"

echo "=== $APP_NAME ==="
echo "Installing read-only scanner. Wallet execution remains manual."

# 1) Download/update the application without requiring git.
curl_download "$ZIP_URL" "$TMP_DIR/radar.zip" || fail "could not download application"
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

valid_python() {
  [ -n "${1:-}" ] && "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1
}

install_managed_python() {
  echo "Installing private Python runtime..."
  mkdir -p "$RUNTIME_DIR/uv" "$RUNTIME_DIR/python"
  curl_download "$UV_INSTALLER" "$TMP_DIR/uv-install.sh" || fail "could not download Python runtime installer"
  env UV_UNMANAGED_INSTALL="$RUNTIME_DIR/uv" UV_NO_MODIFY_PATH=1 sh "$TMP_DIR/uv-install.sh" >/dev/null \
    || fail "could not install runtime manager"
  UV_BIN="$RUNTIME_DIR/uv/uv"
  [ -x "$UV_BIN" ] || fail "runtime manager was not installed"
  env UV_PYTHON_INSTALL_DIR="$RUNTIME_DIR/python" "$UV_BIN" python install 3.12 >/dev/null \
    || fail "could not install Python 3.12"
  PYTHON_BIN=$(env UV_PYTHON_INSTALL_DIR="$RUNTIME_DIR/python" "$UV_BIN" python find 3.12 2>/dev/null || true)
}

tls_probe() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import os, socket, ssl
host='rpc.mainnet.chain.robinhood.com'
cafile=os.environ.get('SSL_CERT_FILE')
ctx=ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
with socket.create_connection((host,443),timeout=10) as raw:
    with ctx.wrap_socket(raw,server_hostname=host) as tls:
        if not tls.getpeercert():
            raise RuntimeError('no peer certificate')
PY
}

validate_status_file() {
  "$PYTHON_BIN" - "$1" <<'PY' >/dev/null 2>&1
import json,sys,time
s=json.load(open(sys.argv[1]))
assert s.get('mode')=='READ_ONLY'
assert s.get('wallet_execution')=='MANUAL_ONLY'
assert s.get('live_ready')=='READY'
assert s.get('chain',{}).get('chain_id')==4663
assert time.time()-float(s.get('generated_at',0)) < 180
PY
}

launchagent_running() {
  launchctl print "$1" 2>/dev/null | grep -q 'state = running'
}

# 2) Resolve Python 3.10+.
PYTHON_BIN=$(command -v python3 || true)
if [ "${RADAR_FORCE_MANAGED_PYTHON:-0}" = "1" ]; then PYTHON_BIN=""; fi
if ! valid_python "$PYTHON_BIN"; then
  install_managed_python
fi
valid_python "$PYTHON_BIN" || fail "Python 3.10+ is unavailable"
echo "Runtime: $($PYTHON_BIN --version 2>&1)"

# Test hook used by CI to reproduce the exact class of Python trust-store fault
# reported on a real Mac. It is never enabled during a normal install.
if [ "${RADAR_TEST_BROKEN_PYTHON_CA:-0}" = "1" ]; then
  SSL_CERT_FILE="/tmp/definitely-missing-robinhood-python-ca.pem"
  export SSL_CERT_FILE
fi

# 3) Repair Python TLS trust without ever disabling certificate verification.
if ! tls_probe; then
  echo "Repairing Python TLS trust store..."
  FOUND_CA=""
  for CA in \
    /etc/ssl/cert.pem \
    /private/etc/ssl/cert.pem \
    /opt/homebrew/etc/ca-certificates/cert.pem \
    /usr/local/etc/ca-certificates/cert.pem \
    /opt/homebrew/etc/openssl@3/cert.pem \
    /usr/local/etc/openssl@3/cert.pem
  do
    if [ -s "$CA" ]; then
      SSL_CERT_FILE="$CA"; export SSL_CERT_FILE
      if tls_probe; then FOUND_CA="$CA"; break; fi
    fi
  done

  if [ -z "$FOUND_CA" ]; then
    CA_BUNDLE="$INSTALL_DIR/data/macos-ca.pem"
    : > "$CA_BUNDLE"
    if [ -x /usr/bin/security ]; then
      /usr/bin/security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain >> "$CA_BUNDLE" 2>/dev/null || true
      /usr/bin/security find-certificate -a -p /Library/Keychains/System.keychain >> "$CA_BUNDLE" 2>/dev/null || true
      USER_KEYCHAIN=$(/usr/bin/security default-keychain -d user 2>/dev/null | tr -d '"' || true)
      if [ -n "$USER_KEYCHAIN" ] && [ -f "$USER_KEYCHAIN" ]; then
        /usr/bin/security find-certificate -a -p "$USER_KEYCHAIN" >> "$CA_BUNDLE" 2>/dev/null || true
      fi
    fi
    if [ -s "$CA_BUNDLE" ]; then
      SSL_CERT_FILE="$CA_BUNDLE"; export SSL_CERT_FILE
      if tls_probe; then FOUND_CA="$CA_BUNDLE"; fi
    fi
  fi

  if [ -z "$FOUND_CA" ]; then
    echo "System Python TLS is unhealthy; switching to private Python runtime..."
    install_managed_python
    valid_python "$PYTHON_BIN" || fail "private Python runtime is unavailable"
    unset SSL_CERT_FILE || true
    if ! tls_probe; then
      CA_BUNDLE="$INSTALL_DIR/data/macos-ca.pem"
      if [ -s "$CA_BUNDLE" ]; then SSL_CERT_FILE="$CA_BUNDLE"; export SSL_CERT_FILE; fi
    fi
    tls_probe || fail "verified TLS connection to Robinhood Chain could not be established"
  else
    echo "TLS CA: $FOUND_CA"
  fi
fi

# 4) Full live doctor before background installation.
cd "$INSTALL_DIR"
PYTHON_BIN="$PYTHON_BIN" sh macos/doctor.sh || fail "live doctor did not pass"

# 5) Prime one real local scan synchronously before LaunchAgents start.
# This writes a fresh status file and advances the durable SQLite checkpoint.
# The old installer deleted status.json and then waited for a potentially slow
# first daemon bootstrap, which could falsely fail after 90 seconds.
echo "Priming local scanner checkpoint..."
rm -f public/status.json
(
  if [ -f ./.env ]; then
    set -a
    . ./.env
    set +a
  fi
  export PYTHONUNBUFFERED=1
  "$PYTHON_BIN" -m radar --once --strict --db "${RADAR_DB:-data/radar.sqlite}" --status public/status.json
) || fail "local scanner priming scan failed"
validate_status_file public/status.json || fail "primed local status is not healthy"
echo "[PASS] local checkpoint primed"

if [ "${RADAR_INSTALL_DRY_RUN:-0}" = "1" ]; then
  PYTHON_BIN="$PYTHON_BIN" sh -n macos/install-launchagent.sh
  PYTHON_BIN="$PYTHON_BIN" sh -n macos/install-dashboard-launchagent.sh
  echo "ONE_DOWNLOAD_DRY_RUN=PASS"
  exit 0
fi

# 6) Install scanner + dashboard as user LaunchAgents.
PYTHON_BIN="$PYTHON_BIN" sh macos/install-launchagent.sh || fail "scanner LaunchAgent install failed"
PYTHON_BIN="$PYTHON_BIN" sh macos/install-dashboard-launchagent.sh || fail "dashboard LaunchAgent install failed"

# 7) Prove both services are actually running, not merely registered.
UID_NOW=$(id -u)
SCANNER_SERVICE="gui/$UID_NOW/com.copytolive.robinhood-mint-radar"
DASHBOARD_SERVICE="gui/$UID_NOW/com.copytolive.robinhood-mint-radar-dashboard"

OK=0
I=0
while [ "$I" -lt 30 ]; do
  if launchagent_running "$SCANNER_SERVICE" && launchagent_running "$DASHBOARD_SERVICE"; then
    OK=1
    break
  fi
  I=$((I+1))
  sleep 1
done
[ "$OK" -eq 1 ] || fail "LaunchAgents were loaded but did not stay running"
echo "[PASS] scanner LaunchAgent running"
echo "[PASS] dashboard LaunchAgent running"

# 8) Dashboard must serve the already-proven fresh local status.
OK=0
I=0
while [ "$I" -lt 30 ]; do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/status.json" >/dev/null 2>&1 \
     && validate_status_file public/status.json; then
    OK=1
    break
  fi
  I=$((I+1))
  sleep 1
done
[ "$OK" -eq 1 ] || fail "local dashboard did not serve the healthy scanner status"

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
