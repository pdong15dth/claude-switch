#!/bin/sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BIN_DIR="${CLAUDE_SWITCH_BIN_DIR:-$HOME/.local/bin}"

mkdir -p "$BIN_DIR"
ln -sf "$ROOT/bin/claude-switch" "$BIN_DIR/claude-switch"
chmod +x "$ROOT/bin/claude-switch"

"$ROOT/scripts/build-menubar.sh"

echo ""
echo "installed: $BIN_DIR/claude-switch"
echo "menubar:   $ROOT/menubar/ClaudeSwitchBar.app"
if ! printf '%s' ":$PATH:" | grep -q ":$BIN_DIR:"; then
    echo ""
    echo "note: $BIN_DIR is not in PATH; add this to ~/.zshrc:"
    echo "  export PATH=\"$BIN_DIR:\$PATH\""
fi
