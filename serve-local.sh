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
exec "$PYTHON_BIN" - "$PORT" <<'PY'
import http.server
import socketserver
import sys

port=int(sys.argv[1])

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma','no-cache')
        self.send_header('Expires','0')
        super().end_headers()

class ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address=True

with ReuseTCPServer(('127.0.0.1',port),NoCacheHandler) as httpd:
    httpd.serve_forever()
PY
