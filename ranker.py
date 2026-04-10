# ./ranker.py
"""
ranker.py — Sort StartupReports by score, apply min_score filter, cap at top_k.
"""
from __future__ import annotations

import asyncio
from typing import Callable, List, Optional

import structlog

from config import ScreeningConfig, get_config
from evaluator import evaluate_candidate
from models import JobCriteria, ResumeProfile, StartupReport

logger = structlog.get_logger(__name__)


async def rank_candidates(
    resumes: List[ResumeProfile],
    job: JobCriteria,
    config: ScreeningConfig | None = None,
    progress_cb: Optional[Callable[[str, float], None]] = None,
) -> List[StartupReport]:
    """
    Evaluate all candidates in parallel (bounded by semaphore), sort by score,
    apply min_score filter, return top_k.
    """
    cfg = config or get_config()

    if not resumes:
        return []

    semaphore = asyncio.Semaphore(cfg.max_workers)

    async def eval_one(resume: ResumeProfile) -> Optional[StartupReport]:
        async with semaphore:
            try:
                report = await evaluate_candidate(resume, job, cfg)
                if progress_cb:
                    progress_cb(resume.candidate_id, report.score)
                return report
            except Exception as exc:
                logger.error("eval_failed", candidate_id=resume.candidate_id, error=str(exc))
                return None

    raw: List[Optional[StartupReport]] = await asyncio.gather(
        *[eval_one(r) for r in resumes]
    )
    reports = [r for r in raw if r is not None]

    # Filter by min_score, sort descending, cap at top_k
    reports = [r for r in reports if r.score >= cfg.min_score]
    reports.sort(key=lambda r: r.score, reverse=True)
    reports = reports[: cfg.top_k]

    logger.info(
        "ranking_complete",
        evaluated=len(raw),
        passed_filter=len(reports),
        top_score=reports[0].score if reports else None,
    )
    return reports
