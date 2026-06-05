from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

RESOURCES_DIR = Path(__file__).resolve().parent / "_resources"


def _compute_prompt_version() -> str:
    h = hashlib.sha256()
    h.update(b"fullname-splitter-v1|")
    try:
        h.update(b"prompt.txt:")
        h.update((RESOURCES_DIR / "prompt.txt").read_bytes())
    except OSError:
        logging.getLogger("full_name_splitter.cleaners.fullname").warning(
            "prompt.txt missing at import time; PROMPT_VERSION hash incomplete"
        )
    return "fullname-splitter-v1-" + h.hexdigest()[:12]


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
        return cls()

    def save(self) -> None:
        return


def resource_path(name: str) -> Path:
    return RESOURCES_DIR / name


_pipeline_logger = logging.getLogger("full_name_splitter.cleaners.fullname")


def log(msg: str) -> None:
    _pipeline_logger.info(msg)
