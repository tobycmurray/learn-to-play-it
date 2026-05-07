#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

BUILD_VENV=".build-venv"

if [[ "${1:-}" == "--clean" ]]; then
    echo "Cleaning previous build artifacts..."
    rm -rf "$BUILD_VENV" build dist
fi

python3 -m venv "$BUILD_VENV"
source "$BUILD_VENV/bin/activate"
python -m pip install --upgrade pip "setuptools<82" wheel
python -m pip install -r requirements-gui.lock
python -m pip install -e '.[gui]' --no-deps
python -m pip install pyinstaller

# Create AppIcon.icns from the checked-in PNG, if needed.
./packaging/macos/make_icns.sh

python -m PyInstaller --clean --noconfirm packaging/macos/learn-to-play-it.spec

# Set CFBundle*Version (from pyproject.toml) and LSMinimumSystemVersion (from
# the highest minos across all bundled Mach-O binaries). Must run before signing.
python packaging/macos/patch_info_plist.py

# Fail the build if any @rpath/ reference inside the bundle resolves to a
# missing file — that would crash the app on every user's machine.
python packaging/macos/verify_bundle.py

printf '\nBuilt: dist/Learn To Play It.app\n'
