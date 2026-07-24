from __future__ import annotations

import re
from typing import Any, Dict, List


PROTECTED_PATTERNS = [
    ("age_or_birth_date", re.compile(r"\b(date of birth|dob|born in|birth year|age\s*[:=])\b", re.I)),
    ("marital_status", re.compile(r"\b(marital status|married|single|divorced|widowed)\b", re.I)),
    ("nationality_or_citizenship", re.compile(r"\b(nationality|citizenship|citizen of)\b", re.I)),
    ("religion", re.compile(r"\b(religion|christian|muslim|islam|hindu|buddhist|church|mosque)\b", re.I)),
    ("gender_or_sex", re.compile(r"\b(gender|sex\s*[:=]|male|female)\b", re.I)),
    ("disability_or_health", re.compile(r"\b(disability|disabled|medical condition|health condition)\b", re.I)),
]


IGNORE_GUIDANCE = (
    "Potential protected or sensitive personal information appears in the CV. "
    "Reviewers should ignore it unless there is a lawful, role-specific reason to consider it."
)


def scan_compliance_flags(text: str, file_name: str) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for category, pattern in PROTECTED_PATTERNS:
        if category in seen:
            continue
        match = pattern.search(text or "")
        if match:
            seen.add(category)
            flags.append(
                {
                    "file": file_name,
                    "category": category,
                    "reason": IGNORE_GUIDANCE,
                    "source_ref": nearest_source_ref(text or "", match.start()),
                }
            )
    return flags


def nearest_source_ref(text: str, index: int) -> str:
    prefix = text[:index]
    matches = list(re.finditer(r"\[(page \d+|ocr page \d+|paragraph \d+|table \d+ row \d+|text)\]", prefix, re.I))
    if not matches:
        return ""
    return matches[-1].group(1)
