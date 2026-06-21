"""Training-only statistics extraction for the seasonalityV2 POC.

Pure deterministic function — no LLM calls, no randomness.
Produces a StatsBundle from the training split only; never touches val or test data.

Usage
-----
    from stats import extract_stats, stats_to_dict

    bundle = extract_stats(train_df, list(meta["changepoints"].values()))
    d = stats_to_dict(bundle)   # JSON-safe dict
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from config import SEASONALITY_PERIOD


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SegmentStats:
    label: str          # e.g. "seg_0", "seg_1"
    start: str          # ISO date string
    end: str            # ISO date string (exclusive)
    n_obs: int
    mean: float
    std: float
    slope: float        # OLS slope (units/day)
    slope_direction: str  # "up" | "down" | "flat"


@dataclass
class StatsBundle:
    n_obs_train: int
    changepoints_detected: list[dict]          # [{date, index}]
    segments: list[SegmentStats]
    seasonality_period_days: int
    seasonality_mode_signal: float             # 0.0=additive, 1.0=multiplicative
    noise_level: float                         # median absolute deviation of detrended residuals
    post_last_cp_days: int
    insufficient_seasonal_history: bool        # post_last_cp_days < seasonality_period_days
    trend_direction: str                       # overall "up" | "down" | "flat"
    level_shift_magnitude: float               # abs mean difference at first detected CP
    variance_ratio: float                      # std(last half) / std(first half) of training
    last_cp_date: str                          # ISO date of latest changepoint in training


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ols_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Simple OLS slope. Returns 0.0 if fewer than 2 points."""
    if len(x) < 2:
        return 0.0
    slope, _, _, _, _ = scipy_stats.linregress(x.astype(float), y.astype(float))
    return float(slope)


def _slope_direction(slope: float, threshold: float = 0.005) -> str:
    if slope > threshold:
        return "up"
    if slope < -threshold:
        return "down"
    return "flat"


def _safe(value: float) -> float:
    """Replace NaN/Inf with 0.0 so JSON serialisation never fails."""
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return float(value)


def _seasonality_mode_signal(
    y: np.ndarray,
    trend: np.ndarray,
    period: int,
) -> float:
    """Heuristic: how multiplicative is the seasonality?

    Idea: if seasonal amplitude scales with the trend level, the series is
    multiplicative. We measure this by regressing log(|seasonal residual|)
    on log(trend level) — a positive slope indicates multiplicativity.

    Returns a value in [0, 1]:  0 = purely additive, 1 = strongly multiplicative.
    """
    seasonal_resid = y - trend
    # Use rolling mean as proxy for trend where trend is available
    trend_pos = np.where(trend > 0.5, trend, 0.5)   # guard against log(0)
    resid_abs  = np.abs(seasonal_resid)
    resid_pos  = np.where(resid_abs > 0.001, resid_abs, 0.001)

    log_trend  = np.log(trend_pos)
    log_resid  = np.log(resid_pos)

    slope, _, r, _, _ = scipy_stats.linregress(log_trend, log_resid)
    # Positive slope → multiplicative; clip to [0, 1]
    signal = float(np.clip(slope, 0.0, 2.0) / 2.0)
    return _safe(signal)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_stats(
    train_df: pd.DataFrame,
    changepoints: list,   # list of pd.Timestamp or convertible
) -> StatsBundle:
    """Extract training-only statistics for the agent.

    Parameters
    ----------
    train_df : pd.DataFrame
        Columns ``ds`` (datetime) and ``y`` (float). Training split only.
    changepoints : list of pd.Timestamp
        Ground-truth injection dates from ``meta["changepoints"].values()``.
        Used to define segment boundaries. Only those within training are used.

    Returns
    -------
    StatsBundle
        All values derived solely from training data.
    """
    y_all   = train_df["y"].to_numpy(dtype=float)
    ds_all  = pd.to_datetime(train_df["ds"])
    n       = len(y_all)
    x_all   = np.arange(n, dtype=float)

    # -----------------------------------------------------------------------
    # Filter changepoints that fall within training window
    # -----------------------------------------------------------------------
    train_start = ds_all.iloc[0]
    train_end   = ds_all.iloc[-1]

    cps_in_train: list[pd.Timestamp] = []
    for cp in changepoints:
        ts = pd.Timestamp(cp)
        if train_start <= ts <= train_end:
            cps_in_train.append(ts)
    cps_in_train.sort()

    # Map timestamps to indices
    cp_indices: list[int] = []
    for ts in cps_in_train:
        loc = ds_all.searchsorted(ts)
        cp_indices.append(int(min(loc, n - 1)))

    detected = [
        {"date": ts.isoformat(), "index": idx}
        for ts, idx in zip(cps_in_train, cp_indices)
    ]

    # -----------------------------------------------------------------------
    # Segment statistics
    # -----------------------------------------------------------------------
    boundaries = [0] + cp_indices + [n]
    segments: list[SegmentStats] = []

    for seg_i, (lo, hi) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        seg_y  = y_all[lo:hi]
        seg_x  = x_all[lo:hi]
        seg_ds = ds_all.iloc[lo:hi]

        slope = _ols_slope(seg_x, seg_y)
        std   = float(np.std(seg_y)) if len(seg_y) > 1 else 0.0
        mean  = float(np.mean(seg_y)) if len(seg_y) > 0 else 0.0

        segments.append(SegmentStats(
            label=f"seg_{seg_i}",
            start=seg_ds.iloc[0].isoformat() if len(seg_ds) > 0 else "",
            end=seg_ds.iloc[-1].isoformat() if len(seg_ds) > 0 else "",
            n_obs=len(seg_y),
            mean=_safe(mean),
            std=_safe(std),
            slope=_safe(slope),
            slope_direction=_slope_direction(slope),
        ))

    # -----------------------------------------------------------------------
    # Overall trend
    # -----------------------------------------------------------------------
    overall_slope = _ols_slope(x_all, y_all)
    # Rolling-mean trend proxy for seasonality-mode signal
    trend_proxy = (
        pd.Series(y_all)
        .rolling(window=SEASONALITY_PERIOD, center=True, min_periods=1)
        .mean()
        .to_numpy()
    )

    # -----------------------------------------------------------------------
    # Seasonality mode signal
    # -----------------------------------------------------------------------
    mode_signal = _seasonality_mode_signal(y_all, trend_proxy, SEASONALITY_PERIOD)

    # -----------------------------------------------------------------------
    # Noise level: MAD of detrended residuals
    # -----------------------------------------------------------------------
    detrended   = y_all - trend_proxy
    noise_level = _safe(float(np.median(np.abs(detrended - np.median(detrended)))))

    # -----------------------------------------------------------------------
    # Post-last-changepoint history
    # -----------------------------------------------------------------------
    if cp_indices:
        last_cp_idx      = cp_indices[-1]
        post_last_cp_days = n - last_cp_idx
        last_cp_date      = cps_in_train[-1].isoformat()
    else:
        post_last_cp_days = n
        last_cp_date      = train_start.isoformat()

    insufficient = post_last_cp_days < SEASONALITY_PERIOD

    # -----------------------------------------------------------------------
    # Level shift magnitude: mean difference around first CP
    # -----------------------------------------------------------------------
    if cp_indices:
        first_cp = cp_indices[0]
        window   = min(30, first_cp, n - first_cp)
        if window > 0:
            before = float(np.mean(y_all[max(0, first_cp - window): first_cp]))
            after  = float(np.mean(y_all[first_cp: first_cp + window]))
            level_shift_mag = _safe(abs(after - before))
        else:
            level_shift_mag = 0.0
    else:
        level_shift_mag = 0.0

    # -----------------------------------------------------------------------
    # Variance ratio: std of second half vs first half of training
    # -----------------------------------------------------------------------
    half = n // 2
    std_first = float(np.std(y_all[:half])) if half > 1 else 1.0
    std_last  = float(np.std(y_all[half:])) if (n - half) > 1 else 1.0
    variance_ratio = _safe(std_last / std_first if std_first > 0 else 1.0)

    return StatsBundle(
        n_obs_train=n,
        changepoints_detected=detected,
        segments=segments,
        seasonality_period_days=SEASONALITY_PERIOD,
        seasonality_mode_signal=_safe(mode_signal),
        noise_level=noise_level,
        post_last_cp_days=post_last_cp_days,
        insufficient_seasonal_history=insufficient,
        trend_direction=_slope_direction(overall_slope),
        level_shift_magnitude=level_shift_mag,
        variance_ratio=variance_ratio,
        last_cp_date=last_cp_date,
    )


def stats_to_dict(bundle: StatsBundle) -> dict:
    """Serialise StatsBundle to a JSON-safe dict (no NaN/Inf).

    Converts nested dataclasses and replaces any remaining NaN/Inf with null.
    """
    import json

    raw = asdict(bundle)

    def _sanitise(obj):
        if isinstance(obj, dict):
            return {k: _sanitise(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitise(v) for v in obj]
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        return obj

    sanitised = _sanitise(raw)

    # Round-trip through JSON to catch any edge cases
    return json.loads(json.dumps(sanitised))
