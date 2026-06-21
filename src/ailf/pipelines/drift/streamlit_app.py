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
_REPORTS_DIR = _PROJECT_ROOT / "reports"

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
    source_mode = st.radio("Input mode", ["Upload CSV", "Data Scenario"])

    uploaded_file = None
    selected_series = None

    if source_mode == "Upload CSV":
        uploaded_file = st.file_uploader(
            "CSV file (ds, y columns)", type=["csv"],
            help="Must have `ds` (date) and `y` (numeric) columns.",
        )
    else:
        # Always show the 5 committed changepoint scenarios + any extra pocs/data CSVs
        _cp_scenarios = list(_SCENARIOS)
        _extra_csvs = [
            p for p in sorted(_DATA_DIR.glob("*_train.csv")) if _DATA_DIR.exists()
            if p.stem.replace("_train", "") not in _cp_scenarios
        ] if _DATA_DIR.exists() else []
        _all_scenario_names = _cp_scenarios + [p.stem.replace("_train", "") for p in _extra_csvs]

        _scenario_idx = st.selectbox(
            "Data Scenario",
            range(len(_all_scenario_names)),
            format_func=lambda i: _all_scenario_names[i],
        )
        _chosen_scenario_name = _all_scenario_names[_scenario_idx]

        # Try to find a matching CSV in pocs/data/
        _csv_candidate = _DATA_DIR / f"{_chosen_scenario_name}_train.csv"
        if _csv_candidate.exists():
            selected_series = _csv_candidate
        elif _scenario_idx >= len(_cp_scenarios):
            # Extra CSV from pocs/data
            selected_series = _extra_csvs[_scenario_idx - len(_cp_scenarios)]
        else:
            selected_series = None
            st.info(
                f"No CSV found for `{_chosen_scenario_name}` in `pocs/data/`. "
                "Use the pipeline panel below to run and generate artifacts."
            )

    # Derive scenario_id from selection (used by pipeline panel below)
    if source_mode == "Data Scenario":
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
        value="us.anthropic.claude-opus-4-8",
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
            st.checkbox(
                t, value=True, disabled=True, key=f"tool_{t}",
                help=_TOOL_HELP.get(t, "Always-on fallback — cannot be disabled."),
            )
            tool_values[t] = True
        else:
            tool_values[t] = st.checkbox(
                t, value=True, key=f"tool_{t}",
                help=_TOOL_HELP.get(t, ""),
            )

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
        st.caption(
            "Traces sent to `LANGSMITH_API_URL` (default: "
            "`https://apac.smith.langchain.com`) under project "
            "`agent-in-the-loop-forecasting`. Trace URL appears after detection."
        )

    st.divider()

    # ── Bedrock Changepoint Pipeline toggle (§13) ─────────────────────────
    bedrock_pipeline_enabled = st.toggle(
        "Bedrock Changepoint Pipeline",
        value=False,
        help=(
            "When ON: clicking the button below runs the full Bedrock agent pipeline "
            "via POST /changepoint/run and shows its artifacts. "
            "Requires FastAPI server running and AWS Bedrock creds in .env. "
            "When OFF: runs the standard drift detection + Prophet forecast."
        ),
    )
    if bedrock_pipeline_enabled:
        st.caption(
            "⚠️ Bedrock pipeline active — the button below invokes "
            "`ailf.pipelines.changepoint.pipeline` on the server."
        )

    if bedrock_pipeline_enabled:
        run_btn = st.button(
            "▶️ Run Bedrock Pipeline",
            type="primary",
            use_container_width=True,
            help="POST /changepoint/run with current scenario + override settings.",
        )
    else:
        run_btn = st.button("🔍 Detect & Forecast", type="primary", use_container_width=True)


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
) -> tuple[pd.DataFrame | None, str]:
    """Return (forecast_df | None, source_label) for the agent-in-the-loop forecast line.

    Strategy (§14 + §Forecasting 3):
    1. When use_pipeline_api=True AND FastAPI is up:
       call POST /changepoint/run → extract agent yhat from _final_eval.
    2. When Bedrock toggle is OFF: use fallback.py (Claude/Qwen tool-call loop →
       Prophet with chosen intervention).
    3. Last resort: plain changepoint-injection Prophet.

    Returns (None, "") when all paths fail or no changepoints.
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
            resp, _resp_err = _api_post("/changepoint/run", payload, timeout=300)
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
                    return df_out, "run_scenario (Bedrock)"
        except Exception:
            pass  # fall through

    # ── Path 2: fallback.py — Claude/Qwen tool-call loop (§Forecasting 3) ─
    if not changepoints:
        return None, ""

    try:
        from ailf.pipelines.drift.fallback import run_fallback_pipeline  # noqa: PLC0415
        return run_fallback_pipeline(
            train_df=train_df,
            test_df=test_df,
            changepoints=changepoints,
            prediction_length=prediction_length,
            freq=freq,
            detect_with_model=detect_with_model,
            anthropic_api_key=anthropic_api_key,
            ollama_url=ollama_url,
        )
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
            return None, ""

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
        return fut, "changepoint-injection Prophet"
    except Exception:
        return None, ""


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


def _api_post(path: str, payload: dict, timeout: int = 300) -> tuple[dict | None, str]:
    """POST JSON to the FastAPI server. Returns (response_dict, error_msg).
    On success error_msg is "". On any error response_dict is None."""
    import urllib.error as _ue
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
            return json.loads(r.read().decode()), ""
    except _ue.HTTPError as exc:
        try:
            body = exc.read().decode()
        except Exception:
            body = str(exc)
        return None, f"HTTP {exc.code}: {body[:300]}"
    except _ue.URLError as exc:
        return None, f"Connection error: {exc.reason}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _load_run_artifacts(run_id: str) -> dict:
    """Load metrics.json and agent_trace.json from reports/ for a run_id prefix.
    Prefers the FastAPI /changepoint/artifacts endpoint when the server is up.
    """
    # Try FastAPI first
    api_arts = _api_get(f"/changepoint/artifacts/{run_id}")
    if isinstance(api_arts, list) and api_arts:
        latest = api_arts[-1]
        out: dict = {"_from_api": True}
        if latest.get("metrics"):
            out["metrics.json"] = latest["metrics"]
        if latest.get("final_eval"):
            out["final_eval"] = latest["final_eval"]
        if latest.get("agent_iterations") is not None:
            out["agent_iterations"] = latest["agent_iterations"]
        out["has_forecast_png"] = latest.get("has_forecast_png", False)
        out["has_context_png"]  = latest.get("has_context_png", False)
        out["run_id"] = latest.get("run_id", run_id)
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
    for img in ("forecast_comparison.png", "agent_context.png"):
        p = run_dir / img
        if p.exists():
            out[img] = p
    return out


def _render_artifacts(arts: dict) -> None:
    """Render pre-computed run artifacts in the expander."""
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

    # Images (disk path or flag only)
    for img_key in ("forecast_comparison.png", "agent_context.png"):
        img_path = arts.get(img_key)
        if img_path and pathlib.Path(str(img_path)).exists():
            st.image(str(img_path), caption=img_key, use_container_width=True)
        elif arts.get(f"has_{img_key.replace('.png','').replace('forecast_comparison','forecast').replace('agent_context','context')}_png"):
            st.info(f"`{img_key}` exists on server disk — view at `reports/`.")



# ── Execution ─────────────────────────────────────────────────────────────

if run_btn and bedrock_pipeline_enabled:
    # ── Bedrock pipeline path (§13) ──────────────────────────────────────
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
    with st.expander("Command being executed", expanded=False):
        st.code(_echo_cmd, language="bash")

    _bp_alive = _api_get("/changepoint/scenarios") is not None
    if not _bp_alive:
        st.error(
            "❌ FastAPI server is not running. "
            "Start it with: `uvicorn ailf.pipelines.drift.pipeline:app --reload`"
        )
        st.code(_echo_cmd, language="bash")
        st.stop()

    with st.spinner(f"Running Bedrock pipeline for `{scenario_id}`…"):
        _bp_resp, _bp_err = _api_post("/changepoint/run", {
            "scenario_id": scenario_id,
            "override": _ov_payload,
        })

    if _bp_resp is None:
        st.error(f"❌ API request failed: {_bp_err}")
        st.stop()

    _bp_status = _bp_resp.get("status")
    if _bp_status == "ok":
        st.success(f"✅ Pipeline complete — run ID: `{_bp_resp.get('run_id')}`")

        # MAE comparison
        _bp_fe = _bp_resp.get("final_eval") or {}
        if _bp_fe:
            _bc1, _bc2, _bc3 = st.columns(3)
            for _bcol, _blbl, _bkey in [
                (_bc1, "Full-history Prophet", "full_history_prophet"),
                (_bc2, "Naive workflow", "naive_workflow"),
                (_bc3, "Agent-in-the-loop", "agent"),
            ]:
                _bmets = (_bp_fe.get(_bkey) or {}).get("test_metrics", {})
                _bmae = _bmets.get("mae")
                _bcol.metric(_blbl + " MAE", f"{_bmae:.4f}" if isinstance(_bmae, float) else "—")

        # Show all artifacts from disk/API
        _bp_arts = _load_run_artifacts(scenario_id)
        if _bp_arts:
            _render_artifacts(_bp_arts)

    elif _bp_status == "unavailable":
        st.warning(f"⚠️ Bedrock unavailable: {_bp_resp.get('error')}")
        st.info("Run the CLI command above manually once Bedrock creds are configured in `.env`.")
    else:
        st.error(f"Pipeline error: {_bp_resp.get('error')}")

elif run_btn:
    # Resolve data
    if source_mode == "Upload CSV":
        if uploaded_file is None:
            st.error("Please upload a CSV file.")
            st.stop()
        df = _load_df(io.BytesIO(uploaded_file.read()))
        series_label = uploaded_file.name
    else:
        if selected_series is None:
            st.error("No series available.")
            st.stop()
        df = _load_df(selected_series)
        series_label = selected_series.stem.replace("_train", "")

    train_df, test_df = _train_test_split(df, ratio=split_ratio / 100.0)
    split_note = (
        f"  ·  train {len(train_df)} rows ({split_ratio}%) / holdout {len(test_df)} rows"
        if test_df is not None else ""
    )
    st.subheader(f"Series: `{series_label}`  ({len(df)} rows{split_note})")

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

                try:
                    with st.spinner("🤖 Agent detecting changepoints and drifts…"):
                        stream = detect_streaming(
                            train_df,
                            model=actual_model_id,
                            ollama_url=ollama_url,
                            langsmith_tracing=langsmith_tracing,
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
                    detection = detect(train_df, model=actual_model_id, ollama_url=ollama_url)
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

        with st.spinner("🔬 Computing agent-in-the-loop forecast…"):
            try:
                agent_fut, agent_source = _run_agent_forecast(
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

    st.subheader("Forecast")
    if agent_fut is not None:
        st.caption(
            f"🟣 **agent-in-the-loop forecast** ({agent_source}) — "
            "changepoints drive Prophet | "
            "🟠 **naive forecast** — plain Prophet auto-changepoints"
        )
    fig = _build_chart(train_df, fut_part, detection.changepoints, test_df, agent_fut)
    st.plotly_chart(fig, use_container_width=True)

    # Metrics
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    mc1.metric("Train rows",       len(train_df))
    mc2.metric("Holdout rows",     len(test_df) if test_df is not None else "—")
    mc3.metric("Forecast horizon", f"{len(fut_part)} days")
    mc4.metric("Changepoints",     len(detection.changepoints))
    mc5.metric("Agent forecast",   agent_source if agent_source else "—")

else:
    st.info(
        "👈 Configure your data source and parameters in the sidebar, then click **Detect & Forecast**.\n\n"
        "The agent will analyse changepoints and drifts **before** fitting Prophet."
    )
