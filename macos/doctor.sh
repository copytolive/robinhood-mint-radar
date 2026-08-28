#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_DIR"

PYTHON_BIN=${PYTHON_BIN:-$(command -v python3 || true)}
if [ -z "$PYTHON_BIN" ]; then
  echo "[FAIL] python3 not found"
  exit 2
fi

echo "[PASS] python: $($PYTHON_BIN --version 2>&1)"
"$PYTHON_BIN" - <<'PY'
import sqlite3, ssl, urllib.request
print('[PASS] sqlite:', sqlite3.sqlite_version)
print('[PASS] ssl:', ssl.OPENSSL_VERSION)
PY

mkdir -p data public logs
"$PYTHON_BIN" -m compileall -q radar tests
"$PYTHON_BIN" -m unittest discover -s tests -v

TMP_DB="/tmp/robinhood-mint-radar-doctor-$$.sqlite"
TMP_STATUS="/tmp/robinhood-mint-radar-doctor-$$.json"
trap 'rm -f "$TMP_DB" "$TMP_STATUS"' EXIT INT TERM
"$PYTHON_BIN" -m radar --once --public-lookback 3 --db "$TMP_DB" --status "$TMP_STATUS" --strict
"$PYTHON_BIN" - "$TMP_STATUS" <<'PY'
import json, sys
p=sys.argv[1]
d=json.load(open(p))
assert d['mode']=='READ_ONLY'
assert d['wallet_execution']=='MANUAL_ONLY'
assert d['chain']['chain_id']==4663
assert d['live_ready']=='READY'
print('[PASS] live chain:', d['chain']['latest_block'])
print('[PASS] wallet execution:', d['wallet_execution'])
print('[PASS] qualified:', d['scan']['qualified_candidates'])
PY

if command -v plutil >/dev/null 2>&1; then
  plutil -lint macos/com.copytolive.robinhood-mint-radar.plist.example >/dev/null
  echo "[PASS] plist template syntax"
fi

echo "DOCTOR: PASS"
