from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_RUBRIC: Dict[str, str] = {
    "0": "Not evidenced",
    "1": "Very weak evidence (vague or unclear)",
    "2": "Some evidence but below requirement",
    "3": "Meets requirement (clear evidence)",
    "4": "Strongly meets (exceeds requirement)",
    "5": "Outstanding (expert-level, leadership, major impact)",
}


BULLET_PATTERN = re.compile(r"^(?:[-*]|\d+[).:]|[A-Za-z][).:]|\u2022)\s+(.*)$")
WEIGHT_PATTERN = re.compile(r"\[\s*weight\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*\]|\(\s*weight\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*\)", re.I)
PASS_PATTERN = re.compile(r"\[\s*pass\s*=\s*([0-5])\s*\]|\(\s*pass(?:\s+score)?\s*[:=]\s*([0-5])\s*\)", re.I)


def normalise_newlines(value: str) -> str:
    return (value or "").replace("\u2028", "\n").replace("\u2029", "\n").replace("\r\n", "\n").replace("\r", "\n")


def clean_header(value: str) -> str:
    value = normalise_newlines(value).strip().rstrip(":").strip().lower()
    value = re.sub(r"[^a-z\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def looks_like_section_header(line: str) -> bool:
    cleaned = clean_header(line)
    if not cleaned:
        return False
    known = {
        "minimum requirements",
        "minimum",
        "mandatory requirements",
        "essential requirements",
        "required qualifications",
        "preferred requirements",
        "preferred",
        "desirable requirements",
        "desirable",
        "education",
        "experience",
        "skills",
        "language requirements",
    }
    return cleaned in known or (line.strip().endswith(":") and len(line.strip()) <= 90 and not BULLET_PATTERN.match(line.strip()))


def section_is_mandatory(section_name: str) -> bool:
    section = clean_header(section_name)
    return any(word in section for word in ("minimum", "mandatory", "essential", "required"))


def extract_number(pattern: re.Pattern[str], text: str, default: float) -> tuple[float, str]:
    match = pattern.search(text)
    if not match:
        return default, text
    value = next(group for group in match.groups() if group is not None)
    cleaned = pattern.sub("", text).strip()
    return float(value), re.sub(r"\s+", " ", cleaned)


def strip_inline_flags(text: str) -> tuple[str, bool]:
    mandatory = False
    flag_pattern = re.compile(r"\((mandatory|required|essential|preferred|desirable)\)|\[(mandatory|required|essential|preferred|desirable)\]", re.I)
    for match in flag_pattern.finditer(text):
        token = (match.group(1) or match.group(2) or "").lower()
        if token in {"mandatory", "required", "essential"}:
            mandatory = True
    text = flag_pattern.sub("", text).strip()
    return re.sub(r"\s+", " ", text), mandatory


def parse_criteria_text(raw: str) -> Dict[str, Any]:
    raw = normalise_newlines(raw).strip()
    if not raw:
        raise ValueError("Criteria paste box is empty.")

    lines = [line.strip() for line in raw.split("\n") if line.strip()]
    role_title = ""
    if lines:
        first = lines[0].strip()
        first_clean = first.rstrip("-:").strip()
        if first.endswith(("-", ":")) and len(first_clean) <= 100 and not looks_like_section_header(first_clean):
            role_title = first_clean
            lines = lines[1:]

    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def start_section(name: str) -> None:
        nonlocal current
        current = {"name": name.strip().rstrip(":") or "Criteria", "criteria": []}
        sections.append(current)

    for line in lines:
        bullet_match = BULLET_PATTERN.match(line)
        candidate_text = bullet_match.group(1).strip() if bullet_match else line

        if looks_like_section_header(line) and not bullet_match:
            header = line.strip().rstrip(":")
            cleaned = clean_header(header)
            if cleaned in {"minimum", "mandatory requirements", "essential requirements", "required qualifications"}:
                header = "Minimum Requirements"
            elif cleaned in {"preferred", "desirable", "desirable requirements"}:
                header = "Preferred Requirements"
            start_section(header)
            continue

        if current is None:
            start_section("Minimum Requirements")

        weight, candidate_text = extract_number(WEIGHT_PATTERN, candidate_text, 1.0)
        pass_score, candidate_text = extract_number(PASS_PATTERN, candidate_text, 3.0)
        candidate_text, inline_mandatory = strip_inline_flags(candidate_text)

        if not candidate_text:
            continue

        current["criteria"].append(
            {
                "text": candidate_text,
                "mandatory": inline_mandatory or section_is_mandatory(current["name"]),
                "weight": weight,
                "pass_score": int(pass_score),
            }
        )

    assign_ids(sections)
    return {
        "role_title": role_title,
        "sections": sections,
        "minimum_pass_score": 3,
        "scoring_rubric": DEFAULT_RUBRIC,
    }


def assign_ids(sections: List[Dict[str, Any]]) -> None:
    counters = {"min": 1, "pref": 1, "other": 1}
    for section in sections:
        mandatory = section_is_mandatory(section.get("name", ""))
        preferred = "preferred" in clean_header(section.get("name", "")) or "desirable" in clean_header(section.get("name", ""))
        for criterion in section.get("criteria", []):
            if criterion.get("mandatory", mandatory):
                prefix = "min"
            elif preferred:
                prefix = "pref"
            else:
                prefix = "other"
            criterion.setdefault("id", f"{prefix}_{counters[prefix]}")
            counters[prefix] += 1


def criteria_to_rows(criteria_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for section in criteria_json.get("sections", []):
        section_name = section.get("name", "Criteria")
        for criterion in section.get("criteria", []):
            rows.append(
                {
                    "section": section_name,
                    "id": str(criterion.get("id", "")).strip(),
                    "text": str(criterion.get("text", "")).strip(),
                    "mandatory": bool(criterion.get("mandatory", section_is_mandatory(section_name))),
                    "weight": float(criterion.get("weight", 1.0) or 1.0),
                    "pass_score": int(criterion.get("pass_score", criteria_json.get("minimum_pass_score", 3)) or 3),
                }
            )
    return rows


def rows_to_criteria(
    rows: Iterable[Dict[str, Any]],
    role_title: str = "",
    scoring_rubric: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        section = str(row.get("section", "")).strip() or "Criteria"
        item_id = str(row.get("id", "")).strip() or f"criterion_{index}"
        mandatory = bool(row.get("mandatory", False))
        try:
            weight = float(row.get("weight", 1.0) or 1.0)
        except (TypeError, ValueError):
            weight = 1.0
        try:
            pass_score = int(row.get("pass_score", 3) or 3)
        except (TypeError, ValueError):
            pass_score = 3
        pass_score = max(0, min(5, pass_score))
        weight = max(0.1, weight)

        grouped.setdefault(section, {"name": section, "criteria": []})["criteria"].append(
            {
                "id": item_id,
                "text": text,
                "mandatory": mandatory,
                "weight": weight,
                "pass_score": pass_score,
            }
        )

    criteria_json = {
        "role_title": role_title.strip(),
        "sections": list(grouped.values()),
        "minimum_pass_score": 3,
        "scoring_rubric": scoring_rubric or DEFAULT_RUBRIC,
    }
    validate_criteria(criteria_json)
    return criteria_json


def validate_criteria(criteria_json: Dict[str, Any]) -> None:
    rows = criteria_to_rows(criteria_json)
    if not rows:
        raise ValueError("No criteria found.")
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        if not row["id"]:
            raise ValueError("Every criterion needs an id.")
        if row["id"] in seen:
            duplicates.add(row["id"])
        seen.add(row["id"])
        if not row["text"]:
            raise ValueError(f"Criterion {row['id']} is missing text.")
    if duplicates:
        raise ValueError("Duplicate criterion ids: " + ", ".join(sorted(duplicates)))
