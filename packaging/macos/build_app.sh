#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"

# we try to target back in time macos by using an older Python (Python 3.12 is from 2023)
# we also use an older ffmpeg (ffmpeg 8) which we install using Conda
# but we don't use conda for python to avoid compatibility issues that arise otherwise

PYTHON_ORG="${PYTHON_ORG:-/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12}"
BUILD_VENV="${BUILD_VENV:-.build-venv}"

# Conda is used only as a source of low-minos FFmpeg dylibs.
# The shipped Python runtime comes from python.org, not Conda.
FFMPEG_CONDA_ENV="${FFMPEG_CONDA_ENV:-ltp-ffmpeg}"
FFMPEG_CONDA_LOCK="${FFMPEG_CONDA_LOCK:-packaging/macos/ffmpeg-conda-lock.txt}"

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
    echo "Creating FFmpeg vendor env $FFMPEG_CONDA_ENV from $FFMPEG_CONDA_LOCK"
    # conda validates the SHA-256 of each downloaded archive against the
    # hash recorded in the lockfile during install. Tampered or republished
    # bytes will fail the build loudly here.
    conda create -y -n "$FFMPEG_CONDA_ENV" --file "$FFMPEG_CONDA_LOCK"
else
    # Env exists. Fail fast if its package set diverges from the committed
    # lockfile, so we never bundle stale dylibs that don't match what's in
    # git. To refresh, run packaging/update_ffmpeg.sh.
    env_pkgs=$(conda list -n "$FFMPEG_CONDA_ENV" --explicit --sha256 | grep '^https://' | sort)
    file_pkgs=$(grep '^https://' "$FFMPEG_CONDA_LOCK" | sort)
    if [[ "$env_pkgs" != "$file_pkgs" ]]; then
        echo "ERROR: Conda env $FFMPEG_CONDA_ENV does not match $FFMPEG_CONDA_LOCK." >&2
        echo "Run packaging/update_ffmpeg.sh to refresh, or remove the env" >&2
        echo "with 'conda env remove -y -n $FFMPEG_CONDA_ENV' to let build_app.sh recreate it." >&2
        exit 1
    fi
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
    echo "Run packaging/update_ffmpeg.sh to recreate the env from $FFMPEG_CONDA_LOCK." >&2
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

python -m pip install --upgrade pip

# Hash-pinned install: pip refuses any wheel whose sha256 doesn't match the
# pin in $LOCK_FILE. setuptools is pinned inside the lockfile (uv includes it
# automatically); wheel and PEP 517 build backends are not needed in the
# environment because every dep installs from a pre-built wheel.
# To bump deps, run packaging/update_locks.sh, review the diff, and commit —
# the lockfile is a controlled artifact, not a build output.
python -m pip install --require-hashes -r "$LOCK_FILE"
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
