"""Smoke tests for seasonalityV2 — dataset generation, splits, stats, config validation.

These tests cover steps 1–3 of the build order and have NO LLM or Prophet dependency.
They can be run in WRITE mode.

Run with:
    uv run pytest pocs/changepoint/seasonalityV2/test_dataset.py -v

No __init__.py — pytest prepend mode adds the directory to sys.path automatically.
"""

from __future__ import annotations

import json
import math
import sys
import os

# Ensure same-dir imports work regardless of invocation
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import pytest

from config import (
    CHANGEPOINT_PRIOR_SCALE_GRID,
    N_CHANGEPOINTS_GRID,
    SEASONALITY_MODE_GRID,
    TEST_FRAC,
    TRAIN_FRAC,
    VAL_FRAC,
    validate_config,
)
from datasets import generate_dataset, split_dataset
from stats import StatsBundle, extract_stats, stats_to_dict


# ---------------------------------------------------------------------------
# Dataset tests
# ---------------------------------------------------------------------------

def test_four_changepoint_types_present():
    """Dataset must contain exactly the 4 required structural changepoint types."""
    df, meta = generate_dataset(seed=42)
    assert set(meta["changepoints"].keys()) == {
        "A_level_shift",
        "B_trend_kink",
        "C_variance_change",
        "D_seasonality_mode",
    }, f"Unexpected changepoint keys: {set(meta['changepoints'].keys())}"


def test_changepoint_timestamps_are_within_series():
    """All changepoint timestamps must fall within the series date range."""
    df, meta = generate_dataset(seed=42)
    ds_min = pd.Timestamp(df["ds"].min())
    ds_max = pd.Timestamp(df["ds"].max())
    for key, ts in meta["changepoints"].items():
        assert ds_min <= pd.Timestamp(ts) <= ds_max, (
            f"Changepoint {key} ({ts}) outside series range [{ds_min}, {ds_max}]"
        )


def test_changepoints_in_ascending_order():
    """Changepoints must be in chronological order A < B < C < D."""
    df, meta = generate_dataset(seed=42)
    keys = ["A_level_shift", "B_trend_kink", "C_variance_change", "D_seasonality_mode"]
    timestamps = [pd.Timestamp(meta["changepoints"][k]) for k in keys]
    for i in range(len(timestamps) - 1):
        assert timestamps[i] < timestamps[i + 1], (
            f"{keys[i]} ({timestamps[i]}) is not before {keys[i+1]} ({timestamps[i+1]})"
        )


def test_dataset_length_and_columns():
    """Dataset must have 1 095 rows and columns ds, y."""
    df, meta = generate_dataset(seed=42)
    assert list(df.columns) == ["ds", "y"]
    assert len(df) == 1095, f"Expected 1095 rows, got {len(df)}"
    assert pd.api.types.is_datetime64_any_dtype(df["ds"])
    assert pd.api.types.is_float_dtype(df["y"])


def test_reproducibility():
    """Same seed must produce identical df and meta changepoints."""
    df1, meta1 = generate_dataset(seed=42)
    df2, meta2 = generate_dataset(seed=42)
    pd.testing.assert_frame_equal(df1, df2, check_names=True)
    assert meta1["changepoints"].keys() == meta2["changepoints"].keys()
    for k in meta1["changepoints"]:
        assert meta1["changepoints"][k] == meta2["changepoints"][k], (
            f"Changepoint {k} not reproducible"
        )


def test_different_seeds_produce_different_series():
    """Different seeds must produce different y values."""
    df1, _ = generate_dataset(seed=42)
    df2, _ = generate_dataset(seed=99)
    assert not (df1["y"].values == df2["y"].values).all()


# ---------------------------------------------------------------------------
# Split tests
# ---------------------------------------------------------------------------

def test_splits_non_overlapping_and_exhaustive():
    """train/val/test splits must be non-overlapping and together cover the full series."""
    df, meta = generate_dataset(seed=42)
    train_df, val_df, test_df = split_dataset(df, meta)

    assert train_df["ds"].max() < val_df["ds"].min(), "train and val overlap"
    assert val_df["ds"].max() < test_df["ds"].min(), "val and test overlap"
    assert len(train_df) + len(val_df) + len(test_df) == len(df), (
        "splits do not cover full series"
    )


def test_split_proportions_approximately_correct():
    """Splits must be within ±2 rows of the configured fractions."""
    df, meta = generate_dataset(seed=42)
    n = len(df)
    train_df, val_df, test_df = split_dataset(df, meta)

    expected_train = int(n * TRAIN_FRAC)
    expected_val   = int(n * VAL_FRAC)

    assert abs(len(train_df) - expected_train) <= 2, (
        f"Train size {len(train_df)} far from expected {expected_train}"
    )
    assert abs(len(val_df) - expected_val) <= 2, (
        f"Val size {len(val_df)} far from expected {expected_val}"
    )


# ---------------------------------------------------------------------------
# Stats tests
# ---------------------------------------------------------------------------

def test_stats_bundle_all_fields_present():
    """StatsBundle must have all required fields populated."""
    df, meta = generate_dataset(seed=42)
    train_df, _, _ = split_dataset(df, meta)
    bundle = extract_stats(train_df, list(meta["changepoints"].values()))

    assert isinstance(bundle, StatsBundle)
    assert bundle.n_obs_train > 0
    assert len(bundle.segments) >= 1
    assert bundle.seasonality_period_days > 0
    assert 0.0 <= bundle.seasonality_mode_signal <= 1.0
    assert bundle.noise_level >= 0.0
    assert bundle.post_last_cp_days > 0
    assert bundle.trend_direction in ("up", "down", "flat")
    assert bundle.last_cp_date != ""


def test_stats_bundle_json_serialisable():
    """stats_to_dict must return a valid JSON object with no NaN/Inf."""
    df, meta = generate_dataset(seed=42)
    train_df, _, _ = split_dataset(df, meta)
    bundle = extract_stats(train_df, list(meta["changepoints"].values()))
    d = stats_to_dict(bundle)

    serialised = json.dumps(d)
    assert "NaN" not in serialised, "NaN found in stats JSON"
    assert "Infinity" not in serialised, "Infinity found in stats JSON"

    # Round-trip: must be parseable back to the same dict
    reparsed = json.loads(serialised)
    assert isinstance(reparsed, dict)


def test_stats_changepoints_within_training():
    """StatsBundle must only report changepoints that fall within the training window."""
    df, meta = generate_dataset(seed=42)
    train_df, _, _ = split_dataset(df, meta)
    bundle = extract_stats(train_df, list(meta["changepoints"].values()))

    train_end = train_df["ds"].max()
    for cp in bundle.changepoints_detected:
        cp_ts = pd.Timestamp(cp["date"])
        assert cp_ts <= pd.Timestamp(train_end), (
            f"Changepoint {cp['date']} is outside training window (ends {train_end})"
        )


def test_stats_segment_stats_non_empty():
    """There must be at least as many segments as changepoints + 1."""
    df, meta = generate_dataset(seed=42)
    train_df, _, _ = split_dataset(df, meta)
    bundle = extract_stats(train_df, list(meta["changepoints"].values()))

    n_cps = len(bundle.changepoints_detected)
    assert len(bundle.segments) >= max(1, n_cps), (
        f"Expected ≥ {max(1, n_cps)} segments, got {len(bundle.segments)}"
    )


def test_stats_deterministic():
    """extract_stats must return the same bundle for the same inputs."""
    df, meta = generate_dataset(seed=42)
    train_df, _, _ = split_dataset(df, meta)
    cps = list(meta["changepoints"].values())

    b1 = stats_to_dict(extract_stats(train_df, cps))
    b2 = stats_to_dict(extract_stats(train_df, cps))
    assert b1 == b2, "extract_stats is not deterministic"


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------

def test_validate_config_accepts_valid_grid_values():
    """A fully valid config must not raise."""
    validate_config({
        "changepoint_prior_scale": 0.05,
        "seasonality_prior_scale": 10.0,
        "seasonality_mode":        "multiplicative",
        "changepoint_range":       0.9,
        "n_changepoints":          25,
    })  # must not raise


def test_validate_config_rejects_out_of_bounds_float():
    """An out-of-bounds changepoint_prior_scale must raise ValueError."""
    with pytest.raises(ValueError, match="out-of-bounds"):
        validate_config({"changepoint_prior_scale": 99.0})


def test_validate_config_rejects_unknown_parameter():
    """An unknown parameter key must raise ValueError."""
    with pytest.raises(ValueError):
        validate_config({"unknown_param": 1.0})


def test_validate_config_rejects_wrong_seasonality_mode():
    """seasonality_mode must be 'additive' or 'multiplicative'."""
    with pytest.raises(ValueError):
        validate_config({"seasonality_mode": "log"})
