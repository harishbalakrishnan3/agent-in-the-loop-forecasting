"""Streamlit UI for drift detection and Prophet forecasting.

SPEC §13: Display Qwen agent reasoning while detecting changepoints/drifts
before invoking Prophet.

Run with:
    PYTHONPATH=src streamlit run src/ailf/pipelines/drift/streamlit_app.py

Features
--------
- Upload a CSV (ds, y) or pick a pre-generated series from pocs/data/
- Agent (Qwen / CUSUM fallback) detects changepoints — shows live reasoning
- Prophet is then fitted and the forecast is rendered interactively
- Prediction length and frequency controls
- Historical solid line, forecast dashed line, 95% CI shaded (Plotly tonexty)
- Changepoints marked as vertical lines
"""

from __future__ import annotations

import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")

import io

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Project path bootstrap ───────────────────────────────────────────────
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[4]
_SRC = _PROJECT_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ailf.pipelines.drift.qwen_detect import DEFAULT_MODEL, detect  # noqa: E402

# ── Pre-generated data dir ───────────────────────────────────────────────
_DATA_DIR = _PROJECT_ROOT / "pocs" / "data"

# ── Page config ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Drift Forecast UI",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Drift Forecast Explorer")
st.caption(
    "Agent-in-the-Loop Forecasting · "
    "[FastAPI UI](http://127.0.0.1:8000/forecast/ui) · "
    "[Swagger](http://127.0.0.1:8000/docs)"
)

# ── Sidebar controls ─────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Controls")

    # Data source
    st.subheader("Data Source")
    source_mode = st.radio("Input mode", ["Upload CSV", "Pre-generated series"])

    uploaded_file = None
    selected_series = None

    if source_mode == "Upload CSV":
        uploaded_file = st.file_uploader(
            "CSV file (ds, y columns)", type=["csv"], help="Must have `ds` (date) and `y` (numeric) columns."
        )
    else:
        # List available _train.csv files
        train_csvs = sorted(_DATA_DIR.glob("*_train.csv")) if _DATA_DIR.exists() else []
        if train_csvs:
            names = [p.stem.replace("_train", "") for p in train_csvs]
            idx = st.selectbox("Series", range(len(names)), format_func=lambda i: names[i])
            selected_series = train_csvs[idx]
        else:
            st.warning("No pre-generated CSVs found in pocs/data/. Run `generate_and_forecast.py` first.")

    st.divider()

    # Forecast params
    st.subheader("Forecast Parameters")
    prediction_length = st.number_input("Prediction length (days)", min_value=1, max_value=3650, value=365)
    freq = st.selectbox("Frequency", ["D", "W", "MS"], index=0, help="D=daily, W=weekly, MS=monthly-start")

    st.divider()

    # Agent params
    st.subheader("Agent (Qwen)")
    ollama_model = st.text_input("Ollama model", value=DEFAULT_MODEL, help="e.g. qwen3.5:4b")
    ollama_url   = st.text_input("Ollama URL", value="http://localhost:11434")

    run_btn = st.button("🔍 Detect & Forecast", type="primary", use_container_width=True)


# ── Main area ────────────────────────────────────────────────────────────

def _load_df(source: str | pathlib.Path | io.BytesIO) -> pd.DataFrame:
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


def _train_test_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Split into train (years 1-4) and test (year 5) when series >= 500 days.

    Returns (train_df, test_df).  test_df is None when the series is too short
    to hold out a full year.
    """
    if len(df) >= 500:
        split_idx = len(df) - 365
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
    """Fit Prophet on train_df and forecast prediction_length steps ahead.

    If test_df is provided the forecast covers exactly ``len(test_df)`` periods
    so the predicted values align with the held-out actuals for comparison.
    """
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
) -> go.Figure:
    fig = go.Figure()

    # Historical solid line
    fig.add_trace(go.Scatter(
        x=df["ds"], y=df["y"],
        mode="lines", name="Historical (train)",
        line=dict(color="#1a3a5c", width=2),
    ))

    # CI upper (invisible, for fill)
    fig.add_trace(go.Scatter(
        x=fut_part["ds"], y=fut_part["yhat_upper"],
        mode="lines", name="Upper bound",
        line=dict(width=0), showlegend=False,
    ))

    # CI lower — fills to upper (tonexty)
    fig.add_trace(go.Scatter(
        x=fut_part["ds"], y=fut_part["yhat_lower"],
        fill="tonexty", fillcolor="rgba(70,130,180,0.15)",
        mode="lines", name="95% CI",
        line=dict(width=0),
    ))

    # Forecast dashed line
    fig.add_trace(go.Scatter(
        x=fut_part["ds"], y=fut_part["yhat"],
        mode="lines", name="Forecast (Prophet)",
        line=dict(color="#e05c00", width=2, dash="dash"),
    ))

    # Actual year-5 holdout overlay (when available)
    if test_df is not None and not test_df.empty:
        fig.add_trace(go.Scatter(
            x=test_df["ds"], y=test_df["y"],
            mode="lines", name="Actual (year 5 holdout)",
            line=dict(color="#2ca02c", width=2),
        ))

    # Changepoints as vertical lines — convert string timestamps to pd.Timestamp
    # so Plotly's internal _mean() doesn't crash on string arithmetic
    for cp in changepoints:
        ts = cp.get("timestamp")
        if ts:
            try:
                x_val = pd.Timestamp(ts)
            except Exception:
                continue
            fig.add_vline(
                x=x_val.value // 10**6,  # epoch ms — avoids Plotly string arithmetic
                line_width=1.5, line_dash="dot", line_color="rgba(220,53,69,0.55)",
                annotation_text=cp.get("type", "cp"),
                annotation_position="top left",
                annotation_font_size=9,
            )

    fig.update_layout(
        title=f"Historical vs. Forecast — horizon: {len(fut_part)} days"
              + (f" | {len(changepoints)} changepoints" if changepoints else ""),
        xaxis=dict(title="Date", rangeslider=dict(visible=True)),
        yaxis=dict(title="y"),
        legend=dict(orientation="h", y=-0.2),
        hovermode="x unified",
        height=480,
    )
    return fig


# ── Execution ─────────────────────────────────────────────────────────────

if run_btn:
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

    train_df, test_df = _train_test_split(df)
    split_note = f"  ·  train {len(train_df)} rows / holdout {len(test_df)} rows" if test_df is not None else ""
    st.subheader(f"Series: `{series_label}`  ({len(df)} rows{split_note})")

    # ── Step 1: Agent detection ──────────────────────────────────────────
    agent_col, _ = st.columns([2, 1])
    with agent_col:
        with st.spinner("🤖 Agent detecting changepoints and drifts…"):
            detection = detect(train_df, model=ollama_model, ollama_url=ollama_url)

    source_label = (
        f"✅ Qwen via Ollama (`{detection.model}`)"
        if detection.source == "qwen"
        else "⚠️ CUSUM fallback (Ollama unavailable)"
    )

    with st.expander(f"🤖 Agent Analysis — {source_label}", expanded=True):
        # Reasoning narrative
        if detection.reasoning:
            st.subheader("Agent reasoning")
            st.text_area(
                label="",
                value=detection.reasoning,
                height=260,
                label_visibility="collapsed",
            )

        # Changepoints table
        if detection.changepoints:
            st.subheader(f"Detected changepoints ({len(detection.changepoints)})")
            cp_df = pd.DataFrame(detection.changepoints)
            display_cols = [c for c in ["timestamp", "type", "direction", "confidence", "reason"]
                            if c in cp_df.columns]
            st.dataframe(cp_df[display_cols], use_container_width=True, hide_index=True)
        else:
            st.info("No changepoints detected.")

    # ── Step 2: Prophet forecast ─────────────────────────────────────────
    with st.spinner("📈 Fitting Prophet forecast…"):
        try:
            fut_part, full_forecast = _run_prophet(train_df, prediction_length, freq, test_df)
        except Exception as exc:
            st.error(f"Prophet error: {exc}")
            st.stop()

    st.subheader("Forecast")
    fig = _build_chart(train_df, fut_part, detection.changepoints, test_df)
    st.plotly_chart(fig, use_container_width=True)

    # Metrics
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Train rows",       len(train_df))
    mc2.metric("Holdout rows",     len(test_df) if test_df is not None else "—")
    mc3.metric("Forecast horizon", f"{len(fut_part)} days")
    mc4.metric("Changepoints",     len(detection.changepoints))

else:
    st.info(
        "👈 Configure your data source and parameters in the sidebar, then click **Detect & Forecast**.\n\n"
        "The agent will analyse changepoints and drifts **before** fitting Prophet."
    )
