from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List

from .compliance import scan_compliance_flags
from .evaluation import compare_scored_results, flatten_criterion_differences, flatten_evaluations
from .excel import write_workbook
from .extraction import ExtractionResult, extract_from_bytes, file_sha256, safe_stem
from .llm import screen_cv_with_metadata
from .model_config import PROMPT_VERSION, cost_preview_to_summary, estimate_cost_usd, summarize_cost_records
from .review import build_calibration_report, build_review_queue
from .scoring import score_candidate


ProgressCallback = Callable[[int, int, str], None]


def process_paths(
    cv_paths: List[Path],
    criteria_json: Dict[str, Any],
    api_key: str,
    model: str,
    output_root: Path,
    thresholds: Dict[str, float] | None = None,
    progress_callback: ProgressCallback | None = None,
    comparison_model: str | None = None,
    reasoning_effort: str = "low",
    comparison_reasoning_effort: str = "low",
    enable_model_comparison: bool = False,
    use_ocr: bool = False,
    use_result_cache: bool = True,
    cost_preview: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if not cv_paths:
        raise ValueError("No CV files supplied.")
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    outputs_dir = output_root / f"outputs_{timestamp}"
    raw_dir = outputs_dir / "raw_results"
    comparison_dir = outputs_dir / "comparison_results"
    text_dir = outputs_dir / "extracted_text"
    cache_dir = output_root / ".cv_screener_cache"
    model_cache_dir = cache_dir / "model_results"
    raw_dir.mkdir(parents=True, exist_ok=True)
    comparison_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    model_cache_dir.mkdir(parents=True, exist_ok=True)

    criteria_path = outputs_dir / "criteria_used.json"
    criteria_path.write_text(json.dumps(criteria_json, ensure_ascii=False, indent=2), encoding="utf-8")

    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    extraction_warnings: List[Dict[str, str]] = []
    model_evaluations: List[Dict[str, Any]] = []
    cost_records: List[Dict[str, Any]] = []

    criteria_hash = criteria_digest(criteria_json)
    total = len(cv_paths)
    for index, path in enumerate(cv_paths, start=1):
        try:
            extraction = load_or_extract(path, cache_dir, use_ocr=use_ocr)
            text_path = text_dir / f"{safe_stem(path.name)}.txt"
            text_path.write_text(extraction.text, encoding="utf-8")
            for warning in extraction.warnings:
                extraction_warnings.append({"file": path.name, "warning": warning})
            if extraction.char_count < 80:
                raise ValueError("Too little extractable text to screen reliably.")

            primary_payload = load_or_screen(
                criteria_json=criteria_json,
                criteria_hash=criteria_hash,
                extraction=extraction,
                api_key=api_key,
                model=model,
                reasoning_effort=reasoning_effort,
                cache_dir=model_cache_dir,
                use_result_cache=use_result_cache,
                stage="primary",
            )
            cost_records.append(cost_record(path.name, "primary", model, primary_payload))
            scored = score_candidate(primary_payload["result"], thresholds=thresholds)
            scored["model"] = model
            scored["reasoning_effort"] = reasoning_effort
            scored["prompt_version"] = PROMPT_VERSION
            scored["extraction"] = {
                "sha256": extraction.sha256,
                "char_count": extraction.char_count,
                "warnings": extraction.warnings,
                "used_ocr": extraction.used_ocr,
            }
            scored["compliance_flags"] = scan_compliance_flags(extraction.text, path.name)

            if enable_model_comparison and comparison_model and comparison_model != model:
                comparison_payload = load_or_screen(
                    criteria_json=criteria_json,
                    criteria_hash=criteria_hash,
                    extraction=extraction,
                    api_key=api_key,
                    model=comparison_model,
                    reasoning_effort=comparison_reasoning_effort,
                    cache_dir=model_cache_dir,
                    use_result_cache=use_result_cache,
                    stage="comparison",
                )
                cost_records.append(cost_record(path.name, "comparison", comparison_model, comparison_payload))
                comparison_scored = score_candidate(comparison_payload["result"], thresholds=thresholds)
                comparison_scored["model"] = comparison_model
                comparison_scored["reasoning_effort"] = comparison_reasoning_effort
                evaluation = compare_scored_results(scored, comparison_scored, model, comparison_model)
                model_evaluations.append(evaluation)
                scored["model_comparison"] = evaluation
                (comparison_dir / f"{safe_stem(path.name)}__{safe_stem(comparison_model)}.json").write_text(
                    json.dumps(comparison_scored, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            results.append(scored)
            (raw_dir / f"{safe_stem(path.name)}.json").write_text(
                json.dumps(scored, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            errors.append({"file": path.name, "error": str(exc)})
        finally:
            if progress_callback:
                progress_callback(index, total, path.name)

    if not results:
        raise RuntimeError("No CVs were processed successfully. Check skipped files and extraction warnings.")

    calibration_rows = build_calibration_report(results)
    review_queue = build_review_queue(results, calibration_rows, model_evaluations, extraction_warnings)
    actual_cost_summary = summarize_cost_records(cost_records)
    cost_summary = {**actual_cost_summary, **cost_preview_to_summary(cost_preview)}

    run_settings = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "comparison_enabled": enable_model_comparison,
        "comparison_model": comparison_model or "",
        "comparison_reasoning_effort": comparison_reasoning_effort,
        "files_total": total,
        "processed": len(results),
        "skipped": len(errors),
        "interview_threshold": (thresholds or {}).get("interview_threshold", 3.5),
        "reserve_threshold": (thresholds or {}).get("reserve_threshold", 3.0),
        "use_ocr": use_ocr,
        "use_result_cache": use_result_cache,
        "extraction_cache": str(cache_dir),
        **cost_summary,
    }

    excel_path = outputs_dir / "screening_results.xlsx"
    write_workbook(
        excel_path,
        criteria_json=criteria_json,
        results=results,
        errors=errors,
        extraction_warnings=extraction_warnings,
        run_settings=run_settings,
        calibration_rows=calibration_rows,
        review_queue=review_queue,
        model_evaluations=flatten_evaluations(model_evaluations),
        model_evaluation_details=flatten_criterion_differences(model_evaluations),
        cost_records=cost_records,
        cost_summary=cost_summary,
        cost_preview=cost_preview,
    )

    manifest = {
        **run_settings,
        "outputs_dir": str(outputs_dir),
        "excel_path": str(excel_path),
        "criteria_path": str(criteria_path),
        "review_queue_count": len(review_queue),
        "calibration_flag_count": sum(1 for row in calibration_rows if row.get("flags")),
        "model_evaluation_count": len(model_evaluations),
    }
    write_json(outputs_dir / "run_manifest.json", manifest)
    write_json(outputs_dir / "results.json", results)
    write_json(outputs_dir / "review_queue.json", review_queue)
    write_json(outputs_dir / "calibration_report.json", calibration_rows)
    write_json(outputs_dir / "model_evaluation.json", model_evaluations)
    write_json(outputs_dir / "cost_records.json", cost_records)
    write_json(outputs_dir / "cost_preview.json", cost_preview or {})

    return {
        "outputs_dir": str(outputs_dir),
        "excel_path": str(excel_path),
        "criteria_snapshot_path": str(criteria_path),
        "processed": len(results),
        "skipped": len(errors),
        "files_total": total,
        "results": results,
        "errors": errors,
        "extraction_warnings": extraction_warnings,
        "review_queue": review_queue,
        "calibration_rows": calibration_rows,
        "model_evaluations": model_evaluations,
        "cost_records": cost_records,
        "cost_summary": cost_summary,
        "cost_preview": cost_preview or {},
    }


def load_or_extract(path: Path, cache_dir: Path, use_ocr: bool = False) -> ExtractionResult:
    data = path.read_bytes()
    digest = file_sha256(data)
    mode = "ocr" if use_ocr else "text"
    cache_path = cache_dir / f"{digest}_{mode}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return ExtractionResult(
            file_name=path.name,
            sha256=digest,
            text=cached.get("text", ""),
            blocks=cached.get("blocks", []),
            warnings=cached.get("warnings", []),
            used_ocr=bool(cached.get("used_ocr", False)),
        )

    extraction = extract_from_bytes(path.name, data, use_ocr=use_ocr)
    cache_path.write_text(
        json.dumps(
            {
                "file_name": path.name,
                "sha256": extraction.sha256,
                "text": extraction.text,
                "blocks": extraction.blocks,
                "warnings": extraction.warnings,
                "used_ocr": extraction.used_ocr,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return extraction


def load_or_screen(
    criteria_json: Dict[str, Any],
    criteria_hash: str,
    extraction: ExtractionResult,
    api_key: str,
    model: str,
    reasoning_effort: str,
    cache_dir: Path,
    use_result_cache: bool,
    stage: str,
) -> Dict[str, Any]:
    key = model_cache_key(extraction.sha256, criteria_hash, model, reasoning_effort)
    cache_path = cache_dir / f"{key}.json"
    if use_result_cache and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        cached["cached"] = True
        return cached

    payload = screen_cv_with_metadata(
        criteria_json=criteria_json,
        cv_text=extraction.text,
        file_name=extraction.file_name,
        api_key=api_key,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    payload["cached"] = False
    payload["stage"] = stage
    payload["cache_key"] = key
    if use_result_cache:
        write_json(cache_path, payload)
    return payload


def cost_record(file_name: str, stage: str, model: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    usage = payload.get("usage", {})
    input_tokens = int(usage.get("input_tokens") or 0)
    cached_input_tokens = int(usage.get("cached_input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    uncached_cost = usage.get("estimated_cost_usd")
    if not isinstance(uncached_cost, (int, float)):
        uncached_cost = estimate_cost_usd(model, input_tokens, output_tokens, cached_input_tokens)
    cached = bool(payload.get("cached", False))
    return {
        "candidate_file": file_name,
        "stage": stage,
        "model": model,
        "cached": cached,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
        "token_source": usage.get("token_source", "api"),
        "cost_usd": 0.0 if cached and isinstance(uncached_cost, (int, float)) else uncached_cost,
        "uncached_estimate_usd": uncached_cost,
    }


def criteria_digest(criteria_json: Dict[str, Any]) -> str:
    raw = json.dumps(criteria_json, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def model_cache_key(file_hash: str, criteria_hash: str, model: str, reasoning_effort: str) -> str:
    raw = json.dumps(
        {
            "file_hash": file_hash,
            "criteria_hash": criteria_hash,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "prompt_version": PROMPT_VERSION,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
