"""Synthetic dataset generator for the seasonalityV2 POC.

Produces a daily 1 095-point series with exactly 4 injected structural changepoints,
one per type, designed to expose default Prophet's blind spots.

Changepoint types
-----------------
A — Level shift    : abrupt step in mean (~day 200)
B — Trend kink     : slope reversal after 80% of training (~day 420)
C — Variance change: noise std doubles (~day 630)
D — Seasonality mode shift: additive → multiplicative (~day 840)

Self-contained: no imports from src/ailf/. Mirrors ref_datasets_seasonal._base_components.

Usage
-----
    from datasets import generate_dataset, split_dataset

    df, meta = generate_dataset(seed=42)
    train_df, val_df, test_df = split_dataset(df, meta)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import (
    BASE_NOISE_STD,
    BASE_SEASONAL_AMPLITUDE,
    BASE_TREND_SLOPE,
    CP_A_IDX,
    CP_B_IDX,
    CP_C_IDX,
    CP_D_IDX,
    DATASET_LENGTH,
    SEASONALITY_PERIOD,
    TEST_FRAC,
    TRAIN_FRAC,
    VAL_FRAC,
)

# ---------------------------------------------------------------------------
# Private helpers (mirrors ref_datasets_seasonal pattern)
# ---------------------------------------------------------------------------

def _piecewise_trend(
    length: int,
    rng: np.random.Generator,
    cp_indices: list[int],
    slopes: list[float],
    start_value: float = 10.0,
) -> np.ndarray:
    """Build a piecewise-linear trend with slope changes at cp_indices."""
    t = np.zeros(length)
    t[0] = start_value
    slope_map = np.full(length, slopes[0])
    boundaries = cp_indices + [length]
    for i, (lo, hi) in enumerate(zip([0] + cp_indices, boundaries)):
        slope_map[lo:hi] = slopes[i]
    for i in range(1, length):
        t[i] = t[i - 1] + slope_map[i]
    return t


def _additive_seasonal(
    length: int,
    period: int,
    amplitude: float,
    start: str = "2020-01-01",
) -> np.ndarray:
    """Pure sine seasonal component (additive)."""
    t = np.arange(length)
    return amplitude * np.sin(2 * np.pi * t / period)


def _step(length: int, break_index: int) -> np.ndarray:
    """Heaviside step mask: 0 before break_index, 1 from break_index onward."""
    s = np.zeros(length)
    s[break_index:] = 1.0
    return s


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_dataset(
    seed: int = 42,
    length: int = DATASET_LENGTH,
    train_frac: float = TRAIN_FRAC,
    val_frac: float = VAL_FRAC,
    start: str = "2020-01-01",
) -> tuple[pd.DataFrame, dict]:
    """Generate the synthetic 4-changepoint dataset.

    Parameters
    ----------
    seed : int
        Global random seed for full reproducibility.
    length : int
        Total number of daily observations (default 1 095 ≈ 3 years).
    train_frac, val_frac : float
        Fraction of data for train and val. test_frac = 1 - train - val.
    start : str
        ISO start date for the time index.

    Returns
    -------
    df : pd.DataFrame
        Columns: ``ds`` (datetime64), ``y`` (float64). Full series.
    meta : dict
        Keys:
        - ``changepoints``: dict mapping type label → pd.Timestamp
        - ``cp_indices``: dict mapping type label → int index
        - ``train_end``: pd.Timestamp (exclusive boundary)
        - ``val_end``: pd.Timestamp (exclusive boundary)
        - ``seed``: int
        - ``length``: int
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range(start=start, periods=length, freq="D")

    # -----------------------------------------------------------------------
    # Changepoint indices (fixed, not random — reproducibility + dataset design)
    # -----------------------------------------------------------------------
    cp_a = CP_A_IDX   # 200  — level shift
    cp_b = CP_B_IDX   # 420  — trend kink (placed after 80% of train ≈ idx 383)
    cp_c = CP_C_IDX   # 630  — variance change
    cp_d = CP_D_IDX   # 840  — seasonality mode shift

    # -----------------------------------------------------------------------
    # Trend: piecewise linear, 5 segments
    # Slopes: up → up (same) → down → down (same) → up
    # The kink at cp_b (after Prophet's default 80% changepoint_range) is the
    # agent's opportunity with changepoint_range=0.95.
    # -----------------------------------------------------------------------
    slopes = [
        BASE_TREND_SLOPE,           # seg 0: 0–cp_a    (+0.02/day)
        BASE_TREND_SLOPE,           # seg 1: cp_a–cp_b  (flat, absorbed by level shift)
        -BASE_TREND_SLOPE * 0.5,    # seg 2: cp_b–cp_c  (-0.01/day, kink)
        -BASE_TREND_SLOPE * 0.5,    # seg 3: cp_c–cp_d  (same, variance change only)
        BASE_TREND_SLOPE * 1.5,     # seg 4: cp_d–end   (+0.03/day, rising for mult. season)
    ]
    trend = _piecewise_trend(length, rng, [cp_a, cp_b, cp_c, cp_d], slopes, start_value=10.0)

    # -----------------------------------------------------------------------
    # Seasonality: additive up to cp_d, multiplicative after
    # Type D blind spot: default Prophet seasonality_mode='additive' fails post cp_d
    # -----------------------------------------------------------------------
    seasonal_base = _additive_seasonal(length, SEASONALITY_PERIOD, BASE_SEASONAL_AMPLITUDE)

    # Post cp_d: amplitude scales with trend level (multiplicative)
    # This produces a 2× or more discrepancy vs. additive at high trend levels
    multiplicative_factor = trend / trend[cp_d]  # normalised to 1.0 at cp_d
    seasonal_mult = BASE_SEASONAL_AMPLITUDE * multiplicative_factor * np.sin(
        2 * np.pi * np.arange(length) / SEASONALITY_PERIOD
    )

    step_d = _step(length, cp_d)
    seasonal = seasonal_base * (1 - step_d) + seasonal_mult * step_d

    # -----------------------------------------------------------------------
    # Noise: homoscedastic up to cp_c, heteroscedastic after (std doubles)
    # Type C blind spot: Prophet assumes constant observation noise
    # -----------------------------------------------------------------------
    noise_std = np.where(np.arange(length) < cp_c, BASE_NOISE_STD, BASE_NOISE_STD * 2.0)
    noise = rng.standard_normal(length) * noise_std

    # -----------------------------------------------------------------------
    # Type A: permanent level shift at cp_a
    # -----------------------------------------------------------------------
    level_shift = 15.0 * _step(length, cp_a)

    # -----------------------------------------------------------------------
    # Compose
    # -----------------------------------------------------------------------
    y = trend + seasonal + level_shift + noise

    df = pd.DataFrame({"ds": index, "y": y})

    # -----------------------------------------------------------------------
    # Split boundaries
    # -----------------------------------------------------------------------
    train_end_idx = int(length * train_frac)
    val_end_idx   = int(length * (train_frac + val_frac))

    train_end = index[train_end_idx]
    val_end   = index[val_end_idx]

    meta: dict = {
        "changepoints": {
            "A_level_shift":      index[cp_a],
            "B_trend_kink":       index[cp_b],
            "C_variance_change":  index[cp_c],
            "D_seasonality_mode": index[cp_d],
        },
        "cp_indices": {
            "A_level_shift":      cp_a,
            "B_trend_kink":       cp_b,
            "C_variance_change":  cp_c,
            "D_seasonality_mode": cp_d,
        },
        "train_end":      train_end,
        "val_end":        val_end,
        "train_end_idx":  train_end_idx,
        "val_end_idx":    val_end_idx,
        "seed":           seed,
        "length":         length,
    }

    return df, meta


def split_dataset(
    df: pd.DataFrame,
    meta: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split df into train / val / test using boundaries from meta.

    Returns
    -------
    train_df, val_df, test_df : pd.DataFrame
        Each has columns ``ds`` and ``y``, index reset.
        No overlap; together they cover the full series.
    """
    ti = meta["train_end_idx"]
    vi = meta["val_end_idx"]

    train_df = df.iloc[:ti].reset_index(drop=True)
    val_df   = df.iloc[ti:vi].reset_index(drop=True)
    test_df  = df.iloc[vi:].reset_index(drop=True)

    return train_df, val_df, test_df
