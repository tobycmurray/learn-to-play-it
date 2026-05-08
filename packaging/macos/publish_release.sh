#!/usr/bin/env bash
set -euo pipefail

# Tag the current commit with the version from pyproject.toml and create a
# GitHub release with the .dmg attached. Refuses to run unless preconditions are
# met (clean tree, on main, in sync with origin, dmg artifact exists, tag is new).
#
# Usage:
#   publish_release.sh                  # interactive — prompts for confirmation
#   publish_release.sh --notes "text"   # non-interactive: skip the notes editor
#   publish_release.sh --yes            # skip the confirmation prompt

cd "$(dirname "$0")/../.."

NOTES=""
ASSUME_YES=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --notes) NOTES="$2"; shift 2 ;;
        --yes) ASSUME_YES=1; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

if ! command -v gh >/dev/null 2>&1; then
    echo "Install gh first: brew install gh && gh auth login" >&2
    exit 1
fi

VERSION=$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')
TAG="v${VERSION}"
DMG="dist/Learn-To-Play-It-${VERSION}.dmg"

echo "Version (from pyproject.toml): $VERSION"
echo "Tag:                           $TAG"
echo "DMG:                           $DMG"
echo

# --- preconditions ---

if [[ ! -f "$DMG" ]]; then
    echo "ERROR: $DMG not found. Run packaging/macos/release.sh first." >&2
    exit 1
fi

if ! git diff-index --quiet HEAD --; then
    echo "ERROR: working tree has uncommitted changes. Commit or stash first." >&2
    git status --short >&2
    exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$BRANCH" != "main" ]]; then
    echo "ERROR: current branch is '$BRANCH', expected 'main'." >&2
    exit 1
fi

git fetch --quiet origin main
LOCAL=$(git rev-parse main)
REMOTE=$(git rev-parse origin/main)
if [[ "$LOCAL" != "$REMOTE" ]]; then
    echo "ERROR: local main ($LOCAL) does not match origin/main ($REMOTE)." >&2
    echo "Pull or push first so the tag refers to a published commit." >&2
    exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "ERROR: tag $TAG already exists locally." >&2
    exit 1
fi

if git ls-remote --tags origin "refs/tags/$TAG" | grep -q "$TAG"; then
    echo "ERROR: tag $TAG already exists on origin. Did you bump the version?" >&2
    exit 1
fi

if gh release view "$TAG" >/dev/null 2>&1; then
    echo "ERROR: GitHub release $TAG already exists." >&2
    exit 1
fi

# Audit the lock files for known CVEs in bundled deps. The .app bundles its
# own Python and dependencies, so anything vulnerable in the lock files
# stays vulnerable in shipped users' installs until the next release. Refuse
# to publish if pip-audit finds anything.
echo "==> Auditing lock files for known vulnerabilities"
if ! command -v pip-audit >/dev/null 2>&1; then
    echo "ERROR: pip-audit not installed. Install with: pip install pip-audit" >&2
    exit 1
fi
if ! pip-audit -r requirements.lock; then
    echo "ERROR: vulnerabilities found in requirements.lock — fix before releasing." >&2
    exit 1
fi
if ! pip-audit -r requirements-gui.lock; then
    echo "ERROR: vulnerabilities found in requirements-gui.lock — fix before releasing." >&2
    exit 1
fi

# --- show plan and confirm ---

echo "Will:"
echo "  1. Tag commit $LOCAL as $TAG"
echo "  2. Push the tag to origin"
echo "  3. Create GitHub release $TAG with $DMG attached"
echo "  4. Update docs/index.html version label and download link to $TAG, then push"
echo

if [[ "$ASSUME_YES" -ne 1 ]]; then
    read -r -p "Proceed? [y/N] " reply
    if [[ "$reply" != "y" && "$reply" != "Y" ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# --- do it ---

echo "==> Tagging $TAG"
git tag -a "$TAG" -m "$TAG"

echo "==> Pushing tag to origin"
git push origin "$TAG"

echo "==> Creating GitHub release"
if [[ -n "$NOTES" ]]; then
    gh release create "$TAG" "$DMG" --title "$TAG" --notes "$NOTES"
else
    gh release create "$TAG" "$DMG" --title "$TAG"
fi

echo "==> Updating website (docs/index.html) to point at $TAG"
WEBSITE="docs/index.html"
APP="dist/Learn To Play It.app"
if [[ -f "$WEBSITE" ]]; then
    SED_ARGS=(
        -e "s|releases/download/v[0-9.]*/Learn-To-Play-It-[0-9.]*\.dmg|releases/download/${TAG}/Learn-To-Play-It-${VERSION}.dmg|"
        -e "s|<span id=\"version\">Version [0-9.]*</span>|<span id=\"version\">Version ${VERSION}</span>|"
    )
    # Pull the minimum macOS version straight from the bundled .app's Info.plist
    # (set by patch_info_plist.py from the highest minos across bundled binaries).
    # If the floor changes between releases, the website tracks it automatically.
    if [[ -d "$APP" ]]; then
        MIN_MACOS=$(defaults read "$(pwd)/${APP}/Contents/Info.plist" LSMinimumSystemVersion 2>/dev/null || true)
        if [[ -n "$MIN_MACOS" ]]; then
            SED_ARGS+=(-e "s|<span id=\"min-macos\">[0-9.]*</span>|<span id=\"min-macos\">${MIN_MACOS}</span>|")
        fi
    fi
    sed -i '' "${SED_ARGS[@]}" "$WEBSITE"
    if git diff --quiet "$WEBSITE"; then
        echo "    (no change — website was already at $VERSION)"
    else
        git add "$WEBSITE"
        git commit -m "bump website download link to $TAG"
        git push
    fi
else
    echo "    (no $WEBSITE found; skipping)"
fi

echo
echo "Done. Don't forget to bump pyproject.toml version for the next release cycle."
gh release view "$TAG" --json url --jq .url
