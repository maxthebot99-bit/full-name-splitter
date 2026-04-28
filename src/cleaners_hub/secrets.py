"""Server-side secret loader.

Keys never live in code, env-var values, or the user's keyring on this machine.
They live in files on disk that are pointed to by env vars:

  XAI_API_KEY_FILE     — path to a file containing the xAI API key (no trailing newline)
  RESEND_API_KEY_FILE  — path to a file containing the Resend API key (optional; if
                          unset, email alerts are disabled)

In production, these env vars are set by systemd via LoadCredentialEncrypted=,
and the files live in /run/credentials/cleaners-hub.service/, readable only by
the unit's User=www-data while the service is running.

In local dev, point the env vars at plaintext files in the repo root (gitignored).
"""

from __future__ import annotations

import os
from pathlib import Path


def _read_credential_file(env_var: str) -> str:
    p = os.environ.get(env_var)
    if not p:
        raise RuntimeError(f"{env_var} is not set")
    path = Path(p)
    if not path.is_file():
        raise RuntimeError(f"{env_var} points to missing file: {p}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"{env_var} points to empty file: {p}")
    return value


def get_xai_key() -> str:
    """Return the xAI API key. Raises if unavailable."""
    return _read_credential_file("XAI_API_KEY_FILE")


def get_resend_key() -> str | None:
    """Return the Resend API key, or None if not configured (alerts disabled).

    The literal placeholder string ``disabled`` is treated as "no key" so
    operators can plant a placeholder credential file (matching the
    install-vps.sh prereq check) without accidentally trying to send
    email through it. README documents this contract.
    """
    try:
        v = _read_credential_file("RESEND_API_KEY_FILE")
    except RuntimeError:
        return None
    if v.strip().lower() == "disabled":
        return None
    return v


def get_key(provider: str) -> str | None:
    """Back-compat shim for vendored llm/xai.py code which calls get_key('xai')."""
    if provider == "xai":
        try:
            return get_xai_key()
        except RuntimeError:
            return None
    return None
