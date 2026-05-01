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

printf '\nBuilt: dist/Learn To Play It.app\n'
