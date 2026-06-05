from __future__ import annotations

import json

import httpx
from tenacity import retry, retry_if_exception_type, wait_exponential_jitter

from ..config import Settings
from ..errors import ProviderAuthError, ProviderBadResponseError, ProviderRateLimitError, ProviderTransientError
from .prompt_loader import build_batch_prompt


CleanOutput = tuple[str | None, str]  # (cleaned_or_None, reason)


# Tenacity doesn't have a built-in "different attempt budget per exception
# type" stop, so we roll a tiny function. Transient/rate-limit failures
# deserve the full 5 retries (they usually clear on their own); malformed
# JSON at temperature=0 tends to reproduce, so 2 attempts is all it should
# cost us before we mark the batch unrecoverable.
def _stop_by_exc(retry_state) -> bool:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, ProviderBadResponseError):
        return retry_state.attempt_number >= 2
    return retry_state.attempt_number >= 5


def _scrub_output_value(s: str) -> str:
    """Sanitize a single LLM-returned string before it lands in CSV / SSE.

    See company/llm/_openai_compat.py for the full rationale — same logic.
    """
    if not s:
        return s
    out_chars = []
    for ch in s:
        code = ord(ch)
        if code in (9, 10, 13):
            out_chars.append(" ")
        elif code < 32:
            continue
        else:
            out_chars.append(ch)
    cleaned = "".join(out_chars).strip()
    if cleaned and cleaned[0] in ("=", "@", "+", "-"):
        cleaned = "'" + cleaned
    return cleaned


def _parse_outputs(content: str, expected_n: int) -> list[CleanOutput]:
    """Extract the outputs array from a model response. Tolerant of code fences.

    Accepts two shapes for backwards-compatibility with older prompt variants:
      • new: [{"cleaned": "Foo", "why": "reason"}, ...]
      • old: ["Foo", "null", ...]  (reason defaults to "")

    All extracted strings pass through _scrub_output_value to defang
    Excel-formula-injection payloads and strip control chars.
    """
    txt = content.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lstrip().lower().startswith("json"):
            txt = txt.lstrip()[4:]
    try:
        obj = json.loads(txt)
    except json.JSONDecodeError as e:
        start = txt.find("{")
        end = txt.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(txt[start : end + 1])
            except json.JSONDecodeError:
                raise ProviderBadResponseError(f"invalid JSON: {e}") from e
        else:
            raise ProviderBadResponseError(f"invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ProviderBadResponseError("response root is not an object")
    outputs = obj.get("outputs")
    if not isinstance(outputs, list):
        raise ProviderBadResponseError("missing 'outputs' array")
    if len(outputs) != expected_n:
        raise ProviderBadResponseError(
            f"outputs length {len(outputs)} != expected {expected_n}"
        )
    parsed: list[CleanOutput] = []
    for v in outputs:
        if v is None:
            parsed.append((None, ""))
        elif isinstance(v, str):
            scrubbed = _scrub_output_value(v)
            cleaned = None if scrubbed.lower() == "null" else scrubbed
            parsed.append((cleaned, ""))
        elif isinstance(v, dict):
            raw_cleaned = v.get("cleaned")
            if raw_cleaned is None:
                cleaned = None
            elif isinstance(raw_cleaned, str):
                scrubbed = _scrub_output_value(raw_cleaned)
                cleaned = None if scrubbed.lower() == "null" else scrubbed
            else:
                cleaned = None
            why = v.get("why") or ""
            if not isinstance(why, str):
                why = str(why)
            parsed.append((cleaned, _scrub_output_value(why)))
        else:
            parsed.append((None, ""))
    return parsed


class OpenAICompatibleClient:
    """Shared implementation for OpenAI-compatible endpoints (OpenAI, xAI, etc.)."""

    def __init__(self, *, name: str, model: str, base_url: str, api_key: str, settings: Settings, cost_in_per_1k: float, cost_out_per_1k: float):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.settings = settings
        self.cost_in_per_1k = cost_in_per_1k
        self.cost_out_per_1k = cost_out_per_1k
        # Session-level usage accumulators. Reset via reset_usage() between runs.
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.api_calls = 0

    def reset_usage(self) -> None:
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.api_calls = 0

    def running_cost(self) -> float:
        return (
            (self.prompt_tokens_total / 1000.0) * self.cost_in_per_1k
            + (self.completion_tokens_total / 1000.0) * self.cost_out_per_1k
        )

    def test_connection(self) -> tuple[bool, str]:
        try:
            out = self.clean_batch(["Greenlight Financial LLC"])
            cleaned, why = out[0]
            return True, f"OK - cleaned={cleaned!r} why={why!r}"
        except ProviderAuthError as e:
            return False, f"Auth failed: {e}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def estimate_cost_per_row(self) -> float:
        # Empirical: ~280 input tokens (prompt + 1 input), ~10 output tokens per row
        # For batches of 50, prompt is amortized but we keep per-row to be conservative.
        in_tokens = 300.0 / 50.0 + 10.0  # amortized prompt + per-row input
        out_tokens = 8.0
        return (in_tokens / 1000.0) * self.cost_in_per_1k + (out_tokens / 1000.0) * self.cost_out_per_1k

    @retry(
        retry=retry_if_exception_type((ProviderRateLimitError, ProviderTransientError, ProviderBadResponseError)),
        stop=_stop_by_exc,
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def clean_batch(self, raw_names: list[str]) -> list[CleanOutput]:
        if not raw_names:
            return []
        prompt = build_batch_prompt(raw_names)
        # Per-row output budget: ~40 tokens for `{cleaned, why}` plus JSON
        # overhead. Multiplied by batch size with a floor so tiny batches
        # still get headroom. Bounds worst-case truncation cost AND gives
        # the API a chance to tell us early if the response would be too
        # large (better than silently truncating the JSON array and losing
        # outputs).
        max_tokens = max(256, len(raw_names) * 60)
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "top_p": 1,
            # Seed pins the RNG for backends that honor it (Grok and newer
            # OpenAI models do). Combined with temperature=0 this is as
            # reproducible as we can get out of the API.
            "seed": 7,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self.settings.request_timeout_s) as client:
                r = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
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

        # Accumulate usage for accurate post-run cost reporting.
        usage = data.get("usage") or {}
        self.prompt_tokens_total += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens_total += int(usage.get("completion_tokens") or 0)
        self.api_calls += 1

        return _parse_outputs(content, len(raw_names))
