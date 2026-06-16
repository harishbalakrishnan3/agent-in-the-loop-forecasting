"""US1: per-flavor injection correctness — the realized series exhibits the change (T008)."""

import numpy as np
import pandas as pd

from ailf.pipelines.drift.datasets import DriftFlavor, GeneratorConfig, generate_case


def _values(case) -> np.ndarray:
    return case.series.values().ravel()


def _rolling_mean(v: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(v).rolling(window, min_periods=1).mean().to_numpy()


def _rolling_std(v: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(v).rolling(window, min_periods=2).std().to_numpy()


def test_mean_level_shifts_level_after_onset() -> None:
    cfg = GeneratorConfig(length=400, onset=200, transition_width=20, magnitude=30.0, seed=42)
    v = _values(generate_case(DriftFlavor.mean_level, seed=42, config=cfg))
    rm = _rolling_mean(v, 30)
    before = rm[150:190].mean()
    after = rm[300:390].mean()
    # Level rises by roughly the injected magnitude.
    assert after - before > 15.0


def test_trend_slope_bends_trajectory_after_onset() -> None:
    cfg = GeneratorConfig(
        length=400, onset=200, transition_width=20, magnitude=2.0, base_noise=0.1, seed=42
    )
    v = _values(generate_case(DriftFlavor.trend_slope, seed=42, config=cfg))
    # Compare average step (discrete slope) well before vs well after the transition.
    slope_before = np.diff(v[20:180]).mean()
    slope_after = np.diff(v[250:390]).mean()
    assert slope_after > slope_before + 1.0


def test_variance_inflation_grows_spread_after_onset() -> None:
    cfg = GeneratorConfig(
        length=400, onset=200, transition_width=20, magnitude=4.0, base_noise=1.0,
        seasonality_period=None, seed=42,
    )
    v = _values(generate_case(DriftFlavor.variance_inflation, seed=42, config=cfg))
    rstd = _rolling_std(v, 30)
    std_before = np.nanmean(rstd[150:190])
    std_after = np.nanmean(rstd[300:390])
    assert std_after > std_before * 2.0


def test_seasonal_amplitude_grows_swing_after_onset() -> None:
    cfg = GeneratorConfig(
        length=480, onset=240, transition_width=24, magnitude=3.0, base_noise=0.1,
        seasonality_period=24, seasonality_amplitude=5.0, seed=42,
    )
    v = _values(generate_case(DriftFlavor.seasonal_amplitude, seed=42, config=cfg))
    # Peak-to-trough swing per period grows after onset.
    swing_before = v[48:96].max() - v[48:96].min()
    swing_after = v[400:448].max() - v[400:448].min()
    assert swing_after > swing_before * 1.5
