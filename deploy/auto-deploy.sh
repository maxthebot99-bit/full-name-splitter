#!/usr/bin/env bash
# Polls origin/main; if there's a new commit, runs install-vps.sh.
# Invoked by full-name-splitter-autodeploy.timer every minute. Designed to be
# a no-op when there's nothing new — git fetch is the only network call
# in the steady state.

set -euo pipefail

SOURCE_DIR="/home/kianna/github-repos/full-name-splitter"
INSTALL_SCRIPT="$SOURCE_DIR/deploy/install-vps.sh"
ASKPASS="/usr/local/bin/github-pat-askpass"

cd "$SOURCE_DIR"

# git refuses to operate on a repo owned by another user (kianna here)
# when invoked as root unless the directory is in safe.directory. Use an
# array so SOURCE_DIR can contain spaces / metacharacters without
# fragile word-splitting through an unquoted scalar.
GIT=(git -c "safe.directory=${SOURCE_DIR}")

if [[ -x "$ASKPASS" ]]; then
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS="$ASKPASS" \
        "${GIT[@]}" -c credential.helper= fetch origin main --quiet
else
    "${GIT[@]}" fetch origin main --quiet
fi

LOCAL=$("${GIT[@]}" rev-parse HEAD)
REMOTE=$("${GIT[@]}" rev-parse origin/main)

if [[ "$LOCAL" == "$REMOTE" ]]; then
    exit 0
fi

echo "[autodeploy] new commit detected: ${LOCAL:0:7} → ${REMOTE:0:7}"
"${GIT[@]}" reset --hard origin/main --quiet
exec "$INSTALL_SCRIPT"
