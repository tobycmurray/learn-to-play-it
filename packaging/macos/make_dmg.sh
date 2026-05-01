#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

if ! command -v create-dmg >/dev/null 2>&1; then
  echo "Install create-dmg first: brew install create-dmg" >&2
  exit 1
fi

rm -f "dist/Learn-To-Play-It.dmg"
create-dmg \
  --volname "Learn To Play It" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 96 \
  --app-drop-link 450 185 \
  "dist/Learn-To-Play-It.dmg" \
  "dist/Learn To Play It.app"
