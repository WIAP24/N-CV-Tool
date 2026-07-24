from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List


DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_COMPARISON_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "low"
PROMPT_VERSION = "cv-screening-2026-07-24-v2"

REASONING_EFFORTS: List[str] = ["none", "low", "medium", "high", "xhigh", "max"]
MAX_CV_INPUT_CHARS = 120_000
MAX_CV_INPUT_TOKENS = 30_000
DEFAULT_FIXED_PROMPT_TOKENS = 450
MIN_OUTPUT_TOKENS_PER_CV = 600
OUTPUT_TOKENS_PER_CRITERION = 90
PRICING_SOURCE_LABEL = "OpenAI API model/pricing docs, checked 2026-07-24"

# USD per 1M text tokens. Cached input is API prompt caching, not the app's local result cache.
MODEL_CATALOG: Dict[str, Dict[str, Any]] = {
    "gpt-5.6-terra": {
        "label": "GPT-5.6 Terra",
        "role": "Balanced quality and cost",
        "input": 2.50,
        "cached_input": 0.25,
        "output": 15.00,
    },
    "gpt-5.6-sol": {
        "label": "GPT-5.6 Sol",
        "role": "Highest quality / complex review",
        "input": 5.00,
        "cached_input": 0.50,
        "output": 30.00,
    },
    "gpt-5.6-luna": {
        "label": "GPT-5.6 Luna",
        "role": "Lowest cost / high volume",
        "input": 1.00,
        "cached_input": 0.10,
        "output": 6.00,
    },
    "gpt-5.6": {
        "label": "GPT-5.6 alias",
        "role": "Alias that routes to GPT-5.6 Sol",
        "input": 5.00,
        "cached_input": 0.50,
        "output": 30.00,
    },
    "gpt-4o-mini": {
        "label": "GPT-4o mini",
        "role": "Low-cost focused tasks",
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    },
}

MODEL_CHOICES: List[str] = list(MODEL_CATALOG.keys())
MODEL_PRICING_PER_MILLION: Dict[str, Dict[str, float]] = {
    model: {
        "input": float(details["input"]),
        "cached_input": float(details["cached_input"]),
        "output": float(details["output"]),
    }
    for model, details in MODEL_CATALOG.items()
}


def pricing_for_model(model: str) -> Dict[str, float] | None:
    return MODEL_PRICING_PER_MILLION.get((model or "").strip())


def model_label(model: str) -> str:
    details = MODEL_CATALOG.get((model or "").strip())
    return str(details.get("label")) if details else (model or "Unknown model")


def model_role(model: str) -> str:
    details = MODEL_CATALOG.get((model or "").strip())
    return str(details.get("role", "")) if details else "Pricing unavailable for custom/unknown model IDs."


def model_rate_card(model: str) -> Dict[str, Any]:
    model = (model or "").strip()
    pricing = pricing_for_model(model)
    return {
        "model": model,
        "label": model_label(model),
        "role": model_role(model),
        "input_usd_per_1m": pricing.get("input") if pricing else None,
        "cached_input_usd_per_1m": pricing.get("cached_input") if pricing else None,
        "output_usd_per_1m": pricing.get("output") if pricing else None,
        "pricing_source": PRICING_SOURCE_LABEL if pricing else "Not available in local pricing table",
    }


def estimate_tokens(text: str) -> int:
    # Simple planning estimate: English prose is often around 4 chars/token.
    return max(1, int(len(text or "") / 4))


def estimate_file_input_tokens(file_name: str, size_bytes: int) -> int:
    """Pre-run estimate before local extraction; intentionally rough and capped like the prompt."""
    ext = Path(file_name).suffix.lower()
    if ext in {".txt", ".md"}:
        estimated_chars = min(size_bytes, MAX_CV_INPUT_CHARS)
    elif ext == ".docx":
        estimated_chars = min(size_bytes * 2, MAX_CV_INPUT_CHARS)
    else:
        estimated_chars = min(size_bytes, MAX_CV_INPUT_CHARS)
    return max(1, min(MAX_CV_INPUT_TOKENS, int(estimated_chars / 4)))


def estimate_output_tokens_per_cv(criteria_count: int) -> int:
    return max(MIN_OUTPUT_TOKENS_PER_CV, DEFAULT_FIXED_PROMPT_TOKENS + max(0, criteria_count) * OUTPUT_TOKENS_PER_CRITERION)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> float | None:
    pricing = pricing_for_model(model)
    if not pricing:
        return None
    cached_input_tokens = max(0, min(int(cached_input_tokens or 0), int(input_tokens or 0)))
    uncached_input_tokens = max(0, int(input_tokens or 0) - cached_input_tokens)
    cost = (
        uncached_input_tokens / 1_000_000 * pricing["input"]
        + cached_input_tokens / 1_000_000 * pricing.get("cached_input", pricing["input"])
        + int(output_tokens or 0) / 1_000_000 * pricing["output"]
    )
    return round(cost, 6)


def estimate_screening_run_cost(
    file_token_estimates: Iterable[Dict[str, Any]],
    criteria_tokens: int,
    criteria_count: int,
    primary_model: str,
    comparison_model: str | None = None,
    enable_model_comparison: bool = False,
) -> Dict[str, Any]:
    file_rows = list(file_token_estimates)
    output_tokens_per_cv = estimate_output_tokens_per_cv(criteria_count)
    stages = [{"stage": "primary", "model": (primary_model or "").strip()}]
    comparison_model = (comparison_model or "").strip()
    if enable_model_comparison and comparison_model and comparison_model != (primary_model or "").strip():
        stages.append({"stage": "comparison", "model": comparison_model})

    rows: List[Dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    has_unknown_cost = False
    total_calls = 0

    for stage in stages:
        model = stage["model"]
        pricing = pricing_for_model(model)
        stage_input_tokens = sum(int(row.get("estimated_cv_input_tokens") or 0) + int(criteria_tokens or 0) for row in file_rows)
        stage_output_tokens = output_tokens_per_cv * len(file_rows)
        stage_calls = len(file_rows)
        stage_cost = estimate_cost_usd(model, stage_input_tokens, stage_output_tokens)
        if stage_cost is None:
            has_unknown_cost = True
        else:
            total_cost += stage_cost
        total_input_tokens += stage_input_tokens
        total_output_tokens += stage_output_tokens
        total_calls += stage_calls
        rows.append(
            {
                "stage": stage["stage"],
                "model": model,
                "model_label": model_label(model),
                "files": len(file_rows),
                "estimated_calls": stage_calls,
                "estimated_input_tokens": stage_input_tokens,
                "estimated_output_tokens": stage_output_tokens,
                "input_usd_per_1m": pricing.get("input") if pricing else None,
                "cached_input_usd_per_1m": pricing.get("cached_input") if pricing else None,
                "output_usd_per_1m": pricing.get("output") if pricing else None,
                "estimated_uncached_cost_usd": stage_cost,
            }
        )

    return {
        "currency": "USD",
        "pricing_source": PRICING_SOURCE_LABEL,
        "estimate_basis": "Pre-run estimate before app result cache; API prompt caching may reduce input cost when applicable.",
        "estimated_files": len(file_rows),
        "estimated_model_calls": total_calls,
        "estimated_input_tokens": total_input_tokens,
        "estimated_output_tokens": total_output_tokens,
        "estimated_total_tokens": total_input_tokens + total_output_tokens,
        "estimated_uncached_cost_usd": None if has_unknown_cost else round(total_cost, 6),
        "output_tokens_per_cv_assumption": output_tokens_per_cv,
        "criteria_tokens_per_call_assumption": int(criteria_tokens or 0),
        "rows": rows,
        "file_estimates": file_rows,
    }


def cost_preview_to_summary(preview: Dict[str, Any] | None) -> Dict[str, Any]:
    if not preview:
        return {}
    return {
        "pre_run_estimated_files": preview.get("estimated_files", 0),
        "pre_run_estimated_model_calls": preview.get("estimated_model_calls", 0),
        "pre_run_estimated_input_tokens": preview.get("estimated_input_tokens", 0),
        "pre_run_estimated_output_tokens": preview.get("estimated_output_tokens", 0),
        "pre_run_estimated_total_tokens": preview.get("estimated_total_tokens", 0),
        "pre_run_estimated_uncached_cost_usd": preview.get("estimated_uncached_cost_usd"),
        "pre_run_cost_estimate_basis": preview.get("estimate_basis", ""),
        "pricing_source": preview.get("pricing_source", PRICING_SOURCE_LABEL),
    }


def summarize_cost_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    calls = len(records)
    cached_calls = sum(1 for row in records if row.get("cached"))
    input_tokens = sum(int(row.get("input_tokens") or 0) for row in records)
    cached_input_tokens = sum(int(row.get("cached_input_tokens") or 0) for row in records)
    output_tokens = sum(int(row.get("output_tokens") or 0) for row in records)
    billed_costs = [row.get("cost_usd") for row in records if isinstance(row.get("cost_usd"), (int, float))]
    uncached_costs = [row.get("uncached_estimate_usd") for row in records if isinstance(row.get("uncached_estimate_usd"), (int, float))]
    return {
        "model_calls": calls,
        "cached_calls": cached_calls,
        "live_model_calls": calls - cached_calls,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "estimated_billed_cost_usd": round(sum(billed_costs), 6),
        "estimated_uncached_cost_usd": round(sum(uncached_costs), 6),
    }


def format_usd(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "Cost unavailable"
    if value == 0:
        return "$0.00"
    if abs(float(value)) < 0.01:
        return f"${float(value):.4f}"
    return f"${float(value):,.2f}"
