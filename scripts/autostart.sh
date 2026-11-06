#!/bin/sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP="$ROOT/menubar/ClaudeSwitchBar.app"
LABEL="local.claudeswitch.bar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_VALUE=$(id -u)

case "${1:-status}" in
    install)
        "$ROOT/scripts/build-menubar.sh"
        mkdir -p "$HOME/Library/LaunchAgents"
        cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>$APP/Contents/MacOS/ClaudeSwitchBar</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<dict>
		<key>SuccessfulExit</key>
		<false/>
	</dict>
	<key>LimitLoadToSessionType</key>
	<string>Aqua</string>
	<key>ProcessType</key>
	<string>Interactive</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>HOME</key>
		<string>$HOME</string>
		<key>PATH</key>
		<string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
	</dict>
	<key>StandardOutPath</key>
	<string>$HOME/.claude-switch/logs/menubar.log</string>
	<key>StandardErrorPath</key>
	<string>$HOME/.claude-switch/logs/menubar.error.log</string>
</dict>
</plist>
EOF
        mkdir -p "$HOME/.claude-switch/logs"
        launchctl bootout "gui/$UID_VALUE/$LABEL" >/dev/null 2>&1 || true
        launchctl bootstrap "gui/$UID_VALUE" "$PLIST"
        echo "installed $LABEL"
        ;;
    uninstall)
        launchctl bootout "gui/$UID_VALUE/$LABEL" >/dev/null 2>&1 || true
        rm -f "$PLIST"
        echo "removed $LABEL"
        ;;
    status)
        launchctl print "gui/$UID_VALUE/$LABEL" 2>/dev/null | head -20 || echo "not installed"
        ;;
    *)
        echo "usage: $0 install|uninstall|status" >&2
        exit 2
        ;;
esac
