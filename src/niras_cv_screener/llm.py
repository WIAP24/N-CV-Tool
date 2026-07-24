from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from .criteria import criteria_to_rows
from .model_config import PROMPT_VERSION, estimate_cost_usd, estimate_tokens


def assessment_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidate_name": {"type": "string"},
            "candidate_file": {"type": "string"},
            "assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "criterion_id": {"type": "string"},
                        "score": {"type": "integer", "minimum": 0, "maximum": 5},
                        "evidence": {"type": "string"},
                        "source_ref": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "notes": {"type": "string"},
                    },
                    "required": ["criterion_id", "score", "evidence", "source_ref", "confidence", "notes"],
                },
            },
        },
        "required": ["candidate_name", "candidate_file", "assessments"],
    }


def build_prompt(criteria_json: Dict[str, Any], cv_text: str, file_name: str) -> tuple[str, str]:
    criteria_rows = criteria_to_rows(criteria_json)
    system = (
        "You are a careful recruitment screening assistant. "
        "Score the CV strictly against the provided criteria only. "
        "Do not infer missing experience, qualifications, degrees, dates, employers, tools, or languages. "
        "Ignore protected characteristics and sensitive personal information such as age, sex, gender, religion, nationality, marital status, disability, health, or family status unless the criteria lawfully and explicitly require a job-related fact. "
        "Return one assessment for every criterion_id exactly once. "
        "Use score 0 when the CV provides no evidence. "
        "Evidence must be a short CV quote or 'Not evidenced'. "
        "Use the source_ref markers from the CV text when available, such as page 2 or paragraph 5. "
        "Do not provide final recommendation, rank, pass counts, or averages."
    )
    payload = {
        "task": "Assess this CV against each criterion and return JSON matching the schema.",
        "candidate_file": file_name,
        "role_title": criteria_json.get("role_title", ""),
        "rubric": criteria_json.get("scoring_rubric", {}),
        "criteria": criteria_rows,
        "cv_text": (cv_text or "")[:120000],
        "prompt_version": PROMPT_VERSION,
    }
    return system, json.dumps(payload, ensure_ascii=False)


def openai_client(api_key: str | None = None) -> Any:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("The openai package is not installed. Run: pip install -r requirements.txt") from exc
    key = (api_key or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("Missing OpenAI API key.")
    return OpenAI(api_key=key)


def screen_cv(
    criteria_json: Dict[str, Any],
    cv_text: str,
    file_name: str,
    api_key: str,
    model: str,
    reasoning_effort: str = "low",
) -> Dict[str, Any]:
    return screen_cv_with_metadata(criteria_json, cv_text, file_name, api_key, model, reasoning_effort)["result"]


def screen_cv_with_metadata(
    criteria_json: Dict[str, Any],
    cv_text: str,
    file_name: str,
    api_key: str,
    model: str,
    reasoning_effort: str = "low",
) -> Dict[str, Any]:
    client = openai_client(api_key)
    instructions, user_input = build_prompt(criteria_json, cv_text, file_name)
    schema = assessment_schema()

    request: Dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "seed": 12345,
        "instructions": instructions,
        "input": user_input,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "cv_assessment",
                "strict": True,
                "schema": schema,
            }
        },
    }
    if reasoning_effort and reasoning_effort != "none" and str(model).startswith("gpt-5.6"):
        request["reasoning"] = {"effort": reasoning_effort}

    response = create_response(client, request)
    raw_result = json.loads(response.output_text)
    normalised = normalise_model_result(raw_result, criteria_to_rows(criteria_json), file_name)
    usage = extract_usage(response)
    estimated_input_tokens = estimate_tokens(instructions + user_input)
    if not usage.get("input_tokens"):
        usage["input_tokens"] = estimated_input_tokens
        usage["token_source"] = "estimated"
    if not usage.get("output_tokens"):
        usage["output_tokens"] = estimate_tokens(response.output_text or "")
        usage["token_source"] = usage.get("token_source", "estimated")
    usage.setdefault("cached_input_tokens", 0)
    usage.setdefault("token_source", "api")
    usage["estimated_input_tokens"] = estimated_input_tokens
    usage["estimated_cost_usd"] = estimate_cost_usd(
        model,
        int(usage.get("input_tokens") or 0),
        int(usage.get("output_tokens") or 0),
        int(usage.get("cached_input_tokens") or 0),
    )
    return {"result": normalised, "usage": usage, "model": model, "prompt_version": PROMPT_VERSION}


def create_response(client: Any, request: Dict[str, Any]) -> Any:
    variants: List[Dict[str, Any]] = [dict(request)]
    for drop_key in ("seed", "temperature", "reasoning"):
        if drop_key in variants[-1]:
            reduced = dict(variants[-1])
            reduced.pop(drop_key, None)
            variants.append(reduced)

    last_error: Exception | None = None
    for variant in variants:
        try:
            return client.responses.create(**variant)
        except TypeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            message = str(exc).lower()
            if any(token in message for token in ("seed", "temperature", "reasoning")):
                last_error = exc
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("OpenAI request failed before a response was returned.")


def extract_usage(response: Any) -> Dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if hasattr(usage, "model_dump"):
        data = usage.model_dump()
    elif isinstance(usage, dict):
        data = usage
    else:
        data = {name: getattr(usage, name) for name in dir(usage) if not name.startswith("_")}
    input_tokens = data.get("input_tokens") or data.get("prompt_tokens") or 0
    output_tokens = data.get("output_tokens") or data.get("completion_tokens") or 0
    total_tokens = data.get("total_tokens") or int(input_tokens or 0) + int(output_tokens or 0)
    details = data.get("input_tokens_details") or data.get("prompt_tokens_details") or {}
    if hasattr(details, "model_dump"):
        details = details.model_dump()
    cached_input_tokens = 0
    if isinstance(details, dict):
        cached_input_tokens = int(details.get("cached_tokens") or details.get("cached_input_tokens") or 0)
    cached_input_tokens = int(data.get("cached_input_tokens") or cached_input_tokens or 0)
    return {
        "input_tokens": int(input_tokens or 0),
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": int(output_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "raw": data,
    }


def normalise_model_result(result: Dict[str, Any], criteria_rows: List[Dict[str, Any]], file_name: str) -> Dict[str, Any]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for item in result.get("assessments", []):
        criterion_id = str(item.get("criterion_id", "")).strip()
        if criterion_id:
            by_id[criterion_id] = item

    assessments: List[Dict[str, Any]] = []
    for criterion in criteria_rows:
        criterion_id = criterion["id"]
        item = by_id.get(criterion_id, {})
        score = clamp_score(item.get("score", 0))
        evidence = str(item.get("evidence", "") or "").strip() or "Not evidenced"
        source_ref = str(item.get("source_ref", "") or "").strip()
        confidence = str(item.get("confidence", "low") or "low").lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        assessments.append(
            {
                "criterion_id": criterion_id,
                "criterion_text": criterion["text"],
                "section": criterion["section"],
                "mandatory": bool(criterion.get("mandatory")),
                "weight": float(criterion.get("weight", 1.0)),
                "pass_score": int(criterion.get("pass_score", 3)),
                "score": score,
                "evidence": evidence[:800],
                "source_ref": source_ref[:120],
                "confidence": confidence,
                "notes": str(item.get("notes", "") or "").strip()[:500],
            }
        )

    candidate_name = str(result.get("candidate_name", "") or "").strip() or "Unknown"
    return {
        "candidate_name": candidate_name,
        "candidate_file": file_name,
        "candidate_id": file_name,
        "assessments": assessments,
    }


def clamp_score(value: Any) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = 0
    return max(0, min(5, score))
