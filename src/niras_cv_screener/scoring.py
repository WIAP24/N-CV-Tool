from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List


DEFAULT_THRESHOLDS = {
    "interview_threshold": 3.5,
    "reserve_threshold": 3.0,
}


def score_candidate(result: Dict[str, Any], thresholds: Dict[str, float] | None = None) -> Dict[str, Any]:
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    assessments = result.get("assessments", [])
    mandatory_items = [item for item in assessments if item.get("mandatory")]
    preferred_items = [item for item in assessments if not item.get("mandatory")]

    mandatory_total = len(mandatory_items)
    mandatory_pass_count = sum(1 for item in mandatory_items if int(item.get("score", 0)) >= int(item.get("pass_score", 3)))
    meets_all_mandatory = mandatory_total > 0 and mandatory_pass_count == mandatory_total

    critical_gaps = [
        item.get("criterion_text", item.get("criterion_id", ""))
        for item in mandatory_items
        if int(item.get("score", 0)) < int(item.get("pass_score", 3))
    ]
    quality_flags = quality_checks(assessments)
    weighted_score = weighted_average(assessments)
    mandatory_average = average_score(mandatory_items)
    preferred_average = average_score(preferred_items)

    if not meets_all_mandatory:
        recommendation = "Reject"
    elif weighted_score >= thresholds["interview_threshold"]:
        recommendation = "Interview"
    elif weighted_score >= thresholds["reserve_threshold"]:
        recommendation = "Reserve"
    else:
        recommendation = "Reserve"

    summary = {
        "recommendation": recommendation,
        "meets_all_mandatory": meets_all_mandatory,
        "mandatory_pass_count": mandatory_pass_count,
        "mandatory_total": mandatory_total,
        "mandatory_average": round(mandatory_average, 2),
        "preferred_average": round(preferred_average, 2),
        "weighted_score": round(weighted_score, 2),
        "critical_gaps": critical_gaps,
        "quality_flags": quality_flags,
    }
    scored = dict(result)
    scored["summary"] = summary
    return scored


def weighted_average(items: List[Dict[str, Any]]) -> float:
    total_weight = 0.0
    total = 0.0
    for item in items:
        weight = max(float(item.get("weight", 1.0) or 1.0), 0.1)
        total += int(item.get("score", 0)) * weight
        total_weight += weight
    return total / total_weight if total_weight else 0.0


def average_score(items: List[Dict[str, Any]]) -> float:
    return mean([int(item.get("score", 0)) for item in items]) if items else 0.0


def quality_checks(assessments: List[Dict[str, Any]]) -> List[str]:
    flags: List[str] = []
    for item in assessments:
        criterion_id = item.get("criterion_id", "")
        evidence = str(item.get("evidence", "") or "").strip().lower()
        score = int(item.get("score", 0))
        confidence = str(item.get("confidence", "") or "").lower()
        if score >= 3 and (not evidence or evidence == "not evidenced"):
            flags.append(f"{criterion_id}: high score without evidence")
        if score >= 4 and confidence == "low":
            flags.append(f"{criterion_id}: high score with low confidence")
        if score <= 1 and evidence and evidence != "not evidenced":
            flags.append(f"{criterion_id}: low score despite cited evidence")
    return flags
