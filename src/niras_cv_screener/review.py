from __future__ import annotations

from statistics import mean, pstdev
from typing import Any, Dict, List


SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def build_calibration_report(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        for item in result.get("assessments", []):
            record = dict(item)
            record["candidate_name"] = result.get("candidate_name", "Unknown")
            record["candidate_file"] = result.get("candidate_file", "")
            grouped.setdefault(item.get("criterion_id", ""), []).append(record)

    rows: List[Dict[str, Any]] = []
    for criterion_id, items in grouped.items():
        if not criterion_id:
            continue
        scores = [int(item.get("score", 0)) for item in items]
        pass_score = int(items[0].get("pass_score", 3))
        passed = [score >= pass_score for score in scores]
        spread = max(scores) - min(scores) if scores else 0
        stdev = pstdev(scores) if len(scores) > 1 else 0.0
        flags: List[str] = []
        if spread >= 3:
            flags.append("Large score spread")
        if len(set(passed)) > 1:
            flags.append("Mixed pass/fail outcomes")
        if stdev >= 1.25 and len(scores) >= 3:
            flags.append("High score variation")

        high_item = max(items, key=lambda item: int(item.get("score", 0)))
        low_item = min(items, key=lambda item: int(item.get("score", 0)))
        rows.append(
            {
                "criterion_id": criterion_id,
                "criterion_text": items[0].get("criterion_text", ""),
                "section": items[0].get("section", ""),
                "mandatory": bool(items[0].get("mandatory", False)),
                "pass_score": pass_score,
                "candidate_count": len(items),
                "average_score": round(mean(scores), 2) if scores else 0,
                "min_score": min(scores) if scores else 0,
                "max_score": max(scores) if scores else 0,
                "score_spread": spread,
                "score_stdev": round(stdev, 2),
                "pass_rate": round(sum(1 for ok in passed if ok) / len(passed), 2) if passed else 0,
                "flags": "; ".join(flags),
                "highest_candidate": high_item.get("candidate_name", ""),
                "highest_evidence": high_item.get("evidence", ""),
                "lowest_candidate": low_item.get("candidate_name", ""),
                "lowest_evidence": low_item.get("evidence", ""),
            }
        )
    return sorted(rows, key=lambda row: (not bool(row.get("flags")), -int(row.get("score_spread", 0)), row.get("criterion_id", "")))


def build_review_queue(
    results: List[Dict[str, Any]],
    calibration_rows: List[Dict[str, Any]],
    model_evaluations: List[Dict[str, Any]],
    extraction_warnings: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    queue: List[Dict[str, Any]] = []

    for result in results:
        candidate_name = result.get("candidate_name", "Unknown")
        candidate_file = result.get("candidate_file", "")
        summary = result.get("summary", {})
        for gap in summary.get("critical_gaps", []):
            queue.append(review_row("High", candidate_name, candidate_file, "Mandatory gap", gap, "Check whether the CV truly lacks this mandatory evidence.", ""))
        for flag in summary.get("quality_flags", []):
            severity = "High" if "high score without evidence" in flag.lower() else "Medium"
            queue.append(review_row(severity, candidate_name, candidate_file, "Quality flag", flag, "Review the cited evidence and adjust if needed.", ""))
        for flag in result.get("compliance_flags", []):
            queue.append(review_row("Medium", candidate_name, candidate_file, "Compliance", flag.get("category", "Sensitive information"), flag.get("reason", "Ignore protected characteristics."), flag.get("source_ref", "")))
        for item in result.get("assessments", []):
            score = int(item.get("score", 0))
            pass_score = int(item.get("pass_score", 3))
            criterion_id = item.get("criterion_id", "")
            if item.get("mandatory") and abs(score - pass_score) <= 1:
                queue.append(review_row("Medium", candidate_name, candidate_file, "Borderline mandatory score", item.get("criterion_text", ""), "Confirm whether the score should pass or fail.", criterion_id))
            if score >= pass_score and item.get("confidence") == "low":
                queue.append(review_row("Medium", candidate_name, candidate_file, "Low confidence pass", item.get("criterion_text", ""), "Check evidence because the model gave a passing score with low confidence.", criterion_id))
            if score >= 3 and not str(item.get("source_ref", "")).strip():
                queue.append(review_row("Low", candidate_name, candidate_file, "Missing source reference", item.get("criterion_text", ""), "Find and record the CV location if keeping this score.", criterion_id))

    for warning in extraction_warnings:
        message = warning.get("warning", "")
        severity = "High" if "no extractable" in message.lower() or "too little" in message.lower() else "Low"
        queue.append(review_row(severity, "", warning.get("file", ""), "Extraction", message, "Open the source CV and verify the extracted text is complete.", ""))

    for row in calibration_rows:
        if row.get("flags"):
            severity = "High" if "Large score spread" in row.get("flags", "") else "Medium"
            queue.append(review_row(severity, "All candidates", "", "Calibration", f"{row.get('criterion_id')}: {row.get('flags')}", "Compare highest and lowest evidence for this criterion.", row.get("criterion_id", "")))

    for evaluation in model_evaluations:
        if evaluation.get("recommendation_changed"):
            queue.append(review_row("High", evaluation.get("candidate_name", "Unknown"), evaluation.get("candidate_file", ""), "Model comparison", "Recommendation changed between models", "Review the model comparison sheet before relying on the recommendation.", ""))
        elif int(evaluation.get("max_abs_score_delta", 0) or 0) >= 2:
            queue.append(review_row("Medium", evaluation.get("candidate_name", "Unknown"), evaluation.get("candidate_file", ""), "Model comparison", "One or more criterion scores changed by 2+ points", "Review criterion-level model differences.", ""))

    return sorted(queue, key=lambda row: (SEVERITY_ORDER.get(row.get("severity", "Low"), 9), row.get("candidate_name", ""), row.get("area", "")))


def review_row(severity: str, candidate_name: str, candidate_file: str, area: str, reason: str, suggested_action: str, criterion_id: str) -> Dict[str, Any]:
    return {
        "severity": severity,
        "candidate_name": candidate_name,
        "candidate_file": candidate_file,
        "area": area,
        "criterion_id": criterion_id,
        "reason": reason,
        "suggested_action": suggested_action,
        "reviewer_decision": "",
        "reviewer_notes": "",
    }
