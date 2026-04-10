# ./extractor.py
"""
extractor.py — Gemini Call 1: extract ResumeProfile + JobCriteria from raw text.
Bug fix: model.generate_content() wrapped in asyncio.to_thread() so it does
         not block the FastAPI event loop.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Tuple

import structlog
from pydantic import ValidationError

from cache import AtsCache, get_cache
from config import ScreeningConfig, get_config
from models import JobCriteria, ResumeProfile
from privacy import prepare_resume_text
from utils import async_retry, clamp, get_tracker

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are a resume parser for a  hiring tool.
Return ONLY valid JSON. No markdown, no extra text.
Normalise skill names (e.g. 'JS' → 'JavaScript', 'ML' → 'Machine Learning').
If data is missing, return 0.0 or []. Never hallucinate."""

_SCHEMA = {
    "resume": {
        "candidate_id": "string",
        "skills": ["string"],
        "tools_technologies": ["string"],
        "certifications": ["string"],
        "education": ["string"],
        "years_experience": "number",
        "recent_roles": ["string"],
        "avg_tenure_months": "number — average months per role across all jobs; 0 if unknown",
        "parse_confidence": "number 0-1",
    },
    "job": {
        "job_id": "string",
        "title": "string",
        "must_have_skills": ["string"],
        "preferred_skills": ["string"],
        "min_experience_years": "number",
        "required_education": ["string"],
        "domain_keywords": ["string"],
    },
}

_EXTRACTION_PROMPT = """\
Extract structured data from the resume and job description.
Return STRICT JSON matching this schema: {schema}

candidate_id = "{candidate_id}"
job_id = "{job_id}"

RESUME:
{resume}

JOB DESCRIPTION:
{jd}
"""


class ParseError(Exception):
    pass


@async_retry(max_attempts=3, exceptions=(ParseError, ValidationError))
async def parse_resume_and_job(
    resume_text: str,
    job_text: str,
    config: ScreeningConfig | None = None,
    candidate_id: str | None = None,
    job_id: str | None = None,
) -> Tuple[ResumeProfile, JobCriteria, bool, float, int]:
    """
    Parse resume + JD into structured Pydantic models via Gemini.
    Returns: (ResumeProfile, JobCriteria, from_cache, latency_ms, tokens_used)
    Bug fix: Gemini call runs in a thread pool via asyncio.to_thread().
    """
    cfg = config or get_config()
    cache = get_cache(cfg.cache_dir, cfg.cache_ttl_hours)
    tracker = get_tracker()

    cid = candidate_id or str(uuid.uuid4())[:8]
    jid = job_id or "job_001"

    clean_resume, _ = prepare_resume_text(resume_text, cfg.redact_pii, cfg.bias_mitigation)
    clean_jd, _ = prepare_resume_text(job_text, redact=False)

    cache_key = cache.make_key(clean_resume, clean_jd, cfg.config_hash())
    cached = cache.get(cache_key)
    if cached is not None:
        logger.info("cache_hit_extraction", candidate_id=cid)
        data = json.loads(cached)
        return ResumeProfile(**data["resume"]), JobCriteria(**data["job"]), True, 0.0, 0

    # --- Build Gemini client (once per call, outside retry scope) ---
    try:
        from google import genai
        client = genai.Client(api_key=cfg.gemini_api_key)
    except Exception as exc:
        raise ParseError(f"Gemini SDK init failed: {exc}") from exc

    prompt = _EXTRACTION_PROMPT.format(
        schema=json.dumps(_SCHEMA),
        candidate_id=cid,
        job_id=jid,
        resume=clean_resume[:8000],
        jd=clean_jd[:4000],
    )

    t0 = time.perf_counter()
    try:
        # Bug fix: run blocking SDK call in thread pool, not on the event loop
        from google import genai
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=cfg.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json", 
                "temperature": 0.0,
                "system_instruction": _SYSTEM_PROMPT
            }
        )
    except Exception as exc:
        raise ParseError(f"Gemini API error during extraction: {exc}") from exc

    latency_ms = (time.perf_counter() - t0) * 1000

    try:
        tracker.record(
            response.usage_metadata.prompt_token_count or 0,
            response.usage_metadata.candidates_token_count or 0,
            latency_ms,
        )
    except Exception:
        pass

    raw_text = response.text or ""
    try:
        raw_json = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Extraction JSON parse failed: {exc}\nRaw: {raw_text[:300]}") from exc

    try:
        rd = raw_json.get("resume", {})
        jd = raw_json.get("job", {})

        rd["years_experience"] = clamp(float(rd.get("years_experience", 0)), 0, 60)
        rd["avg_tenure_months"] = clamp(float(rd.get("avg_tenure_months", 0)), 0, 600)
        rd["parse_confidence"] = clamp(float(rd.get("parse_confidence", 0.5)), 0, 1)
        rd["candidate_id"] = rd.get("candidate_id", cid)
        rd["pii_redacted"] = True
        rd["raw_text_snippet"] = clean_resume[:300]
        jd["min_experience_years"] = clamp(float(jd.get("min_experience_years", 0)), 0, 60)
        jd["job_id"] = jd.get("job_id", jid)

        resume = ResumeProfile(**rd)
        job = JobCriteria(**jd)
    except (ValidationError, TypeError, KeyError) as exc:
        raise ParseError(f"Extraction validation failed: {exc}") from exc

    cache.set(
        cache_key,
        json.dumps({"resume": resume.model_dump(mode="json"), "job": job.model_dump(mode="json")}),
    )

    tokens_used = 0
    try:
        tokens_used = response.usage_metadata.total_token_count or 0
    except Exception:
        pass

    logger.info("extraction_complete", candidate_id=cid, latency_ms=round(latency_ms, 1))
    return resume, job, False, latency_ms, tokens_used
