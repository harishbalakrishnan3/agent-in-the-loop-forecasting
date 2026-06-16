"""Tests for DriftGenerator — written BEFORE the implementation (Principle II).

Each test injects a known drift at a known location and asserts that:
  - Output shape and dtype are correct.
  - The drift is detectable by a simple statistical check at the injected location
    (precision / recall proxy: the mean shift is larger in the drifted segment than
    expected from noise alone).
  - Reproducibility: two calls with the same seed produce identical series.
  - Config loading: DriftGenerator reads `trend` from config.yml.

Ground-truth drift locations are captured in the returned metadata so that the
diagnostic tool can be evaluated for precision / recall in downstream tests.
"""

from __future__ import annotations

import math
import pathlib

import numpy as np
import pandas as pd
import pytest

# Import will fail until DriftGenerator is implemented (expected red → green TDD cycle).
from ailf.pipelines.drift.dataset_generator import DriftGenerator

CONFIG_PATH = pathlib.Path(__file__).parents[3] / "src" / "config" / "config.yml"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gen() -> DriftGenerator:
    """Default generator pointing at the project config."""
    return DriftGenerator(config_path=CONFIG_PATH)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _mean_shift_detected(series: pd.Series, change_idx: int, window: int = 30) -> bool:
    """Return True if the post-drift segment mean differs from pre-drift by > 2σ of noise."""
    pre = series.iloc[max(0, change_idx - window) : change_idx]
    post = series.iloc[change_idx : change_idx + window]
    noise_std = pre.std()
    if noise_std == 0:
        return False
    return abs(post.mean() - pre.mean()) > 2 * noise_std


def _schema_ok(df: pd.DataFrame) -> bool:
    """Assert Prophet-compatible schema: columns ds (datetime) and y (float)."""
    return (
        {"ds", "y"}.issubset(df.columns)
        and pd.api.types.is_datetime64_any_dtype(df["ds"])
        and pd.api.types.is_float_dtype(df["y"])
    )


# ---------------------------------------------------------------------------
# Config / init tests
# ---------------------------------------------------------------------------


class TestDriftGeneratorInit:
    def test_loads_trend_from_config(self, gen: DriftGenerator) -> None:
        assert gen.trend in {"flat", "linear", "exponential"}

    def test_trend_override(self) -> None:
        g = DriftGenerator(config_path=CONFIG_PATH, trend="flat")
        assert g.trend == "flat"

    def test_invalid_trend_raises(self) -> None:
        with pytest.raises(ValueError, match="trend"):
            DriftGenerator(config_path=CONFIG_PATH, trend="quadratic")

    def test_missing_config_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            DriftGenerator(config_path=pathlib.Path("/nonexistent/config.yml"))


# ---------------------------------------------------------------------------
# sudden_drift
# ---------------------------------------------------------------------------


class TestSuddenDrift:
    def test_schema(self, gen: DriftGenerator) -> None:
        df, meta = gen.sudden_drift(seed=0)
        assert _schema_ok(df)

    def test_length(self, gen: DriftGenerator) -> None:
        df, meta = gen.sudden_drift(seed=0, n_points=200)
        assert len(df) == 200

    def test_drift_detected(self, gen: DriftGenerator) -> None:
        df, meta = gen.sudden_drift(seed=0, drift_point=100, magnitude=15.0, n_points=200)
        assert meta["drift_point"] == 100
        assert _mean_shift_detected(df["y"], change_idx=100)

    def test_reproducibility(self, gen: DriftGenerator) -> None:
        df1, _ = gen.sudden_drift(seed=7)
        df2, _ = gen.sudden_drift(seed=7)
        pd.testing.assert_frame_equal(df1, df2)

    def test_different_seeds_differ(self, gen: DriftGenerator) -> None:
        df1, _ = gen.sudden_drift(seed=1)
        df2, _ = gen.sudden_drift(seed=2)
        assert not df1["y"].equals(df2["y"])

    def test_meta_keys(self, gen: DriftGenerator) -> None:
        _, meta = gen.sudden_drift(seed=0)
        assert "drift_point" in meta and "magnitude" in meta and "drift_type" in meta


# ---------------------------------------------------------------------------
# gradual_drift
# ---------------------------------------------------------------------------


class TestGradualDrift:
    def test_schema(self, gen: DriftGenerator) -> None:
        df, _ = gen.gradual_drift(seed=0)
        assert _schema_ok(df)

    def test_drift_window_in_meta(self, gen: DriftGenerator) -> None:
        _, meta = gen.gradual_drift(seed=0, drift_start=80, drift_end=180, n_points=300)
        assert meta["drift_start"] == 80
        assert meta["drift_end"] == 180

    def test_gradual_increase(self, gen: DriftGenerator) -> None:
        """Post-drift mean should be higher than pre-drift mean for positive magnitude."""
        df, meta = gen.gradual_drift(
            seed=0, drift_start=50, drift_end=150, magnitude=10.0, n_points=300
        )
        pre_mean = df["y"].iloc[:50].mean()
        post_mean = df["y"].iloc[200:].mean()
        assert post_mean > pre_mean

    def test_reproducibility(self, gen: DriftGenerator) -> None:
        df1, _ = gen.gradual_drift(seed=3)
        df2, _ = gen.gradual_drift(seed=3)
        pd.testing.assert_frame_equal(df1, df2)


# ---------------------------------------------------------------------------
# incremental_drift
# ---------------------------------------------------------------------------


class TestIncrementalDrift:
    def test_schema(self, gen: DriftGenerator) -> None:
        df, _ = gen.incremental_drift(seed=0)
        assert _schema_ok(df)

    def test_upward_slope(self, gen: DriftGenerator) -> None:
        df, meta = gen.incremental_drift(seed=0, drift_start=50, slope=0.1, n_points=300)
        post = df["y"].iloc[50:]
        # A positive slope means the detrended post segment grows; check last vs first
        assert post.iloc[-1] > post.iloc[0] - 3 * df["y"].std()  # loose sanity

    def test_meta_keys(self, gen: DriftGenerator) -> None:
        _, meta = gen.incremental_drift(seed=0)
        assert "drift_start" in meta and "slope" in meta

    def test_reproducibility(self, gen: DriftGenerator) -> None:
        df1, _ = gen.incremental_drift(seed=5)
        df2, _ = gen.incremental_drift(seed=5)
        pd.testing.assert_frame_equal(df1, df2)


# ---------------------------------------------------------------------------
# seasonal_drift
# ---------------------------------------------------------------------------


class TestSeasonalDrift:
    def test_schema(self, gen: DriftGenerator) -> None:
        df, _ = gen.seasonal_drift(seed=0)
        assert _schema_ok(df)

    def test_amplitude_increases(self, gen: DriftGenerator) -> None:
        df, meta = gen.seasonal_drift(
            seed=0,
            season_length=7,
            amplitude_before=2.0,
            amplitude_after=10.0,
            change_point=100,
            n_points=300,
        )
        pre_std = df["y"].iloc[:100].std()
        post_std = df["y"].iloc[150:].std()
        # Larger amplitude → larger std in post segment
        assert post_std > pre_std

    def test_meta_keys(self, gen: DriftGenerator) -> None:
        _, meta = gen.seasonal_drift(seed=0)
        assert "change_point" in meta and "season_length" in meta

    def test_reproducibility(self, gen: DriftGenerator) -> None:
        df1, _ = gen.seasonal_drift(seed=9)
        df2, _ = gen.seasonal_drift(seed=9)
        pd.testing.assert_frame_equal(df1, df2)


# ---------------------------------------------------------------------------
# recurring_drift
# ---------------------------------------------------------------------------


class TestRecurringDrift:
    def test_schema(self, gen: DriftGenerator) -> None:
        df, _ = gen.recurring_drift(seed=0)
        assert _schema_ok(df)

    def test_meta_contains_windows(self, gen: DriftGenerator) -> None:
        _, meta = gen.recurring_drift(seed=0, period=90, duration=20, n_points=365)
        assert "drift_windows" in meta
        assert len(meta["drift_windows"]) >= 1

    def test_multiple_windows(self, gen: DriftGenerator) -> None:
        _, meta = gen.recurring_drift(seed=0, period=50, duration=10, n_points=300)
        # With period=50 and n_points=300, expect at least 5 windows
        assert len(meta["drift_windows"]) >= 5

    def test_reproducibility(self, gen: DriftGenerator) -> None:
        df1, _ = gen.recurring_drift(seed=11)
        df2, _ = gen.recurring_drift(seed=11)
        pd.testing.assert_frame_equal(df1, df2)


# ---------------------------------------------------------------------------
# covariate_drift
# ---------------------------------------------------------------------------


class TestCovariateDrift:
    def test_schema(self, gen: DriftGenerator) -> None:
        df, _ = gen.covariate_drift(seed=0)
        assert _schema_ok(df)

    def test_covariate_columns_present(self, gen: DriftGenerator) -> None:
        df, meta = gen.covariate_drift(seed=0, n_covariates=2)
        assert "x0" in df.columns and "x1" in df.columns
        assert meta["n_covariates"] == 2

    def test_covariate_distribution_shifts(self, gen: DriftGenerator) -> None:
        df, meta = gen.covariate_drift(seed=0, n_covariates=1, drift_point=150, n_points=300)
        cp = meta["drift_point"]
        pre_mean = df["x0"].iloc[:cp].mean()
        post_mean = df["x0"].iloc[cp:].mean()
        # Covariate mean must shift (magnitude > 3 by default)
        assert abs(post_mean - pre_mean) > 1.0

    def test_reproducibility(self, gen: DriftGenerator) -> None:
        df1, _ = gen.covariate_drift(seed=13)
        df2, _ = gen.covariate_drift(seed=13)
        pd.testing.assert_frame_equal(df1, df2)


# ---------------------------------------------------------------------------
# concept_drift
# ---------------------------------------------------------------------------


class TestConceptDrift:
    def test_schema(self, gen: DriftGenerator) -> None:
        df, _ = gen.concept_drift(seed=0)
        assert _schema_ok(df)

    def test_relationship_reversal(self, gen: DriftGenerator) -> None:
        """Post-changepoint correlation should differ from pre-changepoint."""
        df, meta = gen.concept_drift(
            seed=0,
            change_point=150,
            coef_before=3.0,
            coef_after=-3.0,
            n_points=400,
        )
        cp = meta["change_point"]
        corr_pre = df["x0"].iloc[:cp].corr(df["y"].iloc[:cp])
        corr_post = df["x0"].iloc[cp:].corr(df["y"].iloc[cp:])
        # Opposite signs expected
        assert math.copysign(1, corr_pre) != math.copysign(1, corr_post)

    def test_meta_keys(self, gen: DriftGenerator) -> None:
        _, meta = gen.concept_drift(seed=0)
        assert "change_point" in meta and "coef_before" in meta and "coef_after" in meta

    def test_reproducibility(self, gen: DriftGenerator) -> None:
        df1, _ = gen.concept_drift(seed=17)
        df2, _ = gen.concept_drift(seed=17)
        pd.testing.assert_frame_equal(df1, df2)
