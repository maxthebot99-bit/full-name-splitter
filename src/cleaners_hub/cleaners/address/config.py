from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

RESOURCES_DIR = Path(__file__).resolve().parent / "_resources"


def _compute_prompt_version() -> str:
    """Hash of the authoritative prompt, exposed for provenance/logging."""
    h = hashlib.sha256()
    h.update(b"address-llama-v1|")
    try:
        h.update(b"prompt.txt:")
        h.update((RESOURCES_DIR / "prompt.txt").read_bytes())
    except OSError:
        logging.getLogger("cleaners_hub.cleaners.address").warning(
            "prompt.txt missing at import time; PROMPT_VERSION hash incomplete"
        )
    return "address-llama-v1-" + h.hexdigest()[:12]


PROMPT_VERSION = _compute_prompt_version()


@dataclass
class Settings:
    provider: str = "openrouter"
    model: dict[str, str] = field(
        default_factory=lambda: {"openrouter": "meta-llama/llama-3.1-8b-instruct"}
    )
    # Smaller batch_size than company/name because each row may fetch up to
    # ~10 pages and processes ~3.5K input tokens through the LLM.
    batch_size: int = 100
    chunk_rows: int = 5_000
    max_retries: int = 5
    request_timeout_s: int = 120
    # Per-page char cap for fetched HTML (5K ≈ 1.2K tokens, fits Llama 16K context).
    per_page_chars: int = 5_000
    # Total HTML budget per row sent to LLM.
    max_html_chars: int = 40_000
    # Concurrency for HTML fetching and LLM calls.
    fetch_concurrency: int = 30
    llm_concurrency: int = 16

    @classmethod
    def load(cls) -> "Settings":
        return cls()

    def save(self) -> None:
        return


def resource_path(name: str) -> Path:
    return RESOURCES_DIR / name


_pipeline_logger = logging.getLogger("cleaners_hub.cleaners.address")


def log(msg: str) -> None:
    _pipeline_logger.info(msg)
