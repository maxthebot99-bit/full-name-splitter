"""Llama 3.1 8B Instruct via OpenRouter.

Per-row JSON-schema extraction. Includes a second-look retry pass at temp=0.0
when the first call returns an all-blank result with confidence 0 — empirically
recovers ~30-50% of stochastic LLM misses where the address was visible in the
HTML but the model didn't grab it on the first attempt.

Pricing reference (verified 2026-04 on OpenRouter):
  Llama 3.1 8B Instruct: $0.02/M input, $0.05/M output.
  ~$0.076 per 1K rows at 3,500 input + 120 output tokens. ~$3 per 40K rows.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, wait_exponential_jitter

from cleaners_hub.secrets import get_key

from ..config import Settings, log
from ..errors import (
    ProviderAuthError,
    ProviderBadResponseError,
    ProviderRateLimitError,
    ProviderTransientError,
)
from ..scope import ALLOWED_COUNTRIES, normalize_country
from ..types import AddressContext


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "_resources" / "prompt.txt"


def _stop_by_exc(retry_state) -> bool:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, ProviderBadResponseError):
        return retry_state.attempt_number >= 2
    return retry_state.attempt_number >= 5


def _parse_json_response(content: str) -> dict | None:
    """Llama sometimes wraps JSON in markdown fences or adds prose; handle both."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(l for l in lines if not l.startswith("```"))
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None


def _scrub(s: str | None) -> str | None:
    """CSV-formula-injection defense + control-char strip."""
    if not s:
        return s
    out = []
    for ch in s:
        code = ord(ch)
        if code in (9, 10, 13):
            out.append(" ")
        elif code < 32:
            continue
        else:
            out.append(ch)
    cleaned = "".join(out).strip()
    if cleaned and cleaned[0] in ("=", "@", "+", "-"):
        cleaned = "'" + cleaned
    return cleaned or None


def _is_blank_extraction(d: dict) -> bool:
    """True if all address fields are null and confidence is 0."""
    return (
        float(d.get("confidence") or 0) == 0.0
        and not d.get("street")
        and not d.get("city")
        and not d.get("state")
        and not d.get("zip")
    )


def _apply_to_context(ctx: AddressContext, parsed: dict) -> AddressContext:
    """Copy parsed JSON onto the context, then apply the scope filter."""
    ctx.street = _scrub(parsed.get("street"))
    ctx.city = _scrub(parsed.get("city"))
    ctx.state = _scrub(parsed.get("state"))
    ctx.zip = _scrub(parsed.get("zip"))
    ctx.country = _scrub(parsed.get("country"))
    ctx.source_url = _scrub(parsed.get("source_url"))
    try:
        ctx.confidence = max(0.0, min(1.0, float(parsed.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        ctx.confidence = 0.0

    # Scope filter: if country is set and not in allowed set, null out
    # the address fields and set error=FOREIGN. Country is preserved so
    # downstream UI/CRM can display "filtered: was IN/PE/etc.".
    normalized = normalize_country(ctx.country)
    if normalized and normalized not in ALLOWED_COUNTRIES:
        ctx.street = None
        ctx.city = None
        ctx.state = None
        ctx.zip = None
        ctx.source_url = None
        ctx.confidence = 0.0
        ctx.country = normalized
        ctx.error = "FOREIGN"
    elif normalized:
        ctx.country = normalized

    if not ctx.has_address():
        ctx.is_null = True

    return ctx


class OpenRouterLlamaProvider:
    """Llama 3.1 8B via OpenRouter's OpenAI-compatible endpoint."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        s = Settings.load()
        self.name = "openrouter"
        self.model = model or s.model.get(
            "openrouter", "meta-llama/llama-3.1-8b-instruct"
        )
        key = api_key or get_key("openrouter")
        if not key:
            raise ProviderAuthError(
                "Server-side credential OPENROUTER_API_KEY_FILE not set or empty. "
                "Plant via systemd-creds and restart the unit."
            )
        self._api_key = key
        self._settings = s
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
        # Pricing for Llama 3.1 8B Instruct on OpenRouter (per 1M tokens).
        self._cost_in_per_1k = 0.00002   # $0.02 / 1M
        self._cost_out_per_1k = 0.00005  # $0.05 / 1M
        # Session-level usage accumulators.
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.api_calls = 0

    def reset_usage(self) -> None:
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.api_calls = 0

    def running_cost(self) -> float:
        return (
            (self.prompt_tokens_total / 1000.0) * self._cost_in_per_1k
            + (self.completion_tokens_total / 1000.0) * self._cost_out_per_1k
        )

    def running_usage(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens_total,
            "completion_tokens": self.completion_tokens_total,
            "api_calls": self.api_calls,
            "cost": self.running_cost(),
        }

    def estimate_cost_per_row(self) -> float:
        # ~3,500 input tokens (cleaned HTML) + ~120 output (JSON). Empirical from pilot.
        in_tokens = 3500.0
        out_tokens = 120.0
        return (
            (in_tokens / 1000.0) * self._cost_in_per_1k
            + (out_tokens / 1000.0) * self._cost_out_per_1k
        )

    def _build_user_message(self, name: str, website: str, html_text: str) -> str:
        return (
            f"business_name: {name}\n"
            f"website: {website}\n\n"
            f"Pages fetched (concatenated, cleaned):\n{html_text}"
        )

    @retry(
        retry=retry_if_exception_type(
            (ProviderRateLimitError, ProviderTransientError, ProviderBadResponseError)
        ),
        stop=_stop_by_exc,
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    async def _call(
        self, client: httpx.AsyncClient, user_message: str, *, temperature: float = 0.1
    ) -> tuple[dict | None, dict]:
        """One LLM call. Returns (parsed_json_or_None, usage_dict)."""
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": "https://cleaners.maxcommandcenter.com",
            "X-Title": "cleaners-hub address tab",
            "Content-Type": "application/json",
        }
        try:
            r = await client.post(
                OPENROUTER_URL, json=body, headers=headers,
                timeout=self._settings.request_timeout_s,
            )
        except httpx.TimeoutException as e:
            raise ProviderTransientError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderTransientError(f"http error: {e}") from e

        if r.status_code in (401, 403):
            raise ProviderAuthError(f"{r.status_code}: {r.text[:200]}")
        if r.status_code == 429:
            raise ProviderRateLimitError(f"429 rate limited: {r.text[:200]}")
        if r.status_code >= 500:
            raise ProviderTransientError(f"{r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            raise ProviderBadResponseError(f"{r.status_code}: {r.text[:200]}")

        try:
            data = r.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise ProviderBadResponseError(f"unexpected shape: {e}") from e

        usage = data.get("usage") or {}
        parsed = _parse_json_response(content)
        return parsed, usage

    async def extract(self, ctx: AddressContext, html_text: str) -> AddressContext:
        """Extract an address from cleaned HTML for one row.

        Updates ctx in place with street/city/state/zip/country/source_url/confidence.
        Returns the same ctx for chaining.
        """
        if not html_text:
            ctx.error = ctx.error or "NO_RESPONSE"
            ctx.confidence = 0.0
            ctx.is_null = True
            return ctx

        user_message = self._build_user_message(
            ctx.business_name, ctx.website_url, html_text
        )

        async with httpx.AsyncClient() as client:
            try:
                parsed, usage = await self._call(client, user_message, temperature=0.1)
            except (ProviderAuthError,) as e:
                log(f"address LLM auth error: {e!r}")
                ctx.error = "LLM_UNAVAILABLE"
                ctx.flag("LLM_UNAVAILABLE")
                return ctx
            except Exception as e:
                log(f"address LLM error: {e!r}")
                ctx.error = "LLM_UNAVAILABLE"
                ctx.flag("LLM_UNAVAILABLE")
                return ctx

            self.prompt_tokens_total += int(usage.get("prompt_tokens") or 0)
            self.completion_tokens_total += int(usage.get("completion_tokens") or 0)
            self.api_calls += 1

            if parsed is None:
                # JSON parse failure — retry once at temp 0.0.
                try:
                    parsed, usage2 = await self._call(client, user_message, temperature=0.0)
                    self.prompt_tokens_total += int(usage2.get("prompt_tokens") or 0)
                    self.completion_tokens_total += int(usage2.get("completion_tokens") or 0)
                    self.api_calls += 1
                except Exception:
                    pass

            if parsed is None:
                ctx.error = "LLM_UNAVAILABLE"
                ctx.flag("LLM_UNAVAILABLE")
                return ctx

            # Second-look retry: blank result might be a stochastic miss.
            if _is_blank_extraction(parsed):
                try:
                    retry_parsed, usage3 = await self._call(
                        client, user_message, temperature=0.0
                    )
                    self.prompt_tokens_total += int(usage3.get("prompt_tokens") or 0)
                    self.completion_tokens_total += int(usage3.get("completion_tokens") or 0)
                    self.api_calls += 1
                    if retry_parsed and not _is_blank_extraction(retry_parsed):
                        parsed = retry_parsed
                except Exception:
                    pass

        return _apply_to_context(ctx, parsed)

    async def test_connection(self) -> tuple[bool, str]:
        try:
            ctx = AddressContext(
                business_name="Test Business",
                website_url="https://example.com",
            )
            tiny_html = "Test Business at 123 Main St, Springfield, IL 62701, USA."
            await self.extract(ctx, tiny_html)
            return True, f"OK - error={ctx.error!r} confidence={ctx.confidence}"
        except ProviderAuthError as e:
            return False, f"Auth failed: {e}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
