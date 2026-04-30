"""Mutable runtime settings, JSON-backed, admin-edited from the UI.

The hard daily-cap ceiling (``SPEND_CAP_USD_PER_DAY``) is a code constant
and CANNOT be raised from the UI. ``daily_cap_usd`` here is a SOFT cap
that the UI can lower (or raise up to the hard ceiling). The effective
cap used by the spend tracker is ``min(soft, hard)``.

Bounds are enforced at write-time so a corrupted settings file or an
admin slip-of-the-finger can't shove batch_size to 50000 or the cap to
$1M. Validation lives in ``AppSettings.validate()``.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from cleaners_hub.spend import SPEND_CAP_USD_PER_DAY, _data_dir

_log = logging.getLogger("cleaners_hub.settings")

# Allowed model strings, per kind. Company/name use xAI Grok; address uses
# OpenRouter Llama (different vendor, different cost structure, different
# rate limits — keeping the allowed lists separate keeps validation honest).
ALLOWED_MODELS_GROK: tuple[str, ...] = (
    "grok-4-fast-non-reasoning",
    "grok-4-fast-reasoning",
    "grok-4",
)
ALLOWED_MODELS_OPENROUTER: tuple[str, ...] = (
    "meta-llama/llama-3.1-8b-instruct",
)
# Back-compat alias: existing callers expect ALLOWED_MODELS to be the Grok set.
ALLOWED_MODELS = ALLOWED_MODELS_GROK

# Bound values so a bad write can't lock us out or run us over.
MIN_BATCH_SIZE = 50
MAX_BATCH_SIZE = 500
# Address batches need a smaller floor because each row fetches up to ~10
# pages and runs ~3.5K input tokens through the LLM. 25 keeps wall-clock
# checkpoints frequent without thrashing.
MIN_BATCH_SIZE_ADDRESS = 25
MAX_BATCH_SIZE_ADDRESS = 200
MIN_DAILY_CAP_USD = 0.0  # 0 = block all runs (effectively a kill switch)


@dataclass
class AppSettings:
    daily_cap_usd: float = 10.0
    # batch_size = how many rows we send to Grok in one API call. Smaller
    # batches → telemetry/SSE updates fire more often → progress bar feels
    # real-time instead of jumping every 14s. Trade-off: the system prompt
    # gets re-amortized over fewer rows, so per-row input tokens go up
    # ~14% (300 prompt tokens / 50 vs / 200). For 12k rows that's ~$0.02
    # extra. Worth it. Admin can tune up to MAX_BATCH_SIZE in Settings.
    batch_size_company: int = 50
    batch_size_name: int = 50
    # Address batches default lower because each row does HTML fetch + LLM
    # extract; smaller batches give better progress granularity.
    batch_size_address: int = 100
    model_company: str = "grok-4-fast-non-reasoning"
    model_name: str = "grok-4-fast-non-reasoning"
    model_address: str = "meta-llama/llama-3.1-8b-instruct"

    def validate(self) -> "AppSettings":
        """Return a new instance with values clamped/normalized to safe bounds.
        Raises ValueError if a model name isn't recognized."""
        cap = max(MIN_DAILY_CAP_USD, min(float(self.daily_cap_usd),
                                         float(SPEND_CAP_USD_PER_DAY)))
        bs_co = max(MIN_BATCH_SIZE, min(int(self.batch_size_company), MAX_BATCH_SIZE))
        bs_nm = max(MIN_BATCH_SIZE, min(int(self.batch_size_name), MAX_BATCH_SIZE))
        bs_addr = max(
            MIN_BATCH_SIZE_ADDRESS,
            min(int(self.batch_size_address), MAX_BATCH_SIZE_ADDRESS),
        )
        if self.model_company not in ALLOWED_MODELS_GROK:
            raise ValueError(f"unknown model_company: {self.model_company!r}")
        if self.model_name not in ALLOWED_MODELS_GROK:
            raise ValueError(f"unknown model_name: {self.model_name!r}")
        if self.model_address not in ALLOWED_MODELS_OPENROUTER:
            raise ValueError(f"unknown model_address: {self.model_address!r}")
        return replace(
            self,
            daily_cap_usd=cap,
            batch_size_company=bs_co,
            batch_size_name=bs_nm,
            batch_size_address=bs_addr,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def batch_size_for(self, kind: str) -> int:
        if kind == "address":
            return self.batch_size_address
        if kind == "name":
            return self.batch_size_name
        return self.batch_size_company

    def model_for(self, kind: str) -> str:
        if kind == "address":
            return self.model_address
        if kind == "name":
            return self.model_name
        return self.model_company


class SettingsStore:
    """JSON-file-backed settings, with file lock for atomic writes."""

    def __init__(self, path: Path | None = None):
        self.path = path or (_data_dir() / "settings.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cached: AppSettings | None = None

    def get(self) -> AppSettings:
        with self._lock:
            if self._cached is not None:
                return self._cached
            if not self.path.is_file():
                self._cached = AppSettings()
                return self._cached
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                # Tolerate unknown keys / missing keys
                fields = {k: data[k] for k in AppSettings.__dataclass_fields__
                          if k in data}
                s = AppSettings(**fields)
                # Soft re-validation; file may be old/manually-edited
                self._cached = s.validate()
                return self._cached
            except Exception as e:
                _log.warning("settings.json read failed (%r); using defaults", e)
                self._cached = AppSettings()
                return self._cached

    def update(self, patch: dict[str, Any]) -> AppSettings:
        """Merge ``patch`` into current settings, validate, persist atomically."""
        with self._lock:
            current = self.get()
            merged = AppSettings(**{**current.to_dict(), **patch})
            validated = merged.validate()
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(validated.to_dict(), indent=2, sort_keys=True),
                           encoding="utf-8")
            tmp.replace(self.path)
            self._cached = validated
            return validated

    def reload(self) -> None:
        """Drop cache, force re-read on next .get()."""
        with self._lock:
            self._cached = None


# Singleton.
_singleton: SettingsStore | None = None
_singleton_lock = threading.Lock()


def settings() -> SettingsStore:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = SettingsStore()
    return _singleton
