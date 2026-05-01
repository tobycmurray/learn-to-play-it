#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

src="packaging/macos/learntoplayit/resources/app_icon.png"
out="packaging/macos/AppIcon.icns"
iconset="packaging/macos/AppIcon.iconset"

rm -rf "$iconset"
mkdir -p "$iconset"

sips -z 16 16     "$src" --out "$iconset/icon_16x16.png" >/dev/null
sips -z 32 32     "$src" --out "$iconset/icon_16x16@2x.png" >/dev/null
sips -z 32 32     "$src" --out "$iconset/icon_32x32.png" >/dev/null
sips -z 64 64     "$src" --out "$iconset/icon_32x32@2x.png" >/dev/null
sips -z 128 128   "$src" --out "$iconset/icon_128x128.png" >/dev/null
sips -z 256 256   "$src" --out "$iconset/icon_128x128@2x.png" >/dev/null
sips -z 256 256   "$src" --out "$iconset/icon_256x256.png" >/dev/null
sips -z 512 512   "$src" --out "$iconset/icon_256x256@2x.png" >/dev/null
sips -z 512 512   "$src" --out "$iconset/icon_512x512.png" >/dev/null
cp "$src" "$iconset/icon_512x512@2x.png"

iconutil -c icns "$iconset" -o "$out"
rm -rf "$iconset"

echo "Wrote $out"
