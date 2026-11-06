#!/bin/sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
APP="$ROOT/menubar/ClaudeSwitchBar.app"
ICON="$ROOT/menubar/AppIcon.icns"

if [ ! -f "$ICON" ] || [ "$ROOT/menubar/make-icon.swift" -nt "$ICON" ]; then
    TMP=$(mktemp -d)
    swift "$ROOT/menubar/make-icon.swift" "$TMP"
    ICONSET="$TMP/AppIcon.iconset"
    mkdir -p "$ICONSET"
    for SIZE in 16 32 128 256 512; do
        sips -z "$SIZE" "$SIZE" "$TMP/icon_1024.png" \
            --out "$ICONSET/icon_${SIZE}x${SIZE}.png" >/dev/null
        DOUBLE=$((SIZE * 2))
        sips -z "$DOUBLE" "$DOUBLE" "$TMP/icon_1024.png" \
            --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET" -o "$ICON"
    rm -rf "$TMP"
fi

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/menubar/Info.plist" "$APP/Contents/Info.plist"
cp "$ICON" "$APP/Contents/Resources/AppIcon.icns"
swiftc -O -swift-version 5 "$ROOT/menubar/main.swift" \
    -o "$APP/Contents/MacOS/ClaudeSwitchBar" \
    -framework Cocoa
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true

echo "built $APP"
