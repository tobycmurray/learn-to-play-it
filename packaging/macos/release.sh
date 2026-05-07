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

VERSION=$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')

echo
echo "============================================================"
echo "Release artifacts ready (version $VERSION):"
echo "  dist/Learn To Play It.app"
echo "  dist/Learn-To-Play-It-${VERSION}.dmg"
echo
echo "Next: packaging/macos/publish_release.sh   (tag + GitHub release)"
echo "============================================================"
