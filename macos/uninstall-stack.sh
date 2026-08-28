#!/bin/sh
set -eu
DOMAIN="gui/$(id -u)";for LABEL in com.copytolive.robinhood-mint-radar com.copytolive.robinhood-mint-radar-dashboard;do P="$HOME/Library/LaunchAgents/$LABEL.plist";launchctl bootout "$DOMAIN" "$P" >/dev/null 2>&1 || true;rm -f "$P";echo "REMOVED: $LABEL";done
