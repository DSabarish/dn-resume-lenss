# ./utils.py
"""
utils.py — Logging, retry, cost tracking, text extraction helpers.
Bug fix: datetime.utcnow() replaced with datetime.now(timezone.utc) throughout.
"""
from __future__ import annotations

import asyncio
import functools
import io
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=False),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger("ats_screener")

# Gemini 2.5 Flash approximate pricing (USD per 1M tokens)
_PRICE_INPUT_PER_M = 0.075
_PRICE_OUTPUT_PER_M = 0.30


class CostTracker:
    def __init__(self) -> None:
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.total_calls: int = 0
        self.total_latency_ms: float = 0.0

    def record(self, input_t: int, output_t: int, latency_ms: float) -> None:
        self.input_tokens += input_t
        self.output_tokens += output_t
        self.total_calls += 1
        self.total_latency_ms += latency_ms

    @property
    def estimated_cost_usd(self) -> float:
        return (
            self.input_tokens * _PRICE_INPUT_PER_M / 1_000_000
            + self.output_tokens * _PRICE_OUTPUT_PER_M / 1_000_000
        )

    def summary(self) -> dict[str, Any]:
        return {
            "calls": self.total_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "est_cost_usd": round(self.estimated_cost_usd, 6),
            "avg_latency_ms": round(
                self.total_latency_ms / max(self.total_calls, 1), 1
            ),
        }


_tracker: Optional[CostTracker] = None


def get_tracker() -> CostTracker:
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker


def reset_tracker() -> None:
    global _tracker
    _tracker = CostTracker()


F = TypeVar("F", bound=Callable[..., Any])


def async_retry(
    max_attempts: int = 3,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async for attempt in AsyncRetrying(
                wait=wait_exponential(multiplier=1, min=1, max=10),
                stop=stop_after_attempt(max_attempts),
                retry=retry_if_exception_type(exceptions),
                reraise=True,
            ):
                with attempt:
                    return await fn(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator


def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        import fitz  # type: ignore[import]
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = [page.get_text("text") for page in doc]
        doc.close()
        return "\n".join(pages).strip()
    except Exception as exc:
        logger.warning("pdf_extract_failed", error=str(exc))
        return ""


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document  # type: ignore[import]
        doc = Document(io.BytesIO(file_bytes))
        paras = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paras).strip()
    except Exception as exc:
        logger.warning("docx_extract_failed", error=str(exc))
        return ""


def extract_text(file_bytes: bytes, filename: str) -> str:
    name_lower = filename.lower()
    if name_lower.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    elif name_lower.endswith((".docx", ".doc")):
        return extract_text_from_docx(file_bytes)
    else:
        try:
            return file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1", errors="replace").strip()


def utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 string with proper timezone info."""
    return datetime.now(timezone.utc).isoformat()


def clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def fmt_score(v: float) -> str:
    return f"{v:.1f}/10"
