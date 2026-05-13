#!/usr/bin/env bash
set -euo pipefail

# Regenerate packaging/macos/ffmpeg-conda-lock.txt — the explicit conda
# lockfile pinning FFmpeg and its transitive native deps. build_app.sh
# creates the conda vendor env strictly from this lockfile (with conda
# validating SHA-256 per archive), so a tampered or republished package is
# caught at build time.
#
# When to run:
#   - You want to bump FFmpeg / a transitive dep (pass --upgrade with an
#     optional FFMPEG_CONDA_SPEC override).
#   - You want to verify the env can be recreated from the lockfile (no
#     args; should produce an unchanged lockfile).
#
# Workflow: run this, review the diff, commit, push.
#
# Usage:
#   packaging/update_ffmpeg.sh            # rebuild env from lockfile, regen
#   packaging/update_ffmpeg.sh --upgrade  # solve fresh from FFMPEG_CONDA_SPEC

cd "$(dirname "$0")/.."

FFMPEG_CONDA_ENV="${FFMPEG_CONDA_ENV:-ltp-ffmpeg}"
FFMPEG_CONDA_LOCK="${FFMPEG_CONDA_LOCK:-packaging/macos/ffmpeg-conda-lock.txt}"
FFMPEG_CONDA_SPEC="${FFMPEG_CONDA_SPEC:-ffmpeg>=8,<9}"

UPGRADE=0
if [[ "${1:-}" == "--upgrade" ]]; then
    UPGRADE=1
fi

if ! command -v conda >/dev/null 2>&1; then
    echo "conda not found. Install Miniforge/Conda first." >&2
    exit 1
fi

eval "$(conda shell.bash hook)"

if conda env list | awk '{print $1}' | grep -qx "$FFMPEG_CONDA_ENV"; then
    echo "Removing existing $FFMPEG_CONDA_ENV..."
    conda env remove -y -n "$FFMPEG_CONDA_ENV"
fi

if [[ $UPGRADE -eq 1 ]]; then
    echo "Solving fresh from conda-forge with spec: $FFMPEG_CONDA_SPEC"
    conda create -y -n "$FFMPEG_CONDA_ENV" -c conda-forge "$FFMPEG_CONDA_SPEC"
else
    echo "Recreating $FFMPEG_CONDA_ENV from $FFMPEG_CONDA_LOCK"
    conda create -y -n "$FFMPEG_CONDA_ENV" --file "$FFMPEG_CONDA_LOCK"
fi

echo "Regenerating $FFMPEG_CONDA_LOCK..."
conda list -n "$FFMPEG_CONDA_ENV" --explicit --sha256 > "$FFMPEG_CONDA_LOCK"

echo
echo "Regenerated $FFMPEG_CONDA_LOCK from $FFMPEG_CONDA_ENV."
echo "Review the diff, then commit."
