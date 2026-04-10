# ./evaluator.py
"""
evaluator.py — friendly candidate evaluation.

One score (1-10). No pass/fail.
"Will shine in" + "Needs to grow" — honest, actionable, two-sentence summary.
Bug fix: Gemini call wrapped in asyncio.to_thread() to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import List

import structlog
from pydantic import ValidationError

from cache import AtsCache, get_cache
from config import ScreeningConfig, get_config
from models import JobCriteria, ResumeProfile, StartupReport
from utils import async_retry, clamp, get_tracker

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are helping a  founder make fast, honest hiring decisions.
Be direct and practical. No corporate jargon. No sugarcoating.
Return ONLY valid JSON. No markdown fences."""

_EVALUATION_PROMPT = """\
Evaluate this candidate for the job below. Be honest — startups can't afford bad hires.

JOB:
{job_json}

CANDIDATE:
{resume_json}

Return ONLY this JSON (no extra fields, no markdown):
{{
  "score": <integer 1-10>,
  "matched_skills": ["skills they have that this job needs"],
  "missing_skills": ["skills the job needs that they clearly lack"],
  "shine_areas": ["up to 4 SHORT phrases: why this candidate fits THIS job — lead with matching skills and relevant experience, be specific"],
  "gap_areas": ["up to 4 SHORT phrases: honest gaps or risks for THIS role — be specific, mention job hopping if avg_tenure_months < 12"],
  "red_flags": ["up to 3 SHORT phrases — devil's advocate view: frequent job changes, unexplained gaps, title inflation, overqualification, missing must-haves. Empty list [] if none."],
  "experience_note": "one sentence: their experience level vs what the role needs",
  "summary": "sentence 1: what makes them a fit for this role. Sentence 2: the main risk or concern."
}}

Score guide:
  9-10 = Exceptional — hire fast before someone else does
  7-8  = Strong fit — worth a serious conversation
  5-6  = Possible — could work with some mentoring or adjustment
  3-4  = Stretch — significant gaps, high onboarding cost
  1-2  = Not ready — wrong role or wrong stage

shine_areas: short phrases only (e.g. "5 yrs React", "led 3 product launches", "fintech domain match"). Not sentences.
gap_areas: short phrases only (e.g. "no team lead experience", "avg 8 months/role", "no Python"). Not sentences.
red_flags: short phrases only (e.g. "4 jobs in 2 years", "6-month gap unexplained", "overqualified for IC role"). Not sentences.
Do not say 'pass' or 'fail'. Do not use corporate-speak.
"""


class EvaluationError(Exception):
    pass


@async_retry(max_attempts=3, exceptions=(EvaluationError, ValidationError))
async def evaluate_candidate(
    resume: ResumeProfile,
    job: JobCriteria,
    config: ScreeningConfig | None = None,
) -> StartupReport:
    """
    Evaluate one candidate against one job. Returns a Report with score/10,
    shine areas, gap areas, and a plain-language summary.
    """
    cfg = config or get_config()
    cache = get_cache(cfg.cache_dir, cfg.cache_ttl_hours)
    tracker = get_tracker()

    cache_key = cache.make_key(resume.candidate_id, job.job_id, cfg.config_hash())
    cached = cache.get(cache_key)
    if cached is not None:
        logger.info("cache_hit_evaluation", candidate_id=resume.candidate_id)
        data = json.loads(cached)
        data["from_cache"] = True
        return StartupReport(**data)

    # --- Gemini init (outside retry scope — config errors should fail fast) ---
    try:
        from google import genai
        client = genai.Client(api_key=cfg.gemini_api_key)
    except Exception as exc:
        raise EvaluationError(f"Gemini SDK init failed: {exc}") from exc

    prompt = _EVALUATION_PROMPT.format(
        resume_json=resume.model_dump_json(indent=2),
        job_json=job.model_dump_json(indent=2),
    )

    t0 = time.perf_counter()
    try:
        # Bug fix: blocking SDK call runs in thread pool, not on event loop
        from google import genai
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=cfg.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json", 
                "temperature": 0.1,
                "system_instruction": _SYSTEM_PROMPT
            }
        )
    except Exception as exc:
        raise EvaluationError(f"Gemini API error: {exc}") from exc

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
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"JSON parse failed: {exc}\nRaw: {raw_text[:300]}") from exc

    try:
        score = clamp(float(raw.get("score", 5)), 1.0, 10.0)
        report = StartupReport(
            candidate_id=resume.candidate_id,
            job_id=job.job_id,
            timestamp=datetime.now(timezone.utc),
            score=round(score, 1),
            matched_skills=raw.get("matched_skills", [])[:10],
            missing_skills=raw.get("missing_skills", [])[:10],
            shine_areas=raw.get("shine_areas", [])[:4],
            gap_areas=raw.get("gap_areas", [])[:4],
            red_flags=raw.get("red_flags", [])[:3],
            experience_note=str(raw.get("experience_note", ""))[:300],
            summary=str(raw.get("summary", ""))[:500],
        )
    except (ValidationError, TypeError, KeyError) as exc:
        raise EvaluationError(f"Validation failed: {exc}") from exc

    cache.set(cache_key, json.dumps({
        **report.model_dump(mode="json"),
        "from_cache": False,
    }))

    logger.info(
        "evaluation_complete",
        candidate_id=resume.candidate_id,
        score=report.score,
        latency_ms=round(latency_ms, 1),
    )
    return report
