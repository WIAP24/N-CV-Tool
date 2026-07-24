from __future__ import annotations

from typing import Any, Dict, List


def compare_scored_results(
    primary: Dict[str, Any],
    comparison: Dict[str, Any],
    primary_model: str,
    comparison_model: str,
) -> Dict[str, Any]:
    primary_summary = primary.get("summary", {})
    comparison_summary = comparison.get("summary", {})
    primary_by_id = {item.get("criterion_id"): item for item in primary.get("assessments", [])}
    comparison_by_id = {item.get("criterion_id"): item for item in comparison.get("assessments", [])}

    criterion_differences: List[Dict[str, Any]] = []
    max_abs_delta = 0
    pass_fail_flips = 0
    for criterion_id, primary_item in primary_by_id.items():
        comparison_item = comparison_by_id.get(criterion_id)
        if not comparison_item:
            continue
        primary_score = int(primary_item.get("score", 0))
        comparison_score = int(comparison_item.get("score", 0))
        delta = comparison_score - primary_score
        max_abs_delta = max(max_abs_delta, abs(delta))
        pass_score = int(primary_item.get("pass_score", 3))
        primary_pass = primary_score >= pass_score
        comparison_pass = comparison_score >= pass_score
        if primary_pass != comparison_pass:
            pass_fail_flips += 1
        if abs(delta) >= 2 or primary_pass != comparison_pass:
            criterion_differences.append(
                {
                    "candidate_file": primary.get("candidate_file", ""),
                    "candidate_name": primary.get("candidate_name", "Unknown"),
                    "criterion_id": criterion_id,
                    "criterion_text": primary_item.get("criterion_text", ""),
                    "primary_score": primary_score,
                    "comparison_score": comparison_score,
                    "score_delta": delta,
                    "pass_fail_flip": primary_pass != comparison_pass,
                    "primary_evidence": primary_item.get("evidence", ""),
                    "comparison_evidence": comparison_item.get("evidence", ""),
                }
            )

    recommendation_changed = primary_summary.get("recommendation") != comparison_summary.get("recommendation")
    weighted_delta = round(float(comparison_summary.get("weighted_score", 0) or 0) - float(primary_summary.get("weighted_score", 0) or 0), 2)
    return {
        "candidate_file": primary.get("candidate_file", ""),
        "candidate_name": primary.get("candidate_name", "Unknown"),
        "primary_model": primary_model,
        "comparison_model": comparison_model,
        "primary_recommendation": primary_summary.get("recommendation", ""),
        "comparison_recommendation": comparison_summary.get("recommendation", ""),
        "recommendation_changed": recommendation_changed,
        "primary_weighted_score": primary_summary.get("weighted_score", 0),
        "comparison_weighted_score": comparison_summary.get("weighted_score", 0),
        "weighted_score_delta": weighted_delta,
        "criteria_checked": len(primary_by_id),
        "criteria_with_notable_differences": len(criterion_differences),
        "pass_fail_flips": pass_fail_flips,
        "max_abs_score_delta": max_abs_delta,
        "criterion_differences": criterion_differences,
    }


def flatten_evaluations(evaluations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for evaluation in evaluations:
        rows.append({key: value for key, value in evaluation.items() if key != "criterion_differences"})
    return rows


def flatten_criterion_differences(evaluations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for evaluation in evaluations:
        for difference in evaluation.get("criterion_differences", []):
            row = dict(difference)
            row["primary_model"] = evaluation.get("primary_model", "")
            row["comparison_model"] = evaluation.get("comparison_model", "")
            rows.append(row)
    return rows
