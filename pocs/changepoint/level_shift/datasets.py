"""Level shift dataset generator using Darts.

Generates synthetic time series with known level shifts (abrupt mean changes)
at configurable positions. All generation is seeded for reproducibility.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from darts import TimeSeries
from darts.utils.timeseries_generation import (
    gaussian_timeseries,
    linear_timeseries,
    sine_timeseries,
)


def generate_level_shift_series(
    length: int = 500,
    freq: str = "D",
    start_date: str = "2023-01-01",
    base_level: float = 100.0,
    base_slope: float = 0.0,
    noise_std: float = 5.0,
    changepoint_indices: list[int] | None = None,
    magnitudes: list[float] | None = None,
    seasonality_period: int | None = None,
    seasonality_amplitude: float = 0.0,
    seed: int = 42,
    dataset_id: str = "unnamed",
) -> tuple[TimeSeries, dict]:
    """Generate a synthetic time series with known level shifts.

    Args:
        length: Total number of data points.
        freq: Frequency string ("D" for daily, "H" for hourly, etc.).
        start_date: Start date of the series.
        base_level: Starting mean value.
        base_slope: Underlying linear trend per time step.
        noise_std: Standard deviation of Gaussian noise.
        changepoint_indices: List of indices where level shifts occur.
        magnitudes: List of shift magnitudes (positive = up, negative = down).
        seasonality_period: Period of seasonal component (None = no seasonality).
        seasonality_amplitude: Amplitude of the seasonal component.
        seed: Random seed for reproducibility.
        dataset_id: Identifier for this dataset configuration.

    Returns:
        Tuple of (TimeSeries, metadata dict with ground truth).
    """
    if changepoint_indices is None:
        changepoint_indices = []
    if magnitudes is None:
        magnitudes = []
    if len(changepoint_indices) != len(magnitudes):
        raise ValueError("changepoint_indices and magnitudes must have the same length")
    for idx in changepoint_indices:
        if idx < 0 or idx >= length:
            raise ValueError(f"Changepoint index {idx} out of range [0, {length})")

    rng = np.random.default_rng(seed)

    # Base signal: constant level + linear trend
    time_steps = np.arange(length, dtype=float)
    values = np.full(length, base_level) + base_slope * time_steps

    # Inject level shifts (cumulative: each shift adds to all subsequent points)
    for cp_idx, magnitude in zip(changepoint_indices, magnitudes):
        values[cp_idx:] += magnitude

    # Add seasonality
    if seasonality_period is not None and seasonality_amplitude > 0:
        seasonal = seasonality_amplitude * np.sin(
            2 * np.pi * time_steps / seasonality_period
        )
        values += seasonal

    # Add noise
    noise = rng.normal(0, noise_std, length)
    values += noise

    # Build Darts TimeSeries
    dates = pd.date_range(start=start_date, periods=length, freq=freq)
    ts = TimeSeries.from_times_and_values(
        times=pd.DatetimeIndex(dates),
        values=values,
    )

    # Compute changepoint dates
    changepoint_dates = [str(dates[idx]) for idx in changepoint_indices]

    metadata = {
        "dataset_id": dataset_id,
        "length": length,
        "changepoint_indices": changepoint_indices,
        "changepoint_dates": changepoint_dates,
        "magnitudes": magnitudes,
        "type": "level_shift",
        "noise_std": noise_std,
        "base_level": base_level,
        "base_slope": base_slope,
        "seasonality_period": seasonality_period,
        "seasonality_amplitude": seasonality_amplitude,
        "seed": seed,
    }

    return ts, metadata


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-configured dataset catalog (D1–D10)
# ═══════════════════════════════════════════════════════════════════════════════

DATASET_CONFIGS = {
    "D1_single_large": dict(
        length=500,
        changepoint_indices=[250],
        magnitudes=[40.0],
        noise_std=5.0,
        seed=42,
        dataset_id="D1_single_large",
    ),
    "D2_single_subtle": dict(
        length=500,
        changepoint_indices=[250],
        magnitudes=[10.0],
        noise_std=8.0,
        seed=43,
        dataset_id="D2_single_subtle",
    ),
    "D3_multiple": dict(
        length=600,
        changepoint_indices=[150, 350, 500],
        magnitudes=[30.0, -20.0, 25.0],
        noise_std=3.0,
        seed=44,
        dataset_id="D3_multiple",
    ),
    "D4_noisy": dict(
        length=500,
        changepoint_indices=[250],
        magnitudes=[30.0],
        noise_std=15.0,
        seed=45,
        dataset_id="D4_noisy",
    ),
    "D5_with_trend": dict(
        length=400,
        base_slope=0.1,
        changepoint_indices=[200],
        magnitudes=[30.0],
        noise_std=3.0,
        seed=46,
        dataset_id="D5_with_trend",
    ),
    "D6_with_seasonality": dict(
        length=500,
        changepoint_indices=[250],
        magnitudes=[50.0],
        noise_std=3.0,
        seasonality_period=7,
        seasonality_amplitude=10.0,
        seed=47,
        dataset_id="D6_with_seasonality",
    ),
    "D7_close_together": dict(
        length=400,
        changepoint_indices=[180, 230],
        magnitudes=[25.0, -15.0],
        noise_std=4.0,
        seed=48,
        dataset_id="D7_close_together",
    ),
    "D8_no_changepoint": dict(
        length=400,
        changepoint_indices=[],
        magnitudes=[],
        noise_std=5.0,
        seed=49,
        dataset_id="D8_no_changepoint",
    ),
    "D9_large_series": dict(
        length=2000,
        changepoint_indices=[1000],
        magnitudes=[35.0],
        noise_std=5.0,
        seed=50,
        dataset_id="D9_large_series",
    ),
    "D10_small_magnitude_large_series": dict(
        length=2000,
        changepoint_indices=[1000],
        magnitudes=[8.0],
        noise_std=6.0,
        seed=51,
        dataset_id="D10_small_magnitude_large_series",
    ),
}


def generate_all_datasets() -> dict[str, tuple[TimeSeries, dict]]:
    """Generate all 10 pre-configured datasets.

    Returns:
        Dict mapping dataset name to (TimeSeries, metadata) tuples.
    """
    return {
        name: generate_level_shift_series(**config)
        for name, config in DATASET_CONFIGS.items()
    }
