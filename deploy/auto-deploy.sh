#!/usr/bin/env bash
# Polls origin/main; if there's a new commit, runs install-vps.sh.
# Invoked by cleaners-hub-autodeploy.timer every minute. Designed to be
# a no-op when there's nothing new — git fetch is the only network call
# in the steady state.

set -euo pipefail

SOURCE_DIR="/home/kianna/github-repos/cleaners-hub"
INSTALL_SCRIPT="$SOURCE_DIR/deploy/install-vps.sh"
ASKPASS="/usr/local/bin/github-pat-askpass"

cd "$SOURCE_DIR"

if [[ -x "$ASKPASS" ]]; then
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS="$ASKPASS" \
        git -c credential.helper= fetch origin main --quiet
else
    git fetch origin main --quiet
fi

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [[ "$LOCAL" == "$REMOTE" ]]; then
    exit 0
fi

echo "[autodeploy] new commit detected: ${LOCAL:0:7} → ${REMOTE:0:7}"
git reset --hard origin/main --quiet
exec "$INSTALL_SCRIPT"
