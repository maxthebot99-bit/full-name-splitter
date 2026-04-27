from __future__ import annotations

from ..config import Settings
from ..errors import ProviderAuthError
from cleaners_hub.secrets import get_key
from ._openai_compat import OpenAICompatibleClient


class XAIProvider:
    """xAI Grok via the OpenAI-compatible endpoint.

    Grok 4.1 Fast Reasoning matches the Clay workflow's model.
    List price (2M-token context): $0.20/1M input, $0.50/1M output, $0.05/1M cached input.
    Update if xAI changes pricing.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None):
        s = Settings.load()
        self.name = "xai"
        self.model = model or s.model.get("xai", "grok-4-fast-reasoning")
        key = api_key or get_key("xai")
        if not key:
            raise ProviderAuthError(
                "Server-side credential XAI_API_KEY_FILE not set or empty. "
                "Plant via systemd-creds and restart the unit."
            )
        self._client = OpenAICompatibleClient(
            name="xai",
            model=self.model,
            base_url="https://api.x.ai/v1",
            api_key=key,
            settings=s,
            cost_in_per_1k=0.0002,   # $0.20 per 1M
            cost_out_per_1k=0.0005,  # $0.50 per 1M
        )

    def clean_batch(self, raw_names):
        return self._client.clean_batch(raw_names)

    def test_connection(self):
        return self._client.test_connection()

    def estimate_cost_per_row(self) -> float:
        return self._client.estimate_cost_per_row()

    def running_usage(self) -> dict:
        c = self._client
        return {
            "prompt_tokens": c.prompt_tokens_total,
            "completion_tokens": c.completion_tokens_total,
            "api_calls": c.api_calls,
            "cost": c.running_cost(),
        }

    def reset_usage(self) -> None:
        self._client.reset_usage()
