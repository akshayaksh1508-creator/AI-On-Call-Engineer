#!/usr/bin/env bash
# ==============================================================================
# NightShift Target App Deployment Script
# Sets the running version label and emits a structured change event.
# Usage: ./deploy.sh <ref>
# Example: ./deploy.sh v1.0.1
# ==============================================================================

set -euo pipefail

TARGET_REF="${1:-}"

if [ -z "$TARGET_REF" ]; then
    echo "ERROR: Missing ref argument."
    echo "Usage: ./deploy.sh <ref>"
    echo "Example: ./deploy.sh v1.0.1"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION_FILE="$SCRIPT_DIR/version.txt"
CHANGES_DIR="$ROOT_DIR/data"
CHANGES_FILE="$CHANGES_DIR/changes.json"

# Read previous version
PREV_VERSION="1.0.0"
if [ -f "$VERSION_FILE" ]; then
    PREV_VERSION="$(cat "$VERSION_FILE" | tr -d '[:space:]')"
fi

# If inside target-app git repo, check if ref exists
if [ -d "$SCRIPT_DIR/.git" ]; then
    echo "==> Verifying ref '$TARGET_REF' in target-app git repository..."
    if git -C "$SCRIPT_DIR" rev-parse --verify "$TARGET_REF" >/dev/null 2>&1; then
        RESOLVED_COMMIT="$(git -C "$SCRIPT_DIR" rev-parse --short "$TARGET_REF")"
        echo "==> Resolved ref '$TARGET_REF' to commit $RESOLVED_COMMIT"
    else
        echo "==> Note: '$TARGET_REF' treated as a custom version label."
    fi
fi

# Update version file
echo "$TARGET_REF" > "$VERSION_FILE"

# Record change event
mkdir -p "$CHANGES_DIR"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
EVENT_ID="chg_$(date +%s)_${RANDOM}"

# Create or append to changes.json
python -c "
import json, os
changes_file = r'$CHANGES_FILE'
event = {
    'id': '$EVENT_ID',
    'type': 'deploy',
    'service': 'all',
    'from_version': '$PREV_VERSION',
    'to_version': '$TARGET_REF',
    'ref': '$TARGET_REF',
    'author': os.environ.get('USER', os.environ.get('USERNAME', 'deployer')),
    'timestamp': '$TIMESTAMP'
}
events = []
if os.path.exists(changes_file):
    try:
        with open(changes_file, 'r', encoding='utf-8') as f:
            events = json.load(f)
    except Exception:
        events = []
events.append(event)
with open(changes_file, 'w', encoding='utf-8') as f:
    json.dump(events, f, indent=2)
"

echo "==> [DEPLOY] Successfully deployed ref: '$TARGET_REF'"
echo "==> Version changed from '$PREV_VERSION' -> '$TARGET_REF'"
echo "==> Health endpoints (/health) now reporting version: $TARGET_REF"
