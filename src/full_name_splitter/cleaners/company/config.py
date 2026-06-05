from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

# Resources (prompt.txt, scrape_tails.json) live in a sibling _resources dir.
# In the desktop build, these were under <repo>/resources; on web we vendor them
# inside the package so they ship with the wheel.
RESOURCES_DIR = Path(__file__).resolve().parent / "_resources"


def _compute_prompt_version() -> str:
    """Hash of the authoritative prompt, exposed for provenance/logging.

    Stamping each run with the prompt hash means a row that came back weird is
    traceable to the prompt revision that produced it. Change prompt.txt → hash
    changes → easy to diff.
    """
    h = hashlib.sha256()
    h.update(b"clay-grok-v5|")
    try:
        h.update(b"prompt.txt:")
        h.update((RESOURCES_DIR / "prompt.txt").read_bytes())
    except OSError:
        logging.getLogger("full_name_splitter.cleaners.company").warning(
            "prompt.txt missing at import time; PROMPT_VERSION hash incomplete"
        )
    return "clay-grok-v5-" + h.hexdigest()[:12]


PROMPT_VERSION = _compute_prompt_version()


@dataclass
class Settings:
    provider: str = "xai"
    model: dict[str, str] = field(
        default_factory=lambda: {"xai": "grok-4-fast-non-reasoning"}
    )
    batch_size: int = 200
    chunk_rows: int = 10_000
    max_retries: int = 5
    request_timeout_s: int = 120

    @classmethod
    def load(cls) -> "Settings":
        # Web build has no per-user overrides; always return defaults.
        return cls()

    def save(self) -> None:
        # No-op on web. Settings are constants in code.
        return


def resource_path(name: str) -> Path:
    return RESOURCES_DIR / name


_pipeline_logger = logging.getLogger("full_name_splitter.cleaners.company")


def log(msg: str) -> None:
    """Pipeline log shim. Routes vendored log() calls through stdlib logging
    so they get the same redaction filter and journalctl handling as everything
    else."""
    _pipeline_logger.info(msg)
