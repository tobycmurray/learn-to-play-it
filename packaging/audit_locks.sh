#!/usr/bin/env bash
set -euo pipefail

# Audit the committed lockfiles for known CVEs with pip-audit, honouring the
# assessed suppressions in packaging/suppressed-cves.txt.
#
# A suppression applies ONLY while the lockfiles match the SHA-256 fingerprints
# recorded in that manifest. If either lockfile has changed, ALL suppressions
# are discarded and pip-audit runs clean (fail-closed) — so a stale suppression
# can never silently hide a finding after a dependency bump. See the manifest
# header for the re-bless workflow.
#
# Called by .github/workflows/ci.yml and packaging/macos/publish_release.sh so
# the audit logic lives in exactly one place.
#
# Usage:  packaging/audit_locks.sh
# Exit:   0 if clean (after honoured suppressions); non-zero on any finding,
#         resolve/parse failure, or a suppression whose fingerprint is stale.

cd "$(dirname "$0")/.."

MANIFEST="packaging/suppressed-cves.txt"
LOCKFILES=(requirements.lock requirements-gui.lock)

if ! command -v pip-audit >/dev/null 2>&1; then
    echo "ERROR: pip-audit not installed. Install with: pip install pip-audit" >&2
    exit 1
fi

sha256() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        sha256sum "$1" | awk '{print $1}'
    fi
}

# Print the non-comment, non-empty lines within a [section] of the manifest.
section() {
    [[ -f "$MANIFEST" ]] || return 0
    awk -v sec="[$1]" '
        /^\[/     { in_sec = ($0 == sec); next }
        in_sec && NF && $1 !~ /^#/ { print }
    ' "$MANIFEST"
}

recorded_lockfiles="$(section lockfiles)"
suppress_cves="$(section suppress | awk '{print $1}')"

# --- verify lockfile fingerprints ---
mismatch=0

# Fail-closed: suppressions with no recorded fingerprints are never honoured.
if [[ -n "$suppress_cves" && -z "$recorded_lockfiles" ]]; then
    echo "ERROR: $MANIFEST lists suppressions but records no [lockfiles] fingerprints — refusing to suppress." >&2
    mismatch=1
fi

while read -r fname recorded; do
    [[ -z "$fname" ]] && continue
    if [[ ! -f "$fname" ]]; then
        echo "ERROR: $MANIFEST references a missing lockfile: $fname" >&2
        mismatch=1
        continue
    fi
    current="$(sha256 "$fname")"
    if [[ "$current" != "$recorded" ]]; then
        echo "  lockfile CHANGED since suppressions were assessed: $fname" >&2
        mismatch=1
    fi
done <<< "$recorded_lockfiles"

# --- decide which suppressions to honour ---
IGNORE_ARGS=()
if [[ -n "$suppress_cves" && "$mismatch" -eq 0 ]]; then
    echo "==> Lockfiles match recorded fingerprints; applying assessed suppressions:"
    while read -r cve; do
        [[ -z "$cve" ]] && continue
        echo "      - $cve"
        IGNORE_ARGS+=(--ignore-vuln "$cve")
    done <<< "$suppress_cves"
elif [[ "$mismatch" -ne 0 ]]; then
    {
        echo ""
        echo "==> Lockfiles changed since the suppressions were last assessed."
        echo "    Running pip-audit with NO suppressions (fail-closed)."
        echo "    Re-assess these CVEs against the current lockfiles, then update"
        echo "    $MANIFEST (paste the new hashes, or delete any that no longer apply):"
        while read -r cve; do
            [[ -z "$cve" ]] && continue
            echo "      - $cve"
        done <<< "$suppress_cves"
        echo ""
        echo "    Current hashes:"
        for f in "${LOCKFILES[@]}"; do
            [[ -f "$f" ]] && printf "      %-22s %s\n" "$f" "$(sha256 "$f")"
        done
        echo ""
    } >&2
fi

# --- run pip-audit on each lockfile ---
status=0
for f in "${LOCKFILES[@]}"; do
    echo "==> pip-audit -r $f"
    if ! pip-audit -r "$f" ${IGNORE_ARGS[@]+"${IGNORE_ARGS[@]}"}; then
        status=1
    fi
done

if [[ "$status" -ne 0 ]]; then
    echo "ERROR: lockfile audit failed (see output above)." >&2
fi
exit "$status"
