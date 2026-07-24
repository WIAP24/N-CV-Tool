from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from niras_cv_screener.criteria import (
    DEFAULT_RUBRIC,
    criteria_to_rows,
    parse_criteria_text,
    rows_to_criteria,
    validate_criteria,
)
from niras_cv_screener.extraction import SUPPORTED_EXTENSIONS, list_cv_paths
from niras_cv_screener.model_config import (
    DEFAULT_COMPARISON_MODEL,
    DEFAULT_FIXED_PROMPT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    MODEL_CHOICES,
    REASONING_EFFORTS,
    estimate_file_input_tokens,
    estimate_screening_run_cost,
    estimate_tokens,
    format_usd,
    model_rate_card,
)
from niras_cv_screener.workflow import process_paths


st.set_page_config(
    page_title="NIRAS CV Screener",
    page_icon="N",
    layout="wide",
)


def load_sample_criteria() -> str:
    sample = ROOT / "sample_criteria.txt"
    return sample.read_text(encoding="utf-8") if sample.exists() else ""


def ensure_state() -> None:
    st.session_state.setdefault("criteria_text", load_sample_criteria())
    st.session_state.setdefault("criteria_rows", [])
    st.session_state.setdefault("criteria_role_title", "")
    st.session_state.setdefault("api_key", os.getenv("OPENAI_API_KEY", ""))
    st.session_state.setdefault("last_run", None)


def parse_current_criteria() -> None:
    parsed = parse_criteria_text(st.session_state.criteria_text)
    st.session_state.criteria_rows = criteria_to_rows(parsed)
    st.session_state.criteria_role_title = parsed.get("role_title", "")


def rows_from_editor(editor_value: Any) -> List[Dict[str, Any]]:
    if isinstance(editor_value, pd.DataFrame):
        records = editor_value.to_dict("records")
    else:
        records = list(editor_value or [])
    return [{k: v for k, v in row.items()} for row in records]


def save_uploads_to_temp(uploaded_files: List[Any]) -> List[Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix="niras_cv_uploads_"))
    paths: List[Path] = []
    for uploaded in uploaded_files:
        path = temp_dir / uploaded.name
        path.write_bytes(uploaded.getbuffer())
        paths.append(path)
    return paths


def as_dataframe(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def selected_file_token_estimates(input_mode: str, cv_paths: List[Path], uploaded_files: List[Any]) -> List[Dict[str, Any]]:
    estimates: List[Dict[str, Any]] = []
    if input_mode == "Folder path":
        for path in cv_paths:
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = 0
            estimates.append(
                {
                    "file": path.name,
                    "size_kb": round(size_bytes / 1024, 1),
                    "estimated_cv_input_tokens": estimate_file_input_tokens(path.name, size_bytes),
                }
            )
    else:
        for uploaded in uploaded_files or []:
            size_bytes = int(getattr(uploaded, "size", 0) or len(uploaded.getbuffer()))
            estimates.append(
                {
                    "file": uploaded.name,
                    "size_kb": round(size_bytes / 1024, 1),
                    "estimated_cv_input_tokens": estimate_file_input_tokens(uploaded.name, size_bytes),
                }
            )
    return estimates


def criteria_token_estimate() -> tuple[int, int]:
    criteria_count = len(st.session_state.criteria_rows)
    try:
        criteria_json = rows_to_criteria(
            st.session_state.criteria_rows,
            role_title=st.session_state.criteria_role_title,
            scoring_rubric=DEFAULT_RUBRIC,
        )
        criteria_count = len(criteria_to_rows(criteria_json))
        token_basis = json.dumps(criteria_json, ensure_ascii=False)
    except Exception:
        token_basis = st.session_state.criteria_text
    return estimate_tokens(token_basis) + DEFAULT_FIXED_PROMPT_TOKENS, criteria_count


def build_cost_preview(
    input_mode: str,
    cv_paths: List[Path],
    uploaded_files: List[Any],
    model: str,
    comparison_model: str,
    enable_model_comparison: bool,
) -> Dict[str, Any]:
    criteria_tokens, criteria_count = criteria_token_estimate()
    file_estimates = selected_file_token_estimates(input_mode, cv_paths, uploaded_files)
    return estimate_screening_run_cost(
        file_estimates,
        criteria_tokens=criteria_tokens,
        criteria_count=criteria_count,
        primary_model=model.strip(),
        comparison_model=comparison_model.strip() or None,
        enable_model_comparison=enable_model_comparison,
    )


def cost_rows_for_display(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    display_rows = []
    for row in rows:
        display_rows.append(
            {
                "stage": row.get("stage"),
                "model": row.get("model"),
                "role": row.get("model_label"),
                "calls": row.get("estimated_calls"),
                "input $/1M": row.get("input_usd_per_1m"),
                "cached input $/1M": row.get("cached_input_usd_per_1m"),
                "output $/1M": row.get("output_usd_per_1m"),
                "est. input tokens": row.get("estimated_input_tokens"),
                "est. output tokens": row.get("estimated_output_tokens"),
                "est. cost": format_usd(row.get("estimated_uncached_cost_usd")),
            }
        )
    return pd.DataFrame(display_rows)


def show_rate_caption(model: str, label: str) -> None:
    card = model_rate_card(model)
    if card["input_usd_per_1m"] is None:
        st.caption(f"{label}: {card['model']} - pricing unavailable for this model ID.")
        return
    st.caption(
        f"{label}: {card['model']} - input ${card['input_usd_per_1m']}/1M, "
        f"cached input ${card['cached_input_usd_per_1m']}/1M, output ${card['output_usd_per_1m']}/1M."
    )


ensure_state()

st.title("NIRAS CV Screener")

with st.container(border=True):
    st.subheader("OpenAI Setup")
    api_key = st.text_input(
        "OpenAI API key",
        key="api_key",
        type="password",
        help="Paste your OpenAI API key for this run. It is held in the app session and is not written to output files.",
    )
    if api_key.strip():
        st.caption("API key added for this session.")
    else:
        st.warning("Add your OpenAI API key here before running a screening batch.")

with st.sidebar:
    st.subheader("Run Settings")
    model_entry_mode = st.radio("Primary model", ["Preset", "Custom"], horizontal=True)
    if model_entry_mode == "Preset":
        model = st.selectbox("Primary model preset", MODEL_CHOICES, index=MODEL_CHOICES.index(DEFAULT_MODEL))
    else:
        model = st.text_input("Primary model ID", value=DEFAULT_MODEL)
    reasoning_effort = st.selectbox("Primary reasoning effort", REASONING_EFFORTS, index=REASONING_EFFORTS.index(DEFAULT_REASONING_EFFORT))
    show_rate_caption(model, "Primary cost")

    enable_model_comparison = st.checkbox("Run comparison model", value=False)
    if enable_model_comparison:
        comparison_model = st.selectbox("Comparison model", MODEL_CHOICES, index=MODEL_CHOICES.index(DEFAULT_COMPARISON_MODEL))
        comparison_reasoning_effort = st.selectbox("Comparison reasoning effort", REASONING_EFFORTS, index=REASONING_EFFORTS.index("medium"))
        show_rate_caption(comparison_model, "Comparison cost")
    else:
        comparison_model = ""
        comparison_reasoning_effort = DEFAULT_REASONING_EFFORT

    interview_threshold = st.slider("Interview threshold", 0.0, 5.0, 3.5, 0.1)
    reserve_threshold = st.slider("Reserve threshold", 0.0, 5.0, 3.0, 0.1)
    use_result_cache = st.checkbox("Reuse cached model results", value=True)
    use_ocr = st.checkbox("Try OCR fallback if installed", value=False)
    output_dir_text = st.text_input("Output folder", value=str(ROOT / "outputs"))

criteria_tab, cv_tab, run_tab, results_tab = st.tabs(["Criteria", "CVs", "Run", "Results"])

with criteria_tab:
    st.session_state.criteria_text = st.text_area(
        "Paste criteria",
        value=st.session_state.criteria_text,
        height=260,
    )
    col_a, col_b = st.columns([1, 5])
    with col_a:
        if st.button("Parse Criteria", type="primary"):
            try:
                parse_current_criteria()
                st.success("Criteria parsed.")
            except Exception as exc:
                st.error(str(exc))
    with col_b:
        st.caption("Check and edit the table before running. Mandatory criteria drive pass/fail recommendations.")

    if not st.session_state.criteria_rows:
        try:
            parse_current_criteria()
        except Exception:
            pass

    if st.session_state.criteria_rows:
        st.text_input("Role title", key="criteria_role_title")
        criteria_df = pd.DataFrame(st.session_state.criteria_rows)
        edited = st.data_editor(
            criteria_df,
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "mandatory": st.column_config.CheckboxColumn("Mandatory"),
                "weight": st.column_config.NumberColumn("Weight", min_value=0.1, step=0.1),
                "pass_score": st.column_config.NumberColumn("Pass score", min_value=0, max_value=5, step=1),
                "text": st.column_config.TextColumn("Criterion", width="large"),
            },
        )
        st.session_state.criteria_rows = rows_from_editor(edited)

with cv_tab:
    input_mode = st.radio("CV input", ["Folder path", "Upload files"], horizontal=True)
    cv_paths: List[Path] = []
    uploaded = []
    if input_mode == "Folder path":
        folder_text = st.text_input("CV folder path", value="")
        recursive = st.checkbox("Include subfolders", value=False)
        if folder_text:
            folder = Path(folder_text)
            if folder.is_dir():
                cv_paths = list_cv_paths(folder, recursive=recursive)
                st.write(f"Found {len(cv_paths)} supported files.")
                if cv_paths:
                    st.dataframe(
                        pd.DataFrame(
                            [{"file": p.name, "path": str(p), "size_kb": round(p.stat().st_size / 1024, 1)} for p in cv_paths]
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
            else:
                st.warning("Enter a valid folder path.")
    else:
        uploaded = st.file_uploader(
            "Upload CV files",
            type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS],
            accept_multiple_files=True,
        )
        if uploaded:
            st.write(f"Ready to screen {len(uploaded)} uploaded files.")

with run_tab:
    st.write("Ready checks")
    comparison_active = enable_model_comparison and bool(comparison_model.strip()) and comparison_model.strip() != model.strip()
    checks = {
        "Criteria rows": bool(st.session_state.criteria_rows),
        "OpenAI API key": bool(api_key.strip()),
        "Primary model": bool(model.strip()),
        "Comparison model": (not enable_model_comparison) or bool(comparison_model.strip()),
    }
    st.dataframe(pd.DataFrame([{"check": k, "ok": v} for k, v in checks.items()]), hide_index=True, use_container_width=True)
    if enable_model_comparison and not comparison_active:
        st.info("The comparison model matches the primary model, so no second model call will be made.")

    cost_preview = build_cost_preview(input_mode, cv_paths, uploaded, model, comparison_model, comparison_active)
    st.subheader("Model and cost preview")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Estimated API cost", format_usd(cost_preview.get("estimated_uncached_cost_usd")))
    metric_cols[1].metric("Model calls", cost_preview.get("estimated_model_calls", 0))
    metric_cols[2].metric("Input tokens", f"{int(cost_preview.get('estimated_input_tokens') or 0):,}")
    metric_cols[3].metric("Output tokens", f"{int(cost_preview.get('estimated_output_tokens') or 0):,}")
    st.caption("Estimate shown before app result-cache savings. Actual post-run costs use API token usage where available.")
    if not cost_preview.get("estimated_files"):
        st.info("Select a CV folder or upload CVs to see a batch cost estimate before running.")
    if cost_preview.get("estimated_uncached_cost_usd") is None and cost_preview.get("estimated_model_calls", 0):
        st.warning("Cost estimate unavailable for one or more selected models. Choose a priced preset to see a dollar estimate before running.")
    cost_df = cost_rows_for_display(cost_preview.get("rows", []))
    if not cost_df.empty:
        st.dataframe(cost_df, hide_index=True, use_container_width=True)

    run_clicked = st.button("Run Screening", type="primary")
    if run_clicked:
        try:
            criteria = rows_to_criteria(
                st.session_state.criteria_rows,
                role_title=st.session_state.criteria_role_title,
                scoring_rubric=DEFAULT_RUBRIC,
            )
            validate_criteria(criteria)

            paths_to_process: List[Path]
            if input_mode == "Folder path":
                if not cv_paths:
                    raise ValueError("No CV files found.")
                paths_to_process = cv_paths
            else:
                if not uploaded:
                    raise ValueError("No CV files uploaded.")
                paths_to_process = save_uploads_to_temp(uploaded)

            progress = st.progress(0)
            status = st.empty()

            def on_progress(done: int, total: int, name: str) -> None:
                progress.progress(done / max(total, 1))
                status.write(f"Processed {done} of {total}: {name}")

            output_dir = Path(output_dir_text).expanduser()
            with st.spinner("Screening CVs..."):
                result = process_paths(
                    cv_paths=paths_to_process,
                    criteria_json=criteria,
                    api_key=api_key.strip(),
                    model=model.strip(),
                    output_root=output_dir,
                    thresholds={
                        "interview_threshold": interview_threshold,
                        "reserve_threshold": reserve_threshold,
                    },
                    progress_callback=on_progress,
                    comparison_model=comparison_model.strip() or None,
                    reasoning_effort=reasoning_effort,
                    comparison_reasoning_effort=comparison_reasoning_effort,
                    enable_model_comparison=comparison_active,
                    use_ocr=use_ocr,
                    use_result_cache=use_result_cache,
                    cost_preview=cost_preview,
                )

            st.session_state.last_run = result
            st.success(f"Screening complete. Output: {result['outputs_dir']}")
            st.link_button("Open output folder path", f"file:///{Path(result['outputs_dir']).as_posix()}")
        except Exception as exc:
            st.error(str(exc))

with results_tab:
    result = st.session_state.last_run
    if not result:
        st.info("Run a screening batch to see results here.")
    else:
        summary_rows = []
        for item in result.get("results", []):
            summary = item.get("summary", {})
            comparison = item.get("model_comparison", {})
            summary_rows.append(
                {
                    "candidate": item.get("candidate_name") or item.get("candidate_file"),
                    "file": item.get("candidate_file"),
                    "recommendation": summary.get("recommendation"),
                    "mandatory": f"{summary.get('mandatory_pass_count')}/{summary.get('mandatory_total')}",
                    "weighted_score": summary.get("weighted_score"),
                    "review_items": sum(1 for row in result.get("review_queue", []) if row.get("candidate_file") == item.get("candidate_file")),
                    "model_delta": comparison.get("max_abs_score_delta", ""),
                    "critical_gaps": "; ".join(summary.get("critical_gaps", [])),
                }
            )

        overview_tab, review_tab, calibration_tab, evaluation_tab, cost_tab = st.tabs(["Overview", "Review Queue", "Calibration", "Model Evaluation", "Model / Cost"])
        with overview_tab:
            st.dataframe(as_dataframe(summary_rows), hide_index=True, use_container_width=True)
            excel_path = Path(result["excel_path"])
            if excel_path.exists():
                st.download_button(
                    "Download Excel",
                    data=excel_path.read_bytes(),
                    file_name=excel_path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        with review_tab:
            review_df = as_dataframe(result.get("review_queue", []))
            if review_df.empty:
                st.success("No review queue items were generated.")
            else:
                st.data_editor(review_df, hide_index=True, use_container_width=True)
        with calibration_tab:
            calibration_df = as_dataframe(result.get("calibration_rows", []))
            if calibration_df.empty:
                st.info("No calibration rows available yet.")
            else:
                st.dataframe(calibration_df, hide_index=True, use_container_width=True)
        with evaluation_tab:
            evaluations = result.get("model_evaluations", [])
            if not evaluations:
                st.info("Enable comparison model runs to generate model evaluation results.")
            else:
                st.dataframe(as_dataframe([{k: v for k, v in row.items() if k != "criterion_differences"} for row in evaluations]), hide_index=True, use_container_width=True)
                detail_rows = []
                for row in evaluations:
                    for diff in row.get("criterion_differences", []):
                        detail_rows.append(diff)
                if detail_rows:
                    st.dataframe(as_dataframe(detail_rows), hide_index=True, use_container_width=True)
        with cost_tab:
            preview = result.get("cost_preview", {})
            if preview:
                st.subheader("Pre-run estimate")
                metric_cols = st.columns(4)
                metric_cols[0].metric("Estimated API cost", format_usd(preview.get("estimated_uncached_cost_usd")))
                metric_cols[1].metric("Estimated calls", preview.get("estimated_model_calls", 0))
                metric_cols[2].metric("Estimated input", f"{int(preview.get('estimated_input_tokens') or 0):,}")
                metric_cols[3].metric("Estimated output", f"{int(preview.get('estimated_output_tokens') or 0):,}")
                st.dataframe(cost_rows_for_display(preview.get("rows", [])), hide_index=True, use_container_width=True)
            st.subheader("Actual run")
            cost_summary = result.get("cost_summary", {})
            st.dataframe(as_dataframe([{"metric": k, "value": v} for k, v in cost_summary.items()]), hide_index=True, use_container_width=True)
            cost_records = result.get("cost_records", [])
            if cost_records:
                st.dataframe(as_dataframe(cost_records), hide_index=True, use_container_width=True)
