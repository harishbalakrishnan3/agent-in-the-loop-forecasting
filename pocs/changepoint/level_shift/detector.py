"""Level shift detection using PELT with L2 cost (ruptures).

Detects abrupt changes in mean. The L2 cost model finds points where splitting
the series into segments with different means significantly reduces the total
sum of squared errors.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import ruptures as rpt
from darts import TimeSeries


@dataclass
class LevelShiftResult:
    """Result of level shift detection."""

    changepoint_indices: list[int]
    changepoint_dates: list[str]
    magnitudes: list[float]
    n_changepoints: int
    method: str
    penalty: float | str


def detect_level_shift(
    series: TimeSeries | pd.DataFrame,
    penalty: float | str = "bic",
    min_segment_length: int = 10,
) -> LevelShiftResult:
    """Detect abrupt mean changes in a time series using PELT (L2 cost).

    Args:
        series: Input time series (Darts TimeSeries or DataFrame with [timestamp, value]).
        penalty: Penalty for number of changepoints.
            - "bic": Bayesian Information Criterion (automatic).
            - "aic": Akaike Information Criterion (automatic).
            - float: Manual penalty value (higher = fewer changepoints).
        min_segment_length: Minimum number of points between changepoints.

    Returns:
        LevelShiftResult with detected changepoint locations, dates, and magnitudes.
    """
    # Extract values and timestamps
    if isinstance(series, TimeSeries):
        values = series.values().flatten().astype(float)
        timestamps = series.time_index
    elif isinstance(series, pd.DataFrame):
        if "value" in series.columns:
            values = series["value"].to_numpy(dtype=float)
        elif "y" in series.columns:
            values = series["y"].to_numpy(dtype=float)
        else:
            raise ValueError("DataFrame must have a 'value' or 'y' column")
        if "timestamp" in series.columns:
            timestamps = pd.DatetimeIndex(series["timestamp"])
        elif "ds" in series.columns:
            timestamps = pd.DatetimeIndex(series["ds"])
        else:
            timestamps = None
    else:
        raise TypeError(f"Unsupported input type: {type(series)}")

    # Run PELT with L2 cost model
    algo = rpt.Pelt(model="l2", min_size=min_segment_length).fit(values)

    # Determine penalty
    if isinstance(penalty, str):
        n = len(values)
        if penalty.lower() == "bic":
            pen_value = np.log(n) * np.var(values)
        elif penalty.lower() == "aic":
            pen_value = 2 * np.var(values)
        else:
            raise ValueError(f"Unknown penalty type: {penalty}. Use 'bic', 'aic', or a float.")
    else:
        pen_value = float(penalty)

    # Predict changepoints
    breakpoints = algo.predict(pen=pen_value)

    # ruptures always includes the last index (len(values)) as a breakpoint — remove it
    breakpoints = [b for b in breakpoints if b < len(values)]

    # Compute magnitudes: difference in segment means around each breakpoint
    magnitudes = []
    for bp in breakpoints:
        # Mean of segment before breakpoint
        seg_start = 0
        for prev_bp in breakpoints:
            if prev_bp < bp:
                seg_start = prev_bp
        mean_before = values[seg_start:bp].mean()

        # Mean of segment after breakpoint
        seg_end = len(values)
        for next_bp in breakpoints:
            if next_bp > bp:
                seg_end = next_bp
                break
        mean_after = values[bp:seg_end].mean()

        magnitudes.append(float(mean_after - mean_before))

    # Convert indices to dates
    changepoint_dates = []
    if timestamps is not None:
        for bp in breakpoints:
            if bp < len(timestamps):
                changepoint_dates.append(str(timestamps[bp]))
    else:
        changepoint_dates = [str(bp) for bp in breakpoints]

    return LevelShiftResult(
        changepoint_indices=breakpoints,
        changepoint_dates=changepoint_dates,
        magnitudes=magnitudes,
        n_changepoints=len(breakpoints),
        method="pelt_l2",
        penalty=penalty,
    )
