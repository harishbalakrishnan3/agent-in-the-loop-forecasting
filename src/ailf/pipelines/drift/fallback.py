"""Non-Bedrock fallback pipeline for the agent-in-the-loop forecast (§Forecasting 3).

When the Bedrock Changepoint Pipeline toggle is OFF, this module performs all the same
steps as ``run_scenario`` — baseline comparison, validation scoring, agent tool selection,
test scoring — using Claude (Anthropic SDK) or Qwen (Ollama) instead of Bedrock:

1. Compute baselines: full-history Prophet + naive windowed Prophet.
2. Ask Claude or Qwen to pick an intervention tool from the menu (validation-guided).
3. Validate: score agent yhat on a validation split; verify it beats naive baseline.
4. Score all three methods on the test split.
5. Return (forecast_df, source_label, metrics_report) where metrics_report matches the
   shape of ``metrics.json`` written by ``run_scenario``.

Run via ``run_fallback_pipeline(...)`` from streamlit_app.py.
"""

from __future__ import annotations

import json
import warnings
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Tool menu — shown to the LLM to pick an intervention
# ---------------------------------------------------------------------------

_TOOL_MENU = """
Available intervention tools (choose one based on the changepoint analysis):

1. recent_window(window_start_index: int)
   Fit Prophet only on data AFTER the latest changepoint. Best for level-shift or
   permanent regime changes where the old regime is no longer relevant.
   PREFER this when 1-2 changepoints are detected and the latest one is a clear level shift.

2. step_regressor(changepoint_indices: list[int])
   Add binary step regressors at each changepoint. Best for multiple level shifts
   that must stay in the model history.
   PREFER this when 3+ changepoints are detected or when the series has multiple regimes.

3. full_history_default()
   Use full history with no special intervention. ONLY use this if NO changepoints were
   detected, or if changepoints are negligibly small (confidence < 0.3).
   DO NOT choose this if any significant changepoint was detected.

CRITICAL RULE: If changepoints list is non-empty and confidence >= 0.3, you MUST choose
either recent_window or step_regressor. Choosing full_history_default when changepoints
exist produces the same forecast as the naive baseline — no improvement.

Return JSON: {"tool": "<tool_name>", "params": {...}, "rationale": "<brief reason>"}
"""

# ---------------------------------------------------------------------------
# Intervention tool helpers — lightweight Prophet wrappers (no LangGraph)
# ---------------------------------------------------------------------------

def _call_tool(
    tool_name: str,
    params: dict[str, Any],
    train_df: pd.DataFrame,
    test_ds: pd.Series,
    changepoints: list[dict],
) -> pd.Series | None:
    """Apply the chosen intervention tool; return yhat Series aligned to test_ds."""
    from prophet import Prophet  # noqa: PLC0415

    cp_timestamps = [
        pd.Timestamp(cp["timestamp"])
        for cp in changepoints
        if cp.get("timestamp")
    ]

    if tool_name == "recent_window":
        window_start_idx = params.get("window_start_index")
        if window_start_idx is None and cp_timestamps:
            latest_cp = max(cp_timestamps)
            _mask = pd.to_datetime(train_df["ds"]) >= latest_cp
            if _mask.any():
                window_start_idx = int(_mask.idxmax())
            else:
                # Changepoint is after train end — use second-to-last quarter as fallback
                window_start_idx = max(1, len(train_df) // 4 * 3)
        if window_start_idx is None or window_start_idx <= 0 or window_start_idx >= len(train_df) - 10:
            return None
        train_slice = train_df.iloc[window_start_idx:].copy().reset_index(drop=True)
        m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
        m.fit(train_slice[["ds", "y"]])
        future = pd.DataFrame({"ds": pd.to_datetime(test_ds.reset_index(drop=True))})
        return m.predict(future)["yhat"]

    elif tool_name == "step_regressor":
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
        train_df = train_df.copy()
        for i, cp_idx in enumerate(sorted(set(cp_indices))):
            if cp_idx >= len(train_df):
                continue
            cp_ds = pd.Timestamp(train_df["ds"].iloc[cp_idx])
            col = f"step_{i}"
            train_df[col] = (pd.to_datetime(train_df["ds"]) >= cp_ds).astype(float)
            m.add_regressor(col)

        reg_cols = [c for c in train_df.columns if c.startswith("step_")]
        m.fit(train_df[["ds", "y"] + reg_cols])
        future = pd.DataFrame({"ds": pd.to_datetime(test_ds.reset_index(drop=True))})
        for i, col in enumerate(reg_cols):
            cp_idx = sorted(set(cp_indices))[i]
            cp_ds = pd.Timestamp(train_df["ds"].iloc[cp_idx])
            future[col] = (future["ds"] >= cp_ds).astype(float)
        return m.predict(future)["yhat"]

    else:
        # full_history_default — plain Prophet on full train
        m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
        m.fit(train_df[["ds", "y"]])
        future = pd.DataFrame({"ds": pd.to_datetime(test_ds.reset_index(drop=True))})
        return m.predict(future)["yhat"]


# ---------------------------------------------------------------------------
# LLM tool-choice calls
# ---------------------------------------------------------------------------

def _ask_claude_for_tool(
    detect_result_json: str,
    series_summary: str,
    api_key: str,
    model: str = "claude-sonnet-4-5",
) -> dict:
    """Use Claude Anthropic SDK to pick an intervention tool."""
    try:
        import anthropic  # noqa: PLC0415

        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            f"You are a time-series forecasting expert. A changepoint detection agent has "
            f"analysed a time series and found these results:\n\n{detect_result_json}\n\n"
            f"Series summary: {series_summary}\n\n"
            f"{_TOOL_MENU}\n\n"
            "IMPORTANT: If any changepoints were detected with confidence >= 0.3, you MUST "
            "choose recent_window or step_regressor — NOT full_history_default.\n"
            "Return ONLY valid JSON."
        )
        response = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text if response.content else ""
        start = text.find("{")
        end = text.rfind("}")
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
    """Use Qwen via Ollama to pick an intervention tool."""
    import urllib.request  # noqa: PLC0415

    prompt = (
        f"You are a time-series forecasting expert. Detected changepoints:\n{detect_result_json}\n\n"
        f"Series: {series_summary}\n\n{_TOOL_MENU}\n\n"
        "IMPORTANT: If changepoints list is non-empty, you MUST choose recent_window or "
        "step_regressor. Do NOT choose full_history_default when changepoints exist.\n"
        "Return ONLY valid JSON: {\"tool\": \"...\", \"params\": {...}, \"rationale\": \"...\"}. "
        "No other text, no markdown, no explanation."
    )
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
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
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Metric helpers (pure functions, no dependencies beyond numpy)
# ---------------------------------------------------------------------------

def _mae(y_true: list[float], yhat: list[float]) -> float:
    a = np.array(y_true, dtype=float)
    b = np.array(yhat, dtype=float)
    return float(np.mean(np.abs(a - b)))


def _rmse(y_true: list[float], yhat: list[float]) -> float:
    a = np.array(y_true, dtype=float)
    b = np.array(yhat, dtype=float)
    return float(np.sqrt(np.mean((a - b) ** 2)))


def _score_metrics(y_true: list[float], yhat: list[float]) -> dict[str, float]:
    return {"mae": _mae(y_true, yhat), "rmse": _rmse(y_true, yhat)}


# ---------------------------------------------------------------------------
# Baseline Prophet helpers (no SeriesSplit — work on plain DataFrames)
# ---------------------------------------------------------------------------

def _prophet_predict(
    fit_df: pd.DataFrame,
    future_ds: pd.Series,
) -> list[float]:
    """Fit plain Prophet on fit_df, predict on future_ds; return yhat list."""
    from prophet import Prophet  # noqa: PLC0415
    m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
    m.fit(fit_df[["ds", "y"]])
    future = pd.DataFrame({"ds": pd.to_datetime(future_ds.reset_index(drop=True))})
    return m.predict(future)["yhat"].tolist()


def _split_val_test(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame | None,
    val_frac: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split train_df into fit + validation; keep test_df as-is (may be None).

    Returns (fit_df, val_df, test_df_or_empty).
    """
    n = len(train_df)
    val_rows = max(1, int(n * val_frac))
    fit_end  = n - val_rows
    fit_df  = train_df.iloc[:fit_end].copy().reset_index(drop=True)
    val_df  = train_df.iloc[fit_end:].copy().reset_index(drop=True)
    test_out = test_df if test_df is not None else pd.DataFrame(columns=["ds", "y"])
    return fit_df, val_df, test_out


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
) -> tuple[pd.DataFrame | None, str, dict]:
    """Run the non-Bedrock agent-in-the-loop pipeline (§Forecasting 3).

    Mirrors all steps of ``run_scenario``:
    1. Split training data into fit + validation regions.
    2. Compute baselines: full-history Prophet + naive windowed Prophet.
    3. Ask Claude or Qwen to pick an intervention tool (same menu as run_scenario).
    4. Validate: score agent yhat on validation split; verify it beats naive baseline.
    5. Score all three methods on the test split (when test_df is provided).
    6. Build a metrics_report dict matching ``metrics.json`` written by run_scenario.

    Returns:
        (forecast_df | None, source_label, metrics_report)

    metrics_report keys:
        winner, final_eval.agent, final_eval.full_history_prophet,
        final_eval.naive_workflow, iterations

    Never raises — all exceptions degrade gracefully (returns None, "", {}).
    """
    from prophet import Prophet  # noqa: PLC0415

    try:
        # ── 1. Validation split ──────────────────────────────────────────
        fit_df, val_df, _test = _split_val_test(train_df, test_df)
        future_ds_val  = val_df["ds"]
        future_ds_test = _test["ds"] if not _test.empty else pd.date_range(
            start=train_df["ds"].max() + pd.Timedelta("1D"),
            periods=prediction_length, freq=freq,
        )

        # ── 2. Baselines ─────────────────────────────────────────────────
        try:
            full_val_yhat = _prophet_predict(fit_df, future_ds_val)
            full_val_metrics = _score_metrics(val_df["y"].tolist(), full_val_yhat)
        except Exception:
            full_val_yhat = [float("nan")] * len(val_df)
            full_val_metrics = {"mae": float("inf"), "rmse": float("inf")}

        # Naive: try each changepoint window on validation, pick best MAE
        naive_best_mae = full_val_metrics["mae"]
        naive_best_start = 0
        cp_timestamps = [
            pd.Timestamp(cp["timestamp"])
            for cp in changepoints if cp.get("timestamp")
        ]
        for cp_ts in cp_timestamps:
            try:
                _cp_mask = pd.to_datetime(fit_df["ds"]) >= cp_ts
                if not _cp_mask.any():
                    continue
                cp_idx = int(_cp_mask.idxmax())
                if cp_idx <= 0 or cp_idx >= len(fit_df) - 10:
                    continue
                window_yhat = _prophet_predict(fit_df.iloc[cp_idx:], future_ds_val)
                window_mae = _mae(val_df["y"].tolist(), window_yhat)
                if window_mae < naive_best_mae:
                    naive_best_mae = window_mae
                    naive_best_start = cp_idx
            except Exception:
                continue

        # ── 3. LLM tool selection ─────────────────────────────────────────
        detect_summary = json.dumps(
            [
                {
                    "timestamp": cp.get("timestamp"),
                    "type": cp.get("type"),
                    "direction": cp.get("direction"),
                    "confidence": cp.get("confidence"),
                    "reason": cp.get("reason", ""),
                    "val_naive_mae": round(naive_best_mae, 4),
                }
                for cp in changepoints[:8]
            ],
            indent=2,
        )
        series_info = (
            f"{len(train_df)} training rows, {len(changepoints)} changepoints, "
            f"naive baseline val MAE={naive_best_mae:.4f}, "
            f"date range {train_df['ds'].min().date()} to {train_df['ds'].max().date()}"
        )

        tool_choice: dict = {}
        is_claude = (
            detect_with_model.startswith("claude-")
            or detect_with_model.startswith("bedrock/")
        )

        if is_claude and anthropic_api_key:
            api_model = detect_with_model.removeprefix("bedrock/")
            if "/" in api_model or ":" in api_model:
                api_model = "claude-sonnet-4-5"
            tool_choice = _ask_claude_for_tool(
                detect_summary, series_info,
                api_key=anthropic_api_key, model=api_model,
            )
        elif not is_claude:
            tool_choice = _ask_qwen_for_tool(
                detect_summary, series_info,
                ollama_url=ollama_url, model=detect_with_model,
            )

        tool_name = tool_choice.get("tool", "full_history_default")
        params     = tool_choice.get("params", {})
        rationale  = tool_choice.get("rationale", "fallback pipeline")

        # Auto-override: force intervention when changepoints exist
        significant_cps = [
            cp for cp in changepoints
            if cp.get("confidence", 1.0) >= 0.3 or "confidence" not in cp
        ]
        if tool_name == "full_history_default" and significant_cps:
            tool_name = "recent_window"
            params    = {}
            rationale = (
                f"[auto-override] LLM chose default despite "
                f"{len(significant_cps)} changepoints; using recent_window"
            )

        # ── 4. Validation scoring ─────────────────────────────────────────
        try:
            agent_val_yhat_series = _call_tool(
                tool_name, params, fit_df, future_ds_val, changepoints
            )
            agent_val_yhat = list(agent_val_yhat_series) if agent_val_yhat_series is not None else []
        except Exception:
            agent_val_yhat = []

        agent_val_mae = (
            _mae(val_df["y"].tolist(), agent_val_yhat)
            if len(agent_val_yhat) == len(val_df)
            else float("inf")
        )
        beat_naive = agent_val_mae < naive_best_mae
        val_iteration = {
            "i": 1,
            "proposal": {"tool": tool_name, "params": params, "rationale": rationale},
            "val_result": {"val_mae": agent_val_mae, "naive_val_mae": naive_best_mae},
            "beat_naive": beat_naive,
        }

        # ── 5. Test scoring ───────────────────────────────────────────────
        try:
            agent_test_yhat_series = _call_tool(
                tool_name, params, train_df, pd.Series(future_ds_test), changepoints
            )
            agent_test_yhat = list(agent_test_yhat_series) if agent_test_yhat_series is not None else []
        except Exception:
            agent_test_yhat = []

        try:
            full_test_yhat = _prophet_predict(train_df, pd.Series(future_ds_test))
        except Exception:
            full_test_yhat = [float("nan")] * len(future_ds_test)

        try:
            naive_fit_start = naive_best_start
            naive_test_yhat = _prophet_predict(
                train_df.iloc[naive_fit_start:], pd.Series(future_ds_test)
            )
        except Exception:
            naive_test_yhat = [float("nan")] * len(future_ds_test)

        if not _test.empty:
            y_test_true = _test["y"].tolist()
            agent_test_metrics = (
                _score_metrics(y_test_true, agent_test_yhat)
                if len(agent_test_yhat) == len(y_test_true)
                else {"mae": float("nan"), "rmse": float("nan")}
            )
            full_test_metrics  = _score_metrics(y_test_true, full_test_yhat)
            naive_test_metrics = _score_metrics(y_test_true, naive_test_yhat)
        else:
            agent_test_metrics = full_test_metrics = naive_test_metrics = {}

        # ── 6. Build metrics report ───────────────────────────────────────
        metrics_report: dict = {
            "winner": "agent" if beat_naive else "naive_workflow",
            "source": "fallback_pipeline",
            "model": detect_with_model,
            "final_eval": {
                "agent": {
                    "tool": tool_name,
                    "yhat": agent_test_yhat,
                    "test_metrics": agent_test_metrics,
                    "val_metrics": {"mae": agent_val_mae},
                    "beat_naive": beat_naive,
                },
                "full_history_prophet": {
                    "yhat": full_test_yhat,
                    "test_metrics": full_test_metrics,
                },
                "naive_workflow": {
                    "yhat": naive_test_yhat,
                    "test_metrics": naive_test_metrics,
                    "window_start": naive_best_start,
                },
            },
            "iterations": [val_iteration],
        }

        # ── 7. Build output forecast DataFrame ───────────────────────────
        if agent_test_yhat:
            yhat_list = agent_test_yhat
        else:
            # Fallback to changepoint-injection Prophet
            try:
                m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True)
                cp_dates = [pd.Timestamp(cp["timestamp"]) for cp in changepoints if cp.get("timestamp")]
                if cp_dates:
                    m = Prophet(
                        changepoints=cp_dates,
                        daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=True,
                    )
                m.fit(train_df[["ds", "y"]])
                future_frame = pd.DataFrame({"ds": pd.to_datetime(pd.Series(future_ds_test))})
                yhat_list = m.predict(future_frame)["yhat"].tolist()
                tool_name = "changepoint-injection Prophet"
            except Exception:
                return None, "", {}

        df_out = pd.DataFrame({
            "ds": pd.to_datetime(pd.Series(future_ds_test)).values,
            "yhat": yhat_list,
            "yhat_lower": yhat_list,
            "yhat_upper": yhat_list,
        })
        source_label = (
            f"fallback: {tool_name} | val MAE={agent_val_mae:.3f} "
            f"{'✅ beats naive' if beat_naive else '⚠️ naive wins'}"
        )
        return df_out, source_label, metrics_report

    except Exception:
        return None, "", {}
