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
    default_reasoning_effort_for_model,
    estimate_file_input_tokens,
    estimate_screening_run_cost,
    estimate_tokens,
    format_usd,
    model_rate_card,
    reasoning_efforts_for_model,
)
from niras_cv_screener.workflow import process_paths
from niras_cv_screener.cloud_files import save_uploads, results_zip, memory_uploads, remove_legacy_cloud_files

# Opt in only on a trusted local machine; hosted users use browser transfers.
LOCAL_FILES = os.getenv("NIRAS_ALLOW_LOCAL_PATHS", "").lower() == "true"


@st.cache_resource
def clean_previous_cloud_storage() -> bool:
    # Cache only a boolean, never CVs or reports. Cloud runs on Linux.
    return remove_legacy_cloud_files(ROOT, Path(tempfile.gettempdir()))


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
    st.session_state.setdefault("upload_generation", 0)
    if LOCAL_FILES and "workspace" not in st.session_state:
        st.session_state.workspace = tempfile.TemporaryDirectory(prefix="niras_session_")
    if st.session_state.pop("release_uploads", False):
        st.session_state.pop(f"cv_uploads_{st.session_state.upload_generation}", None)
        st.session_state.upload_generation += 1


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
    primary_reasoning_effort: str,
    comparison_reasoning_effort: str,
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
        primary_reasoning_effort=primary_reasoning_effort,
        comparison_reasoning_effort=comparison_reasoning_effort,
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
                "reasoning": row.get("reasoning_effort"),
                "calls": row.get("estimated_calls"),
                "input $/1M": row.get("input_usd_per_1m"),
                "cached input $/1M": row.get("cached_input_usd_per_1m"),
                "output $/1M": row.get("output_usd_per_1m"),
                "est. input tokens": row.get("estimated_input_tokens"),
                "est. visible output": row.get("estimated_visible_output_tokens"),
                "est. reasoning tokens": row.get("estimated_reasoning_output_tokens"),
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
    cached_rate = card["cached_input_usd_per_1m"]
    cached_text = "no listed discount" if cached_rate is None else f"${cached_rate}/1M"
    deprecated_text = " Deprecated preset." if card.get("deprecated") else ""
    st.caption(
        f"{label}: {card['model']} - input ${card['input_usd_per_1m']}/1M, "
        f"cached input {cached_text}, output ${card['output_usd_per_1m']}/1M. "
        f"Reasoning: {card['supported_reasoning_efforts']}. "
        f"Default reasoning: {card['default_reasoning_effort']}.{deprecated_text}"
    )


def inject_brand_css() -> None:
    st.markdown(
        """
        <style>
        @font-face {
            font-family: 'Soho Gothic Pro';
            font-weight: 400;
            font-display: swap;
            src: url('https://www.niras.com/assets/fonts/soho-gothic-pro/321D43_0_0.woff2') format('woff2');
        }
        @font-face {
            font-family: 'Soho Gothic Pro';
            font-weight: 700;
            font-display: swap;
            src: url('https://www.niras.com/assets/fonts/soho-gothic-pro/321D43_3_0.woff2') format('woff2');
        }
        @font-face {
            font-family: 'Guardian Egyptian';
            font-weight: 300;
            font-display: swap;
            src: url('https://www.niras.com/assets/fonts/guardian-egyptian/GuardianEgyp-Light-Web.woff2') format('woff2');
        }
        @font-face {
            font-family: 'Guardian Egyptian';
            font-weight: 700;
            font-display: swap;
            src: url('https://www.niras.com/assets/fonts/guardian-egyptian/GuardianEgyp-Semibold-Web.woff2') format('woff2');
        }

        :root {
            --niras-red: #BA1223;
            --niras-ink: #333132;
            --niras-muted: #58595B;
            --niras-rock-122: #D1D3D4;
            --niras-rock-133: #B1B3B6;
            --niras-spirit-311: #E3F3F1;
            --niras-spirit-333: #9CC6CA;
            --niras-spirit-344: #7195A6;
            --niras-spirit-366: #004C64;
            --niras-blue: #58C5C7;
            --niras-white: #FFFFFF;
            --niras-canvas: #F6F8F7;
            --niras-soho: 'Soho Gothic Pro', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            --niras-guardian: 'Guardian Egyptian', Georgia, serif;
        }

        .stApp {
            background: var(--niras-canvas);
            color: var(--niras-ink);
            font-family: var(--niras-soho);
        }

        .block-container {
            max-width: 1400px;
            padding-top: 1.35rem;
            padding-bottom: 3rem;
        }

        [data-testid="stHeader"] {
            background: rgba(246, 248, 247, 0.94);
            border-bottom: 1px solid rgba(209, 211, 212, 0.72);
            backdrop-filter: blur(10px);
        }

        [data-testid="stSidebar"] {
            background: var(--niras-white);
            border-right: 1px solid var(--niras-rock-122);
        }

        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        h1, h2, h3 {
            color: var(--niras-ink);
            font-family: var(--niras-guardian);
            letter-spacing: 0;
        }

        p, li, label, div, span, input, textarea, select, button {
            font-family: var(--niras-soho);
            letter-spacing: 0;
        }

        .niras-brand-header {
            display: grid;
            grid-template-columns: minmax(130px, 180px) minmax(0, 1fr);
            gap: 2rem;
            align-items: start;
            padding: 1.15rem 0 1.4rem;
            margin-bottom: 1.25rem;
            border-bottom: 1px solid var(--niras-rock-122);
        }

        .niras-brand-logo {
            width: min(170px, 36vw);
            height: auto;
            display: block;
            margin-top: 0.2rem;
        }

        .niras-brand-kicker {
            color: var(--niras-spirit-344);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            margin-bottom: 0.38rem;
        }

        .niras-brand-title {
            color: var(--niras-ink);
            font-family: var(--niras-guardian);
            font-size: clamp(2rem, 4vw, 3.6rem);
            font-weight: 300;
            line-height: 1;
            margin: 0;
        }

        .niras-brand-subtitle {
            color: var(--niras-muted);
            font-size: 1rem;
            line-height: 1.45;
            max-width: 760px;
            margin-top: 0.7rem;
        }

        .niras-brand-rule {
            width: 86px;
            height: 6px;
            margin-top: 1rem;
            background: var(--niras-red);
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--niras-white);
            border: 1px solid var(--niras-rock-122);
            border-radius: 4px;
            box-shadow: none;
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 0.75rem;
            border-bottom: 2px solid var(--niras-rock-122);
            margin-bottom: 1rem;
            padding-bottom: 0.35rem;
            flex-wrap: wrap;
        }

        .stTabs [data-baseweb="tab"] {
            background: var(--niras-white);
            border: 1.5px solid var(--niras-rock-122);
            border-bottom: 3px solid var(--niras-rock-122);
            border-radius: 4px 4px 0 0;
            color: var(--niras-muted);
            font-weight: 700;
            min-height: 3rem;
            padding: 0.75rem 1.2rem;
        }

        .stTabs [data-baseweb="tab"] p {
            color: inherit;
            font-size: 0.95rem;
            font-weight: 700;
            white-space: nowrap;
        }

        .stTabs [data-baseweb="tab"]:hover {
            border-color: var(--niras-spirit-344);
            color: var(--niras-ink);
        }

        .stTabs [aria-selected="true"] {
            background: var(--niras-spirit-311) !important;
            border-color: var(--niras-red) !important;
            border-bottom: 4px solid var(--niras-red) !important;
            color: var(--niras-red) !important;
        }

        .stButton > button,
        .stDownloadButton > button,
        [data-testid="stBaseButton-primary"] {
            border-radius: 0;
            border: 2px solid var(--niras-red);
            background: var(--niras-red);
            color: var(--niras-white);
            font-weight: 700;
            min-height: 2.7rem;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover,
        [data-testid="stBaseButton-primary"]:hover {
            background: var(--niras-ink);
            border-color: var(--niras-ink);
            color: var(--niras-white);
        }

        [data-testid="stMetric"] {
            background: var(--niras-white);
            border: 1px solid var(--niras-rock-122);
            border-left: 6px solid var(--niras-red);
            padding: 1rem;
        }

        [data-testid="stMetricLabel"] p {
            color: var(--niras-muted);
            font-size: 0.82rem;
            font-weight: 700;
            text-transform: uppercase;
        }

        [data-testid="stMetricValue"] {
            color: var(--niras-ink);
            font-family: var(--niras-guardian);
        }

        div[data-testid="stAlert"] {
            border-radius: 4px;
            border-left: 6px solid var(--niras-blue);
        }

        input, textarea, [data-baseweb="select"] > div {
            border-radius: 4px !important;
        }

        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: var(--niras-ink);
            font-family: var(--niras-soho);
            font-size: 0.98rem;
            font-weight: 700;
            letter-spacing: 0;
        }

        [data-testid="stTextInput"] div[data-baseweb="input"],
        [data-testid="stNumberInput"] div[data-baseweb="input"],
        [data-testid="stTextArea"] textarea,
        [data-baseweb="select"] > div {
            background-color: var(--niras-white) !important;
            border: 1.75px solid var(--niras-red) !important;
            border-radius: 4px !important;
            box-shadow: 0 0 0 1px rgba(186, 18, 35, 0.08) !important;
            overflow: hidden;
        }

        [data-testid="stTextInput"] div[data-baseweb="input"] input,
        [data-testid="stNumberInput"] div[data-baseweb="input"] input {
            border: 0 !important;
            box-shadow: none !important;
        }

        [data-testid="stTextInput"] div[data-baseweb="input"]:focus-within,
        [data-testid="stNumberInput"] div[data-baseweb="input"]:focus-within,
        [data-testid="stTextArea"] textarea:focus,
        [data-baseweb="select"] > div:focus-within {
            border-color: var(--niras-red) !important;
            box-shadow: 0 0 0 3px rgba(186, 18, 35, 0.18) !important;
            outline: none !important;
        }

        [data-testid="stFileUploader"] section {
            background: var(--niras-white);
            border: 1.75px dashed var(--niras-red) !important;
            border-radius: 4px !important;
            overflow: hidden;
        }

        [data-testid="stFileUploader"] section:hover {
            border-color: var(--niras-red) !important;
        }

        [data-testid="stDataFrame"],
        [data-testid="stDataEditor"] {
            background: var(--niras-white);
            border: 1.75px solid var(--niras-red) !important;
            border-radius: 4px !important;
            overflow: hidden;
        }

        a {
            color: var(--niras-red);
            text-decoration-thickness: 1px;
            text-underline-offset: 3px;
        }

        @media (max-width: 720px) {
            .niras-brand-header {
                grid-template-columns: 1fr;
                gap: 0.9rem;
            }
            .niras-brand-logo {
                width: 132px;
            }
            .niras-brand-title {
                font-size: 2.25rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_brand_header() -> None:
    logo_path = ROOT / "assets" / "niras-logo.svg"
    logo_svg = logo_path.read_text(encoding="utf-8") if logo_path.exists() else '<strong style="color:#BA1223;font-size:2rem;">NIRAS</strong>'
    st.markdown(
        f"""
        <div class="niras-brand-header">
            <div>{logo_svg}</div>
            <div>
                <div class="niras-brand-kicker">Recruitment screening workspace</div>
                <h1 class="niras-brand-title">CV Screener</h1>
                <div class="niras-brand-subtitle">Structured criteria, evidence-led scoring, calibration, and model cost review.</div>
                <div class="niras-brand-rule"></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def select_reasoning_effort(label: str, model: str, preferred: str, key: str) -> str:
    options = reasoning_efforts_for_model(model)
    if not options:
        options = ["none"]
    default = preferred if preferred in options else default_reasoning_effort_for_model(model)
    if default not in options:
        default = options[0]

    model_key = f"{key}__model"
    previous_model = st.session_state.get(model_key)
    current_value = st.session_state.get(key)
    if previous_model != model or current_value not in options:
        st.session_state[key] = default
        st.session_state[model_key] = model

    return st.selectbox(label, options, index=options.index(st.session_state[key]), key=key)


inject_brand_css()
if not LOCAL_FILES and sys.platform == "linux" and not clean_previous_cloud_storage():
    st.error("Earlier app files could not be removed. Recreate the cloud deployment before processing more CVs.")
    st.stop()
ensure_state()
render_brand_header()

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
    reasoning_effort = select_reasoning_effort("Primary reasoning effort", model, default_reasoning_effort_for_model(model), "primary_reasoning_effort")
    show_rate_caption(model, "Primary cost")

    enable_model_comparison = st.checkbox(
        "Run comparison model",
        value=True,
        help="Enabled by default. Runs a second assessment pass and includes that extra call in the cost preview.",
    )
    if enable_model_comparison:
        comparison_source = st.radio("Comparison model source", ["Same as primary", "Preset", "Custom"], horizontal=True, index=0)
        if comparison_source == "Same as primary":
            comparison_model = model
            st.caption(f"Comparison will run a second pass with `{comparison_model.strip()}`.")
        elif comparison_source == "Preset":
            comparison_default = model.strip() if model.strip() in MODEL_CHOICES else DEFAULT_COMPARISON_MODEL
            comparison_model = st.selectbox("Comparison model preset", MODEL_CHOICES, index=MODEL_CHOICES.index(comparison_default))
        else:
            comparison_model = st.text_input("Comparison model ID", value=model.strip() or DEFAULT_COMPARISON_MODEL)
        comparison_reasoning_effort = select_reasoning_effort("Comparison reasoning effort", comparison_model, default_reasoning_effort_for_model(comparison_model), "comparison_reasoning_effort")
        show_rate_caption(comparison_model, "Comparison cost")
    else:
        comparison_model = ""
        comparison_reasoning_effort = DEFAULT_REASONING_EFFORT

    interview_threshold = st.slider("Interview threshold", 0.0, 5.0, 3.5, 0.1)
    reserve_threshold = st.slider("Reserve threshold", 0.0, 5.0, 3.0, 0.1)
    use_result_cache = False
    use_ocr = False
    output_dir_text = ""
    if LOCAL_FILES:
        use_result_cache = st.checkbox("Reuse cached model results", value=True)
        use_ocr = st.checkbox("Try OCR fallback if installed", value=False)
        output_dir_text = st.text_input("Output folder on this computer", value=str(ROOT / "outputs"))
    else:
        st.caption("CVs and reports stay in session memory. Server file storage, result caching, and cloud OCR are disabled. Download reports before clearing this session.")
    if st.button("Clear CVs, results and session"):
        next_generation = st.session_state.upload_generation + 1
        if "workspace" in st.session_state:
            st.session_state.workspace.cleanup()
        st.session_state.clear()
        st.session_state.upload_generation = next_generation
        st.rerun()

criteria_tab, cv_tab, run_tab, results_tab = st.tabs(["1. Criteria", "2. CVs", "3. Run", "4. Results"])

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
    input_mode = st.radio("CV input", ["Upload files", "Folder path"] if LOCAL_FILES else ["Upload files"], horizontal=True)
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
            key=f"cv_uploads_{st.session_state.upload_generation}",
        )
        st.caption("Select CVs from your computer or synced OneDrive folder. OneDrive files must be downloaded to your device first. Cloud hosting cannot read a pasted desktop folder path.")
        if not LOCAL_FILES:
            st.info("Scanned PDFs need OCR on your computer before upload. CV text is sent to OpenAI for scoring; its data-retention policy still applies.")
        if uploaded:
            st.write(f"Ready to screen {len(uploaded)} uploaded files.")

with run_tab:
    st.write("Ready checks")
    comparison_active = enable_model_comparison and bool(comparison_model.strip())
    checks = {
        "Criteria rows": bool(st.session_state.criteria_rows),
        "CV files": bool(cv_paths or uploaded),
        "OpenAI API key": bool(api_key.strip()),
        "Primary model": bool(model.strip()),
        "Comparison model": (not enable_model_comparison) or bool(comparison_model.strip()),
    }
    st.dataframe(pd.DataFrame([{"check": k, "ok": v} for k, v in checks.items()]), hide_index=True, use_container_width=True)
    if comparison_active and comparison_model.strip() == model.strip():
        st.info("Comparison is enabled and will run a second pass using the same model. The cost preview includes this extra comparison call and its selected reasoning effort.")

    cost_preview = build_cost_preview(input_mode, cv_paths, uploaded, model, comparison_model, comparison_active, reasoning_effort, comparison_reasoning_effort)
    st.subheader("Model and cost preview")
    metric_cols = st.columns(5)
    metric_cols[0].metric("Estimated API cost", format_usd(cost_preview.get("estimated_uncached_cost_usd")))
    metric_cols[1].metric("Model calls", cost_preview.get("estimated_model_calls", 0))
    metric_cols[2].metric("Input tokens", f"{int(cost_preview.get('estimated_input_tokens') or 0):,}")
    metric_cols[3].metric("Output tokens", f"{int(cost_preview.get('estimated_output_tokens') or 0):,}")
    metric_cols[4].metric("Reasoning output", f"{int(cost_preview.get('estimated_reasoning_output_tokens') or 0):,}")
    st.caption("Estimate shown before app result-cache savings. Output tokens include estimated reasoning tokens from the selected effort level. Actual post-run costs use API token usage where available.")
    if not cost_preview.get("estimated_files"):
        st.info("Select a CV folder or upload CVs to see a batch cost estimate before running.")
    if cost_preview.get("estimated_uncached_cost_usd") is None and cost_preview.get("estimated_model_calls", 0):
        st.warning("Cost estimate unavailable for one or more selected models. Choose a priced preset to see a dollar estimate before running.")
    cost_df = cost_rows_for_display(cost_preview.get("rows", []))
    if not cost_df.empty:
        st.dataframe(cost_df, hide_index=True, use_container_width=True)

    run_clicked = st.button("Run Screening", type="primary", disabled=not all(checks.values()))
    if run_clicked:
        upload_temp = None
        result = None
        st.session_state.last_run = None
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
                if LOCAL_FILES:
                    upload_temp = tempfile.TemporaryDirectory(dir=st.session_state.workspace.name, prefix="uploads_")
                    paths_to_process = save_uploads(uploaded, Path(upload_temp.name))
                else:
                    paths_to_process = memory_uploads(uploaded)

            progress = st.progress(0)
            status = st.empty()

            def on_progress(done: int, total: int, name: str) -> None:
                progress.progress(done / max(total, 1))
                status.write(f"Processed {done} of {total}: {name}")

            output_dir = Path(output_dir_text).expanduser() if LOCAL_FILES else None
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

            if LOCAL_FILES:
                result["excel_download"] = Path(result["excel_path"]).read_bytes()
                result["zip_download"] = results_zip(Path(result["outputs_dir"]))
            st.session_state.last_run = result
            st.success(f"Screening complete: {result['processed']} processed, {result['skipped']} skipped. Downloads are in Results.")
            if LOCAL_FILES:
                st.caption(f"Saved to: {result['outputs_dir']}")
        except Exception as exc:
            message = str(exc) if LOCAL_FILES else "Screening could not finish. Check the criteria, files and API settings, then upload the CVs again."
            st.session_state.run_error = message
        finally:
            if upload_temp is not None:
                upload_temp.cleanup()
            if not LOCAL_FILES:
                st.session_state.release_uploads = True
        st.rerun()
    if st.session_state.get("run_error"):
        st.error(st.session_state.pop("run_error"))

with results_tab:
    result = st.session_state.last_run
    if not result:
        st.info("Run a screening batch to see results here.")
    else:
        st.caption("Download the ZIP to save all JSON reports, extracted text and Excel locally. Clear the session after downloading.")
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
            if result.get("excel_download"):
                st.download_button(
                    "Download Excel",
                    data=result["excel_download"],
                    file_name="screening_results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            if result.get("zip_download"):
                st.download_button("Download all results (ZIP)", data=result["zip_download"],
                                   file_name="screening_results.zip", mime="application/zip")
            if result.get("errors"):
                st.warning(f"{result['skipped']} CV files were skipped.")
                st.dataframe(as_dataframe(result["errors"]), hide_index=True, use_container_width=True)
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
                metric_cols = st.columns(5)
                metric_cols[0].metric("Estimated API cost", format_usd(preview.get("estimated_uncached_cost_usd")))
                metric_cols[1].metric("Estimated calls", preview.get("estimated_model_calls", 0))
                metric_cols[2].metric("Estimated input", f"{int(preview.get('estimated_input_tokens') or 0):,}")
                metric_cols[3].metric("Estimated output", f"{int(preview.get('estimated_output_tokens') or 0):,}")
                metric_cols[4].metric("Reasoning output", f"{int(preview.get('estimated_reasoning_output_tokens') or 0):,}")
                st.dataframe(cost_rows_for_display(preview.get("rows", [])), hide_index=True, use_container_width=True)
            st.subheader("Actual run")
            cost_summary = result.get("cost_summary", {})
            st.dataframe(as_dataframe([{"metric": k, "value": v} for k, v in cost_summary.items()]), hide_index=True, use_container_width=True)
            cost_records = result.get("cost_records", [])
            if cost_records:
                st.dataframe(as_dataframe(cost_records), hide_index=True, use_container_width=True)
