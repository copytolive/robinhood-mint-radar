#!/bin/sh
set -eu
LABEL='com.copytolive.robinhood-mint-radar-dashboard'
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-$(command -v python3 || true)}
if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: python3 not found" >&2
  exit 2
fi
AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENT_DIR/$LABEL.plist"
mkdir -p "$AGENT_DIR" "$REPO_DIR/logs" "$REPO_DIR/public"
xml_escape() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g; s/'"'"'/\&apos;/g'; }
R=$(xml_escape "$REPO_DIR")
P=$(xml_escape "$PYTHON_BIN")
PATH_VALUE=$(xml_escape "$PATH")
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array><string>/bin/sh</string><string>$R/serve-local.sh</string></array>
<key>WorkingDirectory</key><string>$R</string>
<key>EnvironmentVariables</key><dict><key>PYTHON_BIN</key><string>$P</string><key>PATH</key><string>$PATH_VALUE</string></dict>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>10</integer>
<key>StandardOutPath</key><string>$R/logs/dashboard.out.log</string>
<key>StandardErrorPath</key><string>$R/logs/dashboard.err.log</string>
</dict></plist>
EOF
plutil -lint "$PLIST" >/dev/null
DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
echo "DASHBOARD_INSTALLED: http://127.0.0.1:${RADAR_DASHBOARD_PORT:-4173}/"
