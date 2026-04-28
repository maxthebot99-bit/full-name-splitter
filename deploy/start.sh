#!/usr/bin/env bash
# Entry point for the cleaners-hub systemd unit.
#
# The unit invokes this script as User=www-data with:
#   $PORT                            assigned by /usr/local/bin/app
#   $XAI_API_KEY_FILE                injected via LoadCredentialEncrypted=
#   $RESEND_API_KEY_FILE             injected via LoadCredentialEncrypted=
#   $CLEANERS_HUB_DATA_DIR           /var/lib/cleaners-hub (persistent, on-disk)
#   $CLEANERS_HUB_SESSIONS_DIR       /var/tmp/cleaners-hub/sessions (PrivateTmp)
#
# The .venv was created by `app deploy` (or `app update`) at deploy time.

set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8181}"
exec ./.venv/bin/python -m cleaners_hub.main
