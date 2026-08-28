#!/bin/sh
set -eu
LABEL="com.copytolive.robinhood-mint-radar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
if [ -f "$PLIST" ]; then
  launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
  rm -f "$PLIST"
fi
echo "REMOVED: $LABEL"
