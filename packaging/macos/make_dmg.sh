#!/usr/bin/env bash
set -euo pipefail

# Build dist/Learn-To-Play-It.dmg from the (already signed+notarized+stapled) .app,
# then notarize and staple the dmg itself.
#
# Pass --skip-notarize to only build the dmg (useful for iterating on layout).

cd "$(dirname "$0")/../.."

SKIP_NOTARIZE=0
if [[ "${1:-}" == "--skip-notarize" ]]; then
    SKIP_NOTARIZE=1
fi

NOTARY_PROFILE="${NOTARY_PROFILE:-ltpi-notary}"
DMG="dist/Learn-To-Play-It.dmg"
APP="dist/Learn To Play It.app"
BG="packaging/macos/dmg-background.png"

if ! command -v create-dmg >/dev/null 2>&1; then
  echo "Install create-dmg first: brew install create-dmg" >&2
  exit 1
fi

if [[ ! -d "$APP" ]]; then
    echo "App bundle not found: $APP" >&2
    echo "Run packaging/macos/build_app.sh and packaging/macos/sign_and_notarize.sh first." >&2
    exit 1
fi

rm -f "$DMG"

ARGS=(
  --volname "Learn To Play It"
  --window-pos 200 120
  --window-size 600 400
  --icon-size 96
  --icon "Learn To Play It.app" 150 185
  --hide-extension "Learn To Play It.app"
  --app-drop-link 450 185
)

if [[ -f "$BG" ]]; then
  ARGS+=(--background "$BG")
else
  echo "Note: no background image at $BG (DMG will have plain background)." >&2
  echo "      For the drag-to-Applications visual hint, create a 600x400 PNG there." >&2
fi

echo "==> Building $DMG"
create-dmg "${ARGS[@]}" "$DMG" "$APP"

if [[ "$SKIP_NOTARIZE" -eq 1 ]]; then
    echo
    echo "Skipped notarization (--skip-notarize)."
    echo "DMG ready for local testing: $DMG"
    exit 0
fi

echo "==> Submitting DMG to Apple notary service"
xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait

echo "==> Stapling notarization ticket"
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"

echo
echo "Done. Distribute: $DMG"
