#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"

PYTHON_ORG="${PYTHON_ORG:-/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12}"
BUILD_VENV="${BUILD_VENV:-.build-venv}"

# Conda is used only as a source of low-minos FFmpeg dylibs.
# The shipped Python runtime comes from python.org, not Conda.
FFMPEG_CONDA_ENV="${FFMPEG_CONDA_ENV:-ltp-ffmpeg}"
FFMPEG_CONDA_SPEC="${FFMPEG_CONDA_SPEC:-ffmpeg>=8,<9}"

REGENERATE_LOCK="${REGENERATE_LOCK:-1}"
LOCK_FILE="${LOCK_FILE:-requirements-gui.lock}"
SPEC_FILE="${SPEC_FILE:-packaging/macos/learn-to-play-it.spec}"

if [[ "${1:-}" == "--clean" ]]; then
    echo "Cleaning previous build artifacts..."
    rm -rf "$BUILD_VENV" build dist
fi

if [[ ! -x "$PYTHON_ORG" ]]; then
    echo "ERROR: python.org Python not found at: $PYTHON_ORG" >&2
    exit 1
fi

if ! command -v conda >/dev/null 2>&1; then
    echo "ERROR: conda not found on PATH. Install Miniforge/Conda first." >&2
    exit 1
fi

# Make `conda activate`/metadata available in non-interactive shells.
eval "$(conda shell.bash hook)"

if ! conda env list | awk '{print $1}' | grep -qx "$FFMPEG_CONDA_ENV"; then
    echo "Creating FFmpeg vendor env: $FFMPEG_CONDA_ENV"
    conda create -y -n "$FFMPEG_CONDA_ENV" -c conda-forge "$FFMPEG_CONDA_SPEC"
fi

FFMPEG_CONDA_PREFIX="$(
    conda env list | awk -v env="$FFMPEG_CONDA_ENV" '$1 == env {print $NF}'
)"

if [[ -z "$FFMPEG_CONDA_PREFIX" || ! -d "$FFMPEG_CONDA_PREFIX/lib" ]]; then
    echo "ERROR: Could not find lib dir for conda env: $FFMPEG_CONDA_ENV" >&2
    exit 1
fi

export FFMPEG_LIB_DIR="$FFMPEG_CONDA_PREFIX/lib"

echo "Using app Python:      $PYTHON_ORG"
echo "Using FFmpeg lib dir:  $FFMPEG_LIB_DIR"
echo "Deployment target:     $MACOSX_DEPLOYMENT_TARGET"

# Quick sanity check: this is not a full dependency-closure check; the spec and
# verify_bundle.py handle that later.
if ! find "$FFMPEG_LIB_DIR" -maxdepth 1 \( -name 'libav*.dylib' -o -name 'libsw*.dylib' \) | grep -q .; then
    echo "ERROR: No FFmpeg libav*/libsw* dylibs found in $FFMPEG_LIB_DIR" >&2
    echo "Try: conda install -y -n $FFMPEG_CONDA_ENV -c conda-forge '$FFMPEG_CONDA_SPEC'" >&2
    exit 1
fi

echo "Sample FFmpeg dylib minos:"
find "$FFMPEG_LIB_DIR" -maxdepth 1 \( -name 'libav*.dylib' -o -name 'libsw*.dylib' \) |
    sort |
    head -20 |
    while IFS= read -r lib; do
        minos="$(
            otool -l "$lib" 2>/dev/null | awk '
                /LC_BUILD_VERSION/ { in_lc=1 }
                in_lc && /minos/ { print $2; in_lc=0 }
                /LC_VERSION_MIN_MACOSX/ { in_old=1 }
                in_old && /version/ { print $2; in_old=0 }
            ' | head -n 1
        )"
        printf "  %-32s %s\n" "$(basename "$lib")" "${minos:-unknown}"
    done

if [[ ! -d "$BUILD_VENV" ]]; then
    "$PYTHON_ORG" -m venv "$BUILD_VENV"
fi

source "$BUILD_VENV/bin/activate"

echo "Build venv Python:     $(which python)"
echo "Build venv version:    $(python --version)"
python - <<'PY'
import sys
print("Build sys.version:    ", repr(sys.version))
PY

python -m pip install --upgrade pip "setuptools<82" wheel pip-tools

if [[ "$REGENERATE_LOCK" == "1" ]]; then
    python -m piptools compile \
        --extra=gui \
        --output-file="$LOCK_FILE" \
        pyproject.toml
fi

python -m pip install -r "$LOCK_FILE"
python -m pip install -e '.[gui]' --no-deps
python -m pip install pyinstaller

# Keep Homebrew and Conda executables out of discovery during packaging.
# FFMPEG_LIB_DIR remains available for the spec file.
export PATH="$PWD/$BUILD_VENV/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset DYLD_LIBRARY_PATH
unset LIBRARY_PATH
unset CPATH
unset PKG_CONFIG_PATH

echo "PATH during PyInstaller: $PATH"
echo "FFMPEG_LIB_DIR:           ${FFMPEG_LIB_DIR:-}"

./packaging/macos/make_icns.sh

python -m PyInstaller --clean --noconfirm "$SPEC_FILE"

python packaging/macos/patch_info_plist.py
python packaging/macos/verify_bundle.py

printf '\nBuilt: dist/Learn To Play It.app\n'