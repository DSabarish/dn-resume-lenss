# ./models.py
"""
models.py — Lean data models for the startup ATS pipeline.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ResumeProfile(BaseModel):
    model_config = ConfigDict(strict=True)

    candidate_id: str
    skills: List[str] = []
    tools_technologies: List[str] = []
    certifications: List[str] = []
    education: List[str] = []
    years_experience: float = Field(default=0.0, ge=0.0)
    recent_roles: List[str] = []
    parse_confidence: float = Field(default=0.0, ge=0, le=1)
    pii_redacted: bool = True
    raw_text_snippet: str = ""


class JobCriteria(BaseModel):
    model_config = ConfigDict(strict=True)

    job_id: str
    title: str
    must_have_skills: List[str] = []
    preferred_skills: List[str] = []
    min_experience_years: float = Field(default=0.0, ge=0.0)
    required_education: List[str] = []
    domain_keywords: List[str] = []


class StartupReport(BaseModel):
    """
    Simple, honest candidate evaluation for a startup context.
    Score 1-10. No pass/fail. Show where they shine and where they need growth.
    """
    model_config = ConfigDict(strict=True)

    candidate_id: str
    job_id: str
    timestamp: datetime
    score: float = Field(ge=1.0, le=10.0)          # out of 10
    matched_skills: List[str] = []                  # skills they have that the JD needs
    missing_skills: List[str] = []                  # skills from JD they lack
    shine_areas: List[str] = []                     # max 4 — where they'll genuinely excel
    gap_areas: List[str] = []                       # max 4 — honest gaps
    experience_note: str = ""                       # one sentence on experience fit
    summary: str = ""                               # 2 sentences: strength + main risk
    from_cache: bool = False


class ExtractionResult(BaseModel):
    model_config = ConfigDict(strict=True)

    resume: ResumeProfile
    job: JobCriteria
    from_cache: bool = False
    latency_ms: float = 0.0
    tokens_used: int = 0
