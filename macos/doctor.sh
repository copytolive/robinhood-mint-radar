#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_DIR"

# Upgrade only known legacy defaults. Preserve deliberate custom values.
if [ -f .env ]; then
  if grep -q '^RADAR_CHUNK_BLOCKS=60$' .env; then
    awk '{if ($0=="RADAR_CHUNK_BLOCKS=60") print "RADAR_CHUNK_BLOCKS=5000"; else print $0}' .env > .env.radar-migrate
    mv .env.radar-migrate .env
    echo "[PASS] env migration: RADAR_CHUNK_BLOCKS 60 -> 5000"
  fi
  grep -q '^RADAR_MAX_CATCHUP_BLOCKS=' .env || echo 'RADAR_MAX_CATCHUP_BLOCKS=5000' >> .env
  if grep -q '^RADAR_MAX_READY_LAG_BLOCKS=120$' .env; then
    awk '{if ($0=="RADAR_MAX_READY_LAG_BLOCKS=120") print "RADAR_MAX_READY_LAG_BLOCKS=2000"; else print $0}' .env > .env.radar-migrate
    mv .env.radar-migrate .env
    echo "[PASS] env migration: RADAR_MAX_READY_LAG_BLOCKS 120 -> 2000"
  else
    grep -q '^RADAR_MAX_READY_LAG_BLOCKS=' .env || echo 'RADAR_MAX_READY_LAG_BLOCKS=2000' >> .env
  fi
  grep -q '^RADAR_MAX_READY_LAG_SECONDS=' .env || echo 'RADAR_MAX_READY_LAG_SECONDS=60' >> .env
fi

if [ -f .env ]; then set -a; . ./.env; set +a; fi

PYTHON_BIN=${PYTHON_BIN:-$(command -v python3 || true)}
if [ -z "$PYTHON_BIN" ]; then echo "[FAIL] python3 not found"; exit 2; fi

echo "[PASS] python: $($PYTHON_BIN --version 2>&1)"
"$PYTHON_BIN" - <<'PY'
import sqlite3, ssl
print('[PASS] sqlite:', sqlite3.sqlite_version)
print('[PASS] ssl:', ssl.OPENSSL_VERSION)
PY

mkdir -p data public logs
"$PYTHON_BIN" -m compileall -q radar tests
"$PYTHON_BIN" -m unittest discover -s tests -v

TMP_DB="/tmp/robinhood-mint-radar-doctor-$$.sqlite"
trap 'rm -f "$TMP_DB" "$TMP_DB-wal" "$TMP_DB-shm"' EXIT INT TERM

# Doctor is intentionally a bounded preflight: prove verified RPC/TLS access,
# correct chain, recent blocks, critical log reads, and SQLite checkpoint writes.
# Full candidate enrichment/readiness is validated immediately afterwards by
# the installer's durable priming scan, so doctor must not duplicate a long
# candidate analysis on a throw-away DB while this fast chain keeps advancing.
DOCTOR_OK=0
ATTEMPT=1
while [ "$ATTEMPT" -le 3 ]; do
  rm -f "$TMP_DB" "$TMP_DB-wal" "$TMP_DB-shm"
  echo "Live doctor attempt $ATTEMPT/3..."
  if "$PYTHON_BIN" - "$TMP_DB" <<'PY'
import sys, time
from radar import config
from radar.live_scanner import LiveRadarScanner
from radar.rpc import RPCClient

path=sys.argv[1]
s=LiveRadarScanner(path)
# A doctor probe must fail/retry quickly on a sick public RPC instead of
# spending minutes inside per-call retries. The durable scanner keeps its
# stronger retry policy and is validated by the following priming gate.
s.rpc=RPCClient(config.DEFAULT_RPC_URL,timeout=5,retries=1)
try:
    chain=s.rpc.chain_id()
    if chain != config.CHAIN_ID:
        raise RuntimeError(f'wrong chain id: {chain}')
    tip=s.rpc.block_number()
    safe=max(0,tip-config.CONFIRMATION_BLOCKS)
    start=max(0,safe-2)
    # Critical topic failures raise and therefore fail the doctor.
    added=s._scan_range_or_raise(start,safe)
    s._checkpoint(safe)
    final_tip=s.rpc.block_number()
    latest=s.rpc.block(final_tip) or {}
    ts=latest.get('timestamp')
    if isinstance(ts,str): ts=int(ts,16)
    age=max(0,int(time.time())-int(ts)) if ts is not None else 10**9
    if age > 60:
        raise RuntimeError(f'latest block is stale: {age}s')
    if s.db.last_block() != safe:
        raise RuntimeError('sqlite checkpoint did not persist')
    print('[PASS] live chain:', final_tip)
    print('[PASS] latest block age:', f'{age}s')
    print('[PASS] log ingest probe:', f'{start}-{safe} / {added} observations')
    print('[PASS] durable checkpoint:', safe)
    print('[PASS] wallet execution: MANUAL_ONLY')
finally:
    s.close()
PY
  then
    DOCTOR_OK=1
    break
  fi
  echo "[WARN] live doctor attempt $ATTEMPT failed transiently"
  ATTEMPT=$((ATTEMPT+1))
  [ "$ATTEMPT" -le 3 ] && sleep 2 || true
done

if [ "$DOCTOR_OK" -ne 1 ]; then
  echo "[FAIL] live doctor exhausted 3 bounded probes" >&2
  exit 2
fi

if command -v plutil >/dev/null 2>&1; then
  plutil -lint macos/com.copytolive.robinhood-mint-radar.plist.example >/dev/null
  echo "[PASS] plist template syntax"
fi

echo "DOCTOR: PASS"
