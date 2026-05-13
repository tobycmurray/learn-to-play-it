#!/usr/bin/env bash
set -euo pipefail

# Regenerate requirements.lock and requirements-gui.lock from pyproject.toml.
# Lockfiles are committed artifacts and pinned by sha256, so the build pipeline
# can use --require-hashes. Run this whenever you change dependencies in
# pyproject.toml, or when you want to pick up upstream releases.
#
# Uses `uv pip compile --universal` so the lockfiles work on macOS arm64
# (where we build the .app) and Linux (where CI runs and where source users
# install). pip-tools cannot produce truly cross-platform lockfiles —
# platform-conditional deps like cuda-toolkit are absent from a macOS-resolved
# lockfile, breaking installs on Linux.
#
# Workflow: run this, review the diff, commit, push. CI checks that
# pyproject.toml and the lockfiles don't drift.
#
# Usage:
#   packaging/update_locks.sh           # respect existing pins where possible
#   packaging/update_locks.sh --upgrade # also bump existing pins to latest

cd "$(dirname "$0")/.."

UPGRADE=""
if [[ "${1:-}" == "--upgrade" ]]; then
    UPGRADE="--upgrade"
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found. Install it with: pip install uv  (or: brew install uv)" >&2
    exit 1
fi

uv pip compile $UPGRADE --universal --generate-hashes --output-file requirements.lock pyproject.toml
uv pip compile $UPGRADE --universal --generate-hashes --extra=gui --output-file requirements-gui.lock pyproject.toml

echo
echo "Regenerated requirements.lock and requirements-gui.lock."
echo "Review the diff, then commit."
