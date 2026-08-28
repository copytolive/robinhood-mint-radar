#!/bin/sh
set -eu

LABEL="com.copytolive.robinhood-mint-radar"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-$(command -v python3 || true)}

if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: python3 not found. Install Python 3.10+ first." >&2
  exit 2
fi

AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENT_DIR/$LABEL.plist"
mkdir -p "$AGENT_DIR" "$REPO_DIR/data" "$REPO_DIR/logs" "$REPO_DIR/public"

xml_escape() {
  printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g; s/'"'"'/\&apos;/g'
}
R=$(xml_escape "$REPO_DIR")
P=$(xml_escape "$PYTHON_BIN")
PATH_VALUE=$(xml_escape "$PATH")
SSL_ENV=""
if [ -n "${SSL_CERT_FILE:-}" ]; then
  SSL_VALUE=$(xml_escape "$SSL_CERT_FILE")
  SSL_ENV="    <key>SSL_CERT_FILE</key><string>$SSL_VALUE</string>"
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-s</string>
    <string>/bin/sh</string>
    <string>$R/run-local.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$R</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHON_BIN</key><string>$P</string>
    <key>PATH</key><string>$PATH_VALUE</string>
$SSL_ENV
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$R/logs/radar.out.log</string>
  <key>StandardErrorPath</key><string>$R/logs/radar.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST" >/dev/null
DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || true

echo "INSTALLED: $PLIST"
echo "SERVICE: $DOMAIN/$LABEL"
echo "POWER: prevents system sleep while on AC power"
if [ -n "${SSL_CERT_FILE:-}" ]; then echo "TLS CA: $SSL_CERT_FILE"; fi
echo "LOG: $REPO_DIR/logs/radar.out.log"
echo "STATUS: $REPO_DIR/public/status.json"
