#!/usr/bin/env bash
set -euo pipefail

# Sign, notarize, and staple dist/Learn To Play It.app.
#
# Prerequisites (one-time):
#   1. Developer ID Application cert installed in login keychain. Verify with:
#         security find-identity -v -p codesigning
#   2. Developer ID - G2 intermediate installed (so the cert chains to a root):
#         https://www.apple.com/certificateauthority/
#   3. App-specific password stored under a notarytool keychain profile:
#         xcrun notarytool store-credentials "$NOTARY_PROFILE" \
#             --apple-id "<apple-id>" --team-id "<team-id>" --password "<app-pw>"
#
# Override defaults via environment variables, e.g.:
#   IDENTITY="Developer ID Application: ..." NOTARY_PROFILE=ltpi-notary ./sign_and_notarize.sh

cd "$(dirname "$0")/../.."

IDENTITY="${IDENTITY:-Developer ID Application: Tobias Murray (385626X5BV)}"
NOTARY_PROFILE="${NOTARY_PROFILE:-ltpi-notary}"
APP="${APP:-dist/Learn To Play It.app}"
ENTITLEMENTS="${ENTITLEMENTS:-packaging/macos/entitlements.plist}"
ZIP="dist/LearnToPlayIt.zip"

if [[ ! -d "$APP" ]]; then
    echo "Bundle not found: $APP" >&2
    echo "Run packaging/macos/build_app.sh first." >&2
    exit 1
fi

CODESIGN_ARGS=(--deep --force --timestamp --options runtime --sign "$IDENTITY")
if [[ -f "$ENTITLEMENTS" ]]; then
    echo "Signing with entitlements: $ENTITLEMENTS"
    CODESIGN_ARGS+=(--entitlements "$ENTITLEMENTS")
else
    echo "Signing without entitlements (none at $ENTITLEMENTS)"
fi

echo "==> Signing $APP"
codesign "${CODESIGN_ARGS[@]}" "$APP"

echo "==> Verifying signature"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "==> Packaging for notarization: $ZIP"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"

echo "==> Submitting to Apple notary service (this can take 5-60 minutes)"
xcrun notarytool submit "$ZIP" --keychain-profile "$NOTARY_PROFILE" --wait

echo "==> Stapling notarization ticket"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

echo
echo "Done. Distribute: $APP"
echo "To also notarize a DMG, run packaging/macos/make_dmg.sh then:"
echo "  xcrun notarytool submit dist/Learn-To-Play-It.dmg --keychain-profile $NOTARY_PROFILE --wait"
echo "  xcrun stapler staple dist/Learn-To-Play-It.dmg"
