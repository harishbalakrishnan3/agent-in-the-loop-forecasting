"""Non-Bedrock fallback pipeline for the agent-in-the-loop forecast (§Forecasting 3).

When the Bedrock Changepoint Pipeline toggle is OFF, this module provides an
alternative path that uses Claude (Anthropic SDK) or Qwen (Ollama) directly —
without AWS credentials — to:

1. Detect changepoints from the uploaded CSV using the existing ``detect()`` backend.
2. Reason about which intervention tool to apply (recent_window / step_regressor).
3. Apply the tool to tune Prophet hyperparameters.
4. Return a forecast DataFrame suitable for the agent-in-the-loop purple line.

This mirrors what ``run_scenario`` does via Bedrock + LangGraph, but uses a simpler
single-pass tool-call loop that works with any supported ``detect_with`` model.

Run via ``_run_agent_forecast_fallback(...)`` from streamlit_app.py.
"""

from __future__ import annotations

import json
import warnings
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Intervention tool helpers — lightweight wrappers that need only a DataFrame
# (no DiagnosticsBundle, no SeriesSplit, no LangGraph)
# ---------------------------------------------------------------------------

_TOOL_MENU = """
Available intervention tools (choose one based on the changepoint analysis):

1. recent_window(window_start_index: int)
   Fit Prophet only on data AFTER the latest changepoint. Best for level-shift or
   permanent regime changes.

2. step_regressor(changepoint_indices: list[int])
   Add binary step regressors at each changepoint. Best for multiple level shifts
   that must stay in the model history.

3. full_history_default()
   Use full history with no special intervention (baseline / fallback).

Return JSON: {"tool": "<tool_name>", "params": {...}, "rationale": "<brief reason>"}
"""


def _call_tool(
    tool_name: str,
    params: dict[str, Any],
    train_df: pd.DataFrame,
    test_ds: pd.Series,
    changepoints: list[dict],
) -> pd.Series | None:
    """Apply the chosen intervention tool; return yhat Series aligned to test_ds.

    Returns None if the tool cannot be applied (e.g. no changepoints for recent_window).
    """
    from prophet import Prophet  # noqa: PLC0415

    cp_timestamps = [
        pd.Timestamp(cp["timestamp"])
        for cp in changepoints
        if cp.get("timestamp")
    ]

    if tool_name == "recent_window":
        # Slice training data from the latest changepoint onward
        window_start_idx = params.get("window_start_index")
        if window_start_idx is None and cp_timestamps:
            # Use the latest changepoint as the window start
            latest_cp = max(cp_timestamps)
            window_start_idx = int((train_df["ds"] >= latest_cp).idxmax())
        if window_start_idx is None or window_start_idx >= len(train_df) - 10:
            return None
        train_slice = train_df.iloc[window_start_idx:].copy().reset_index(drop=True)
        m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
        m.fit(train_slice[["ds", "y"]])
        future = pd.DataFrame({"ds": pd.to_datetime(test_ds.reset_index(drop=True))})
        return m.predict(future)["yhat"]

    elif tool_name == "step_regressor":
        # Add binary step regressors at the detected changepoints
        cp_indices = params.get("changepoint_indices")
        if not cp_indices and cp_timestamps:
            cp_indices = [
                int((train_df["ds"] >= ts).idxmax())
                for ts in cp_timestamps
                if (train_df["ds"] >= ts).any()
            ]
        if not cp_indices:
            return None

        m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
        all_ds = pd.concat([train_df["ds"], pd.to_datetime(test_ds)], ignore_index=True)
        for i, cp_idx in enumerate(sorted(set(cp_indices))):
            if cp_idx >= len(train_df):
                continue
            cp_ds = pd.Timestamp(train_df["ds"].iloc[cp_idx])
            col = f"step_{i}"
            train_df = train_df.copy()
            train_df[col] = (pd.to_datetime(train_df["ds"]) >= cp_ds).astype(float)
            m.add_regressor(col)

        reg_cols = [c for c in train_df.columns if c.startswith("step_")]
        m.fit(train_df[["ds", "y"] + reg_cols])
        future = pd.DataFrame({"ds": pd.to_datetime(test_ds.reset_index(drop=True))})
        for col in reg_cols:
            cp_ds_str = col.split("_", 1)[1] if "_" in col else ""
            try:
                cp_ds = pd.Timestamp(train_df["ds"].iloc[int(col.split("_")[-1])])
            except Exception:
                cp_ds = pd.Timestamp(train_df["ds"].iloc[-1])
            future[col] = (future["ds"] >= cp_ds).astype(float)
        return m.predict(future)["yhat"]

    else:
        # full_history_default — plain Prophet on full train
        m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
        m.fit(train_df[["ds", "y"]])
        future = pd.DataFrame({"ds": pd.to_datetime(test_ds.reset_index(drop=True))})
        return m.predict(future)["yhat"]


def _ask_claude_for_tool(
    detect_result_json: str,
    series_summary: str,
    api_key: str,
    model: str = "claude-sonnet-4-5",
) -> dict:
    """Use Claude Anthropic SDK to pick an intervention tool via structured tool use.

    Returns {"tool": str, "params": dict, "rationale": str} or empty dict on failure.
    """
    try:
        import anthropic  # noqa: PLC0415

        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            f"You are a time-series forecasting expert. A changepoint detection agent has "
            f"analysed a time series and found these results:\n\n{detect_result_json}\n\n"
            f"Series summary: {series_summary}\n\n"
            f"{_TOOL_MENU}\n\n"
            "Choose the best intervention tool for this series. Return ONLY valid JSON."
        )
        response = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text if response.content else ""
        # Extract JSON
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])
    except Exception:
        pass
    return {}


def _ask_qwen_for_tool(
    detect_result_json: str,
    series_summary: str,
    ollama_url: str = "http://localhost:11434",
    model: str = "qwen3.5:4b",
) -> dict:
    """Use Qwen via Ollama to pick an intervention tool.

    Returns {"tool": str, "params": dict, "rationale": str} or empty dict on failure.
    """
    import urllib.request  # noqa: PLC0415

    prompt = (
        f"You are a time-series forecasting expert. Detected changepoints:\n{detect_result_json}\n\n"
        f"Series: {series_summary}\n\n{_TOOL_MENU}\n\n"
        "Return ONLY valid JSON with tool, params, rationale."
    )
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 256},
    }).encode()
    req = urllib.request.Request(
        f"{ollama_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            obj = json.loads(r.read().decode())
        text = obj.get("message", {}).get("content", "")
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_fallback_pipeline(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame | None,
    changepoints: list[dict],
    prediction_length: int,
    freq: str,
    detect_with_model: str,
    anthropic_api_key: str = "",
    ollama_url: str = "http://localhost:11434",
) -> tuple[pd.DataFrame | None, str]:
    """Run the non-Bedrock agent-in-the-loop pipeline (§Forecasting 3).

    Steps:
    1. Summarise the changepoint detection result.
    2. Ask Claude or Qwen to pick an intervention tool from the menu.
    3. Apply the tool (Prophet with selected hyperparameter adjustments).
    4. Return (forecast_df, source_label) aligned to test_df or prediction_length.

    Falls back to plain changepoint-injection Prophet if the tool call fails.
    Never raises — all exceptions degrade gracefully.

    Parameters
    ----------
    train_df : DataFrame with ds, y columns (training region).
    test_df  : Optional holdout DataFrame; aligns forecast if present.
    changepoints : list of dicts from detect(); must have "timestamp" field.
    prediction_length : fallback horizon when test_df is None.
    freq : pandas frequency string.
    detect_with_model : the model ID used for detection (routes to Claude or Qwen).
    anthropic_api_key : ANTHROPIC_API_KEY; required for Claude-based tool call.
    ollama_url : Ollama base URL for Qwen-based tool call.
    """
    # Future timestamps
    from prophet import Prophet  # noqa: PLC0415

    n_future = len(test_df) if test_df is not None else prediction_length
    future_ds = (
        test_df["ds"].reset_index(drop=True)
        if test_df is not None
        else pd.date_range(
            start=train_df["ds"].max() + pd.Timedelta("1D"),
            periods=prediction_length,
            freq=freq,
        )
    )

    # Summarise detection result for the LLM
    detect_summary = json.dumps(
        [
            {
                "timestamp": cp.get("timestamp"),
                "type": cp.get("type"),
                "direction": cp.get("direction"),
                "confidence": cp.get("confidence"),
                "reason": cp.get("reason", ""),
            }
            for cp in changepoints[:8]  # truncate for token budget
        ],
        indent=2,
    )
    series_info = (
        f"{len(train_df)} training rows, "
        f"{len(changepoints)} changepoints detected, "
        f"date range {train_df['ds'].min().date()} to {train_df['ds'].max().date()}"
    )

    # Ask the LLM to pick a tool
    tool_choice: dict = {}
    is_claude = detect_with_model.startswith("claude-") or detect_with_model.startswith("bedrock/")

    if is_claude and anthropic_api_key:
        # Use the direct Anthropic model (strip bedrock/ prefix)
        api_model = detect_with_model.removeprefix("bedrock/")
        if "/" in api_model or ":" in api_model:
            api_model = "claude-sonnet-4-5"  # safe fallback for unknown IDs
        tool_choice = _ask_claude_for_tool(
            detect_summary, series_info,
            api_key=anthropic_api_key,
            model=api_model,
        )
    elif not detect_with_model.startswith("claude-"):
        # Qwen / Ollama path
        tool_choice = _ask_qwen_for_tool(
            detect_summary, series_info,
            ollama_url=ollama_url,
            model=detect_with_model,
        )

    tool_name = tool_choice.get("tool", "full_history_default")
    params     = tool_choice.get("params", {})
    rationale  = tool_choice.get("rationale", "fallback pipeline")

    # Apply the chosen tool
    try:
        yhat = _call_tool(tool_name, params, train_df, pd.Series(future_ds), changepoints)
    except Exception:
        yhat = None

    if yhat is None:
        # Last resort: plain Prophet
        try:
            m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
            m.fit(train_df[["ds", "y"]])
            future_frame = pd.DataFrame({"ds": pd.to_datetime(pd.Series(future_ds))})
            yhat = m.predict(future_frame)["yhat"]
            tool_name = "plain Prophet (fallback)"
        except Exception:
            return None, ""

    yhat_list = list(yhat)
    df_out = pd.DataFrame({
        "ds": pd.to_datetime(pd.Series(future_ds)).values,
        "yhat": yhat_list,
        "yhat_lower": yhat_list,
        "yhat_upper": yhat_list,
    })
    source_label = f"fallback: {tool_name} ({rationale[:60]})" if rationale else f"fallback: {tool_name}"
    return df_out, source_label
