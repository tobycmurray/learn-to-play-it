#!/usr/bin/env bash
set -euo pipefail

# Full release pipeline: build the .app, sign+notarize+staple it, then build the
# .dmg and sign+notarize+staple that too.
#
# Usage:
#   release.sh           # incremental rebuild
#   release.sh --clean   # wipe build artifacts first

cd "$(dirname "$0")/../.."

CLEAN=""
if [[ "${1:-}" == "--clean" ]]; then
    CLEAN="--clean"
fi

echo "============================================================"
echo "Building app bundle"
echo "============================================================"
packaging/macos/build_app.sh $CLEAN

echo
echo "============================================================"
echo "Signing and notarizing app"
echo "============================================================"
packaging/macos/sign_and_notarize.sh

echo
echo "============================================================"
echo "Building, notarizing, and stapling DMG"
echo "============================================================"
packaging/macos/make_dmg.sh

echo
echo "============================================================"
echo "Release artifacts ready:"
echo "  dist/Learn To Play It.app"
echo "  dist/Learn-To-Play-It.dmg"
echo "============================================================"
