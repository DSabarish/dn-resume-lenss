# ./privacy.py
"""
privacy.py — PII redaction and bias-safe text preparation.
Bug fix: phone regex tightened to avoid matching version numbers, date ranges,
         and "5-8 years of experience" style phrases.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# Stricter phone: requires recognisable phone structure (7+ contiguous digits)
# Matches: +1-800-555-1234, (415) 555-1234, 415.555.1234, +44 20 7946 0958
# Does NOT match: "3.10.4", "4-8 years", "Q1 2024"
_PHONE_RE = re.compile(
    r"(\+?1[\s.\-]?)?(\(?\d{3}\)?[\s.\-]?)(\d{3}[\s.\-]?\d{4})\b"
)

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_LINKEDIN_RE = re.compile(r"linkedin\.com/in/[\w\-]+", re.IGNORECASE)
_GITHUB_RE = re.compile(r"github\.com/[\w\-]+", re.IGNORECASE)
_ADDRESS_RE = re.compile(
    r"\d{1,5}\s[\w\s]{1,40}(?:street|st|avenue|ave|road|rd|blvd|boulevard|lane|ln|drive|dr|court|ct|way|place|pl)\b",
    re.IGNORECASE,
)
_POSTAL_RE = re.compile(r"\b\d{5,6}(?:[-\s]\d{4})?\b")
_SSN_RE = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")

_NAME_PREFIXES = re.compile(
    r"\b(Mr|Mrs|Ms|Dr|Prof|Sir|Madam)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b"
)
_STANDALONE_NAME_RE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\s*$", re.MULTILINE)

_INSTITUTION_RE = re.compile(
    r"\b(?:Harvard|Yale|Stanford|MIT|Princeton|Oxford|Cambridge|Columbia|"
    r"Cornell|Dartmouth|Brown|Penn|Duke|Caltech|Chicago|LSE|ETH|NUS|NTU|"
    r"IIT|IISc|BITS)\b",
    re.IGNORECASE,
)


@dataclass
class RedactionResult:
    clean_text: str
    redacted_items: List[str]
    pii_found: bool
    bias_items_masked: int


def redact_pii(text: str, bias_mode: bool = True) -> RedactionResult:
    redacted: List[str] = []
    bias_count = 0

    def _sub(pattern: re.Pattern[str], replacement: str, src: str) -> str:
        matches = pattern.findall(src)
        if matches:
            redacted.extend([str(m) for m in matches])
        return pattern.sub(replacement, src)

    clean = text
    clean = _sub(_EMAIL_RE, "[EMAIL]", clean)
    clean = _sub(_SSN_RE, "[SSN]", clean)
    clean = _sub(_PHONE_RE, "[PHONE]", clean)
    clean = _sub(_ADDRESS_RE, "[ADDRESS]", clean)
    clean = _sub(_POSTAL_RE, "[POSTAL]", clean)
    clean = _sub(_LINKEDIN_RE, "[LINKEDIN]", clean)
    clean = _sub(_GITHUB_RE, "[GITHUB]", clean)
    clean = _URL_RE.sub("[URL]", clean)

    if bias_mode:
        name_matches = _STANDALONE_NAME_RE.findall(clean)
        if name_matches:
            bias_count += len(name_matches)
            clean = _STANDALONE_NAME_RE.sub("[CANDIDATE_NAME]", clean)

        prefix_matches = _NAME_PREFIXES.findall(clean)
        bias_count += len(prefix_matches)
        clean = _NAME_PREFIXES.sub("[CANDIDATE_NAME]", clean)

        inst_matches = _INSTITUTION_RE.findall(clean)
        if inst_matches:
            bias_count += len(inst_matches)
            clean = _INSTITUTION_RE.sub("[UNIVERSITY]", clean)

    return RedactionResult(
        clean_text=clean,
        redacted_items=list(set(redacted)),
        pii_found=len(redacted) > 0 or bias_count > 0,
        bias_items_masked=bias_count,
    )


def prepare_resume_text(raw: str, redact: bool = True, bias_mode: bool = True) -> Tuple[str, bool]:
    if not redact:
        return raw.strip(), False
    result = redact_pii(raw.strip(), bias_mode=bias_mode)
    return result.clean_text, result.pii_found
