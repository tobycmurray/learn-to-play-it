#!/usr/bin/env bash
set -euo pipefail

# Regenerate requirements.lock and requirements-gui.lock from pyproject.toml.
# Lockfiles are committed artifacts and pinned by sha256, so the build pipeline
# can use --require-hashes. Run this whenever you change dependencies in
# pyproject.toml, or when you want to pick up upstream releases.
#
# Workflow: run this, review the diff (it's normal to see version churn and a
# big hash refresh), commit, push. CI checks that pyproject.toml and the
# lockfiles don't drift.
#
# Usage:
#   packaging/update_locks.sh           # respect existing pins where possible
#   packaging/update_locks.sh --upgrade # also bump existing pins to latest

cd "$(dirname "$0")/.."

UPGRADE=""
if [[ "${1:-}" == "--upgrade" ]]; then
    UPGRADE="--upgrade"
fi

if ! command -v pip-compile >/dev/null 2>&1; then
    echo "pip-compile not found. Install it with: pip install pip-tools" >&2
    exit 1
fi

pip-compile $UPGRADE --generate-hashes --allow-unsafe --output-file requirements.lock pyproject.toml
pip-compile $UPGRADE --generate-hashes --allow-unsafe --extra=gui --output-file requirements-gui.lock pyproject.toml

echo
echo "Regenerated requirements.lock and requirements-gui.lock."
echo "Review the diff, then commit."
