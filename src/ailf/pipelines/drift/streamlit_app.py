"""Streamlit UI for drift detection and Prophet forecasting.

SPEC §Visualization 4-11:
- Model dropdown: Ollama (Qwen) / Claude Sonnet & Opus / Bedrock / LangSmith
- When cloud model selected: streams reasoning live before Prophet
- Scenario selector + Model Settings + Agent Settings + Diagnostic Toggles + Tool Toggles
  (§9-11) build a --override JSON for the changepoint pipeline CLI
- Pre-generated series from pocs/data/; year-5 holdout comparison

Run with:
    PYTHONPATH=src streamlit run src/ailf/pipelines/drift/streamlit_app.py
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Project path bootstrap ───────────────────────────────────────────────
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[4]
_SRC = _PROJECT_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ailf.pipelines.drift.llm_reason import (  # noqa: E402
    BEDROCK_MODELS,
    CLAUDE_MODELS,
    DEFAULT_MODEL,
    detect,
    detect_streaming,
)

# ── Constants ────────────────────────────────────────────────────────────
_DATA_DIR = _PROJECT_ROOT / "pocs" / "data"
_REPORTS_DIR = _PROJECT_ROOT / "reports" / "changepoint"

_SCENARIOS = [
    "level_shift_loses_seasonality",
    "gradual_drift_loses_seasonality",
    "temporary_event_not_regime_change",
    "many_temporary_events_long_history",
    "prophet_prior_tuning_recurring_event",
]

_ALL_DIAGNOSTICS = [
    "detected_changepoints",
    "latest_changepoint",
    "primary_changepoint",
    "post_changepoint_history_len",
    "post_changepoint_shorter_than_season",
    "seasonal_period",
    "segment_stats",
    "candidate_event_blocks",
    "recurring_event_summary",
    "local_boundary_jumps",
    "candidate_drift_intervals",
    "transient_event_score",
    "permanent_shift_magnitude",
]

_ALL_TOOLS = [
    "recent_window",
    "full_history_step_regressor",
    "full_history_ramp_regressor",
    "full_history_clean_event",
    "full_history_prophet_tuned_holidays",
    "full_history_default",  # always-on fallback
]

_DIAG_HELP: dict[str, str] = {
    "detected_changepoints":              "All changepoints detected in training data.",
    "latest_changepoint":                 "Most recent changepoint index and date.",
    "primary_changepoint":                "Largest-magnitude changepoint detected.",
    "post_changepoint_history_len":       "Rows available after the latest changepoint.",
    "post_changepoint_shorter_than_season": "Post-CP window shorter than seasonal period.",
    "seasonal_period":                    "Estimated dominant seasonal cycle length.",
    "segment_stats":                      "Mean/std stats per changepoint segment.",
    "candidate_event_blocks":             "Date ranges flagged as recurring events.",
    "recurring_event_summary":            "Summary of repeating event patterns found.",
    "local_boundary_jumps":               "Sharp value jumps at segment boundaries.",
    "candidate_drift_intervals":          "Intervals exhibiting gradual trend drift.",
    "transient_event_score":              "Score: how transient vs permanent the shift.",
    "permanent_shift_magnitude":          "Estimated size of any permanent level shift.",
}

_TOOL_HELP: dict[str, str] = {
    "recent_window":                    "Fit Prophet on the most recent window only.",
    "full_history_step_regressor":      "Add binary step regressor at changepoint.",
    "full_history_ramp_regressor":      "Add linear ramp regressor at changepoint.",
    "full_history_clean_event":         "Zero-out event blocks as regressors.",
    "full_history_prophet_tuned_holidays": "Tune Prophet holiday prior around events.",
    "full_history_default":             "Always-on baseline; cannot be disabled.",
}

# ── Page config ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Drift Forecast UI",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Forecast Explorer")
st.caption(
    "Agent-in-the-Loop Forecasting · "
    "[FastAPI UI](http://127.0.0.1:8000/forecast/ui) · "
    "[Swagger](http://127.0.0.1:8000/docs)"
)

# ── Sidebar controls ─────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Controls")

    # ── Data source ───────────────────────────────────────────────────────
    st.subheader("Data Source")
    source_mode = st.radio("Input mode", ["Upload CSV", "Data Scenario", "pocs/data/ CSV"])

    uploaded_file = None
    selected_series = None

    if source_mode == "Upload CSV":
        uploaded_file = st.file_uploader(
            "CSV file (ds, y columns)", type=["csv"],
            help="Must have `ds` (date) and `y` (numeric) columns.",
        )
    elif source_mode == "pocs/data/ CSV":
        _poc_csvs = sorted(_DATA_DIR.glob("*_train.csv"))
        if _poc_csvs:
            _poc_labels = [f.stem.replace("_train", "") for f in _poc_csvs]
            _poc_idx = st.selectbox(
                "pocs/data/ file",
                range(len(_poc_csvs)),
                format_func=lambda i: _poc_labels[i],
            )
            selected_series = _poc_csvs[_poc_idx]
            _chosen_scenario_name = _poc_labels[_poc_idx]
        else:
            st.warning("No *_train.csv files found in pocs/data/")
            _chosen_scenario_name = _SCENARIOS[0]
    else:
        # Show only the 5 committed changepoint scenarios (§Forecasting 7)
        _scenario_idx = st.selectbox(
            "Data Scenario",
            range(len(_SCENARIOS)),
            format_func=lambda i: _SCENARIOS[i],
        )
        _chosen_scenario_name = _SCENARIOS[_scenario_idx]

        # Try to find a matching CSV in pocs/data/ (silently — no warning shown)
        _csv_candidate = _DATA_DIR / f"{_chosen_scenario_name}_train.csv"
        selected_series = _csv_candidate if _csv_candidate.exists() else None

    # Derive scenario_id from selection (used by pipeline panel below)
    if source_mode in ("Data Scenario", "pocs/data/ CSV"):
        scenario_id: str = _chosen_scenario_name
    else:
        scenario_id = _SCENARIOS[0]  # default for Upload CSV mode

    st.divider()

    # ── Forecast parameters ───────────────────────────────────────────────
    st.subheader("Forecast Parameters")
    prediction_length = st.number_input(
        "Prediction length (days)", min_value=1, max_value=3650, value=365,
    )
    freq = st.selectbox(
        "Frequency", ["D", "W", "MS"], index=0,
        help="D=daily, W=weekly, MS=monthly-start",
    )
    split_ratio = st.slider(
        "Split Dataset Ratio (train %)",
        min_value=50, max_value=95, value=80, step=5,
        help="Percentage of rows used for training; remainder is the holdout for comparison.",
    )

    st.divider()

    # ── Model Settings (§10) — includes Detect with dropdown ─────────────
    st.subheader("Model Settings")

    # Detect with (moved here per §10)
    _model_options: dict[str, str] = {
        f"Qwen via Ollama ({DEFAULT_MODEL})": DEFAULT_MODEL,
        "Claude Sonnet 4.6  (needs ANTHROPIC_API_KEY)": "claude-sonnet-4-6",
        "Claude Sonnet 4.5  (needs ANTHROPIC_API_KEY)": "claude-sonnet-4-5",
        "Claude Opus 4.5  (needs ANTHROPIC_API_KEY)": "claude-opus-4-5",
        "Claude 3.5 Sonnet  (needs ANTHROPIC_API_KEY)": "claude-3-5-sonnet-20241022",
        "Bedrock: Claude 3.5 Sonnet  (needs AWS creds)": "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
        "Bedrock: Claude 3 Haiku  (needs AWS creds)": "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
    }
    selected_model_label = st.selectbox(
        "Detect with",
        list(_model_options.keys()),
        help="LLM backend for changepoint detection before Prophet.",
    )
    actual_model_id = _model_options[selected_model_label]

    ollama_url = "http://localhost:11434"
    is_ollama = not (
        actual_model_id.startswith("claude-")
        or actual_model_id.startswith("bedrock/")
    )
    if is_ollama:
        ollama_url = st.text_input("Ollama URL", value="http://localhost:11434")

    # Bedrock model settings — greyed out (disabled) when not a Bedrock model (§10 note)
    _is_bedrock_model = actual_model_id.startswith("bedrock/")
    visual_model_id = st.text_input(
        "visual_model_id",
        value="us.anthropic.claude-sonnet-4-6",
        help="Bedrock model ID for the visual-inspection node. Active only for Bedrock.",
        disabled=not _is_bedrock_model,
    )
    decision_model_id = st.text_input(
        "decision_model_id",
        value="us.anthropic.claude-sonnet-4-6",
        help="Bedrock model ID for the decision node. Active only for Bedrock.",
        disabled=not _is_bedrock_model,
    )
    aws_region = st.text_input(
        "aws_region", value="us-west-2",
        disabled=not _is_bedrock_model,
    )
    if not _is_bedrock_model:
        st.caption("ℹ️ Bedrock model settings are greyed out — select a Bedrock model above to enable.")

    st.divider()

    # ── Agent Settings (§10) ──────────────────────────────────────────────
    st.subheader("Agent Settings")
    visual_analysis_enabled = st.toggle(
        "visual_analysis_enabled",
        value=True,
        help="When off, no agent_context.png is produced and the visual node is skipped.",
    )
    if not visual_analysis_enabled:
        st.caption("ℹ️ No agent_context.png will be produced (visual node disabled).")
    seed = st.number_input("seed", min_value=0, max_value=99999, value=1729, step=1)

    st.divider()

    # ── Diagnostic Toggles (§11) ──────────────────────────────────────────
    st.subheader("Diagnostic Toggles")
    st.caption("Unchecked = computed by backend but hidden from agent.")
    diag_values: dict[str, bool] = {}
    for d in _ALL_DIAGNOSTICS:
        diag_values[d] = st.checkbox(
            d, value=True, key=f"diag_{d}",
            help=_DIAG_HELP.get(d, ""),
        )

    st.divider()

    # ── Tool Toggles (§11) ────────────────────────────────────────────────
    st.subheader("Tool Toggles")
    tool_values: dict[str, bool] = {}
    for t in _ALL_TOOLS:
        if t == "full_history_default":
            # Must stay enabled (FR-016: guaranteed-valid fallback, cannot be disabled).
            # The agent prompt strongly discourages choosing it when changepoints exist.
            st.checkbox(t, value=True, disabled=True, key=f"tool_{t}",
                        help="Always enabled — required safety net (FR-016). "
                             "The agent is prompted to prefer recent_window/step_regressor.")
            tool_values[t] = True
        else:
            tool_values[t] = st.checkbox(t, value=True, key=f"tool_{t}",
                                         help=_TOOL_HELP.get(t, ""))

    st.divider()

    # ── LangSmith tracing (works with ANY model, incl. Qwen) ─────────────
    st.subheader("🔗 LangSmith Tracing")
    langsmith_tracing = st.toggle(
        "Trace with LangSmith",
        value=True,
        help=(
            "Records each detection run to LangSmith. "
            "Requires LANGSMITH_API_KEY (and optionally LANGSMITH_API_URL) in .env. "
            "Works with Qwen/Ollama too — no Anthropic key needed for tracing alone. "
            "Trace failures are non-fatal and degrade silently."
        ),
    )
    if langsmith_tracing:
        import os as _os
        _ls_key = _os.environ.get("LANGSMITH_API_KEY", "").strip()
        if not _ls_key:
            # Try reading from .env
            try:
                _env_path = _PROJECT_ROOT / ".env"
                if _env_path.exists():
                    for _line in _env_path.read_text().splitlines():
                        if _line.startswith("LANGSMITH_API_KEY="):
                            _ls_key = _line.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception:
                pass
        if _ls_key:
            st.caption(
                "Traces sent to `LANGSMITH_API_URL` (default: "
                "`https://apac.smith.langchain.com`) under project "
                "`agent-in-the-loop-forecasting`. Trace URL appears after detection."
            )
        else:
            st.warning("⚠️ `LANGSMITH_API_KEY` not set in `.env` — tracing will be skipped.")

    st.divider()

    # ── Bedrock Changepoint Pipeline toggle (§13, ON by default per §8) ────
    bedrock_pipeline_enabled = st.toggle(
        "Bedrock Changepoint Pipeline",
        value=True,
        help=(
            "When ON: runs run_scenario directly (or via FastAPI fallback) using "
            "Bedrock / Claude creds from .env. "
            "When OFF: runs standard drift detection + Prophet forecast."
        ),
    )

    if bedrock_pipeline_enabled:
        run_btn = st.button(
            "▶️ Run Forecast",
            type="primary",
            use_container_width=True,
            help="POST /changepoint/run with current scenario + override settings.",
        )
    else:
        run_btn = st.button("🔍 Detect & Forecast", type="primary", use_container_width=True)

    if run_btn:
        st.cache_data.clear()


# ── Helpers ───────────────────────────────────────────────────────────────

def _load_df(source) -> pd.DataFrame:
    df = pd.read_csv(source)
    missing = {"ds", "y"} - set(df.columns)
    if missing:
        st.error(f"CSV missing required columns: {sorted(missing)}")
        st.stop()
    df["ds"] = pd.to_datetime(df["ds"])
    df["y"]  = pd.to_numeric(df["y"], errors="coerce")
    df = df.dropna(subset=["ds", "y"]).sort_values("ds").reset_index(drop=True)
    if len(df) < 2:
        st.error("CSV must contain at least 2 valid rows.")
        st.stop()
    return df


def _train_test_split(df: pd.DataFrame, ratio: float = 0.8) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Split df at `ratio` of rows for train; remainder is holdout.

    Falls back to no holdout when the series is too short to leave
    at least 10 rows for the test set.
    """
    split_idx = int(len(df) * ratio)
    if split_idx < len(df) - 10:
        train = df.iloc[:split_idx].copy().reset_index(drop=True)
        test  = df.iloc[split_idx:].copy().reset_index(drop=True)
        return train, test
    return df.copy(), None


def _run_prophet(
    train_df: pd.DataFrame,
    prediction_length: int,
    freq: str,
    test_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    from prophet import Prophet
    actual_periods = len(test_df) if test_df is not None else prediction_length
    m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
    regressor_cols = [c for c in train_df.columns if c not in ("ds", "y")]
    for col in regressor_cols:
        m.add_regressor(col)
    m.fit(train_df[["ds", "y"] + regressor_cols])
    future = m.make_future_dataframe(periods=actual_periods, freq=freq)
    for col in regressor_cols:
        future[col] = train_df[col].iloc[-1]
    forecast = m.predict(future)
    cutoff   = train_df["ds"].max()
    fut_part = forecast[forecast["ds"] > cutoff]
    return fut_part, forecast


def _build_chart(
    df: pd.DataFrame,
    fut_part: pd.DataFrame,
    changepoints: list[dict],
    test_df: pd.DataFrame | None = None,
    agent_fut: pd.DataFrame | None = None,
) -> go.Figure:
    """Build the forecast chart.

    Traces:
    - Historical (solid dark blue)
    - naive forecast (orange dashed) — plain Prophet auto-changepoints
    - 95% CI shaded band (for naive forecast)
    - agent-in-the-loop forecast (dotted light purple, §14) — when agent_fut is provided
    - Actual holdout (green solid)
    - Changepoints (dotted red verticals)
    """
    fig = go.Figure()

    # Historical solid line
    fig.add_trace(go.Scatter(
        x=df["ds"], y=df["y"],
        mode="lines", name="Historical (train)",
        line=dict(color="#1a3a5c", width=2),
    ))

    # CI band (naive forecast)
    fig.add_trace(go.Scatter(
        x=fut_part["ds"], y=fut_part["yhat_upper"],
        mode="lines", name="Naive CI upper",
        line=dict(width=0), showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=fut_part["ds"], y=fut_part["yhat_lower"],
        fill="tonexty", fillcolor="rgba(70,130,180,0.12)",
        mode="lines", name="Naive 95% CI",
        line=dict(width=0),
    ))

    # Naive forecast (orange dashed)
    fig.add_trace(go.Scatter(
        x=fut_part["ds"], y=fut_part["yhat"],
        mode="lines", name="naive forecast",
        line=dict(color="#e05c00", width=2, dash="dash"),
    ))

    # Agent-in-the-loop forecast (dotted light purple, §14)
    if agent_fut is not None and not agent_fut.empty:
        fig.add_trace(go.Scatter(
            x=agent_fut["ds"], y=agent_fut["yhat"],
            mode="lines", name="agent-in-the-loop forecast",
            line=dict(color="#b57bee", width=2, dash="dot"),
        ))

    # Actual holdout (green)
    if test_df is not None and not test_df.empty:
        fig.add_trace(go.Scatter(
            x=test_df["ds"], y=test_df["y"],
            mode="lines", name="Actual (holdout)",
            line=dict(color="#2ca02c", width=2),
        ))

    # Changepoint vertical markers
    for cp in changepoints:
        ts = cp.get("timestamp")
        if ts:
            try:
                x_val = pd.Timestamp(ts)
            except Exception:
                continue
            fig.add_vline(
                x=x_val.value // 10**6,
                line_width=1.5, line_dash="dot", line_color="rgba(220,53,69,0.55)",
                annotation_text=cp.get("type", "cp"),
                annotation_position="top left",
                annotation_font_size=9,
            )

    agent_note = " | +agent-in-the-loop" if agent_fut is not None else ""
    fig.update_layout(
        title=(
            f"Historical vs. Forecast — horizon: {len(fut_part)} days"
            + (f" | {len(changepoints)} changepoints" if changepoints else "")
            + agent_note
        ),
        xaxis=dict(title="Date", rangeslider=dict(visible=True)),
        yaxis=dict(title="y"),
        legend=dict(orientation="h", y=-0.25),
        hovermode="x unified",
        height=500,
    )
    return fig


def _run_agent_forecast(
    train_df: pd.DataFrame,
    changepoints: list[dict],
    prediction_length: int,
    freq: str,
    test_df: pd.DataFrame | None = None,
    scenario_id: str | None = None,
    override_payload: dict | None = None,
    use_pipeline_api: bool = False,
    csv_path: str | None = None,
    split_ratio: float = 0.8,
    detect_with_model: str = "",
    anthropic_api_key: str = "",
    ollama_url: str = "http://localhost:11434",
) -> tuple[pd.DataFrame | None, str, dict]:
    """Return (forecast_df | None, source_label, metrics_report) for the agent-in-the-loop line.

    Strategy (§14 + §Forecasting 3):
    1. When use_pipeline_api=True AND FastAPI is up:
       call POST /changepoint/run → extract agent yhat from _final_eval.
    2. When Bedrock toggle is OFF: use fallback.py (Claude/Qwen tool-call loop →
       Prophet with chosen intervention).
    3. Last resort: plain changepoint-injection Prophet.

    Returns (None, "", {}) when all paths fail or no changepoints.
    Never raises.
    """
    # ── Path 1: run_scenario via FastAPI (Bedrock pipeline) ──────────────
    if use_pipeline_api and scenario_id:
        try:
            payload: dict = {
                "scenario_id": scenario_id,
                "override": override_payload or {},
                "split_ratio": split_ratio,
            }
            if csv_path:
                payload["csv_path"] = csv_path
            resp = _api_post("/changepoint/run", payload, timeout=300)
            if resp and resp.get("status") == "ok":
                fe = resp.get("final_eval") or {}
                agent_yhat = (fe.get("agent") or {}).get("yhat")
                if agent_yhat and test_df is not None:
                    n_test = len(test_df)
                    if len(agent_yhat) >= n_test:
                        yhat_aligned = agent_yhat[-n_test:]
                    else:
                        yhat_aligned = agent_yhat + [agent_yhat[-1]] * (n_test - len(agent_yhat))
                    df_out = pd.DataFrame({
                        "ds": test_df["ds"].values,
                        "yhat": yhat_aligned,
                        "yhat_lower": yhat_aligned,
                        "yhat_upper": yhat_aligned,
                    })
                    return df_out, "run_scenario (Bedrock)", resp
        except Exception:
            pass  # fall through

    # ── Path 2: fallback.py — full pipeline with baseline comparison (§Forecasting 3) ─
    if not changepoints:
        return None, "", {}

    try:
        from ailf.pipelines.drift.fallback import run_fallback_pipeline  # noqa: PLC0415
        fb_df, fb_label, fb_metrics = run_fallback_pipeline(
            train_df=train_df,
            test_df=test_df,
            changepoints=changepoints,
            prediction_length=prediction_length,
            freq=freq,
            detect_with_model=detect_with_model,
            anthropic_api_key=anthropic_api_key,
            ollama_url=ollama_url,
        )
        if fb_df is not None:
            return fb_df, fb_label, fb_metrics
    except Exception:
        pass  # fall through to plain changepoint injection

    # ── Path 3: plain changepoint-injection Prophet (last resort) ─────────
    try:
        from prophet import Prophet  # noqa: PLC0415

        cp_dates = [
            pd.Timestamp(cp["timestamp"])
            for cp in changepoints
            if cp.get("timestamp")
        ]
        if not cp_dates:
            return None, "", {}

        actual_periods = len(test_df) if test_df is not None else prediction_length
        m = Prophet(
            changepoints=cp_dates,
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
        regressor_cols = [c for c in train_df.columns if c not in ("ds", "y")]
        for col in regressor_cols:
            m.add_regressor(col)
        m.fit(train_df[["ds", "y"] + regressor_cols])
        future = m.make_future_dataframe(periods=actual_periods, freq=freq)
        for col in regressor_cols:
            future[col] = train_df[col].iloc[-1]
        forecast = m.predict(future)
        cutoff = train_df["ds"].max()
        fut = forecast[forecast["ds"] > cutoff][["ds", "yhat", "yhat_lower", "yhat_upper"]]
        return fut, "changepoint-injection Prophet", {}
    except Exception:
        return None, "", {}


def _build_override_json() -> str:
    """Build the --override JSON string from sidebar control values."""
    override: dict = {
        "models": {
            "visual_model_id": visual_model_id,
            "decision_model_id": decision_model_id,
            "aws_region": aws_region,
        },
        "visual_analysis_enabled": visual_analysis_enabled,
        "seed": int(seed),
        "diagnostics": diag_values,
        "agent_tools": tool_values,
    }
    return json.dumps(override)


_FASTAPI_BASE = "http://127.0.0.1:8000"


def _api_get(path: str, timeout: int = 5) -> dict | list | None:
    """GET from the FastAPI server; returns None on any error."""
    import urllib.request as _ur
    try:
        with _ur.urlopen(f"{_FASTAPI_BASE}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _api_post(path: str, payload: dict, timeout: int = 300) -> dict | None:
    """POST JSON to the FastAPI server; returns parsed response dict or None on error."""
    import urllib.request as _ur
    data = json.dumps(payload).encode()
    req = _ur.Request(
        f"{_FASTAPI_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _ur.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _load_run_artifacts(run_id: str) -> dict:
    """Load metrics.json and agent_trace.json from reports/ for a run_id prefix.
    Prefers the FastAPI /changepoint/artifacts endpoint when the server is up.
    """
    # Try FastAPI first
    api_arts = _api_get(f"/changepoint/artifacts/{run_id}")
    if isinstance(api_arts, list) and api_arts:
        latest = api_arts[-1]
        _api_run_id = latest.get("run_id", run_id)
        out: dict = {"_from_api": True, "run_id": _api_run_id}
        if latest.get("metrics"):
            out["metrics.json"] = latest["metrics"]
        if latest.get("final_eval"):
            out["final_eval"] = latest["final_eval"]
        if latest.get("agent_iterations") is not None:
            out["agent_iterations"] = latest["agent_iterations"]
        out["has_forecast_png"] = latest.get("has_forecast_png", False)
        out["has_context_png"]  = latest.get("has_context_png", False)
        out["has_forecast_csv"] = latest.get("has_forecast_csv", False)
        # Resolve local paths — Streamlit and FastAPI share the same filesystem
        run_local = _REPORTS_DIR / _api_run_id
        for _fname, _flag in (
            ("forecast_comparison.png", "has_forecast_png"),
            ("agent_context.png",       "has_context_png"),
            ("forecast_comparison.csv", "has_forecast_csv"),
        ):
            if latest.get(_flag):
                _p = run_local / _fname
                if _p.exists():
                    out[_fname] = _p
        return out

    # Fallback: read from disk
    run_dirs = list(_REPORTS_DIR.glob(f"{run_id}*")) if _REPORTS_DIR.exists() else []
    if not run_dirs:
        return {}
    run_dir = sorted(run_dirs)[-1]
    out = {"run_dir": run_dir}
    for fname in ("metrics.json", "agent_trace.json", "effective_config.json"):
        p = run_dir / fname
        if p.exists():
            try:
                out[fname] = json.loads(p.read_text())
            except Exception:
                pass
    for item in ("forecast_comparison.png", "agent_context.png", "forecast_comparison.csv"):
        p = run_dir / item
        if p.exists():
            out[item] = p
    return out


def _render_artifacts(arts: dict, train_df: pd.DataFrame | None = None) -> None:
    """Render pre-computed run artifacts in the expander.

    When ``train_df`` is provided (the training split), the forecast chart is
    extended to show the full historical context + forecast in a single view.
    """
    if arts.get("_from_api"):
        st.success(f"✅ Artifacts loaded via API — run `{arts.get('run_id','')}`")
    elif "run_dir" in arts:
        st.success(f"Artifacts found on disk: `{arts['run_dir'].name}`")

    if "effective_config.json" in arts:
        with st.expander("effective_config.json", expanded=False):
            st.json(arts["effective_config.json"])

    # MAE comparison
    m = arts.get("metrics.json") or {}
    fe = arts.get("final_eval") or m.get("final_eval") or {}
    if fe:
        cols = st.columns(3)
        for i, (label, key) in enumerate([
            ("Full-history Prophet", "full_history_prophet"),
            ("Naive workflow", "naive_workflow"),
            ("Agent-in-the-loop", "agent"),
        ]):
            mets = (fe.get(key) or {}).get("test_metrics", {})
            mae = mets.get("mae")
            cols[i].metric(label + " MAE", f"{mae:.4f}" if isinstance(mae, float) else "—")

    # Agent iterations
    iters = arts.get("agent_iterations") or (arts.get("agent_trace.json") or {}).get("iterations", [])
    if iters:
        st.markdown(f"**Agent iterations:** {len(iters)}")
        for it in iters:
            prop = it.get("proposal", {})
            beat = it.get("beat_naive")
            icon = "✅" if beat else "❌"
            st.markdown(
                f"{icon} Iter {it.get('i','')} — `{prop.get('tool','')}` | "
                f"{prop.get('rationale','')[:100]}"
            )

    # ── Forecast chart: prefer CSV (interactive Plotly), fall back to PNG ──
    csv_path = arts.get("forecast_comparison.csv")
    if csv_path and pathlib.Path(str(csv_path)).exists():
        try:
            fc_df = pd.read_csv(str(csv_path), parse_dates=["ds"])
            fig_fc = go.Figure()

            # Split into train/forecast regions (new CSV has 'region' column)
            has_region = "region" in fc_df.columns
            _train_rows = fc_df[fc_df["region"] == "train"] if has_region else pd.DataFrame()
            _fc_rows    = fc_df[fc_df["region"] == "forecast"] if has_region else fc_df

            # ── Historical training data from CSV ───────────────────────────
            if not _train_rows.empty and "y_actual" in _train_rows.columns:
                fig_fc.add_trace(go.Scatter(
                    x=_train_rows["ds"], y=_train_rows["y_actual"],
                    mode="lines", name="Historical (train)",
                    line=dict(color="#1a3a5c", width=2),
                ))
                # Train/test boundary marker
                _split_ts = _train_rows["ds"].max()
                fig_fc.add_vline(
                    x=_split_ts.value // 10**6,
                    line_width=1.5, line_dash="dash", line_color="rgba(100,100,100,0.45)",
                    annotation_text="train│test",
                    annotation_position="top right",
                    annotation_font_size=9,
                )
            elif train_df is not None and not train_df.empty:
                # Fallback: use passed train_df
                fig_fc.add_trace(go.Scatter(
                    x=train_df["ds"], y=train_df["y"],
                    mode="lines", name="Historical (train)",
                    line=dict(color="#1a3a5c", width=2),
                ))

            # ── Test-period actual values ────────────────────────────────────
            if "y_actual" in _fc_rows.columns:
                fig_fc.add_trace(go.Scatter(
                    x=_fc_rows["ds"], y=_fc_rows["y_actual"],
                    mode="lines", name="Actual (holdout)",
                    line=dict(color="#2ca02c", width=2),
                ))

            # ── Three forecast lines ─────────────────────────────────────────
            if "yhat_full_history" in _fc_rows.columns:
                fig_fc.add_trace(go.Scatter(
                    x=_fc_rows["ds"], y=_fc_rows["yhat_full_history"],
                    mode="lines", name="Full-history Prophet",
                    line=dict(color="#aec7e8", width=1.5, dash="dot"),
                ))
            if "yhat_naive" in _fc_rows.columns:
                fig_fc.add_trace(go.Scatter(
                    x=_fc_rows["ds"], y=_fc_rows["yhat_naive"],
                    mode="lines", name="naive forecast",
                    line=dict(color="#e05c00", width=2, dash="dash"),
                ))
            if "yhat_agent" in _fc_rows.columns:
                fig_fc.add_trace(go.Scatter(
                    x=_fc_rows["ds"], y=_fc_rows["yhat_agent"],
                    mode="lines", name="agent-in-the-loop forecast",
                    line=dict(color="#b57bee", width=2, dash="dot"),
                ))

            # ── Changepoint verticals from agent_trace (if available) ────────
            _trace = arts.get("agent_trace.json") or {}
            for _cp in _trace.get("changepoints", []):
                _ts = _cp.get("timestamp") or _cp.get("ds")
                if _ts:
                    try:
                        _x = pd.Timestamp(_ts)
                        fig_fc.add_vline(
                            x=_x.value // 10**6,
                            line_width=1.2, line_dash="dot", line_color="rgba(220,53,69,0.55)",
                            annotation_text=_cp.get("type", "cp"),
                            annotation_position="top left",
                            annotation_font_size=9,
                        )
                    except Exception:
                        pass

            _has_train = train_df is not None and not train_df.empty
            fig_fc.update_layout(
                title="Historical + Forecast comparison (run_scenario)" if _has_train
                      else "Forecast comparison (from run_scenario)",
                xaxis=dict(title="Date", rangeslider=dict(visible=True)),
                yaxis=dict(title="y"),
                legend=dict(orientation="h", y=-0.25),
                hovermode="x unified",
                height=520 if _has_train else 420,
            )
            st.plotly_chart(fig_fc, use_container_width=True)
        except Exception as _csv_plot_exc:
            st.warning(f"CSV chart failed: {_csv_plot_exc} — showing PNG instead.")
            csv_path = None  # trigger PNG fallback

    if not csv_path:
        # PNG fallback — show static image
        png_path = arts.get("forecast_comparison.png")
        if png_path and pathlib.Path(str(png_path)).exists():
            st.image(str(png_path), caption="forecast_comparison.png", use_container_width=True)
        elif arts.get("has_forecast_png"):
            st.info("`forecast_comparison.png` on server — check `reports/`.")

    # Agent context image (visual node)
    ctx_path = arts.get("agent_context.png")
    if ctx_path and pathlib.Path(str(ctx_path)).exists():
        st.image(str(ctx_path), caption="agent_context.png (training-only)", use_container_width=True)
    elif arts.get("has_context_png"):
        st.info("`agent_context.png` on server — check `reports/`.")



# ── Execution ─────────────────────────────────────────────────────────────

if run_btn and bedrock_pipeline_enabled:
    # ── Bedrock / run_scenario path (§13 / §Forecasting 4) ───────────────
    # Calls run_scenario directly in-process (lazy import). Falls back to
    # FastAPI /changepoint/run if the in-process call fails (e.g. missing creds).
    # Results are displayed in the same UI layout as Detect & Forecast.
    st.subheader(f"🔬 Bedrock Changepoint Pipeline — `{scenario_id}`")

    _ov_payload: dict = {
        "models": {
            "visual_model_id": visual_model_id,
            "decision_model_id": decision_model_id,
            "aws_region": aws_region,
        },
        "visual_analysis_enabled": visual_analysis_enabled,
        "seed": int(seed),
        "diagnostics": diag_values,
        "agent_tools": tool_values,
    }
    _override_str = json.dumps(_ov_payload)
    _echo_cmd = (
        f"uv run python -m ailf.pipelines.changepoint.pipeline "
        f"--scenario {scenario_id} "
        f"--override '{_override_str}'"
    )
    with st.expander("CLI equivalent", expanded=False):
        st.code(_echo_cmd, language="bash")

    # Determine csv_path for non-registered scenarios
    _bp_csv_path: str | None = None
    if selected_series is not None:
        _bp_csv_path = str(selected_series)

    _bp_result: dict | None = None
    _bp_error: str = ""

    # Load CSV before run so _bp_series_df is in scope for chart rendering
    _bp_series_df = None
    if _bp_csv_path:
        try:
            _bp_series_df = pd.read_csv(_bp_csv_path, parse_dates=["ds"])
        except Exception:
            pass

    # For registered scenarios without a CSV, load the series from scenario metadata
    if _bp_series_df is None:
        try:
            from ailf.pipelines.changepoint.scenarios import load_scenario as _ls  # noqa: PLC0415
            _sc = _ls(scenario_id)
            _bp_series_df = pd.concat([_sc.split.train_df, _sc.split.test_df], ignore_index=True)
        except Exception:
            pass

    # ── Launch run_scenario in background IMMEDIATELY ─────────────────────
    # Start the heavy pipeline before the reasoning stream so both run in parallel.
    import threading as _threading  # noqa: PLC0415
    _rs_result_holder: list = []
    _rs_error_holder:  list = []

    def _run_scenario_thread() -> None:
        try:
            from ailf.pipelines.changepoint.pipeline import run_scenario as _run_scenario  # noqa: PLC0415
            from ailf.core.config.schema import ConfigOverride as _ConfigOverride  # noqa: PLC0415
            _ov_obj = _ConfigOverride.from_dict(_ov_payload)
            _rs_result_holder.append(
                _run_scenario(
                    scenario_id,
                    override=_ov_obj,
                    series_df=_bp_series_df,
                    split_ratio=split_ratio / 100.0,
                    emit_events=True,
                )
            )
        except Exception as _exc:
            _rs_error_holder.append(str(_exc))

    _rs_thread = _threading.Thread(target=_run_scenario_thread, daemon=True)
    _rs_thread.start()

    # ── Step 1: Agent reasoning (live) — runs while pipeline works in background ─
    _bp_train_df: pd.DataFrame | None = None
    if _bp_series_df is not None and not _bp_series_df.empty:
        _bp_train_df, _ = _train_test_split(_bp_series_df, ratio=split_ratio / 100.0)

    if _bp_train_df is not None:
        from ailf.pipelines.drift.llm_reason import detect_streaming as _bp_detect_stream  # noqa: PLC0415
        from ailf.pipelines.drift.llm_reason import detect as _bp_detect  # noqa: PLC0415
        from ailf.pipelines.drift.llm_reason import DetectionResult as _BPDetResult  # noqa: PLC0415
        _cusum_fb = _BPDetResult(changepoints=[], reasoning="", source="cusum", model="cusum")

        _bp_is_streaming = actual_model_id.startswith("claude-") or actual_model_id.startswith("bedrock/")

        agent_col_bp, _ = st.columns([2, 1])
        with agent_col_bp:
            if _bp_is_streaming:
                with st.expander(f"🤖 Agent Analysis — `{actual_model_id}`", expanded=True):
                    st.subheader("Agent reasoning (live)")
                    _bp_reasoning_ph = st.empty()
                    _bp_cp_ph = st.empty()
                    _bp_reasoning_ph.markdown("🤖 _Connecting to model…_")
                    try:
                        _bp_stream = _bp_detect_stream(
                            _bp_train_df,
                            model=actual_model_id,
                            ollama_url=ollama_url,
                            langsmith_tracing=langsmith_tracing,
                            enabled_diagnostics=diag_values,
                            enabled_tools=tool_values,
                        )
                        _bp_chunks: list[str] = []
                        for _bp_chunk in _bp_stream:
                            _bp_chunks.append(_bp_chunk)
                            _bp_reasoning_ph.markdown("".join(_bp_chunks))
                        _bp_stream_detection = _bp_stream.detection_result
                    except Exception as _bp_stream_exc:
                        st.warning(f"⚠️ Live reasoning failed: {_bp_stream_exc}")
                        _bp_stream_detection = _cusum_fb

                    if _bp_stream_detection.changepoints:
                        st.subheader(f"Detected changepoints ({len(_bp_stream_detection.changepoints)})")
                        _bp_cp_df = pd.DataFrame(_bp_stream_detection.changepoints)
                        _bp_disp_cols = [c for c in ["timestamp", "type", "direction", "confidence", "reason"]
                                         if c in _bp_cp_df.columns]
                        _bp_cp_ph.dataframe(_bp_cp_df[_bp_disp_cols], use_container_width=True, hide_index=True)
                    else:
                        _bp_cp_ph.info("No changepoints detected in pre-analysis.")

                    if getattr(_bp_stream_detection, "langsmith_run_url", ""):
                        if _bp_stream_detection.langsmith_run_url.startswith("http"):
                            st.markdown(f"🔗 [View LangSmith trace]({_bp_stream_detection.langsmith_run_url})")
                        else:
                            st.caption(f"LangSmith: {_bp_stream_detection.langsmith_run_url}")
            else:
                # Qwen / Ollama — non-streaming, show reasoning in expander
                try:
                    with st.spinner("🤖 Agent detecting changepoints and drifts…"):
                        _bp_qwen_det = _bp_detect(
                            _bp_train_df, model=actual_model_id,
                            ollama_url=ollama_url, langsmith_tracing=langsmith_tracing,
                            enabled_diagnostics=diag_values, enabled_tools=tool_values,
                        )
                except Exception as _bp_q_exc:
                    st.warning(f"⚠️ Detection error: {_bp_q_exc} — using CUSUM fallback.")
                    _bp_qwen_det = _cusum_fb

                _bp_src_label = (
                    f"✅ Qwen via Ollama (`{_bp_qwen_det.model}`)"
                    if _bp_qwen_det.source == "qwen"
                    else "⚠️ CUSUM fallback"
                )
                with st.expander(f"🤖 Agent Analysis — {_bp_src_label}", expanded=True):
                    if _bp_qwen_det.reasoning:
                        st.subheader("Agent reasoning")
                        st.text_area(
                            label="", value=_bp_qwen_det.reasoning,
                            height=260, label_visibility="collapsed",
                        )
                    if _bp_qwen_det.changepoints:
                        st.subheader(f"Detected changepoints ({len(_bp_qwen_det.changepoints)})")
                        _bp_cp_df2 = pd.DataFrame(_bp_qwen_det.changepoints)
                        _bp_disp2 = [c for c in ["timestamp", "type", "direction", "confidence", "reason"]
                                     if c in _bp_cp_df2.columns]
                        st.dataframe(_bp_cp_df2[_bp_disp2], use_container_width=True, hide_index=True)
                    else:
                        st.info("No changepoints detected.")

    # ── Wait for pipeline thread — poll so Streamlit can render as soon as done ──
    import time as _time  # noqa: PLC0415
    st.divider()
    _pipe_status = st.empty()
    _POLL_S = 0.4
    _MAX_WAIT_S = 300
    _elapsed = 0
    _dots = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    _di = 0
    while _rs_thread.is_alive() and _elapsed < _MAX_WAIT_S:
        _pipe_status.info(f"{_dots[_di % len(_dots)]} Agent pipeline running… ({int(_elapsed)}s)")
        _time.sleep(_POLL_S)
        _elapsed += _POLL_S
        _di += 1

    if _rs_thread.is_alive():
        _rs_error_holder.append(f"run_scenario timed out after {_MAX_WAIT_S}s")
    _pipe_status.empty()

    if _rs_error_holder:
        _bp_error = _rs_error_holder[0]
    elif _rs_result_holder:
        _bp_result = _rs_result_holder[0]

    if _bp_result is None:
        st.warning(f"⚠️ run_scenario failed: {_bp_error} — trying FastAPI…")
        _bp_api_resp = _api_post("/changepoint/run", {
            "scenario_id": scenario_id,
            "override": _ov_payload,
            "csv_path": _bp_csv_path,
            "split_ratio": split_ratio / 100.0,
        })
        if _bp_api_resp and _bp_api_resp.get("status") == "ok":
            _bp_result = _bp_api_resp
            st.success("✅ Completed via FastAPI fallback.")
        else:
            _err = (_bp_api_resp or {}).get("error", "API unreachable") if _bp_api_resp else "API unreachable"
            st.error(f"❌ Both paths failed: {_err}")
            st.stop()
    else:
        st.success(f"✅ Pipeline complete — run ID: `{scenario_id}-{int(seed)}`")

    # ── Display results in same layout as Detect & Forecast ──────────────
    _bp_fe = _bp_result.get("final_eval") or {}
    _bp_winner = _bp_result.get("winner", "—")
    st.caption(f"Winner: **{_bp_winner}**")

    # Forecast chart from CSV (preferred) or stored artifacts
    _bp_arts = _load_run_artifacts(scenario_id)
    if _bp_arts:
        _bp_train_slice = None
        if _bp_series_df is not None and not _bp_series_df.empty:
            _n_train = int(len(_bp_series_df) * split_ratio / 100.0)
            _bp_train_slice = _bp_series_df.iloc[:_n_train].copy()
        _render_artifacts(_bp_arts, train_df=_bp_train_slice)
    elif _bp_fe:
        # Build inline chart from yhat arrays in final_eval
        try:
            _bp_test_n = len((_bp_fe.get("agent") or {}).get("yhat") or [])
            if _bp_test_n > 0:
                _bp_ds = pd.date_range(
                    end=pd.Timestamp("today"), periods=_bp_test_n, freq="D"
                )
                _bp_fig = go.Figure()
                for _bpname, _bpkey, _bpcolor, _bpdash in [
                    ("Full-history Prophet", "full_history_prophet", "#aec7e8", "dot"),
                    ("naive forecast",       "naive_workflow",        "#e05c00", "dash"),
                    ("agent-in-the-loop",    "agent",                 "#b57bee", "dot"),
                ]:
                    _bpy = (_bp_fe.get(_bpkey) or {}).get("yhat", [])
                    if _bpy:
                        _bp_fig.add_trace(go.Scatter(
                            x=_bp_ds, y=_bpy[:_bp_test_n],
                            mode="lines", name=_bpname,
                            line=dict(color=_bpcolor, width=2, dash=_bpdash),
                        ))
                _bp_fig.update_layout(
                    title="Forecast comparison (run_scenario)",
                    xaxis=dict(title="Date"), yaxis=dict(title="y"),
                    legend=dict(orientation="h", y=-0.25),
                    hovermode="x unified", height=400,
                )
                st.plotly_chart(_bp_fig, use_container_width=True)
        except Exception:
            pass

    # MAE metrics row
    if _bp_fe:
        _bc1, _bc2, _bc3 = st.columns(3)
        for _bcol, _blbl, _bkey in [
            (_bc1, "Full-history Prophet", "full_history_prophet"),
            (_bc2, "Naive workflow",       "naive_workflow"),
            (_bc3, "Agent-in-the-loop",   "agent"),
        ]:
            _bmets = (_bp_fe.get(_bkey) or {}).get("test_metrics", {})
            _bmae  = _bmets.get("mae")
            _bcol.metric(_blbl + " MAE", f"{_bmae:.4f}" if isinstance(_bmae, float) else "—")

elif run_btn:
    # Resolve data
    if source_mode == "Upload CSV":
        if uploaded_file is None:
            st.error("Please upload a CSV file.")
            st.stop()
        df = _load_df(io.BytesIO(uploaded_file.read()))
        series_label = uploaded_file.name
    else:
        if selected_series is not None:
            df = _load_df(selected_series)
            series_label = selected_series.stem.replace("_train", "")
        else:
            # No CSV in pocs/data/ — load from registered scenario metadata
            try:
                from ailf.pipelines.changepoint.scenarios import load_scenario as _ls_df  # noqa: PLC0415
                _sc_df = _ls_df(scenario_id)
                df = pd.concat(
                    [_sc_df.split.train_df, _sc_df.split.test_df],
                    ignore_index=True,
                )
                series_label = scenario_id
            except Exception as _sc_exc:
                st.error(f"No series available for `{scenario_id}`: {_sc_exc}")
                st.stop()

    train_df, test_df = _train_test_split(df, ratio=split_ratio / 100.0)
    split_note = (
        f"  ·  train {len(train_df)} rows ({split_ratio}%) / holdout {len(test_df)} rows"
        if test_df is not None else ""
    )
    st.subheader(f"Series: `{series_label}`  ({len(df)} rows{split_note})")

    # ── PNG agent-context image (mirrors run_scenario visual_inspection_node) ──
    import tempfile as _tf  # noqa: PLC0415
    import matplotlib as _mpl  # noqa: PLC0415
    _mpl.use("Agg")
    import matplotlib.pyplot as _plt  # noqa: PLC0415

    _png_path: pathlib.Path | None = None
    try:
        _fig, _ax = _plt.subplots(figsize=(13, 5))
        _ax.plot(train_df["ds"], train_df["y"], color="#1f77b4", linewidth=1.2)
        _ax.axvline(train_df["ds"].max(), color="black", linewidth=1.3,
                    linestyle="--", label="forecast origin")
        _ax.set_title(f"{series_label} — training history (agent context)")
        _ax.set_xlabel("date")
        _ax.set_ylabel("y")
        _ax.legend(loc="best")
        _fig.tight_layout()
        _tmp = _tf.NamedTemporaryFile(suffix=".png", delete=False)
        _png_path = pathlib.Path(_tmp.name)
        _tmp.close()
        _fig.savefig(_png_path, dpi=150)
        _plt.close(_fig)
        with st.expander("🖼️ Agent context image (training history only — SC-002)", expanded=visual_analysis_enabled):
            st.image(str(_png_path), caption="Only training rows; no test data, no annotations.",
                     use_container_width=True)
    except Exception as _png_exc:
        st.warning(f"PNG generation failed: {_png_exc}")

    # ── Visual inspection via LLM (mirrors visual_inspection_node in run_scenario) ──
    _is_vision_capable = actual_model_id.startswith("claude-")
    if visual_analysis_enabled and _is_vision_capable and _png_path is not None:
        try:
            from ailf.core.models.llm import AnthropicStructuredClient as _AVClient, ModelWrapper as _MW  # noqa: PLC0415
            from ailf.pipelines.changepoint.schemas import VisualInspectionResult as _VIR  # noqa: PLC0415
            from ailf.core.prompts.loader import load_prompt as _lp  # noqa: PLC0415

            _cp_prompt_dir = pathlib.Path(__file__).resolve().parent.parent / "changepoint" / "prompts"
            _visual_prompt = _lp(_cp_prompt_dir, "visual_inspection", 1)
            _vi_client = _AVClient(actual_model_id, max_tokens=2000)
            _vi_wrapper = _MW(_vi_client, actual_model_id)
            with st.spinner("👁️ Visual model inspecting training history PNG…"):
                _vi_result = _vi_wrapper.invoke_structured_with_image(
                    prompt=_visual_prompt,
                    image_path=_png_path,
                    schema=_VIR,
                )
            with st.expander("👁️ Visual inspection (from PNG)", expanded=True):
                st.markdown(f"**Pattern**: {_vi_result.pattern_summary}")
                if _vi_result.observations:
                    st.markdown("**Observations**")
                    for _obs in _vi_result.observations:
                        st.markdown(f"- {_obs}")
                if _vi_result.hypotheses:
                    st.markdown("**Failure mode hypotheses**")
                    for _h in _vi_result.hypotheses:
                        st.markdown(f"- {_h}")
                if _vi_result.uncertainties:
                    st.caption("Uncertainties: " + " · ".join(_vi_result.uncertainties))
        except Exception as _vi_exc:
            st.warning(f"Visual inspection skipped ({actual_model_id}): {_vi_exc}")

    # ── Step 1: Agent detection — with graceful fallback (§15) ──────────
    from ailf.pipelines.drift.llm_reason import DetectionResult as _DetResult  # noqa: PLC0415
    _cusum_fallback = _DetResult(changepoints=[], reasoning="", source="cusum", model="cusum")

    is_streaming = actual_model_id.startswith("claude-") or actual_model_id.startswith("bedrock/")

    agent_col, _ = st.columns([2, 1])
    with agent_col:
        if is_streaming:
            with st.expander(f"🤖 Agent Analysis — `{actual_model_id}`", expanded=True):
                st.subheader("Agent reasoning (live)")
                reasoning_placeholder = st.empty()
                cp_placeholder = st.empty()

                reasoning_placeholder.markdown("🤖 _Connecting to model…_")
                try:
                    stream = detect_streaming(
                        train_df,
                        model=actual_model_id,
                        ollama_url=ollama_url,
                        langsmith_tracing=langsmith_tracing,
                        enabled_diagnostics=diag_values,
                        enabled_tools=tool_values,
                    )
                    chunks: list[str] = []
                    for chunk in stream:
                        chunks.append(chunk)
                        reasoning_placeholder.markdown("".join(chunks))
                    detection = stream.detection_result
                except Exception as _det_exc:
                    st.warning(f"⚠️ Detection error: {_det_exc} — using CUSUM fallback.")
                    detection = _cusum_fallback

                if detection.changepoints:
                    st.subheader(f"Detected changepoints ({len(detection.changepoints)})")
                    cp_df = pd.DataFrame(detection.changepoints)
                    display_cols = [c for c in ["timestamp", "type", "direction", "confidence", "reason"]
                                    if c in cp_df.columns]
                    cp_placeholder.dataframe(cp_df[display_cols], use_container_width=True, hide_index=True)
                else:
                    cp_placeholder.info("No changepoints detected.")

                if getattr(detection, "langsmith_run_url", ""):
                    if detection.langsmith_run_url.startswith("http"):
                        st.markdown(f"🔗 [View LangSmith trace]({detection.langsmith_run_url})")
                    else:
                        st.caption(f"LangSmith: {detection.langsmith_run_url}")
        else:
            try:
                with st.spinner("🤖 Agent detecting changepoints and drifts…"):
                    detection = detect(train_df, model=actual_model_id, ollama_url=ollama_url, langsmith_tracing=langsmith_tracing,
                                       enabled_diagnostics=diag_values, enabled_tools=tool_values)
            except Exception as _det_exc:
                st.warning(f"⚠️ Detection error: {_det_exc} — using CUSUM fallback.")
                detection = _cusum_fallback

            source_label = (
                f"✅ Qwen via Ollama (`{detection.model}`)"
                if detection.source == "qwen"
                else "⚠️ CUSUM fallback (Ollama unavailable)"
            )
            with st.expander(f"🤖 Agent Analysis — {source_label}", expanded=True):
                if detection.reasoning:
                    st.subheader("Agent reasoning")
                    st.text_area(
                        label="",
                        value=detection.reasoning,
                        height=260,
                        label_visibility="collapsed",
                    )
                if detection.changepoints:
                    st.subheader(f"Detected changepoints ({len(detection.changepoints)})")
                    cp_df = pd.DataFrame(detection.changepoints)
                    display_cols = [c for c in ["timestamp", "type", "direction", "confidence", "reason"]
                                    if c in cp_df.columns]
                    st.dataframe(cp_df[display_cols], use_container_width=True, hide_index=True)
                else:
                    st.info("No changepoints detected.")

    # ── Show hidden diagnostics (config_resolved transparency) ────────────
    _hidden_diags = [k for k, v in diag_values.items() if not v]
    _hidden_tools = [k for k, v in tool_values.items() if not v]
    if _hidden_diags or _hidden_tools:
        with st.expander("🔒 Hidden diagnostics / disabled tools (config_resolved)", expanded=False):
            if _hidden_diags:
                st.caption(f"Hidden from agent: {', '.join(_hidden_diags)}")
            if _hidden_tools:
                st.caption(f"Disabled tools: {', '.join(_hidden_tools)}")

    # ── Step 2: Prophet forecast (naive + agent-in-the-loop) ─────────────
    with st.spinner("📈 Fitting Prophet forecasts…"):
        try:
            fut_part, _ = _run_prophet(train_df, prediction_length, freq, test_df)
        except Exception as exc:
            st.error(f"Prophet (naive) error: {exc}")
            st.stop()

        # Agent-in-the-loop forecast (§14)
        # Path 1: run_scenario via FastAPI when Bedrock pipeline toggle is on
        # Path 2: Prophet with agent-detected changepoints injected (universal fallback)
        agent_fut: pd.DataFrame | None = None
        agent_source: str = ""
        agent_metrics: dict = {}
        _override_payload = {
            "models": {
                "visual_model_id": visual_model_id,
                "decision_model_id": decision_model_id,
                "aws_region": aws_region,
            },
            "visual_analysis_enabled": visual_analysis_enabled,
            "seed": int(seed),
            "diagnostics": diag_values,
            "agent_tools": tool_values,
        }
        # Resolve csv_path for pocs/data/ CSVs (§14i)
        _csv_path_for_api: str | None = None
        if selected_series is not None:
            _csv_path_for_api = str(selected_series)

        # Resolve Anthropic API key for fallback.py
        try:
            from ailf.pipelines.drift.llm_reason import _claude_api_key as _get_anthropic_key  # noqa: PLC0415
            _anthropic_key = _get_anthropic_key() or ""
        except Exception:
            _anthropic_key = ""

        with st.spinner("🔬 Running agent-in-the-loop pipeline…"):
            try:
                agent_fut, agent_source, agent_metrics = _run_agent_forecast(
                    train_df,
                    detection.changepoints,
                    prediction_length,
                    freq,
                    test_df,
                    scenario_id=scenario_id,
                    override_payload=_override_payload,
                    use_pipeline_api=bedrock_pipeline_enabled and _api_get("/changepoint/scenarios") is not None,
                    csv_path=_csv_path_for_api,
                    split_ratio=split_ratio / 100.0,
                    detect_with_model=actual_model_id,
                    anthropic_api_key=_anthropic_key,
                    ollama_url=ollama_url,
                )
            except Exception as exc:
                st.warning(f"Agent-in-the-loop forecast skipped: {exc}")
                agent_metrics = {}

    st.subheader("Forecast")
    if agent_fut is not None:
        st.caption(
            f"🟣 **agent-in-the-loop forecast** ({agent_source}) — "
            "changepoints drive Prophet | "
            "🟠 **naive forecast** — plain Prophet auto-changepoints"
        )
    fig = _build_chart(train_df, fut_part, detection.changepoints, test_df, agent_fut)
    st.plotly_chart(fig, use_container_width=True)

    # ── Forecast metrics row ──────────────────────────────────────────────
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    mc1.metric("Train rows",       len(train_df))
    mc2.metric("Holdout rows",     len(test_df) if test_df is not None else "—")
    mc3.metric("Forecast horizon", f"{len(fut_part)} days")
    mc4.metric("Changepoints",     len(detection.changepoints))
    mc5.metric("Agent forecast",   agent_source[:30] if agent_source else "—")

    # ── §15: Baseline comparison + agent trace tab ────────────────────────
    if agent_metrics:
        with st.expander("📊 Baseline Comparison & Agent Trace", expanded=False):
            fe = agent_metrics.get("final_eval") or {}
            winner = agent_metrics.get("winner", "—")
            st.markdown(f"**Winner:** `{winner}` | Source: `{agent_metrics.get('source', '—')}`")

            # MAE comparison table
            if fe:
                st.subheader("Test metrics comparison")
                comparison_rows = []
                for method_key, label in [
                    ("full_history_prophet", "Full-history Prophet"),
                    ("naive_workflow",        "Naive workflow"),
                    ("agent",                 "Agent-in-the-loop"),
                ]:
                    mets = (fe.get(method_key) or {}).get("test_metrics") or {}
                    comparison_rows.append({
                        "Method": label,
                        "MAE":  f"{mets.get('mae', float('nan')):.4f}" if mets else "—",
                        "RMSE": f"{mets.get('rmse', float('nan')):.4f}" if mets else "—",
                        "Tool": (fe.get(method_key) or {}).get("tool", ""),
                    })
                st.dataframe(
                    pd.DataFrame(comparison_rows),
                    use_container_width=True, hide_index=True,
                )

                # Highlight winner
                agent_mae  = (fe.get("agent") or {}).get("test_metrics", {}).get("mae")
                naive_mae  = (fe.get("naive_workflow") or {}).get("test_metrics", {}).get("mae")
                if isinstance(agent_mae, float) and isinstance(naive_mae, float):
                    if agent_mae < naive_mae:
                        st.success(
                            f"✅ Agent-in-the-loop beat naive by "
                            f"{naive_mae - agent_mae:.4f} MAE "
                            f"({100*(naive_mae-agent_mae)/naive_mae:.1f}% improvement)"
                        )
                    else:
                        st.warning(
                            f"⚠️ Naive workflow won by {agent_mae - naive_mae:.4f} MAE. "
                            "Consider selecting a different model or adjusting diagnostics."
                        )

            # Agent trace — iterations
            iterations = agent_metrics.get("iterations") or []
            if iterations:
                st.subheader("Agent iterations")
                for it in iterations:
                    prop = it.get("proposal", {})
                    beat = it.get("beat_naive")
                    icon = "✅" if beat else "❌"
                    val_res = it.get("val_result") or {}
                    st.markdown(
                        f"{icon} **Iter {it.get('i','')}** — tool: `{prop.get('tool','')}`  "
                        f"val MAE: {val_res.get('val_mae', '—')}  "
                        f"naive MAE: {val_res.get('naive_val_mae', '—')}  \n"
                        f"> {prop.get('rationale','')[:120]}"
                    )

            # Also load artifacts from disk (metrics.json + agent_trace.json)
            _disk_arts = _load_run_artifacts(scenario_id)
            if _disk_arts:
                st.divider()
                st.caption("Also showing pre-computed artifacts from disk:")
                _render_artifacts(_disk_arts)

else:
    st.info(
        "👈 Configure your data source and parameters in the sidebar, then click **Detect & Forecast**.\n\n"
        "The agent will analyse changepoints and drifts **before** fitting Prophet."
    )
