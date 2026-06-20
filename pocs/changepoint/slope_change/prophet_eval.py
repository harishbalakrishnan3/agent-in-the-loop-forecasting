"""Naive Prophet evaluation for slope-change datasets.

Fits a default ("naive") Prophet model on the first ``TRAIN_FRACTION`` of each
series, forecasts the held-out remainder, scores forecast error (MAE/RMSE/MAPE)
on the horizon, extracts Prophet's own automatic changepoints (ranked by trend
delta magnitude), matches them to ground-truth slope changes within a tolerance
window, and classifies each dataset pass/borderline/fail by MAPE bands.

"Naive" = default Prophet config, fit on the training portion only — no
changepoint hints, custom priors, or tuning.

Self-contained: imports only numpy/pandas/prophet/darts and the local datasets
module.

Usage:
    uv run python -m pocs.changepoint.slope_change.prophet_eval
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from darts import TimeSeries
from prophet import Prophet

from pocs.changepoint.slope_change.datasets import generate_all_datasets

# ─────────────────────────────────────────────────────────────────────────────
# Tunable constants (documented, inspectable)
# ─────────────────────────────────────────────────────────────────────────────
TRAIN_FRACTION = 0.8          # hold out the last 20% as the forecast horizon
PASS_MAPE = 10.0              # MAPE ≤ 10% ⇒ "pass" (naive Prophet handles it)
FAIL_MAPE = 25.0             # MAPE ≥ 25% ⇒ "fail" (baseline breaks down)
MATCH_TOL_FRACTION = 0.05     # changepoint match window = ±5% of series length
DELTA_KEEP_FRACTION = 0.01    # keep Prophet CPs with |delta| ≥ 1% of max|delta|


@contextmanager
def _suppress_prophet_logs():
    """Silence Prophet/cmdstanpy chatter during fitting."""
    loggers = [logging.getLogger(n) for n in ("prophet", "cmdstanpy", "stan")]
    prev = [lg.level for lg in loggers]
    for lg in loggers:
        lg.setLevel(logging.CRITICAL)
    # cmdstanpy also writes to stderr/stdout via the C++ backend; redirect fd.
    try:
        with open(os.devnull, "w") as devnull:
            yield devnull
    finally:
        for lg, lvl in zip(loggers, prev):
            lg.setLevel(lvl)


@dataclass
class SlopeChangeEvalResult:
    """Per-dataset naive-Prophet evaluation result."""

    dataset_id: str
    train_end_index: int
    horizon: int
    n_true_changepoints: int
    detected_changepoint_indices: list[int]
    detected_changepoint_dates: list[str]
    matched_true_indices: list[int]
    detection_precision: float
    detection_recall: float
    mae: float
    rmse: float
    mape: float
    classification: str  # "pass" | "borderline" | "fail"
    expected_difficulty: str = "unknown"
    extra: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Core helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_prophet_frame(ts: TimeSeries) -> pd.DataFrame:
    """Convert a Darts TimeSeries to a Prophet ``ds,y`` frame."""
    values = ts.values().flatten().astype(float)
    dates = ts.time_index
    return pd.DataFrame({"ds": pd.DatetimeIndex(dates), "y": values})


def _detected_changepoints(model: Prophet, n_total: int) -> list[int]:
    """Return Prophet's significant changepoints as series indices.

    Keep changepoints whose fitted trend-rate change ``|delta|`` is at least
    ``DELTA_KEEP_FRACTION`` of the largest, then map their dates to the nearest
    series index in ``[0, n_total)``.
    """
    deltas = np.asarray(model.params["delta"]).mean(axis=0).flatten()
    cps = np.asarray(model.changepoints)  # timestamps (training range)
    if len(deltas) == 0 or len(cps) == 0:
        return []
    max_abs = float(np.max(np.abs(deltas)))
    if max_abs == 0.0:
        return []
    keep = np.abs(deltas) >= DELTA_KEEP_FRACTION * max_abs
    start = model.history["ds"].min()
    freq = pd.infer_freq(model.history["ds"]) or "D"
    step = pd.tseries.frequencies.to_offset(freq)
    indices: list[int] = []
    for ts_cp, k in zip(cps, keep):
        if not k:
            continue
        # index = number of steps from series start to the changepoint date
        delta_steps = (pd.Timestamp(ts_cp) - start) / step.delta if hasattr(step, "delta") else None
        if delta_steps is None:
            # fallback: positional via business-agnostic day diff
            delta_steps = (pd.Timestamp(ts_cp) - start).days
        idx = int(round(delta_steps))
        if 0 <= idx < n_total:
            indices.append(idx)
    return sorted(set(indices))


def _match_detections(
    detected: list[int], truth: list[int], n_total: int
) -> tuple[list[int], float, float]:
    """Match detected changepoints to ground truth within ±tol indices.

    Returns (matched_true_indices, precision, recall). By convention, with zero
    true changepoints recall is 1.0; with zero detections precision is 0.0
    unless there is also nothing to find (then 1.0).
    """
    tol = max(1, int(round(MATCH_TOL_FRACTION * n_total)))
    matched_true = [t for t in truth if any(abs(d - t) <= tol for d in detected)]
    matched_det = [d for d in detected if any(abs(d - t) <= tol for t in truth)]

    if len(truth) == 0:
        recall = 1.0
    else:
        recall = len(matched_true) / len(truth)

    if len(detected) == 0:
        precision = 1.0 if len(truth) == 0 else 0.0
    else:
        precision = len(matched_det) / len(detected)

    return matched_true, precision, recall


def _metrics(actual: np.ndarray, forecast: np.ndarray) -> tuple[float, float, float]:
    """MAE, RMSE, MAPE on the held-out horizon."""
    err = forecast - actual
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    denom = np.where(np.abs(actual) < 1e-9, 1e-9, np.abs(actual))
    mape = float(np.mean(np.abs(err) / denom) * 100.0)
    return mae, rmse, mape


def forecast_holdout(ts: TimeSeries) -> dict:
    """Fit naive Prophet on the first TRAIN_FRACTION, forecast the held-out tail.

    Returns a dict with the held-out forecast, actuals, metrics, detected
    changepoint indices/dates, and the split index. Used by both the evaluator
    and the visualization overlay.
    """
    n = len(ts)
    train_end = int(round(TRAIN_FRACTION * n))
    df = _to_prophet_frame(ts)
    train_df = df.iloc[:train_end]
    horizon = n - train_end

    model = Prophet()  # naive: all defaults
    with _suppress_prophet_logs():
        model.fit(train_df)
        future = model.make_future_dataframe(periods=horizon, freq=pd.infer_freq(df["ds"]) or "D")
        fcst = model.predict(future)

    forecast = fcst["yhat"].to_numpy()[train_end:train_end + horizon]
    actual = df["y"].to_numpy()[train_end:train_end + horizon]
    mae, rmse, mape = _metrics(actual, forecast)

    det_idx = _detected_changepoints(model, n)
    dates = ts.time_index
    det_dates = [str(dates[i]) for i in det_idx if i < len(dates)]

    return {
        "train_end_index": train_end,
        "horizon": horizon,
        "forecast": forecast,
        "actual": actual,
        "mae": mae,
        "rmse": rmse,
        "mape": mape,
        "detected_changepoint_indices": det_idx,
        "detected_changepoint_dates": det_dates,
    }


def _classify(mape: float) -> str:
    if mape <= PASS_MAPE:
        return "pass"
    if mape >= FAIL_MAPE:
        return "fail"
    return "borderline"


def evaluate_dataset(ts: TimeSeries, metadata: dict) -> SlopeChangeEvalResult:
    """Evaluate naive Prophet on one slope-change dataset."""
    out = forecast_holdout(ts)
    truth = list(metadata.get("changepoint_indices", []))
    matched, precision, recall = _match_detections(
        out["detected_changepoint_indices"], truth, len(ts)
    )
    return SlopeChangeEvalResult(
        dataset_id=metadata.get("dataset_id", "unnamed"),
        train_end_index=out["train_end_index"],
        horizon=out["horizon"],
        n_true_changepoints=len(truth),
        detected_changepoint_indices=out["detected_changepoint_indices"],
        detected_changepoint_dates=out["detected_changepoint_dates"],
        matched_true_indices=matched,
        detection_precision=round(precision, 3),
        detection_recall=round(recall, 3),
        mae=round(out["mae"], 3),
        rmse=round(out["rmse"], 3),
        mape=round(out["mape"], 2),
        classification=_classify(out["mape"]),
    )


# Expected difficulty per catalog id (for reporting context, from data-model.md).
EXPECTED_DIFFICULTY = {
    "S1_single_gentle": "easy",
    "S2_single_sharp": "easy",
    "S3_single_subtle": "hard",
    "S4_multiple_changes": "medium",
    "S5_noisy": "hard",
    "S6_with_seasonality": "medium",
    "S7_trend_reversal": "medium",
    "S8_close_together": "hard",
    "S9_no_changepoint": "control",
    "S10_frequent_changes": "hardest",
}


def evaluate_all() -> list[SlopeChangeEvalResult]:
    """Generate the full catalog and evaluate naive Prophet on each dataset."""
    results: list[SlopeChangeEvalResult] = []
    for name, (ts, meta) in generate_all_datasets().items():
        res = evaluate_dataset(ts, meta)
        res.expected_difficulty = EXPECTED_DIFFICULTY.get(name, "unknown")
        results.append(res)
    return results


def summarize(results: list[SlopeChangeEvalResult]) -> str:
    """Render a markdown results table + a complex-failure section."""
    lines = []
    lines.append("| Dataset | Difficulty | True CPs | Prophet CPs | Matched | "
                 "Precision | Recall | MAE | RMSE | MAPE % | Verdict |")
    lines.append("|---------|-----------|---------:|------------:|--------:|"
                 "----------:|-------:|----:|-----:|-------:|---------|")
    for r in results:
        lines.append(
            f"| {r.dataset_id} | {r.expected_difficulty} | "
            f"{r.n_true_changepoints} | "
            f"{len(r.detected_changepoint_indices)} | {len(r.matched_true_indices)} | "
            f"{r.detection_precision:.2f} | {r.detection_recall:.2f} | "
            f"{r.mae:.1f} | {r.rmse:.1f} | {r.mape:.1f} | {r.classification.upper()} |"
        )

    failures = [r for r in results if r.classification == "fail"]
    lines.append("")
    lines.append("### Complex datasets where naive Prophet fails")
    lines.append("")
    if not failures:
        lines.append("_No datasets exceeded the failure threshold._")
    else:
        for r in failures:
            lines.append(
                f"- **{r.dataset_id}** ({r.expected_difficulty}): held-out "
                f"MAPE={r.mape:.1f}% (≥ {FAIL_MAPE:.0f}% fail threshold), "
                f"RMSE={r.rmse:.1f}; matched {len(r.matched_true_indices)} of its true "
                f"slope changes. Naive Prophet extrapolates the wrong trend over the "
                f"held-out horizon."
            )
    return "\n".join(lines)


def main():
    print("Evaluating naive Prophet on the slope-change catalog...\n")
    results = evaluate_all()
    print(summarize(results))
    n_pass = sum(r.classification == "pass" for r in results)
    n_fail = sum(r.classification == "fail" for r in results)
    print(f"\nPASS={n_pass}  FAIL={n_fail}  BORDERLINE="
          f"{sum(r.classification == 'borderline' for r in results)}")


if __name__ == "__main__":
    main()
