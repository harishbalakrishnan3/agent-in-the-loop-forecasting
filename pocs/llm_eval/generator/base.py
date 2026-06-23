"""Base signal + pure injection primitives (composable building blocks).

Reuses the EXACT _base_signal formula + fixed-index injection idiom from
pocs/changepoint/export_scenario_csvs.py so generated cases behave like the committed fixtures.
Each injector mutates df['y'] in place and RETURNS the ground-truth records it contributed
(decoded form: {kind:'point',index} or {kind:'interval',start,end,interval_type}).

Out-of-vocabulary injectors (growing amplitude / multiplicative / nonlinear trend) carry NO
point/interval ground truth — their family is decided by the brute-force gate (expected = fallback
when no tool beats naive). The multiplicative/growing recipe mirrors
pocs/changepoint/seasonalityV2/datasets.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Split layout constants (mirror export_scenario_csvs.py): golden ABSOLUTE splits so the realized
# detector train_end == metadata train_end (Topic-1 #2). train_end = train_rows + val_rows.
SHORT_LEN, SHORT_TRAIN_END = 1000, 880
LONG_LEN, LONG_TRAIN_END = 1730, 1610
VALIDATION_HORIZON = 120
TEST_HORIZON = 120
SEASONAL_PERIOD = 365
START_DATE = "2019-01-01"

REPO_ROOT = Path(__file__).resolve().parents[3]
POC_DATA_DIR = REPO_ROOT / "pocs" / "llm_eval" / "data"
CSV_DIR = POC_DATA_DIR / "csv"
METADATA_PATH = POC_DATA_DIR / "scenario_metadata.json"


def base_signal(length: int, seed: int) -> pd.DataFrame:
    """Trend + annual + weekly seasonality + noise (identical formula to the committed fixtures)."""
    rng = np.random.default_rng(seed)
    t = np.arange(length)
    ds = pd.date_range(START_DATE, periods=length, freq="D")
    annual = 22.0 * np.sin(2 * np.pi * t / 365.0) + 7.0 * np.cos(2 * np.pi * t / 365.0)
    weekly = 2.5 * np.sin(2 * np.pi * t / 7.0)
    trend = 0.018 * t
    noise = rng.normal(0.0, 1.7, length)
    y = 100.0 + trend + annual + weekly + noise
    return pd.DataFrame({"ds": ds, "y": y})


# --- in-vocabulary injectors (carry decoded ground truth) ----------------------------------------

def inject_step(df: pd.DataFrame, cps: list[tuple[int, float]]) -> list[dict[str, Any]]:
    """Permanent level shift(s): y[idx:] += lift. GT = POINT per changepoint."""
    gt = []
    for idx, lift in cps:
        df.loc[df.index >= idx, "y"] += lift
        gt.append({"kind": "point", "index": int(idx)})
    return gt


def inject_ramp(df: pd.DataFrame, start: int, end: int, lift: float) -> list[dict[str, Any]]:
    """Gradual drift over [start, end): clipped ramp. GT = one drift INTERVAL [start, end)."""
    t = np.arange(len(df))
    ramp = np.clip((t - start) / (end - start), 0.0, 1.0)
    df["y"] += lift * ramp
    return [{"kind": "interval", "start": int(start), "end": int(end), "interval_type": "drift"}]


def inject_events(df: pd.DataFrame, blocks: list[tuple[int, int, float]]) -> list[dict[str, Any]]:
    """Temporary event blocks [start, end) += lift (return to baseline after). GT = event INTERVALs."""
    gt = []
    for start, end, lift in blocks:
        df.loc[(df.index >= start) & (df.index < end), "y"] += lift
        gt.append({"kind": "interval", "start": int(start), "end": int(end), "interval_type": "event"})
    return gt


def inject_recurring(df: pd.DataFrame, month: int, day_start: int, day_end: int, lift: float,
                     years: list[int]) -> list[dict[str, Any]]:
    """Recurring calendar event each year. Holiday family scores recall on KINKS not the recurring
    windows, so this contributes NO boundary GT (Topic-1)."""
    base = df["ds"].iloc[0]
    for year in years:
        start = int((pd.Timestamp(year=year, month=month, day=day_start) - base).days)
        end = int((pd.Timestamp(year=year, month=month, day=day_end) - base).days)
        if 0 <= start < len(df):
            df.loc[(df.index >= start) & (df.index < min(end, len(df))), "y"] += lift
    return []


def inject_kinks(df: pd.DataFrame, cps: list[tuple[int, float]]) -> list[dict[str, Any]]:
    """Trend slope changes: y[idx:] += slope_delta*(t-idx). GT = POINT per kink."""
    t = np.arange(len(df))
    gt = []
    for idx, slope_delta in cps:
        mask = df.index >= idx
        df.loc[mask, "y"] += slope_delta * (t[mask] - idx)
        gt.append({"kind": "point", "index": int(idx)})
    return gt


# --- out-of-vocabulary injectors (no GT; family resolved by the gate, expected fallback) ----------

def inject_growing_seasonal_amplitude(df: pd.DataFrame, growth_rate: float) -> list[dict[str, Any]]:
    """The NOTES.md sinusoid: annual seasonal amplitude GROWS linearly over time. No step/ramp/event/
    holiday tool expresses a time-varying amplitude."""
    t = np.arange(len(df))
    annual_unit = np.sin(2 * np.pi * t / 365.0)  # unit-amplitude annual shape
    df["y"] += growth_rate * t * annual_unit
    return []


def inject_multiplicative_seasonality(df: pd.DataFrame, strength: float) -> list[dict[str, Any]]:
    """Seasonal swing scales with the trended level (additive -> multiplicative). Mirrors
    seasonalityV2: amplitude proportional to the level."""
    t = np.arange(len(df))
    level = 100.0 + 0.05 * t  # rising level
    annual_unit = np.sin(2 * np.pi * t / 365.0)
    df["y"] += strength * level * annual_unit / 100.0
    return []


def inject_nonlinear_trend(df: pd.DataFrame, curvature: float) -> list[dict[str, Any]]:
    """Quadratic trend (no abrupt point, no clean ramp interval) — out of step/ramp vocabulary."""
    t = np.arange(len(df))
    df["y"] += curvature * (t / len(df)) ** 2 * len(df)
    return []
