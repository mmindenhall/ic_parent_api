#!/bin/bash
# Install the weekday (Mon-Fri) 07:00 launchd job.
# Before running this: `ic-tracker auth`, `ic-tracker migrate`, and a successful `ic-tracker run`.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=com.mindenhall.ic-tracker
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|@PROJECT_DIR@|$PROJECT_DIR|g" -e "s|@HOME@|$HOME|g" \
    "$PROJECT_DIR/deploy/$LABEL.plist.template" > "$DEST"
plutil -lint "$DEST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "Installed $LABEL (weekdays 07:00). Logs: $HOME/Library/Logs/ic-tracker.log"
echo "Uninstall: launchctl bootout gui/$(id -u)/$LABEL && rm $DEST"
