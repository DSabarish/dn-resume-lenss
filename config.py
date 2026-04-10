# ./config.py
"""
config.py — Lean configuration for the  ATS.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScreeningConfig(BaseSettings):
    """Configuration for the ATS screening pipeline."""

    # --- LLM ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="ATS_GEMINI_MODEL")

    # --- Shortlisting ---
    min_score: float = Field(default=5.0, ge=1.0, le=10.0)   # out of 10
    top_k: int = Field(default=10, ge=1)

    # --- Runtime ---
    max_workers: int = Field(default=4, ge=1, le=16)

    # --- Cache ---
    cache_ttl_hours: int = Field(default=24, ge=0)
    cache_dir: str = ".ats_cache"

    # --- Privacy ---
    redact_pii: bool = True
    bias_mitigation: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ATS_",
        extra="ignore",
        populate_by_name=True,
        validate_default=True,
    )

    def config_hash(self) -> str:
        """Stable fingerprint of scoring-relevant fields (used for cache keys)."""
        payload = {
            "gemini_model": self.gemini_model,
            "min_score": self.min_score,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()[:16]


@lru_cache(maxsize=1)
def get_config() -> ScreeningConfig:
    """Return singleton config (cached). Call get_config.cache_clear() to reload."""
    return ScreeningConfig()
