"""Synthetic seasonality-amplitude-shift generator for the changepoint POC.

Self-contained — no imports from src/ailf/. Mirrors the drift track's
_base_components pattern but uses a flat trend so PELT (rbf) focuses
purely on the amplitude-variance signal.

Usage
-----
    from datasets_seasonal import generate_seasonal_shift, generate_control

    series, break_idx = generate_seasonal_shift(seed=42)
    control = generate_control(seed=99)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from darts import TimeSeries
from darts.utils.timeseries_generation import linear_timeseries, sine_timeseries


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _base_components(
    length: int,
    start: str,
    freq: str,
    seasonality_period: int,
    seasonality_amplitude: float,
    base_noise: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (trend, seasonal, noise) as NumPy arrays.

    Intentionally mirrors src/ailf/pipelines/drift/datasets._base_components
    with ONE difference: end_value=0.0 (flat trend) instead of _BASE_TREND_RISE.
    A non-zero trend slope is a confounding signal for rbf cost — this POC
    wants PELT to react only to the amplitude-variance change.
    """
    ts = pd.Timestamp(start)

    trend = linear_timeseries(
        start_value=0.0,
        end_value=0.0,      # flat — diverges from drift track intentionally
        length=length,
        start=ts,
        freq=freq,
    ).values().ravel()

    seasonal = sine_timeseries(
        value_frequency=1.0 / seasonality_period,
        value_amplitude=seasonality_amplitude,
        length=length,
        start=ts,
        freq=freq,
    ).values().ravel()

    rng = np.random.default_rng(seed)
    noise = base_noise * rng.standard_normal(length)

    return trend, seasonal, noise


def _step(length: int, break_index: int) -> np.ndarray:
    """Heaviside step mask: 0 before break_index, 1 from break_index onward.

    Contrast with the drift track's _ramp() which spreads the change over a
    transition window. Here the structural break is instantaneous (abrupt).
    """
    s = np.zeros(length)
    s[break_index:] = 1.0
    return s


def _validate(
    length: int,
    break_index: int,
    magnitude: float,
    seasonality_period: int,
) -> None:
    """Minimal validation — POC, not production-grade."""
    if length <= 0:
        raise ValueError(f"length must be positive, got {length}.")
    if seasonality_period <= 0:
        raise ValueError(f"seasonality_period must be positive, got {seasonality_period}.")
    if magnitude == 0:
        raise ValueError(
            "magnitude must be non-zero — a zero magnitude produces a series "
            "with no actual change but a label claiming one."
        )
    if break_index < seasonality_period:
        raise ValueError(
            f"break_index={break_index} leaves fewer than {seasonality_period} "
            "points before the break — not enough pre-break seasonal cycles to "
            "establish a stable reference regime."
        )
    if break_index > length - seasonality_period:
        raise ValueError(
            f"break_index={break_index} leaves fewer than {seasonality_period} "
            f"points after the break (length={length}) — the amplitude change "
            "has no room to develop into a recognisable pattern."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_seasonal_shift(
    length: int = 365,
    break_index: int | None = None,     # resolved to length // 2 when None
    magnitude: float = 1.0,            # 1.0 → amplitude doubles (A → 2A)
    seasonality_period: int = 30,
    seasonality_amplitude: float = 5.0,
    base_noise: float = 0.5,           # low so shift is the dominant signal
    seed: int = 42,
    start: str = "2020-01-01",
    freq: str = "D",
) -> tuple[TimeSeries, int]:
    """Generate a univariate series with one abrupt seasonality amplitude shift.

    Parameters
    ----------
    length:
        Total number of time steps.
    break_index:
        Index at which the amplitude shift occurs. Defaults to ``length // 2``.
        Must satisfy ``seasonality_period <= break_index <= length - seasonality_period``.
    magnitude:
        Fractional change in seasonal amplitude at the break.
        ``magnitude=1.0`` doubles the amplitude (A → 2A).
        ``magnitude=-0.5`` halves it (A → 0.5A).
        Must be non-zero.
    seasonality_period:
        Period of the sine component (in time steps).
    seasonality_amplitude:
        Base amplitude of the seasonal component before the break.
    base_noise:
        Standard deviation of the Gaussian noise component.
        Keep low (default 0.5) so the amplitude shift dominates.
    seed:
        Random seed for the noise component (reproducibility).
    start:
        ISO-format start timestamp for the time index.
    freq:
        Pandas-compatible frequency string (e.g. ``"D"`` for daily).

    Returns
    -------
    (series, break_index)
        ``series`` — the synthetic univariate :class:`darts.TimeSeries`.
        ``break_index`` — the ground-truth break location (0-based integer index).
    """
    k = break_index if break_index is not None else length // 2
    _validate(length, k, magnitude, seasonality_period)

    trend, seasonal, noise = _base_components(
        length, start, freq, seasonality_period, seasonality_amplitude, base_noise, seed
    )

    # Inject amplitude shift: seasonal[t] *= (1 + magnitude) for t >= k
    step = _step(length, k)
    seasonal_shifted = seasonal * (1.0 + magnitude * step)

    values = trend + seasonal_shifted + noise
    index = pd.date_range(start=start, periods=length, freq=freq)
    series = TimeSeries.from_times_and_values(index, values.reshape(-1, 1))

    return series, k


def generate_control(
    length: int = 365,
    seasonality_period: int = 30,
    seasonality_amplitude: float = 5.0,
    base_noise: float = 0.5,
    seed: int = 99,                    # different from generate_seasonal_shift default
    start: str = "2020-01-01",
    freq: str = "D",
) -> TimeSeries:
    """Generate a univariate series with NO injected changepoint.

    Used for false-positive testing: PELT should return no breaks on this
    series at the working penalty value.

    The seed defaults to 99 (not 42) so the noise realization differs from
    the shift series — prevents accidental seed-correlation artefacts.
    """
    trend, seasonal, noise = _base_components(
        length, start, freq, seasonality_period, seasonality_amplitude, base_noise, seed
    )
    values = trend + seasonal + noise
    index = pd.date_range(start=start, periods=length, freq=freq)
    return TimeSeries.from_times_and_values(index, values.reshape(-1, 1))
