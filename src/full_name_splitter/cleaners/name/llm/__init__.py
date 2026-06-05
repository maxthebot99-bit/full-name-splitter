from __future__ import annotations

import os

from .base import Provider
from .prompt_loader import build_batch_prompt, load_prompt

__all__ = ["Provider", "load_prompt", "build_batch_prompt"]


def get_provider(name: str = "xai") -> Provider:
    # Stress-test / offline mode. Set ``COMPANY_CLEANER_MOCK_LLM=1`` before
    # launching the app or the stress harness to route every LLM call
    # through MockProvider — zero API cost, deterministic, tunable latency.
    if os.environ.get("COMPANY_CLEANER_MOCK_LLM", "").strip() in ("1", "true", "yes"):
        from .mock import MockProvider
        return MockProvider()
    # xAI Grok is the only real provider today. `name` kept for signature
    # stability if we add OpenAI/Anthropic/Ollama back later.
    if name.lower() != "xai":
        raise ValueError(f"Unknown provider: {name}. Only 'xai' is supported.")
    from .xai import XAIProvider
    return XAIProvider()
