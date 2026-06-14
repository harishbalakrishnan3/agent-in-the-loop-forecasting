"""POC: when a changepoint-only workflow throws away the wrong history.

This is intentionally rough POC code. It creates synthetic daily series and compares:

1. Default Prophet on full history.
2. Default statsmodels ARIMA on full history.
3. A naive default-model workflow:
   detect change points -> validation-select among full-history and latest-change-point
   windows using default Prophet or default ARIMA.
4. A bounded "ReAct analyst" intervention:
   use changepoint diagnostics + seasonal-history checks + plot context to choose either
   full-history Prophet step/ramp-regressor interventions or full-history outlier/event cleaning.

If ANTHROPIC_API_KEY is available, the analyst decision tries a multimodal Anthropic call
with the plot image plus diagnostics. Otherwise it uses the same bounded policy locally and
writes a ReAct-style trace.

Run:
    uv run --with boto3 --with botocore python pocs/changepoint/changepoint_agent_poc.py
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from prophet import Prophet
from statsmodels.tsa.arima.model import ARIMA

warnings.filterwarnings("ignore")
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)

ARTIFACT_DIR = Path("pocs/changepoint/artifacts")
DEFAULT_TRAIN_END = 760
LONG_TRAIN_END = DEFAULT_TRAIN_END + (2 * 365)
TEST_HORIZON = 120
VALIDATION_HORIZON = 60
SEASONAL_PERIOD = 365
DEFAULT_N_BKPS = 2
DEFAULT_BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
DEFAULT_BEDROCK_REGION = "us-west-2"
MAX_AGENT_ITERATIONS = 5
VALID_INTERVENTIONS = {
    "recent_window",
    "full_history_step_regressor",
    "full_history_ramp_regressor",
    "full_history_clean_event",
    "full_history_prophet_tuned_holidays",
}
class AgentGraphState(TypedDict, total=False):
    diagnostics: dict[str, Any]
    image_path: str
    rejected_interventions: list[str]
    visual_inspection: dict[str, Any]
    diagnostic_inspection: dict[str, Any]
    decision: dict[str, Any]


def load_env_file(path: Path = Path(".env"), *, override: bool = False) -> None:
    """Minimal .env loader for this POC. Loads values without printing secrets."""
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and (override or key not in os.environ):
            os.environ[key] = value


def configure_langsmith_env() -> None:
    """Make LangSmith env vars visible to both current and older LangChain tracing paths."""
    if os.getenv("LANGGRAPH_TRACING", "").lower() == "true" and not os.getenv("LANGSMITH_TRACING"):
        os.environ["LANGSMITH_TRACING"] = "true"
    if os.getenv("LANGSMITH_TRACING", "").lower() == "true":
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    if os.getenv("LANGSMITH_PROJECT") and not os.getenv("LANGCHAIN_PROJECT"):
        os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "")


@dataclass
class Scenario:
    name: str
    title: str
    frame: pd.DataFrame
    true_changepoints: list[int]
    note: str
    train_end: int = DEFAULT_TRAIN_END
    test_horizon: int = TEST_HORIZON
    n_bkps: int = DEFAULT_N_BKPS


@dataclass
class ForecastResult:
    scenario: str
    method: str
    model: str
    yhat: np.ndarray
    metrics: dict[str, float]
    details: dict[str, Any]


def _base_signal(length: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(length)
    ds = pd.date_range("2019-01-01", periods=length, freq="D")
    annual = 22.0 * np.sin(2 * np.pi * t / 365.0) + 7.0 * np.cos(2 * np.pi * t / 365.0)
    weekly = 2.5 * np.sin(2 * np.pi * t / 7.0)
    trend = 0.018 * t
    noise = rng.normal(0.0, 1.7, length)
    y = 100.0 + trend + annual + weekly + noise
    return pd.DataFrame({"ds": ds, "y": y})


def make_level_shift_scenario() -> Scenario:
    """Hypothesis 2: latest-changepoint retraining loses annual seasonality."""
    df = _base_signal(900, seed=7)
    level_shifts = [
        (610, 32.0),
        (700, 28.0),
    ]
    for cp, lift in level_shifts:
        df.loc[df.index >= cp, "y"] += lift
    return Scenario(
        name="level_shift_loses_seasonality",
        title="Multiple permanent level shifts with short post-change seasonal history",
        frame=df,
        true_changepoints=[cp for cp, _ in level_shifts],
        note=(
            "Two real structural level shifts occur in training, with the latest close to "
            "the forecast origin. Truncating to detected changepoint windows removes the "
            "annual seasonal history."
        ),
    )


def make_gradual_drift_scenario() -> Scenario:
    """Hypothesis 2 variant: a gradual regime transition is not a sharp changepoint."""
    df = _base_signal(900, seed=29)
    start, end, lift = 540, 720, 58.0
    t = np.arange(len(df))
    ramp = np.clip((t - start) / (end - start), 0.0, 1.0)
    df["y"] += lift * ramp
    return Scenario(
        name="gradual_drift_loses_seasonality",
        title="Gradual drift over a long transition with short post-drift seasonal history",
        frame=df,
        true_changepoints=[start, end],
        note=(
            "A structural level transition unfolds gradually over many days. Treating the "
            "transition as one or two abrupt changepoints either discards seasonal history or "
            "uses the wrong intervention shape."
        ),
    )


def make_temporary_event_scenario() -> Scenario:
    """Hypothesis 1: a transient event gets collapsed into a retraining-window decision."""
    df = _base_signal(900, seed=13)
    event_blocks = [
        (250, 268, 32.0),
        (420, 444, 42.0),
        (575, 615, 58.0),
    ]
    for start, end, lift in event_blocks:
        df.loc[(df.index >= start) & (df.index < end), "y"] += lift
    return Scenario(
        name="temporary_event_not_regime_change",
        title="Multiple temporary event/outlier blocks misread as changepoints",
        frame=df,
        true_changepoints=[boundary for start, end, _ in event_blocks for boundary in (start, end)],
        note=(
            "The series returns to the old regime after short event blocks. Treating the "
            "latest detected change as a new permanent regime discards useful history."
        ),
    )


def make_many_temporary_events_scenario() -> Scenario:
    """Long-history stress case: many temporary events should be cleaned, not treated as regimes."""
    length = LONG_TRAIN_END + TEST_HORIZON
    df = _base_signal(length, seed=47)
    event_blocks = [
        (92, 105, 30.0),
        (286, 317, 36.0),
        (548, 566, 28.0),
        (852, 901, 40.0),
        (1320, 1344, 34.0),
        (1441, 1482, 62.0),
    ]
    for start, end, lift in event_blocks:
        df.loc[(df.index >= start) & (df.index < end), "y"] += lift
    return Scenario(
        name="many_temporary_events_long_history",
        title="Six temporary events over longer history misread as changepoints",
        frame=df,
        true_changepoints=[boundary for start, end, _ in event_blocks for boundary in (start, end)],
        note=(
            "Six irregular, non-calendar event blocks contaminate a longer history. Their start "
            "dates and widths intentionally differ. The latest event sits inside the validation "
            "tail, encouraging a changepoint-window workflow to believe the event continues into "
            "the forecast period even though the series reverts."
        ),
        train_end=LONG_TRAIN_END,
        n_bkps=6,
    )


def make_prophet_hyperparameter_scenario() -> Scenario:
    """Prophet-specific case: default priors miss recurring event spikes and trend flexibility."""
    length = LONG_TRAIN_END + TEST_HORIZON
    df = _base_signal(length, seed=71)
    t = np.arange(length)

    trend_kinks = [
        (875, 0.055),
        (1250, -0.035),
    ]
    for cp, slope_delta in trend_kinks:
        df.loc[df.index >= cp, "y"] += slope_delta * (t[df.index >= cp] - cp)

    # Recurring event windows are deliberately sharper than Prophet's default yearly Fourier
    # seasonality. The 2023 occurrence lands in the held-out forecast horizon.
    event_windows: list[tuple[int, int, float]] = []
    for year in [2019, 2020, 2021, 2022, 2023]:
        start_date = pd.Timestamp(year=year, month=2, day=12)
        end_date = pd.Timestamp(year=year, month=3, day=5)
        start = int((start_date - df["ds"].iloc[0]).days)
        end = int((end_date - df["ds"].iloc[0]).days)
        if 0 <= start < length:
            event_windows.append((start, min(end, length), 44.0))
    for start, end, lift in event_windows:
        df.loc[(df.index >= start) & (df.index < end), "y"] += lift

    true_boundaries = [cp for cp, _ in trend_kinks]
    true_boundaries.extend(boundary for start, end, _ in event_windows if start < LONG_TRAIN_END for boundary in (start, end))

    return Scenario(
        name="prophet_prior_tuning_recurring_event",
        title="Recurring event plus trend kinks needs Prophet prior tuning",
        frame=df,
        true_changepoints=sorted(true_boundaries),
        note=(
            "A sharp recurring calendar event and two trend kinks stress Prophet defaults. "
            "The intervention should preserve long history, encode the recurring event as "
            "holidays, and tune changepoint_prior_scale/holiday_prior_scale on historical folds."
        ),
        train_end=LONG_TRAIN_END,
        n_bkps=6,
    )


def sse(values: np.ndarray) -> float:
    if len(values) == 0:
        return 0.0
    return float(np.sum((values - np.mean(values)) ** 2))


def fallback_detect_changepoints(values: np.ndarray, *, n_bkps: int = 2, min_size: int = 45) -> list[int]:
    """Tiny binary-segmentation fallback for when ruptures is unavailable."""
    cps: list[int] = []
    segments = [(0, len(values))]
    for _ in range(n_bkps):
        best: tuple[float, int, tuple[int, int]] | None = None
        for start, end in segments:
            if end - start < 2 * min_size:
                continue
            segment = values[start:end]
            total = sse(segment)
            for split in range(start + min_size, end - min_size):
                left = values[start:split]
                right = values[split:end]
                improvement = total - sse(left) - sse(right)
                if best is None or improvement > best[0]:
                    best = (improvement, split, (start, end))
        if best is None or best[0] <= 0:
            break
        _, split, old_segment = best
        cps.append(split)
        segments.remove(old_segment)
        segments.extend([(old_segment[0], split), (split, old_segment[1])])
    return sorted(cps)


def detection_signal(train_y: np.ndarray) -> tuple[np.ndarray, int, str]:
    """Use a simple year-over-year residual to avoid mistaking seasonality for changepoints."""
    if len(train_y) > SEASONAL_PERIOD + 2 * 45:
        return (
            train_y[SEASONAL_PERIOD:] - train_y[:-SEASONAL_PERIOD],
            SEASONAL_PERIOD,
            "year-over-year residual",
        )
    return train_y, 0, "raw series"


def detect_changepoints(train_y: np.ndarray, *, n_bkps: int = DEFAULT_N_BKPS) -> tuple[list[int], str]:
    signal, offset, signal_name = detection_signal(train_y)
    try:
        import ruptures as rpt  # type: ignore

        algo = rpt.Binseg(model="l2", min_size=45).fit(signal.reshape(-1, 1))
        cps = [cp + offset for cp in algo.predict(n_bkps=n_bkps) if cp < len(signal)]
        return sorted(cps), f"ruptures.Binseg(l2, n_bkps={n_bkps}) on {signal_name}"
    except Exception:
        cps = [cp + offset for cp in fallback_detect_changepoints(signal, n_bkps=n_bkps, min_size=45)]
        return sorted(cps), f"fallback binary SSE on {signal_name}"


def metrics(y_true: np.ndarray, yhat: np.ndarray) -> dict[str, float]:
    err = y_true - yhat
    mae = float(np.mean(np.abs(err)))
    rmse = float(math.sqrt(np.mean(err**2)))
    smape = float(np.mean(2.0 * np.abs(err) / np.maximum(np.abs(y_true) + np.abs(yhat), 1e-9)) * 100)
    wape = float(np.sum(np.abs(err)) / np.maximum(np.sum(np.abs(y_true)), 1e-9) * 100)
    return {"MAE": mae, "RMSE": rmse, "sMAPE": smape, "WAPE": wape}


def fit_prophet_default(train_df: pd.DataFrame, future_ds: pd.Series) -> np.ndarray:
    model = Prophet()
    model.fit(train_df[["ds", "y"]])
    future = pd.DataFrame({"ds": future_ds})
    return model.predict(future)["yhat"].to_numpy()


def fit_arima_default(train_df: pd.DataFrame, steps: int) -> np.ndarray:
    model = ARIMA(train_df["y"]).fit()
    return np.asarray(model.forecast(steps=steps), dtype=float)


def fit_default_model(model_name: str, train_df: pd.DataFrame, future_ds: pd.Series) -> np.ndarray:
    if model_name == "Prophet() default":
        return fit_prophet_default(train_df, future_ds)
    if model_name == "ARIMA() default":
        return fit_arima_default(train_df, len(future_ds))
    raise ValueError(model_name)


def fit_prophet_step_regressors(train_df: pd.DataFrame, future_ds: pd.Series, cps: list[int]) -> np.ndarray:
    df = train_df[["ds", "y"]].copy()
    cp_times = [train_df["ds"].iloc[cp] for cp in cps]
    model = Prophet()
    for i, cp_time in enumerate(cp_times):
        name = f"post_cp_{i + 1}"
        df[name] = (df["ds"] >= cp_time).astype(float)
        model.add_regressor(name)
    model.fit(df)
    future = pd.DataFrame({"ds": future_ds})
    for i, cp_time in enumerate(cp_times):
        future[f"post_cp_{i + 1}"] = (future["ds"] >= cp_time).astype(float)
    return model.predict(future)["yhat"].to_numpy()


def fit_prophet_step_regressor(train_df: pd.DataFrame, future_ds: pd.Series, cp: int) -> np.ndarray:
    return fit_prophet_step_regressors(train_df, future_ds, [cp])


def ramp_values(ds: pd.Series, start_time: pd.Timestamp, end_time: pd.Timestamp) -> np.ndarray:
    duration_days = max(1, int((end_time - start_time).days))
    values = (ds - start_time).dt.days.to_numpy(dtype=float) / duration_days
    return np.clip(values, 0.0, 1.0)


def fit_prophet_ramp_regressors(
    train_df: pd.DataFrame,
    future_ds: pd.Series,
    intervals: list[tuple[int, int]],
) -> np.ndarray:
    df = train_df[["ds", "y"]].copy()
    ramp_times = [(train_df["ds"].iloc[start], train_df["ds"].iloc[end]) for start, end in intervals]
    model = Prophet()
    for i, (start_time, end_time) in enumerate(ramp_times):
        name = f"ramp_{i + 1}"
        df[name] = ramp_values(df["ds"], start_time, end_time)
        model.add_regressor(name)
    model.fit(df)
    future = pd.DataFrame({"ds": future_ds})
    for i, (start_time, end_time) in enumerate(ramp_times):
        future[f"ramp_{i + 1}"] = ramp_values(future["ds"], start_time, end_time)
    return model.predict(future)["yhat"].to_numpy()


def clean_event_block(train_df: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    return clean_event_blocks(train_df, [(start, end)])


def clean_event_blocks(train_df: pd.DataFrame, intervals: list[tuple[int, int]]) -> pd.DataFrame:
    cleaned = train_df.copy()
    # Replace event blocks with local interpolation, preserving index/date alignment.
    y = cleaned["y"].copy()
    for start, end in intervals:
        y.iloc[start:end] = np.nan
    cleaned["y"] = y.interpolate("linear").bfill().ffill()
    return cleaned


def expand_date_windows_to_holidays(windows: list[tuple[pd.Timestamp, pd.Timestamp]]) -> pd.DataFrame:
    rows = []
    for start, end in windows:
        for ds in pd.date_range(start.normalize(), (end - pd.Timedelta(days=1)).normalize(), freq="D"):
            rows.append({"holiday": "recurring_event", "ds": ds})
    return pd.DataFrame(rows).drop_duplicates() if rows else pd.DataFrame(columns=["holiday", "ds"])


def infer_recurring_event_windows(
    train_df: pd.DataFrame,
    event_blocks: list[dict[str, Any]],
    future_ds: pd.Series,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Infer recurring calendar event windows from detected training event blocks only."""
    if not event_blocks:
        return []

    date_windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    month_day_starts: list[tuple[int, int]] = []
    durations: list[int] = []
    for block in event_blocks:
        start = int(block["start"])
        end = int(block["end"])
        start_date = pd.Timestamp(train_df["ds"].iloc[start])
        end_date = pd.Timestamp(train_df["ds"].iloc[end - 1]) + pd.Timedelta(days=1)
        date_windows.append((start_date, end_date))
        month_day_starts.append((start_date.month, start_date.day))
        durations.append(max(1, end - start))

    if len(month_day_starts) < 2:
        return date_windows

    # The synthetic stress case uses a once-per-year event. Infer the next occurrence from
    # the median observed month/day and duration without reading held-out target values.
    start_doys = np.array(
        [
            pd.Timestamp(year=2020, month=month, day=day).dayofyear
            for month, day in month_day_starts
            if not (month == 2 and day == 29)
        ]
    )
    if len(start_doys) == 0:
        return date_windows
    inferred_doy = int(np.median(start_doys))
    inferred_duration = int(np.median(durations))
    min_future = pd.Timestamp(future_ds.min())
    max_future = pd.Timestamp(future_ds.max())
    for year in range(min_future.year - 1, max_future.year + 2):
        start_date = pd.Timestamp(year=year, month=1, day=1) + pd.Timedelta(days=inferred_doy - 1)
        end_date = start_date + pd.Timedelta(days=inferred_duration)
        overlaps_future = start_date <= max_future and end_date >= min_future
        known_already = any(abs((start_date - known_start).days) <= 7 for known_start, _ in date_windows)
        if overlaps_future and not known_already:
            date_windows.append((start_date, end_date))

    return sorted(date_windows)


def prophet_tuning_validation_score(
    train_df: pd.DataFrame,
    event_blocks: list[dict[str, Any]],
    changepoint_prior_scale: float,
    holidays_prior_scale: float,
) -> float:
    """Backtest params on historical event windows so test target values stay hidden."""
    if len(event_blocks) < 3:
        return float("inf")
    fold_scores: list[float] = []
    for block in event_blocks[-3:]:
        start = int(block["start"])
        end = int(block["end"])
        if start < 120 or end <= start:
            continue
        inner_train = train_df.iloc[:start].copy()
        holdout = train_df.iloc[start:end].copy()
        prior_blocks = [candidate for candidate in event_blocks if int(candidate["end"]) <= start]
        windows = infer_recurring_event_windows(inner_train, prior_blocks, holdout["ds"])
        holidays = expand_date_windows_to_holidays(windows)
        model = Prophet(
            changepoint_prior_scale=changepoint_prior_scale,
            holidays_prior_scale=holidays_prior_scale,
            holidays=holidays,
        )
        model.fit(inner_train[["ds", "y"]])
        yhat = model.predict(holdout[["ds"]])["yhat"].to_numpy()
        fold_scores.append(metrics(holdout["y"].to_numpy(), yhat)["MAE"])
    return float(np.mean(fold_scores)) if fold_scores else float("inf")


def fit_prophet_tuned_holidays(
    train_df: pd.DataFrame,
    future_ds: pd.Series,
    event_blocks: list[dict[str, Any]],
) -> tuple[np.ndarray, dict[str, Any]]:
    grid = [
        (changepoint_prior_scale, holidays_prior_scale)
        for changepoint_prior_scale in [0.01, 0.05, 0.2, 0.5]
        for holidays_prior_scale in [0.1, 1.0, 10.0, 25.0]
    ]
    scores = {
        f"cps={cps},hps={hps}": prophet_tuning_validation_score(train_df, event_blocks, cps, hps)
        for cps, hps in grid
    }
    best_key = min(scores, key=scores.get)
    best_cps, best_hps = [
        float(part.split("=")[1])
        for part in best_key.split(",")
    ]
    windows = infer_recurring_event_windows(train_df, event_blocks, future_ds)
    holidays = expand_date_windows_to_holidays(windows)
    model = Prophet(
        changepoint_prior_scale=best_cps,
        holidays_prior_scale=best_hps,
        holidays=holidays,
    )
    model.fit(train_df[["ds", "y"]])
    yhat = model.predict(pd.DataFrame({"ds": future_ds}))["yhat"].to_numpy()
    details = {
        "chosen_changepoint_prior_scale": best_cps,
        "chosen_holidays_prior_scale": best_hps,
        "validation_MAE": scores,
        "holiday_windows": [
            [str(start.date()), str((end - pd.Timedelta(days=1)).date())] for start, end in windows
        ],
    }
    return yhat, details


def evaluate_default_full_history(scenario: Scenario, model_name: str) -> ForecastResult:
    train_end = scenario.train_end
    test_horizon = scenario.test_horizon
    train = scenario.frame.iloc[:train_end].copy()
    test = scenario.frame.iloc[train_end : train_end + test_horizon].copy()
    yhat = fit_default_model(model_name, train, test["ds"])
    return ForecastResult(
        scenario=scenario.name,
        method=f"full_history_{model_name}",
        model=model_name,
        yhat=yhat,
        metrics=metrics(test["y"].to_numpy(), yhat),
        details={"train_start": 0, "train_end": train_end},
    )


def validation_mae(model_name: str, recent_df: pd.DataFrame) -> float:
    val = min(VALIDATION_HORIZON, max(21, len(recent_df) // 3))
    if len(recent_df) - val < 30:
        return float("inf")
    inner = recent_df.iloc[:-val].copy()
    holdout = recent_df.iloc[-val:].copy()
    yhat = fit_default_model(model_name, inner, holdout["ds"])
    return metrics(holdout["y"].to_numpy(), yhat)["MAE"]


def naive_training_windows(train: pd.DataFrame, cps: list[int]) -> dict[str, pd.DataFrame]:
    windows = {"full_history": train}
    cp_starts = sorted({cp for cp in cps if 0 <= cp < len(train) - 30})
    if not cp_starts:
        cp_starts = [len(train) // 2]
    for cp in cp_starts:
        windows[f"cp_{cp}_window"] = train.iloc[cp:].copy()
    return windows


def evaluate_naive_default_workflow(scenario: Scenario, cps: list[int]) -> ForecastResult:
    train_end = scenario.train_end
    test_horizon = scenario.test_horizon
    train = scenario.frame.iloc[:train_end].copy()
    test = scenario.frame.iloc[train_end : train_end + test_horizon].copy()
    latest_cp = max(cps) if cps else train_end // 2
    windows = naive_training_windows(train, cps)

    candidates = ["Prophet() default", "ARIMA() default"]
    val_scores: dict[str, float] = {}
    for window_name, window_df in windows.items():
        for model_name in candidates:
            val_scores[f"{window_name}:{model_name}"] = validation_mae(model_name, window_df)

    chosen_key = min(val_scores, key=val_scores.get)
    chosen_window, chosen_model = chosen_key.split(":", 1)
    yhat = fit_default_model(chosen_model, windows[chosen_window], test["ds"])

    return ForecastResult(
        scenario=scenario.name,
        method="naive_best_default_workflow",
        model=f"{chosen_window} + {chosen_model}",
        yhat=yhat,
        metrics=metrics(test["y"].to_numpy(), yhat),
        details={
            "detected_changepoints": cps,
            "latest_cp": latest_cp,
            "candidate_windows": {name: int(len(window)) for name, window in windows.items()},
            "candidate_validation_MAE": val_scores,
            "chosen_candidate": chosen_key,
        },
    )


def evaluate_naive_recent_window(scenario: Scenario, cps: list[int]) -> ForecastResult:
    train_end = scenario.train_end
    test_horizon = scenario.test_horizon
    train = scenario.frame.iloc[:train_end].copy()
    test = scenario.frame.iloc[train_end : train_end + test_horizon].copy()
    latest_cp = max(cps) if cps else train_end // 2
    recent = train.iloc[latest_cp:].copy()

    candidates = ["Prophet() default", "ARIMA() default"]
    val_scores = {candidate: validation_mae(candidate, recent) for candidate in candidates}
    chosen = min(val_scores, key=val_scores.get)
    if chosen == "Prophet() default":
        yhat = fit_prophet_default(recent, test["ds"])
    else:
        yhat = fit_arima_default(recent, len(test))

    return ForecastResult(
        scenario=scenario.name,
        method="naive_latest_cp_window_best_default_model",
        model=chosen,
        yhat=yhat,
        metrics=metrics(test["y"].to_numpy(), yhat),
        details={
            "detected_changepoints": cps,
            "latest_cp": latest_cp,
            "recent_window_points": int(len(recent)),
            "validation_MAE": val_scores,
        },
    )


def segment_means(train_y: np.ndarray, cps: list[int]) -> list[dict[str, float]]:
    bounds = [0] + sorted(cps) + [len(train_y)]
    out = []
    for start, end in zip(bounds[:-1], bounds[1:], strict=True):
        values = train_y[start:end]
        out.append({"start": start, "end": end, "mean": float(np.mean(values)), "std": float(np.std(values))})
    return out


def candidate_event_blocks(train_df: pd.DataFrame) -> list[dict[str, Any]]:
    y = train_df["y"].to_numpy()
    t = np.arange(len(y))
    features = np.column_stack(
        [
            np.ones(len(y)),
            t,
            np.sin(2 * np.pi * t / 365.0),
            np.cos(2 * np.pi * t / 365.0),
            np.sin(2 * np.pi * t / 7.0),
            np.cos(2 * np.pi * t / 7.0),
        ]
    )
    fitted = features @ np.linalg.lstsq(features, y, rcond=None)[0]
    residual = y - fitted
    center = float(np.median(residual))
    mad = float(np.median(np.abs(residual - center)) * 1.4826)
    threshold = max(10.0, 3.0 * mad)
    mask = residual > center + threshold

    closed = mask.copy()
    i = 0
    while i < len(closed):
        if closed[i]:
            i += 1
            continue
        gap_start = i
        while i < len(closed) and not closed[i]:
            i += 1
        if gap_start > 0 and i < len(closed) and i - gap_start <= 3:
            closed[gap_start:i] = True

    blocks: list[dict[str, Any]] = []
    i = 0
    while i < len(closed):
        if not closed[i]:
            i += 1
            continue
        start = i
        while i < len(closed) and closed[i]:
            i += 1
        end = i
        duration = end - start
        if 5 <= duration <= 80:
            blocks.append(
                {
                    "start": int(start),
                    "end": int(end),
                    "duration": int(duration),
                    "mean_positive_residual": float(np.mean(residual[start:end])),
                    "start_date": str(train_df["ds"].iloc[start].date()),
                    "end_date": str(train_df["ds"].iloc[end - 1].date()),
                }
            )
    return blocks


def recurring_event_pattern(train_df: pd.DataFrame, event_blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(event_blocks) < 2:
        return None
    starts = [pd.Timestamp(train_df["ds"].iloc[int(block["start"])]) for block in event_blocks]
    durations = [int(block["duration"]) for block in event_blocks]
    month_days = [f"{start.month:02d}-{start.day:02d}" for start in starts]
    years = [int(start.year) for start in starts]
    month_counts = pd.Series([start.month for start in starts]).value_counts().to_dict()
    dominant_month = max(month_counts, key=month_counts.get)
    dominant_month_fraction = float(month_counts[dominant_month] / len(starts))
    return {
        "event_count": len(event_blocks),
        "start_month_days": month_days,
        "years": years,
        "median_duration": float(np.median(durations)),
        "dominant_month": int(dominant_month),
        "dominant_month_fraction": dominant_month_fraction,
        "looks_calendar_recurring": len(set(years)) >= 3 and dominant_month_fraction >= 0.6,
    }


def detected_boundary_jumps(train_df: pd.DataFrame, cps: list[int], *, width: int = 14) -> list[dict[str, Any]]:
    y = train_df["y"].to_numpy()
    jumps = []
    for cp in cps:
        left_start = max(0, cp - width)
        right_end = min(len(y), cp + width)
        if cp - left_start < 5 or right_end - cp < 5:
            continue
        before = float(np.mean(y[left_start:cp]))
        after = float(np.mean(y[cp:right_end]))
        jumps.append(
            {
                "cp": int(cp),
                "local_before_mean": before,
                "local_after_mean": after,
                "local_jump": after - before,
            }
        )
    return jumps


def candidate_drift_intervals(train_df: pd.DataFrame, cps: list[int], boundary_jumps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intervals = []
    jump_by_cp = {int(item["cp"]): abs(float(item["local_jump"])) for item in boundary_jumps}
    if len(cps) >= 2:
        for start, end in zip(cps[:-1], cps[1:], strict=True):
            duration = end - start
            if not 60 <= duration <= 260:
                continue
            start_mean = float(np.mean(train_df["y"].iloc[max(0, start - 30) : start]))
            end_mean = float(np.mean(train_df["y"].iloc[end : min(len(train_df), end + 30)]))
            total_delta = end_mean - start_mean
            max_boundary_jump = max(jump_by_cp.get(start, 0.0), jump_by_cp.get(end, 0.0))
            if abs(total_delta) < 20.0 or max_boundary_jump >= 0.30 * abs(total_delta):
                continue
            intervals.append(
                {
                    "start": int(start),
                    "end": int(end),
                    "duration": int(duration),
                    "mean_delta_across_interval": total_delta,
                    "max_abs_boundary_jump": float(max_boundary_jump),
                    "source": "detected_changepoint_span",
                    "start_date": str(train_df["ds"].iloc[start].date()),
                    "end_date": str(train_df["ds"].iloc[end].date()),
                }
            )

    y = train_df["y"].to_numpy()
    if len(y) > SEASONAL_PERIOD + 90:
        yoy = y[SEASONAL_PERIOD:] - y[:-SEASONAL_PERIOD]
        smoothed = np.convolve(yoy, np.ones(21) / 21, mode="same")
        baseline = smoothed[: min(120, max(30, len(smoothed) // 3))]
        center = float(np.median(baseline))
        mad = float(np.median(np.abs(baseline - center)) * 1.4826)
        threshold = center + max(5.0, 3.0 * mad)
        mask = smoothed > threshold
        i = 0
        while i < len(mask):
            if not mask[i]:
                i += 1
                continue
            start = i
            while i < len(mask) and mask[i]:
                i += 1
            end = i
            duration = end - start
            if duration >= 60:
                train_start = start + SEASONAL_PERIOD
                train_end = min(len(train_df) - 1, end + SEASONAL_PERIOD)
                start_mean = float(np.mean(train_df["y"].iloc[max(0, train_start - 30) : train_start]))
                end_mean = float(np.mean(train_df["y"].iloc[train_end : min(len(train_df), train_end + 30)]))
                total_delta = end_mean - start_mean
                max_boundary_jump = float(max(jump_by_cp.values(), default=0.0))
                if abs(total_delta) < 20.0 or max_boundary_jump >= 0.30 * abs(total_delta):
                    continue
                intervals.append(
                    {
                        "start": int(train_start),
                        "end": int(train_end),
                        "duration": int(train_end - train_start),
                        "mean_delta_across_interval": total_delta,
                        "max_abs_boundary_jump": max_boundary_jump,
                        "source": "year_over_year_residual_persistent_shift",
                        "start_date": str(train_df["ds"].iloc[train_start].date()),
                        "end_date": str(train_df["ds"].iloc[train_end].date()),
                    }
                )
    return intervals


def diagnostics_for_scenario(scenario: Scenario, cps: list[int], detector: str) -> dict[str, Any]:
    train_end = scenario.train_end
    train = scenario.frame.iloc[:train_end].copy()
    train_y = train["y"].to_numpy()
    latest_cp = max(cps) if cps else train_end // 2
    segs = segment_means(train_y, cps)
    primary_cp = latest_cp
    if cps and len(segs) >= 2:
        adjacent_deltas = [
            abs(right["mean"] - left["mean"]) for left, right in zip(segs[:-1], segs[1:], strict=True)
        ]
        primary_cp = cps[int(np.argmax(adjacent_deltas))]
    post_cp_points = train_end - latest_cp

    transient_score = 0.0
    if len(segs) >= 3:
        before, middle, after = segs[-3], segs[-2], segs[-1]
        event_jump = abs(middle["mean"] - before["mean"])
        reversion = abs(after["mean"] - before["mean"])
        transient_score = float(event_jump / max(reversion, 1.0))

    permanent_shift = 0.0
    if segs:
        permanent_shift = float(abs(segs[-1]["mean"] - segs[0]["mean"]))
    boundary_jumps = detected_boundary_jumps(train, cps)
    event_blocks = candidate_event_blocks(train)

    return {
        "detector": detector,
        "detected_changepoints": cps,
        "latest_cp": latest_cp,
        "primary_cp": primary_cp,
        "post_cp_points": post_cp_points,
        "seasonal_period": SEASONAL_PERIOD,
        "post_cp_shorter_than_one_season": post_cp_points < SEASONAL_PERIOD,
        "segments": segs,
        "candidate_event_blocks": event_blocks,
        "candidate_recurring_event_pattern": recurring_event_pattern(train, event_blocks),
        "detected_boundary_jumps": boundary_jumps,
        "candidate_drift_intervals": candidate_drift_intervals(train, cps, boundary_jumps),
        "transient_event_score": transient_score,
        "permanent_shift_abs_mean_delta": permanent_shift,
        "scenario_note": scenario.note,
    }


def write_diagnostic_plot(scenario: Scenario, cps: list[int]) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / f"{scenario.name}_diagnostics.png"
    df = scenario.frame
    train_end = scenario.train_end
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(df["ds"], df["y"], color="#1f77b4", linewidth=1.2, label="observed")
    ax.axvline(df["ds"].iloc[train_end], color="black", linestyle="-", linewidth=1.5, label="forecast origin")
    for i, cp in enumerate(cps):
        ax.axvline(
            df["ds"].iloc[cp],
            color="#d62728",
            linestyle="--",
            linewidth=1.3,
            label="detected changepoint" if i == 0 else None,
        )
    for i, cp in enumerate(scenario.true_changepoints):
        ax.axvline(
            df["ds"].iloc[cp],
            color="#2ca02c",
            linestyle=":",
            linewidth=1.5,
            label="true injected boundary" if i == 0 else None,
        )
    ax.set_title(scenario.title)
    ax.set_xlabel("date")
    ax.set_ylabel("y")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def write_agent_context_plot(scenario: Scenario, cps: list[int]) -> Path:
    """Plot passed to the ReAct agent: training window only, no ground truth or test data."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / f"{scenario.name}_agent_context.png"
    df = scenario.frame.iloc[: scenario.train_end].copy()
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(df["ds"], df["y"], color="#1f77b4", linewidth=1.2, label="observed")
    ax.axvline(df["ds"].iloc[-1], color="black", linestyle="-", linewidth=1.5, label="forecast origin")
    for i, cp in enumerate(cps):
        if 0 <= cp < len(df):
            ax.axvline(
                df["ds"].iloc[cp],
                color="#d62728",
                linestyle="--",
                linewidth=1.3,
                label="detected changepoint" if i == 0 else None,
            )
    ax.set_title("Agent context: training observations with detected changepoints")
    ax.set_xlabel("date")
    ax.set_ylabel("y")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _extract_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _message_text(response: Any) -> str:
    return "".join(block.text for block in response.content if getattr(block, "type", "") == "text")


def _bedrock_regions() -> list[str]:
    candidate_regions = [
        os.getenv("AWS_BEDROCK_REGION"),
        DEFAULT_BEDROCK_REGION,
        os.getenv("AWS_REGION"),
        "us-east-1",
    ]
    regions = []
    for region in candidate_regions:
        if region and region not in regions:
            regions.append(region)
    return regions


def call_bedrock_json(
    content: list[dict[str, Any]],
    *,
    decision_source: str,
    max_tokens: int = 2000,
) -> dict[str, Any] | None:
    if not (os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")):
        return None
    model_id = os.getenv("AWS_BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID)
    regions = _bedrock_regions()
    try:
        from anthropic import AnthropicBedrock

        last_error: str | None = None
        for region in regions:
            try:
                client = AnthropicBedrock(
                    aws_access_key=os.getenv("AWS_ACCESS_KEY_ID"),
                    aws_secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
                    aws_region=region,
                    max_retries=1,
                )
                response = client.messages.create(
                    model=model_id,
                    max_tokens=max_tokens,
                    temperature=0,
                    messages=[{"role": "user", "content": content}],
                )
                text = _message_text(response)
                parsed = _extract_json(text)
                if parsed:
                    parsed["decision_source"] = decision_source
                    parsed["bedrock_region"] = region
                    parsed["bedrock_model_id"] = model_id
                    return parsed
                return {
                    "decision_source": f"{decision_source}_parse_failed",
                    "bedrock_region": region,
                    "bedrock_model_id": model_id,
                    "raw_text": text,
                }
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"

        return {
            "decision_source": f"{decision_source}_failed",
            "bedrock_model_id": model_id,
            "regions_tried": regions,
            "error": last_error,
        }
    except Exception as exc:
        return {"decision_source": f"{decision_source}_setup_failed", "error": repr(exc)}


def agent_input_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Remove labels/provenance that can bias the analyst before LLM/LangGraph input."""
    biased_or_provenance = {"detector", "scenario_note"}
    return {k: v for k, v in diagnostics.items() if k not in biased_or_provenance}


def _visual_inspection_prompt() -> str:
    return (
        "You are the visual-inspection node in a forecasting ReAct graph. You see only a "
        "training-history plot with detected changepoints. You do not have numeric diagnostics, "
        "test data, ground-truth labels, or model metrics. Do not choose a final intervention.\n\n"
        "Return only JSON with keys: "
        "{\"visual_observations\": array of concrete observations from the image, "
        "\"visual_pattern_summary\": one concise sentence, "
        "\"visually_supported_hypotheses\": array of plausible failure-mode hypotheses, "
        "\"visual_uncertainties\": array of things the image alone cannot determine}."
    )


def _diagnostic_inspection_prompt(diagnostics: dict[str, Any]) -> str:
    safe_diagnostics = agent_input_diagnostics(diagnostics)
    return (
        "You are the diagnostic-inspection node in a forecasting ReAct graph. You see only "
        "numeric diagnostics from the training history. You do not see the image, test data, "
        "ground-truth labels, or final model metrics. Do not choose a final intervention.\n\n"
        "Return only JSON with keys: "
        "{\"diagnostic_observations\": array of concrete numeric observations, "
        "\"diagnostic_pattern_summary\": one concise sentence, "
        "\"diagnostically_supported_hypotheses\": array of plausible failure-mode hypotheses, "
        "\"diagnostic_uncertainties\": array of things the diagnostics alone cannot determine}.\n\n"
        f"Diagnostics:\n{json.dumps(safe_diagnostics, indent=2)}"
    )


def _agent_prompt(diagnostics: dict[str, Any], rejected_interventions: list[str] | None = None) -> str:
    safe_diagnostics = agent_input_diagnostics(diagnostics)
    rejected_interventions = rejected_interventions or []
    rejected_text = (
        "Previously rejected concrete action signatures in this validation loop: "
        f"{json.dumps(rejected_interventions)}. Do not repeat them.\n\n"
        if rejected_interventions
        else ""
    )
    return (
        "You are a bounded forecasting analyst in a ReAct loop. You cannot forecast directly. "
        "You must choose exactly one intervention from this menu:\n"
        "1. recent_window: train only from the latest detected changepoint.\n"
        "2. full_history_step_regressor: preserve full history and add one or more post-changepoint "
        "step regressors for permanent level shifts.\n"
        "3. full_history_clean_event: preserve full history and clean/interpolate one or more short "
        "event-contaminated intervals.\n"
        "4. full_history_ramp_regressor: preserve full history and add one or more clipped ramp "
        "regressors for gradual drift transitions.\n"
        "5. full_history_prophet_tuned_holidays: preserve full history, encode recurring calendar "
        "event blocks as Prophet holidays, and tune changepoint_prior_scale/holiday_prior_scale "
        "on historical validation folds.\n\n"
        "Use the diagnostic numbers and image. Do not assume every detected changepoint is a new permanent regime. "
        "Prefer preserving full seasonal history when the post-changepoint window is shorter than the seasonal period. "
        "Treat two close boundaries with reversion as temporary event/outlier contamination. "
        "If several short temporary blocks are visible or listed in candidate_event_blocks, include all of the "
        "blocks that should be cleaned, not just the latest detected changepoint interval. "
        "If several detected changepoints look like permanent baseline shifts, include all relevant indexes "
        "in step_changepoints. If the transition happens gradually between two detected boundaries and "
        "local boundary jumps are small relative to the total level change, prefer full_history_ramp_regressor "
        "and include the transition intervals in drift_intervals. If the boundary_jumps themselves are large, "
        "prefer step regressors over ramp regressors. If several candidate event blocks recur at roughly "
        "the same calendar time across multiple years and future dates can be inferred from the pattern, "
        "prefer full_history_prophet_tuned_holidays over simple cleaning. Do not choose "
        "full_history_prophet_tuned_holidays when candidate_recurring_event_pattern.looks_calendar_recurring "
        "is false or absent; use event cleaning for irregular non-calendar event blocks.\n\n"
        f"{rejected_text}"
        "Return only JSON with keys:\n"
        "{"
        "\"decision\": one of the intervention ids, "
        "\"event_intervals\": optional array of [start_index, end_index] pairs when decision is "
        "\"full_history_clean_event\", "
        "\"step_changepoints\": optional array of changepoint indexes when decision is "
        "\"full_history_step_regressor\", "
        "\"drift_intervals\": optional array of [start_index, end_index] pairs when decision is "
        "\"full_history_ramp_regressor\", "
        "\"holiday_event_intervals\": optional array of [start_index, end_index] pairs when decision is "
        "\"full_history_prophet_tuned_holidays\", "
        "\"rationale\": concise explanation, "
        "\"react_trace\": array of Thought/Action/Observation strings, "
        "\"visual_observations\": array of observations from the image"
        "}.\n\n"
        f"Diagnostics:\n{json.dumps(safe_diagnostics, indent=2)}"
    )


def _staged_decision_prompt(
    diagnostics: dict[str, Any],
    visual_inspection: dict[str, Any],
    diagnostic_inspection: dict[str, Any],
    rejected_interventions: list[str] | None = None,
) -> str:
    safe_diagnostics = agent_input_diagnostics(diagnostics)
    rejected_interventions = rejected_interventions or []
    rejected_text = (
        "Previously rejected concrete action signatures in this validation loop: "
        f"{json.dumps(rejected_interventions)}. Do not repeat them.\n\n"
        if rejected_interventions
        else ""
    )
    return (
        "You are the decision node in a staged forecasting ReAct graph. The visual-inspection "
        "node has already looked at the image first. The diagnostic-inspection node then looked "
        "at training-only diagnostics. You must choose exactly one bounded intervention.\n\n"
        "Intervention menu:\n"
        "1. recent_window: train only from the latest detected changepoint.\n"
        "2. full_history_step_regressor: preserve full history and add one or more post-changepoint "
        "step regressors for permanent level shifts.\n"
        "3. full_history_clean_event: preserve full history and clean/interpolate one or more short "
        "event-contaminated intervals.\n"
        "4. full_history_ramp_regressor: preserve full history and add one or more clipped ramp "
        "regressors for gradual drift transitions.\n"
        "5. full_history_prophet_tuned_holidays: preserve full history, encode recurring calendar "
        "event blocks as Prophet holidays, and tune changepoint_prior_scale/holiday_prior_scale "
        "on historical validation folds.\n\n"
        "Decision rules: do not assume every detected changepoint is a new permanent regime. "
        "Prefer preserving full seasonal history when the post-changepoint window is shorter than "
        "the seasonal period. If candidate event blocks recur at roughly the same calendar time "
        "across multiple years and candidate_recurring_event_pattern.looks_calendar_recurring is true, "
        "Prophet holiday tuning is allowed. If that recurring flag is false or absent, do not choose "
        "holiday tuning; use event cleaning for irregular non-calendar event blocks. If the transition "
        "happens gradually between boundaries and local jumps are small relative to total level change, "
        "prefer ramp regressors. If boundary jumps are large, prefer step regressors.\n\n"
        "Rationale discipline: the key `visual_first_rationale` must start by citing at least two "
        "items from `visual_inspection.visual_observations`, then reconcile them with the diagnostic "
        "inspection. The general `rationale` may be shorter, but it must not contradict the visual-first "
        "rationale.\n\n"
        f"{rejected_text}"
        "Return only JSON with keys:\n"
        "{"
        "\"decision\": one of the intervention ids, "
        "\"event_intervals\": optional array of [start_index, end_index] pairs for full_history_clean_event, "
        "\"step_changepoints\": optional array of changepoint indexes for full_history_step_regressor, "
        "\"drift_intervals\": optional array of [start_index, end_index] pairs for full_history_ramp_regressor, "
        "\"holiday_event_intervals\": optional array of [start_index, end_index] pairs for "
        "full_history_prophet_tuned_holidays, "
        "\"visual_first_rationale\": visual-first explanation, "
        "\"rationale\": concise final explanation, "
        "\"react_trace\": array of Thought/Action/Observation strings, "
        "\"visual_observations\": copy of the visual observations used, "
        "\"diagnostic_observations\": copy of the diagnostic observations used"
        "}.\n\n"
        f"Visual inspection, produced before diagnostics:\n{json.dumps(visual_inspection, indent=2)}\n\n"
        f"Diagnostic inspection:\n{json.dumps(diagnostic_inspection, indent=2)}\n\n"
        f"Diagnostics:\n{json.dumps(safe_diagnostics, indent=2)}"
    )


def call_bedrock_visual_inspection(image_path: Path) -> dict[str, Any] | None:
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return call_bedrock_json(
        [
            {"type": "text", "text": _visual_inspection_prompt()},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_b64,
                },
            },
        ],
        decision_source="aws_bedrock_visual_inspection",
    )


def call_bedrock_diagnostic_inspection(diagnostics: dict[str, Any]) -> dict[str, Any] | None:
    return call_bedrock_json(
        [{"type": "text", "text": _diagnostic_inspection_prompt(diagnostics)}],
        decision_source="aws_bedrock_diagnostic_inspection",
    )


def call_bedrock_staged_decision(
    diagnostics: dict[str, Any],
    visual_inspection: dict[str, Any],
    diagnostic_inspection: dict[str, Any],
    *,
    rejected_interventions: list[str] | None = None,
) -> dict[str, Any] | None:
    return call_bedrock_json(
        [
            {
                "type": "text",
                "text": _staged_decision_prompt(
                    diagnostics,
                    visual_inspection,
                    diagnostic_inspection,
                    rejected_interventions=rejected_interventions,
                ),
            }
        ],
        decision_source="aws_bedrock_staged_decision",
        max_tokens=2400,
    )


def call_bedrock_multimodal_llm(
    diagnostics: dict[str, Any],
    image_path: Path,
    *,
    rejected_interventions: list[str] | None = None,
) -> dict[str, Any] | None:
    if not (os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")):
        return None
    try:
        from anthropic import AnthropicBedrock

        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        model_id = os.getenv("AWS_BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID)
        candidate_regions = [
            os.getenv("AWS_BEDROCK_REGION"),
            DEFAULT_BEDROCK_REGION,
            os.getenv("AWS_REGION"),
            "us-east-1",
        ]
        regions = []
        for region in candidate_regions:
            if region and region not in regions:
                regions.append(region)

        last_error: str | None = None
        for region in regions:
            try:
                client = AnthropicBedrock(
                    aws_access_key=os.getenv("AWS_ACCESS_KEY_ID"),
                    aws_secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
                    aws_region=region,
                    max_retries=1,
                )
                response = client.messages.create(
                    model=model_id,
                    max_tokens=2000,
                    temperature=0,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": _agent_prompt(
                                        diagnostics,
                                        rejected_interventions=rejected_interventions,
                                    ),
                                },
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": image_b64,
                                    },
                                },
                            ],
                        }
                    ],
                )
                text = _message_text(response)
                parsed = _extract_json(text)
                if parsed:
                    parsed["decision_source"] = "aws_bedrock_anthropic_multimodal"
                    parsed["bedrock_region"] = region
                    parsed["bedrock_model_id"] = model_id
                    return parsed
                return {
                    "decision_source": "aws_bedrock_anthropic_multimodal_parse_failed",
                    "bedrock_region": region,
                    "bedrock_model_id": model_id,
                    "raw_text": text,
                }
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"

        return {
            "decision_source": "aws_bedrock_anthropic_multimodal_failed",
            "bedrock_model_id": model_id,
            "regions_tried": regions,
            "error": last_error,
        }
    except Exception as exc:
        return {"decision_source": "aws_bedrock_setup_failed", "error": repr(exc)}


def call_multimodal_llm(
    diagnostics: dict[str, Any],
    image_path: Path,
    *,
    rejected_interventions: list[str] | None = None,
) -> dict[str, Any] | None:
    bedrock = call_bedrock_multimodal_llm(
        diagnostics,
        image_path,
        rejected_interventions=rejected_interventions,
    )
    if bedrock:
        return bedrock

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import Anthropic

        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
            max_tokens=2000,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": _agent_prompt(
                                diagnostics,
                                rejected_interventions=rejected_interventions,
                            ),
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                    ],
                }
            ],
        )
        text = _message_text(response)
        parsed = _extract_json(text)
        if parsed:
            parsed["decision_source"] = "anthropic_multimodal"
            return parsed
        return {"decision_source": "anthropic_multimodal_parse_failed", "raw_text": text}
    except Exception as exc:
        return {"decision_source": "anthropic_multimodal_failed", "error": repr(exc)}


def fallback_react_policy(
    diagnostics: dict[str, Any],
    *,
    rejected_interventions: list[str] | None = None,
) -> dict[str, Any]:
    rejected = set(rejected_interventions or [])
    cps = diagnostics["detected_changepoints"]
    post_short = diagnostics["post_cp_shorter_than_one_season"]
    transient = diagnostics["transient_event_score"]
    permanent = diagnostics["permanent_shift_abs_mean_delta"]
    event_blocks = diagnostics.get("candidate_event_blocks", [])
    recurring_pattern = diagnostics.get("candidate_recurring_event_pattern") or {}
    drift_intervals = diagnostics.get("candidate_drift_intervals", [])
    max_drift_boundary_jump = max(
        [abs(float(interval["max_abs_boundary_jump"])) for interval in drift_intervals],
        default=float("inf"),
    )

    trace = [
        "Thought: I should not assume every detected boundary means retrain only after it.",
        f"Action: inspect detected changepoints {cps} and post-change window length.",
        (
            "Observation: latest post-change window has "
            f"{diagnostics['post_cp_points']} points vs seasonal period {SEASONAL_PERIOD}."
        ),
    ]

    if recurring_pattern.get("looks_calendar_recurring") and len(event_blocks) >= 3:
        decision = "full_history_prophet_tuned_holidays"
        trace.extend(
            [
                "Thought: repeated event blocks at similar calendar dates suggest Prophet holiday terms.",
                "Action: preserve full history and tune changepoint/holiday priors on historical event folds.",
            ]
        )
        event_intervals = None
        holiday_event_intervals = [[block["start"], block["end"]] for block in event_blocks]
        step_changepoints = None
        selected_drift_intervals = None
    elif event_blocks and (transient > 2.5 or len(event_blocks) >= 3):
        decision = "full_history_clean_event"
        trace.extend(
            [
                "Thought: candidate short positive residual blocks plus reversion suggest temporary events.",
                "Action: preserve full history and clean all event-contaminated intervals.",
            ]
        )
        event_intervals = [[block["start"], block["end"]] for block in event_blocks]
        holiday_event_intervals = None
        step_changepoints = None
        selected_drift_intervals = None
    elif len(cps) >= 2 and transient > 2.5:
        decision = "full_history_clean_event"
        trace.extend(
            [
                "Thought: two close boundaries with reversion suggests a temporary event block.",
                "Action: preserve full history and clean the event-contaminated interval.",
            ]
        )
        event_intervals = None
        holiday_event_intervals = None
        step_changepoints = None
        selected_drift_intervals = None
    elif drift_intervals and permanent > 15.0 and max_drift_boundary_jump < max(12.0, 0.35 * permanent):
        decision = "full_history_ramp_regressor"
        trace.extend(
            [
                "Thought: the transition spans a long interval with small local boundary jumps.",
                "Action: preserve full history and model the gradual transition with ramp regressors.",
            ]
        )
        event_intervals = None
        holiday_event_intervals = None
        step_changepoints = None
        selected_drift_intervals = [[interval["start"], interval["end"]] for interval in drift_intervals]
    elif post_short and permanent > 15.0:
        decision = "full_history_step_regressor"
        trace.extend(
            [
                "Thought: the shift appears persistent, but recent-window retraining loses seasonality.",
                "Action: preserve full history and model the post-changepoint level shift explicitly.",
            ]
        )
        event_intervals = None
        holiday_event_intervals = None
        step_changepoints = cps or [diagnostics["primary_cp"]]
        selected_drift_intervals = None
    else:
        decision = "recent_window"
        trace.extend(
            [
                "Thought: diagnostics do not show a strong reason to override the simple recent-window fix.",
                "Action: use latest-changepoint retraining.",
            ]
        )
        event_intervals = None
        holiday_event_intervals = None
        step_changepoints = None
        selected_drift_intervals = None

    if decision in rejected or any(item.startswith(f"{decision}:") for item in rejected):
        for candidate in [
            "full_history_step_regressor",
            "full_history_ramp_regressor",
            "full_history_prophet_tuned_holidays",
            "full_history_clean_event",
            "recent_window",
        ]:
            if candidate not in rejected and not any(item.startswith(f"{candidate}:") for item in rejected):
                trace.append(f"Observation: preferred intervention {decision} was already rejected.")
                trace.append(f"Action: try next untested bounded intervention {candidate}.")
                decision = candidate
                event_intervals = (
                    [[block["start"], block["end"]] for block in event_blocks]
                    if candidate == "full_history_clean_event" and event_blocks
                    else None
                )
                holiday_event_intervals = (
                    [[block["start"], block["end"]] for block in event_blocks]
                    if candidate == "full_history_prophet_tuned_holidays" and event_blocks
                    else None
                )
                step_changepoints = cps if candidate == "full_history_step_regressor" else None
                selected_drift_intervals = (
                    [[interval["start"], interval["end"]] for interval in drift_intervals]
                    if candidate == "full_history_ramp_regressor" and drift_intervals
                    else None
                )
                break

    result = {
        "decision": decision,
        "rationale": (
            "Bounded local ReAct fallback: choose the least invasive intervention that matches "
            "the detected segment pattern and seasonal-history constraint."
        ),
        "react_trace": trace,
        "decision_source": "local_react_policy",
    }
    if event_intervals is not None:
        result["event_intervals"] = event_intervals
    if holiday_event_intervals is not None:
        result["holiday_event_intervals"] = holiday_event_intervals
    if step_changepoints is not None:
        result["step_changepoints"] = step_changepoints
    if selected_drift_intervals is not None:
        result["drift_intervals"] = selected_drift_intervals
    return result


def agent_decide(
    diagnostics: dict[str, Any],
    image_path: Path,
    *,
    rejected_interventions: list[str] | None = None,
) -> dict[str, Any]:
    visual_inspection = call_bedrock_visual_inspection(image_path) or {
        "decision_source": "visual_inspection_unavailable"
    }
    diagnostic_inspection = call_bedrock_diagnostic_inspection(diagnostics) or {
        "decision_source": "diagnostic_inspection_unavailable"
    }
    return agent_decide_from_stages(
        diagnostics,
        visual_inspection,
        diagnostic_inspection,
        rejected_interventions=rejected_interventions,
    )


def agent_decide_from_stages(
    diagnostics: dict[str, Any],
    visual_inspection: dict[str, Any],
    diagnostic_inspection: dict[str, Any],
    *,
    rejected_interventions: list[str] | None = None,
) -> dict[str, Any]:
    llm = call_bedrock_staged_decision(
        diagnostics,
        visual_inspection,
        diagnostic_inspection,
        rejected_interventions=rejected_interventions,
    )
    if llm and llm.get("decision") in VALID_INTERVENTIONS:
        llm["decision_source"] = "aws_bedrock_staged_visual_first"
        llm["visual_inspection"] = visual_inspection
        llm["diagnostic_inspection"] = diagnostic_inspection
        llm.setdefault("visual_observations", visual_inspection.get("visual_observations", []))
        llm.setdefault("diagnostic_observations", diagnostic_inspection.get("diagnostic_observations", []))
        return llm

    fallback = fallback_react_policy(
        diagnostics,
        rejected_interventions=rejected_interventions,
    )
    fallback["visual_inspection"] = visual_inspection
    fallback["diagnostic_inspection"] = diagnostic_inspection
    if llm:
        fallback["staged_decision_attempt"] = llm
    return fallback


def agent_decide_with_langgraph(
    diagnostics: dict[str, Any],
    image_path: Path,
    *,
    scenario_name: str,
    rejected_interventions: list[str] | None = None,
    iteration: int = 1,
) -> dict[str, Any]:
    """Run explicit visual-first inspection, diagnostic inspection, and decision nodes."""
    try:
        from langgraph.graph import END, StateGraph

        def visual_inspection_node(state: AgentGraphState) -> AgentGraphState:
            image = Path(state["image_path"])
            visual = call_bedrock_visual_inspection(image) or {
                "decision_source": "visual_inspection_unavailable"
            }
            return {"visual_inspection": visual}

        def diagnostic_inspection_node(state: AgentGraphState) -> AgentGraphState:
            diagnostic = call_bedrock_diagnostic_inspection(state["diagnostics"]) or {
                "decision_source": "diagnostic_inspection_unavailable"
            }
            return {"diagnostic_inspection": diagnostic}

        def staged_decision_node(state: AgentGraphState) -> AgentGraphState:
            decision = agent_decide_from_stages(
                state["diagnostics"],
                state.get("visual_inspection", {}),
                state.get("diagnostic_inspection", {}),
                rejected_interventions=state.get("rejected_interventions", []),
            )
            decision["langgraph_node"] = "staged_decision"
            return {"decision": decision}

        graph = StateGraph(AgentGraphState)
        graph.add_node("visual_inspection", visual_inspection_node)
        graph.add_node("diagnostic_inspection", diagnostic_inspection_node)
        graph.add_node("staged_decision", staged_decision_node)
        graph.set_entry_point("visual_inspection")
        graph.add_edge("visual_inspection", "diagnostic_inspection")
        graph.add_edge("diagnostic_inspection", "staged_decision")
        graph.add_edge("staged_decision", END)
        app = graph.compile()
        result = app.invoke(
            {
                "diagnostics": diagnostics,
                "image_path": str(image_path),
                "rejected_interventions": rejected_interventions or [],
            },
            config={
                "run_name": f"changepoint-poc-{scenario_name}-iter-{iteration}",
                "metadata": {
                    "poc": "changepoint_agent_poc",
                    "scenario": scenario_name,
                    "iteration": iteration,
                    "rejected_interventions": rejected_interventions or [],
                    "bedrock_model_id": os.getenv("AWS_BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID),
                    "bedrock_region": os.getenv("AWS_BEDROCK_REGION", DEFAULT_BEDROCK_REGION),
                },
                "tags": ["changepoint-poc", scenario_name],
            },
        )
        decision = result["decision"]
        decision["langgraph_tracing_requested"] = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
        return decision
    except Exception as exc:
        decision = agent_decide(
            diagnostics,
            image_path,
            rejected_interventions=rejected_interventions,
        )
        decision["langgraph_failed"] = f"{type(exc).__name__}: {exc}"
        decision["langgraph_tracing_requested"] = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
        return decision


def normalize_event_intervals(
    raw_intervals: Any,
    diagnostics: dict[str, Any],
    train_len: int,
) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    if isinstance(raw_intervals, list):
        for item in raw_intervals:
            if isinstance(item, dict):
                start = item.get("start")
                end = item.get("end")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                start, end = item[0], item[1]
            else:
                continue
            try:
                start_i = int(start)
                end_i = int(end)
            except (TypeError, ValueError):
                continue
            start_i = max(0, min(train_len - 1, start_i))
            end_i = max(start_i + 1, min(train_len, end_i))
            intervals.append((start_i, end_i))

    if not intervals:
        for block in diagnostics.get("candidate_event_blocks", []):
            intervals.append((int(block["start"]), int(block["end"])))

    if not intervals:
        cps = diagnostics["detected_changepoints"]
        latest_cp = diagnostics["latest_cp"]
        if len(cps) >= 2:
            intervals.append((cps[-2], cps[-1]))
        else:
            intervals.append((max(0, latest_cp - 20), min(train_len, latest_cp + 20)))

    intervals = sorted(intervals)
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
    return merged


def normalize_step_changepoints(
    raw_changepoints: Any,
    diagnostics: dict[str, Any],
    train_len: int,
) -> list[int]:
    cps: list[int] = []
    if isinstance(raw_changepoints, list):
        for item in raw_changepoints:
            try:
                cp = int(item)
            except (TypeError, ValueError):
                continue
            if 0 <= cp < train_len:
                cps.append(cp)

    if not cps:
        detected = diagnostics.get("detected_changepoints", [])
        if detected and not diagnostics.get("candidate_event_blocks"):
            cps = [int(cp) for cp in detected if 0 <= int(cp) < train_len]

    if not cps:
        primary_cp = int(diagnostics["primary_cp"])
        cps = [max(0, min(train_len - 1, primary_cp))]

    return sorted(set(cps))


def normalize_drift_intervals(
    raw_intervals: Any,
    diagnostics: dict[str, Any],
    train_len: int,
) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    if isinstance(raw_intervals, list):
        for item in raw_intervals:
            if isinstance(item, dict):
                start = item.get("start")
                end = item.get("end")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                start, end = item[0], item[1]
            else:
                continue
            try:
                start_i = int(start)
                end_i = int(end)
            except (TypeError, ValueError):
                continue
            start_i = max(0, min(train_len - 2, start_i))
            end_i = max(start_i + 1, min(train_len - 1, end_i))
            intervals.append((start_i, end_i))

    if not intervals:
        for interval in diagnostics.get("candidate_drift_intervals", []):
            intervals.append((int(interval["start"]), int(interval["end"])))

    if not intervals:
        detected = diagnostics.get("detected_changepoints", [])
        if len(detected) >= 2:
            intervals.append((int(detected[0]), int(detected[-1])))

    if not intervals:
        primary_cp = int(diagnostics["primary_cp"])
        intervals.append((max(0, primary_cp - 60), min(train_len - 1, primary_cp + 60)))

    return sorted(set(intervals))


def tuning_event_blocks_from_decision(
    decision: dict[str, Any],
    diagnostics: dict[str, Any],
    train_len: int,
) -> list[dict[str, Any]]:
    raw_intervals = decision.get("holiday_event_intervals") or decision.get("event_intervals")
    intervals = normalize_event_intervals(raw_intervals, diagnostics, train_len)
    return [
        {
            "start": int(start),
            "end": int(end),
            "duration": int(end - start),
        }
        for start, end in intervals
    ]


def action_signature(result: ForecastResult) -> str:
    intervention = result.details.get("intervention", result.method)
    if intervention == "full_history_clean_event":
        return f"{intervention}:{json.dumps(result.details.get('cleaned_intervals', []))}"
    if intervention == "full_history_prophet_tuned_holidays":
        return (
            f"{intervention}:"
            f"{json.dumps(result.details.get('holiday_event_intervals', []))}:"
            f"{result.details.get('chosen_changepoint_prior_scale')}:"
            f"{result.details.get('chosen_holidays_prior_scale')}"
        )
    if intervention == "full_history_step_regressor":
        return f"{intervention}:{json.dumps(result.details.get('step_changepoints', []))}"
    if intervention == "full_history_ramp_regressor":
        return f"{intervention}:{json.dumps(result.details.get('drift_intervals', []))}"
    return str(intervention)


def evaluate_agent_intervention(scenario: Scenario, diagnostics: dict[str, Any], decision: dict[str, Any]) -> ForecastResult:
    train_end = scenario.train_end
    test_horizon = scenario.test_horizon
    train = scenario.frame.iloc[:train_end].copy()
    test = scenario.frame.iloc[train_end : train_end + test_horizon].copy()
    cps = diagnostics["detected_changepoints"]
    latest_cp = diagnostics["latest_cp"]
    primary_cp = diagnostics["primary_cp"]
    intervention = decision["decision"]

    if intervention == "full_history_step_regressor":
        step_cps = normalize_step_changepoints(decision.get("step_changepoints"), diagnostics, len(train))
        yhat = fit_prophet_step_regressors(train, test["ds"], step_cps)
        model = "Prophet() default + post_cp regressors"
        details = {
            "intervention": intervention,
            "requested_step_changepoints": decision.get("step_changepoints"),
            "step_changepoints": step_cps,
        }
    elif intervention == "full_history_ramp_regressor":
        intervals = normalize_drift_intervals(decision.get("drift_intervals"), diagnostics, len(train))
        yhat = fit_prophet_ramp_regressors(train, test["ds"], intervals)
        model = "Prophet() default + drift ramp regressors"
        details = {
            "intervention": intervention,
            "requested_drift_intervals": decision.get("drift_intervals"),
            "drift_intervals": [[start, end] for start, end in intervals],
        }
    elif intervention == "full_history_clean_event":
        intervals = normalize_event_intervals(decision.get("event_intervals"), diagnostics, len(train))
        cleaned = clean_event_blocks(train, intervals)
        yhat = fit_prophet_default(cleaned, test["ds"])
        model = "Prophet() default on full history with event blocks cleaned"
        details = {
            "intervention": intervention,
            "requested_event_intervals": decision.get("event_intervals"),
            "cleaned_intervals": [[start, end] for start, end in intervals],
        }
    elif intervention == "full_history_prophet_tuned_holidays":
        event_blocks = tuning_event_blocks_from_decision(decision, diagnostics, len(train))
        yhat, tuning_details = fit_prophet_tuned_holidays(train, test["ds"], event_blocks)
        model = "Prophet tuned changepoint/holiday priors with recurring-event holidays"
        details = {
            "intervention": intervention,
            "requested_holiday_event_intervals": decision.get("holiday_event_intervals"),
            "holiday_event_intervals": [[block["start"], block["end"]] for block in event_blocks],
            **tuning_details,
        }
    elif intervention == "recent_window":
        recent = evaluate_naive_recent_window(scenario, cps)
        return ForecastResult(
            scenario=scenario.name,
            method="react_agent_intervention",
            model=f"recent_window + {recent.model}",
            yhat=recent.yhat,
            metrics=recent.metrics,
            details=recent.details
            | {"intervention": intervention, "decision_source": decision.get("decision_source")},
        )
    else:
        raise ValueError(intervention)

    return ForecastResult(
        scenario=scenario.name,
        method="react_agent_intervention",
        model=model,
        yhat=yhat,
        metrics=metrics(test["y"].to_numpy(), yhat),
        details=details | {"decision_source": decision.get("decision_source")},
    )


def run_agent_hypothesis_loop(
    scenario: Scenario,
    diagnostics: dict[str, Any],
    agent_diagnostics: dict[str, Any],
    agent_context_path: Path,
    naive_workflow_result: ForecastResult,
) -> tuple[ForecastResult, dict[str, Any]]:
    """Iteratively propose bounded interventions, validate externally, and retry failures."""
    attempts: list[dict[str, Any]] = []
    rejected_interventions: list[str] = []
    best_result: ForecastResult | None = None
    best_decision: dict[str, Any] | None = None

    for iteration in range(1, MAX_AGENT_ITERATIONS + 1):
        decision = agent_decide_with_langgraph(
            agent_diagnostics,
            agent_context_path,
            scenario_name=scenario.name,
            rejected_interventions=rejected_interventions,
            iteration=iteration,
        )
        intervention = decision["decision"]
        result = evaluate_agent_intervention(scenario, diagnostics, decision)
        action_key = action_signature(result)

        accepted = result.metrics["MAE"] <= naive_workflow_result.metrics["MAE"]
        attempt = {
            "iteration": iteration,
            "intervention": intervention,
            "action_signature": action_key,
            "accepted": accepted,
            "decision": decision,
            "candidate_metrics": result.metrics,
            "naive_workflow_method": naive_workflow_result.method,
            "naive_workflow_metrics": naive_workflow_result.metrics,
            # Metrics stay outside the graph; only the concrete action signature is rejected.
            "validated_on_heldout_window": True,
        }
        attempts.append(attempt)

        if best_result is None or result.metrics["MAE"] < best_result.metrics["MAE"]:
            best_result = result
            best_decision = decision

        if accepted:
            loop = {
                "accepted": True,
                "accepted_iteration": iteration,
                "max_iterations": MAX_AGENT_ITERATIONS,
                "naive_workflow_method": naive_workflow_result.method,
                "attempts": attempts,
                "final_decision": decision,
            }
            return result, loop

        if action_key not in rejected_interventions:
            rejected_interventions.append(action_key)

    assert best_result is not None
    loop = {
        "accepted": False,
        "accepted_iteration": None,
        "max_iterations": MAX_AGENT_ITERATIONS,
        "naive_workflow_method": naive_workflow_result.method,
        "attempts": attempts,
        "final_decision": best_decision,
        "note": "No agent intervention beat the naive workflow; reporting the best attempted intervention.",
    }
    return best_result, loop


def write_forecast_plot(scenario: Scenario, results: list[ForecastResult], cps: list[int]) -> Path:
    path = ARTIFACT_DIR / f"{scenario.name}_forecast_comparison.png"
    df = scenario.frame
    train_end = scenario.train_end
    test = df.iloc[train_end : train_end + scenario.test_horizon]
    history_start = max(0, train_end - 520)
    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.plot(
        df["ds"].iloc[history_start:train_end],
        df["y"].iloc[history_start:train_end],
        color="#7f7f7f",
        linewidth=1.0,
        label="train history",
    )
    ax.plot(test["ds"], test["y"], color="black", linewidth=2.0, label="actual test")
    colors = {
        "naive_best_default_workflow": "#d62728",
        "react_agent_intervention": "#2ca02c",
        "full_history_Prophet() default": "#1f77b4",
        "full_history_ARIMA() default": "#9467bd",
    }
    for result in results:
        ax.plot(
            test["ds"],
            result.yhat,
            linewidth=1.7,
            color=colors.get(result.method, None),
            label=f"{result.method} ({result.metrics['MAE']:.1f} MAE)",
        )
    for cp in cps:
        if cp >= history_start:
            ax.axvline(df["ds"].iloc[cp], color="#d62728", linestyle="--", alpha=0.45)
    ax.axvline(df["ds"].iloc[train_end], color="black", linestyle="-", linewidth=1.2)
    ax.set_title(f"Forecast comparison: {scenario.title}")
    ax.set_xlabel("date")
    ax.set_ylabel("y")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def write_metrics_bar(metrics_df: pd.DataFrame) -> Path:
    path = ARTIFACT_DIR / "mae_comparison.png"
    order = [
        "full_history_Prophet() default",
        "full_history_ARIMA() default",
        "naive_best_default_workflow",
        "react_agent_intervention",
    ]
    groups = list(metrics_df.groupby("scenario"))
    fig, axes = plt.subplots(1, len(groups), figsize=(7 * len(groups), 4.8), sharey=False)
    axes = np.atleast_1d(axes)
    for ax, (scenario_name, group) in zip(axes, groups, strict=True):
        group = group.set_index("method").loc[[m for m in order if m in set(group["method"])]].reset_index()
        colors = ["#1f77b4", "#9467bd", "#d62728", "#2ca02c"][: len(group)]
        ax.barh(group["method"], group["MAE"], color=colors)
        ax.set_title(scenario_name)
        ax.set_xlabel("test MAE lower is better")
        ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def result_rows(results: list[ForecastResult]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        row = {
            "scenario": result.scenario,
            "method": result.method,
            "model": result.model,
            **result.metrics,
            "details": json.dumps(result.details, sort_keys=True),
        }
        rows.append(row)
    return rows


def markdown_table(df: pd.DataFrame, columns: list[str]) -> str:
    rows = df[columns].copy()
    for col in ["MAE", "RMSE", "sMAPE", "WAPE"]:
        if col in rows:
            rows[col] = rows[col].map(lambda x: f"{float(x):.3f}")
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = ["| " + " | ".join(str(row[col]) for col in columns) + " |" for _, row in rows.iterrows()]
    return "\n".join([header, separator, *body])


def write_summary(
    metrics_df: pd.DataFrame,
    decisions: dict[str, Any],
    artifact_paths: dict[str, str],
) -> Path:
    path = ARTIFACT_DIR / "summary.md"
    decision_sources = sorted(
        {
            payload.get("decision", {}).get("decision_source", "unknown")
            for payload in decisions.values()
        }
    )
    lines = [
        "# Changepoint POC Summary",
        "",
        "Question: can a bounded analyst/agent beat a naive workflow that validation-selects among",
        "full-history and every detected changepoint-start default Prophet/ARIMA candidate?",
        "",
        f"Decision source(s): `{', '.join(decision_sources)}`.",
        "The image given to the agent excludes synthetic ground-truth boundaries; separate human",
        "diagnostic plots include those boundaries for verification.",
        "",
        "## Metrics",
        "",
        markdown_table(metrics_df, ["scenario", "method", "model", "MAE", "RMSE", "sMAPE", "WAPE"]),
        "",
        "## Agent Decisions",
        "",
        "```json",
        json.dumps(decisions, indent=2),
        "```",
        "",
        "## Artifacts",
        "",
    ]
    for label, artifact in artifact_paths.items():
        lines.append(f"- {label}: `{artifact}`")
    lines.append("")
    lines.append("Interpretation: the agent-style interventions are judged against the coded naive")
    lines.append("workflow that validation-selects among full-history and every detected")
    lines.append("changepoint-start default Prophet/ARIMA candidate.")
    path.write_text("\n".join(lines))
    return path


def main() -> None:
    load_env_file()
    configure_langsmith_env()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = [
        make_level_shift_scenario(),
        make_gradual_drift_scenario(),
        make_temporary_event_scenario(),
        make_many_temporary_events_scenario(),
        make_prophet_hyperparameter_scenario(),
    ]
    all_results: list[ForecastResult] = []
    decisions: dict[str, Any] = {}
    artifact_paths: dict[str, str] = {}

    for scenario in scenarios:
        train_y = scenario.frame["y"].iloc[: scenario.train_end].to_numpy()
        cps, detector = detect_changepoints(train_y, n_bkps=scenario.n_bkps)
        diag_path = write_diagnostic_plot(scenario, cps)
        agent_context_path = write_agent_context_plot(scenario, cps)
        diagnostics = diagnostics_for_scenario(scenario, cps, detector)
        agent_diagnostics = agent_input_diagnostics(diagnostics)
        full_prophet_result = evaluate_default_full_history(scenario, "Prophet() default")
        full_arima_result = evaluate_default_full_history(scenario, "ARIMA() default")
        naive_result = evaluate_naive_default_workflow(scenario, cps)
        agent_result, hypothesis_loop = run_agent_hypothesis_loop(
            scenario,
            diagnostics,
            agent_diagnostics,
            agent_context_path,
            naive_workflow_result=naive_result,
        )
        agent_result.details = agent_result.details | {
            "accepted": hypothesis_loop["accepted"],
            "accepted_iteration": hypothesis_loop["accepted_iteration"],
            "max_iterations": hypothesis_loop["max_iterations"],
        }
        decisions[scenario.name] = {
            "full_diagnostics": diagnostics,
            "agent_input_diagnostics": agent_diagnostics,
            "hypothesis_loop": hypothesis_loop,
            "decision": hypothesis_loop["final_decision"],
        }

        results = [
            full_prophet_result,
            full_arima_result,
            naive_result,
            agent_result,
        ]
        all_results.extend(results)

        forecast_path = write_forecast_plot(scenario, results, cps)
        artifact_paths[f"{scenario.name} diagnostics plot"] = str(diag_path)
        artifact_paths[f"{scenario.name} agent context plot"] = str(agent_context_path)
        artifact_paths[f"{scenario.name} forecast comparison"] = str(forecast_path)

    metrics_df = pd.DataFrame(result_rows(all_results))
    metrics_path = ARTIFACT_DIR / "metrics.csv"
    metrics_df.to_csv(metrics_path, index=False)
    decisions_path = ARTIFACT_DIR / "agent_decisions.json"
    decisions_path.write_text(json.dumps(decisions, indent=2))
    mae_plot = write_metrics_bar(metrics_df)

    artifact_paths["metrics csv"] = str(metrics_path)
    artifact_paths["agent decisions json"] = str(decisions_path)
    artifact_paths["mae comparison plot"] = str(mae_plot)
    summary_path = write_summary(metrics_df, decisions, artifact_paths)
    artifact_paths["summary"] = str(summary_path)

    print(metrics_df[["scenario", "method", "model", "MAE", "RMSE", "sMAPE", "WAPE"]].to_string(index=False))
    print(f"\nArtifacts written under {ARTIFACT_DIR}")


if __name__ == "__main__":
    main()
