"""Slope-change dataset generator using Darts.

Generates synthetic time series with known *slope changes* (changes in trend
rate) at configurable positions. Unlike a level shift, the trend stays
continuous at each changepoint — only its slope changes. The trend is built as
a continuous piecewise-linear function: the per-step slope starts at
``initial_slope`` and is incremented by each ``slope_deltas[i]`` at
``changepoint_indices[i]``; values accumulate cumulatively so there is no jump
in level at a changepoint.

All generation is seeded for reproducibility. Self-contained: imports nothing
from the level_shift POC or from src/ailf.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from darts import TimeSeries


def generate_slope_change_series(
    length: int = 500,
    freq: str = "D",
    start_date: str = "2023-01-01",
    base_level: float = 100.0,
    initial_slope: float = 0.1,
    changepoint_indices: list[int] | None = None,
    slope_deltas: list[float] | None = None,
    noise_std: float = 3.0,
    seasonality_period: int | None = None,
    seasonality_amplitude: float = 0.0,
    min_segment: int = 20,
    seed: int = 42,
    dataset_id: str = "unnamed",
) -> tuple[TimeSeries, dict]:
    """Generate a synthetic time series with known slope changes.

    Args:
        length: Total number of data points.
        freq: Frequency string ("D" for daily, "H" for hourly, etc.).
        start_date: Start date of the series.
        base_level: Starting value of the trend (the trend's intercept).
        initial_slope: Per-step slope of the first segment.
        changepoint_indices: Indices where the slope changes (strictly increasing).
        slope_deltas: Change applied to the per-step slope at each changepoint
            (positive = steeper up, negative = down). Same length as indices.
        noise_std: Standard deviation of additive Gaussian noise.
        seasonality_period: Period of the seasonal component (None = none).
        seasonality_amplitude: Amplitude of the seasonal component.
        min_segment: Minimum distance from either boundary at which a
            changepoint may be planted (guards against segments too short to
            define a slope).
        seed: Random seed for reproducibility.
        dataset_id: Identifier for this dataset configuration.

    Returns:
        Tuple of (TimeSeries, ground-truth metadata dict).

    Raises:
        ValueError: on mismatched ``changepoint_indices``/``slope_deltas``
            lengths, an index outside ``[min_segment, length - min_segment)``,
            or non-increasing indices.
    """
    if changepoint_indices is None:
        changepoint_indices = []
    if slope_deltas is None:
        slope_deltas = []

    # --- Validation (FR-007) ---
    if len(changepoint_indices) != len(slope_deltas):
        raise ValueError(
            "changepoint_indices and slope_deltas must have the same length "
            f"({len(changepoint_indices)} != {len(slope_deltas)})"
        )
    lo, hi = min_segment, length - min_segment
    for idx in changepoint_indices:
        if idx < lo or idx >= hi:
            raise ValueError(
                f"Changepoint index {idx} too close to a boundary; must be in "
                f"[{lo}, {hi}) for length={length}, min_segment={min_segment}"
            )
    for prev, cur in zip(changepoint_indices, changepoint_indices[1:]):
        if cur <= prev:
            raise ValueError(
                f"changepoint_indices must be strictly increasing; got {changepoint_indices}"
            )

    rng = np.random.default_rng(seed)
    time_steps = np.arange(length, dtype=float)

    # --- Build the per-step slope array (piecewise-constant slope) ---
    slope = np.full(length, float(initial_slope))
    for cp_idx, delta in zip(changepoint_indices, slope_deltas):
        slope[cp_idx:] += delta

    # --- Continuous piecewise-linear trend: cumulative sum of per-step slope ---
    # trend[t] = base_level + sum_{k<t} slope[k]  → continuous at every changepoint.
    increments = np.zeros(length)
    increments[1:] = slope[:-1]
    trend = base_level + np.cumsum(increments)

    values = trend.copy()

    # --- Seasonality (additive) ---
    if seasonality_period is not None and seasonality_amplitude > 0:
        values = values + seasonality_amplitude * np.sin(
            2 * np.pi * time_steps / seasonality_period
        )

    # --- Noise (additive, seeded) ---
    values = values + rng.normal(0.0, noise_std, length)

    # --- Build Darts TimeSeries ---
    dates = pd.date_range(start=start_date, periods=length, freq=freq)
    ts = TimeSeries.from_times_and_values(
        times=pd.DatetimeIndex(dates),
        values=values,
    )

    # --- Ground-truth metadata (FR-004) ---
    slopes_per_segment = [float(initial_slope)]
    for delta in slope_deltas:
        slopes_per_segment.append(slopes_per_segment[-1] + float(delta))

    changepoint_dates = [str(dates[idx]) for idx in changepoint_indices]

    metadata = {
        "dataset_id": dataset_id,
        "length": length,
        "changepoint_indices": list(changepoint_indices),
        "changepoint_dates": changepoint_dates,
        "slope_deltas": [float(d) for d in slope_deltas],
        "slopes_per_segment": slopes_per_segment,
        "type": "slope_change",
        "noise_std": noise_std,
        "base_level": base_level,
        "initial_slope": initial_slope,
        "seasonality_period": seasonality_period,
        "seasonality_amplitude": seasonality_amplitude,
        "seed": seed,
    }

    return ts, metadata


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-configured dataset catalog (S1–S10)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Difficulty is shaped by slope-delta size, noise, number of changes, and the
# placement of changes relative to the 80% train/test split. Series are 500 pts
# (split at 400) unless noted; "near the horizon" means inside the last 20%.

DATASET_CONFIGS = {
    "S1_single_gentle": dict(
        length=500,
        initial_slope=0.1,
        changepoint_indices=[200],
        slope_deltas=[0.25],
        noise_std=2.0,
        seed=42,
        dataset_id="S1_single_gentle",
    ),
    "S2_single_sharp": dict(
        length=500,
        initial_slope=0.1,
        changepoint_indices=[200],
        slope_deltas=[1.2],
        noise_std=2.0,
        seed=43,
        dataset_id="S2_single_sharp",
    ),
    "S3_single_subtle": dict(
        length=500,
        initial_slope=0.1,
        changepoint_indices=[200],
        slope_deltas=[0.18],
        noise_std=8.0,
        seed=44,
        dataset_id="S3_single_subtle",
    ),
    "S4_multiple_changes": dict(
        length=600,
        initial_slope=0.1,
        changepoint_indices=[120, 300, 450],
        slope_deltas=[0.6, -0.9, 0.7],
        noise_std=3.0,
        seed=45,
        dataset_id="S4_multiple_changes",
    ),
    "S5_noisy": dict(
        length=500,
        initial_slope=0.2,
        changepoint_indices=[200],
        slope_deltas=[0.8],
        noise_std=18.0,
        seed=46,
        dataset_id="S5_noisy",
    ),
    "S6_with_seasonality": dict(
        length=500,
        initial_slope=0.1,
        changepoint_indices=[200],
        slope_deltas=[0.7],
        noise_std=3.0,
        seasonality_period=7,
        seasonality_amplitude=15.0,
        seed=47,
        dataset_id="S6_with_seasonality",
    ),
    "S7_trend_reversal": dict(
        length=500,
        initial_slope=0.6,
        changepoint_indices=[250],
        slope_deltas=[-1.2],  # slope flips from +0.6 to -0.6
        noise_std=3.0,
        seed=48,
        dataset_id="S7_trend_reversal",
    ),
    "S8_close_together": dict(
        length=500,
        initial_slope=0.1,
        changepoint_indices=[200, 230],
        slope_deltas=[1.0, -1.3],
        noise_std=4.0,
        seed=49,
        dataset_id="S8_close_together",
    ),
    "S9_no_changepoint": dict(
        length=500,
        initial_slope=0.3,
        changepoint_indices=[],
        slope_deltas=[],
        noise_std=3.0,
        seed=50,
        dataset_id="S9_no_changepoint",
    ),
    "S10_frequent_changes": dict(
        length=600,
        initial_slope=0.1,
        # Several changes, with the last two inside the held-out horizon
        # (split at 480 for length=600): 360 < 480 ≤ 500, 540.
        changepoint_indices=[120, 240, 360, 500, 540],
        slope_deltas=[0.8, -1.1, 0.9, -1.4, 1.2],
        noise_std=5.0,
        seed=51,
        dataset_id="S10_frequent_changes",
    ),
}


def generate_all_datasets() -> dict[str, tuple[TimeSeries, dict]]:
    """Generate all 10 pre-configured datasets.

    Returns:
        Dict mapping dataset name to (TimeSeries, metadata) tuples.
    """
    return {
        name: generate_slope_change_series(**config)
        for name, config in DATASET_CONFIGS.items()
    }
