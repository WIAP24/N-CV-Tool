from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from niras_cv_screener.criteria import criteria_to_rows, parse_criteria_text, rows_to_criteria
from niras_cv_screener.evaluation import compare_scored_results
from niras_cv_screener.excel import write_workbook
from niras_cv_screener.model_config import estimate_cost_usd, estimate_screening_run_cost
from niras_cv_screener.review import build_calibration_report, build_review_queue
from niras_cv_screener.scoring import score_candidate


class CriteriaParsingTests(unittest.TestCase):
    def test_parse_sections_weights_and_pass_scores(self) -> None:
        parsed = parse_criteria_text(
            """
            MEAL Lead -
            Minimum Requirements
            - Master's degree [weight=2] [pass=4]
            - Five years experience

            Preferred Requirements
            - Power BI experience
            """
        )
        rows = criteria_to_rows(parsed)
        self.assertEqual(parsed["role_title"], "MEAL Lead")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["id"], "min_1")
        self.assertTrue(rows[0]["mandatory"])
        self.assertEqual(rows[0]["weight"], 2.0)
        self.assertEqual(rows[0]["pass_score"], 4)
        self.assertEqual(rows[2]["id"], "pref_1")
        self.assertFalse(rows[2]["mandatory"])

    def test_rows_to_criteria_validates_duplicate_ids(self) -> None:
        with self.assertRaises(ValueError):
            rows_to_criteria(
                [
                    {"section": "Minimum Requirements", "id": "min_1", "text": "A", "mandatory": True},
                    {"section": "Minimum Requirements", "id": "min_1", "text": "B", "mandatory": True},
                ]
            )


class ScoringTests(unittest.TestCase):
    def test_failed_mandatory_rejects_candidate(self) -> None:
        result = make_result("Example Candidate", "example_candidate.pdf", min_score=2, pref_score=5)
        scored = score_candidate(result)
        self.assertEqual(scored["summary"]["recommendation"], "Reject")
        self.assertFalse(scored["summary"]["meets_all_mandatory"])

    def test_all_mandatory_passes_can_interview(self) -> None:
        result = make_result("Example Candidate", "example_candidate.pdf", min_score=4, pref_score=4)
        scored = score_candidate(result)
        self.assertEqual(scored["summary"]["recommendation"], "Interview")
        self.assertEqual(scored["summary"]["mandatory_pass_count"], 1)


class CostEstimateTests(unittest.TestCase):
    def test_estimate_cost_uses_cached_input_pricing(self) -> None:
        self.assertEqual(estimate_cost_usd("gpt-5.6-luna", 1_000_000, 1_000_000), 7.0)
        self.assertEqual(estimate_cost_usd("gpt-5.6-luna", 1_000_000, 1_000_000, cached_input_tokens=500_000), 6.55)

    def test_pre_run_preview_includes_comparison_model_cost(self) -> None:
        preview = estimate_screening_run_cost(
            [
                {"file": "a.pdf", "estimated_cv_input_tokens": 1000},
                {"file": "b.pdf", "estimated_cv_input_tokens": 2000},
            ],
            criteria_tokens=500,
            criteria_count=3,
            primary_model="gpt-5.6-luna",
            comparison_model="gpt-5.6-terra",
            enable_model_comparison=True,
        )
        self.assertEqual(preview["estimated_files"], 2)
        self.assertEqual(preview["estimated_model_calls"], 4)
        self.assertEqual(len(preview["rows"]), 2)
        self.assertIsNotNone(preview["estimated_uncached_cost_usd"])
        self.assertGreater(preview["estimated_uncached_cost_usd"], 0)


class EvaluationAndReviewTests(unittest.TestCase):
    def test_model_comparison_flags_recommendation_change(self) -> None:
        primary = score_candidate(make_result("Example Candidate", "example_candidate.pdf", min_score=2, pref_score=5))
        comparison = score_candidate(make_result("Example Candidate", "example_candidate.pdf", min_score=4, pref_score=5))
        evaluation = compare_scored_results(primary, comparison, "primary", "comparison")
        self.assertTrue(evaluation["recommendation_changed"])
        self.assertGreaterEqual(evaluation["pass_fail_flips"], 1)

    def test_calibration_report_flags_spread(self) -> None:
        results = [
            score_candidate(make_result("A", "a.pdf", min_score=1, pref_score=3)),
            score_candidate(make_result("B", "b.pdf", min_score=5, pref_score=3)),
        ]
        rows = build_calibration_report(results)
        degree_row = next(row for row in rows if row["criterion_id"] == "min_1")
        self.assertIn("Large score spread", degree_row["flags"])

    def test_review_queue_includes_mandatory_gap(self) -> None:
        results = [score_candidate(make_result("A", "a.pdf", min_score=1, pref_score=3))]
        queue = build_review_queue(results, build_calibration_report(results), [], [])
        self.assertTrue(any(row["area"] == "Mandatory gap" for row in queue))

    def test_workbook_writes_review_sheets(self) -> None:
        criteria = sample_criteria()
        results = [score_candidate(make_result("Example Candidate", "example_candidate.pdf", min_score=4, pref_score=4))]
        calibration = build_calibration_report(results)
        review = build_review_queue(results, calibration, [], [])
        preview = estimate_screening_run_cost(
            [{"file": "example_candidate.pdf", "estimated_cv_input_tokens": 1000}],
            criteria_tokens=500,
            criteria_count=2,
            primary_model="gpt-5.6-luna",
        )
        out = Path(tempfile.gettempdir()) / "niras_cv_screener_workbook_test.xlsx"
        write_workbook(
            out,
            criteria,
            results,
            errors=[],
            extraction_warnings=[],
            run_settings={"model": "test"},
            calibration_rows=calibration,
            review_queue=review,
            model_evaluations=[],
            model_evaluation_details=[],
            cost_records=[{"candidate_file": "example_candidate.pdf", "stage": "primary", "model": "test", "cached": False, "input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5, "total_tokens": 15, "token_source": "estimated", "cost_usd": None, "uncached_estimate_usd": None}],
            cost_summary={"model_calls": 1},
            cost_preview=preview,
        )
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)


def sample_criteria() -> dict:
    return {
        "role_title": "Test Role",
        "minimum_pass_score": 3,
        "sections": [
            {"name": "Minimum Requirements", "criteria": [{"id": "min_1", "text": "Degree", "mandatory": True, "weight": 1.0, "pass_score": 3}]},
            {"name": "Preferred Requirements", "criteria": [{"id": "pref_1", "text": "Power BI", "mandatory": False, "weight": 1.0, "pass_score": 3}]},
        ],
    }


def make_result(name: str, file_name: str, min_score: int, pref_score: int) -> dict:
    return {
        "candidate_name": name,
        "candidate_file": file_name,
        "candidate_id": file_name,
        "assessments": [
            {"criterion_id": "min_1", "criterion_text": "Degree", "section": "Minimum Requirements", "mandatory": True, "score": min_score, "pass_score": 3, "weight": 1, "evidence": "MSc", "source_ref": "page 1", "confidence": "high"},
            {"criterion_id": "pref_1", "criterion_text": "Power BI", "section": "Preferred Requirements", "mandatory": False, "score": pref_score, "pass_score": 3, "weight": 1, "evidence": "Power BI", "source_ref": "page 2", "confidence": "high"},
        ],
    }


if __name__ == "__main__":
    unittest.main()

