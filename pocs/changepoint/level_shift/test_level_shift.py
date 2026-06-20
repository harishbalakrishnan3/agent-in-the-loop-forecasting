"""Unit tests for level shift dataset generation and detection.

Written BEFORE implementation (test-first). These should all FAIL initially,
then pass once datasets.py and detector.py are implemented.
"""

import numpy as np
import pandas as pd
import pytest

from pocs.changepoint.level_shift.datasets import generate_level_shift_series
from pocs.changepoint.level_shift.detector import detect_level_shift, LevelShiftResult


# ═══════════════════════════════════════════════════════════════════════════════
# DATASET GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestDatasetGenerator:
    """Tests for generate_level_shift_series()."""

    def test_output_type_and_shape(self):
        """Generator returns a Darts TimeSeries + metadata dict with correct length."""
        from darts import TimeSeries

        ts, meta = generate_level_shift_series(length=300, seed=42)
        assert isinstance(ts, TimeSeries)
        assert len(ts) == 300
        assert isinstance(meta, dict)

    def test_metadata_has_required_fields(self):
        """Metadata contains all required ground truth fields."""
        _, meta = generate_level_shift_series(
            length=400,
            changepoint_indices=[200],
            magnitudes=[40.0],
            seed=42,
        )
        required_keys = [
            "dataset_id",
            "length",
            "changepoint_indices",
            "changepoint_dates",
            "magnitudes",
            "type",
            "noise_std",
            "base_level",
            "seed",
        ]
        for key in required_keys:
            assert key in meta, f"Missing key: {key}"

    def test_reproducibility(self):
        """Same seed produces identical output."""
        ts1, meta1 = generate_level_shift_series(length=200, seed=123)
        ts2, meta2 = generate_level_shift_series(length=200, seed=123)
        np.testing.assert_array_equal(ts1.values(), ts2.values())
        assert meta1 == meta2

    def test_different_seeds_produce_different_output(self):
        """Different seeds produce different series."""
        ts1, _ = generate_level_shift_series(length=200, seed=1)
        ts2, _ = generate_level_shift_series(length=200, seed=2)
        assert not np.array_equal(ts1.values(), ts2.values())

    def test_level_shift_present_single(self):
        """Mean after changepoint ≈ base_level + magnitude (within noise tolerance)."""
        ts, meta = generate_level_shift_series(
            length=500,
            base_level=100.0,
            noise_std=5.0,
            changepoint_indices=[250],
            magnitudes=[40.0],
            seed=42,
        )
        values = ts.values().flatten()
        mean_before = values[:250].mean()
        mean_after = values[250:].mean()

        assert abs(mean_before - 100.0) < 3.0  # within noise
        assert abs(mean_after - 140.0) < 3.0  # base + magnitude

    def test_level_shift_present_multiple(self):
        """Multiple changepoints produce distinct levels."""
        ts, meta = generate_level_shift_series(
            length=600,
            base_level=100.0,
            noise_std=3.0,
            changepoint_indices=[150, 350, 500],
            magnitudes=[30.0, -20.0, 25.0],
            seed=42,
        )
        values = ts.values().flatten()

        # Expected levels: 100, 130, 110, 135
        assert abs(values[:150].mean() - 100.0) < 3.0
        assert abs(values[150:350].mean() - 130.0) < 3.0
        assert abs(values[350:500].mean() - 110.0) < 3.0
        assert abs(values[500:].mean() - 135.0) < 3.0

    def test_no_changepoint_control(self):
        """Control dataset with no changepoints has roughly constant mean."""
        ts, meta = generate_level_shift_series(
            length=400,
            base_level=100.0,
            noise_std=5.0,
            changepoint_indices=[],
            magnitudes=[],
            seed=42,
        )
        values = ts.values().flatten()
        # Mean of first half ≈ mean of second half
        assert abs(values[:200].mean() - values[200:].mean()) < 3.0
        assert meta["changepoint_indices"] == []

    def test_with_seasonality(self):
        """Seasonal pattern is present but level shift is still visible."""
        ts, meta = generate_level_shift_series(
            length=500,
            base_level=100.0,
            noise_std=3.0,
            changepoint_indices=[250],
            magnitudes=[50.0],
            seasonality_period=7,
            seasonality_amplitude=10.0,
            seed=42,
        )
        values = ts.values().flatten()
        # Level shift should still be detectable in the means
        mean_before = values[:250].mean()
        mean_after = values[250:].mean()
        assert (mean_after - mean_before) > 40.0  # shift dominates seasonality

    def test_with_trend(self):
        """Underlying linear trend + level shift coexist."""
        ts, meta = generate_level_shift_series(
            length=400,
            base_level=100.0,
            base_slope=0.1,
            noise_std=3.0,
            changepoint_indices=[200],
            magnitudes=[30.0],
            seed=42,
        )
        values = ts.values().flatten()
        # After removing trend, the shift should be visible
        # Simple check: jump at changepoint is much larger than trend step
        diff_at_cp = values[201] - values[199]  # should be ~30 (shift) + 0.2 (trend)
        avg_diff = np.diff(values[:190]).mean()  # should be ~0.1 (just trend)
        assert diff_at_cp > 10 * avg_diff

    def test_metadata_dates_match_indices(self):
        """changepoint_dates correspond correctly to changepoint_indices."""
        ts, meta = generate_level_shift_series(
            length=365,
            start_date="2023-01-01",
            freq="D",
            changepoint_indices=[100],
            magnitudes=[20.0],
            seed=42,
        )
        expected_date = pd.Timestamp("2023-01-01") + pd.Timedelta(days=100)
        assert pd.Timestamp(meta["changepoint_dates"][0]) == expected_date


# ═══════════════════════════════════════════════════════════════════════════════
# DETECTION TOOL TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestLevelShiftDetector:
    """Tests for detect_level_shift()."""

    TOLERANCE = 5  # detected index must be within ±5 of ground truth

    def _generate_and_detect(self, **kwargs):
        """Helper: generate dataset and run detector."""
        ts, meta = generate_level_shift_series(**kwargs)
        result = detect_level_shift(ts)
        return result, meta

    def test_output_schema(self):
        """Result has all required fields in LevelShiftResult."""
        result, _ = self._generate_and_detect(
            length=400, changepoint_indices=[200], magnitudes=[40.0], seed=42
        )
        assert isinstance(result, LevelShiftResult)
        assert hasattr(result, "changepoint_indices")
        assert hasattr(result, "changepoint_dates")
        assert hasattr(result, "magnitudes")
        assert hasattr(result, "n_changepoints")
        assert hasattr(result, "method")
        assert hasattr(result, "penalty")

    def test_finds_single_large_shift(self):
        """Detects a large, obvious level shift within ±5 indices."""
        result, meta = self._generate_and_detect(
            length=500,
            changepoint_indices=[250],
            magnitudes=[40.0],
            noise_std=5.0,
            seed=42,
        )
        assert result.n_changepoints >= 1
        # At least one detected changepoint should be near the true one
        true_idx = 250
        detected = result.changepoint_indices
        assert any(abs(d - true_idx) <= self.TOLERANCE for d in detected), (
            f"No detection near index {true_idx}. Detected: {detected}"
        )

    def test_finds_multiple_shifts(self):
        """Finds all 3 planted changepoints (within tolerance)."""
        result, meta = self._generate_and_detect(
            length=600,
            changepoint_indices=[150, 350, 500],
            magnitudes=[30.0, -20.0, 25.0],
            noise_std=3.0,
            seed=42,
        )
        true_indices = [150, 350, 500]
        for true_idx in true_indices:
            assert any(
                abs(d - true_idx) <= self.TOLERANCE for d in result.changepoint_indices
            ), f"Missed changepoint at index {true_idx}. Detected: {result.changepoint_indices}"

    def test_no_false_positives_on_clean_data(self):
        """Returns 0 changepoints on clean data (no level shifts)."""
        result, _ = self._generate_and_detect(
            length=400,
            changepoint_indices=[],
            magnitudes=[],
            noise_std=5.0,
            seed=42,
        )
        assert result.n_changepoints == 0, (
            f"False positives: detected {result.n_changepoints} changepoints on clean data"
        )

    def test_detects_subtle_shift(self):
        """Finds a subtle level shift (low signal-to-noise ratio)."""
        result, meta = self._generate_and_detect(
            length=500,
            changepoint_indices=[250],
            magnitudes=[10.0],
            noise_std=8.0,
            seed=42,
        )
        true_idx = 250
        # Allow wider tolerance for subtle shifts
        wider_tolerance = 10
        assert result.n_changepoints >= 1
        assert any(
            abs(d - true_idx) <= wider_tolerance for d in result.changepoint_indices
        ), f"Missed subtle shift at {true_idx}. Detected: {result.changepoint_indices}"

    def test_handles_noisy_data(self):
        """Finds changepoint in high-noise data."""
        result, meta = self._generate_and_detect(
            length=500,
            changepoint_indices=[250],
            magnitudes=[30.0],
            noise_std=15.0,
            seed=42,
        )
        true_idx = 250
        assert result.n_changepoints >= 1
        assert any(
            abs(d - true_idx) <= self.TOLERANCE * 2 for d in result.changepoint_indices
        ), f"Missed changepoint in noisy data. Detected: {result.changepoint_indices}"

    def test_works_with_trend(self):
        """Detects level shift even with underlying linear trend."""
        ts, meta = generate_level_shift_series(
            length=400,
            base_level=100.0,
            base_slope=0.1,
            noise_std=3.0,
            changepoint_indices=[200],
            magnitudes=[30.0],
            seed=42,
        )
        result = detect_level_shift(ts)
        true_idx = 200
        assert result.n_changepoints >= 1
        assert any(
            abs(d - true_idx) <= self.TOLERANCE for d in result.changepoint_indices
        ), f"Missed level shift with trend. Detected: {result.changepoint_indices}"

    def test_works_with_seasonality(self):
        """Detects level shift even with seasonal pattern."""
        ts, meta = generate_level_shift_series(
            length=500,
            base_level=100.0,
            noise_std=3.0,
            changepoint_indices=[250],
            magnitudes=[50.0],
            seasonality_period=7,
            seasonality_amplitude=10.0,
            seed=42,
        )
        result = detect_level_shift(ts)
        true_idx = 250
        assert result.n_changepoints >= 1
        assert any(
            abs(d - true_idx) <= self.TOLERANCE for d in result.changepoint_indices
        ), f"Missed level shift with seasonality. Detected: {result.changepoint_indices}"

    def test_correct_magnitude(self):
        """Reported magnitude is within ±20% of true magnitude."""
        result, meta = self._generate_and_detect(
            length=500,
            changepoint_indices=[250],
            magnitudes=[40.0],
            noise_std=5.0,
            seed=42,
        )
        true_magnitude = 40.0
        # Find the detection closest to the true changepoint
        true_idx = 250
        closest_idx = min(
            range(len(result.changepoint_indices)),
            key=lambda i: abs(result.changepoint_indices[i] - true_idx),
        )
        detected_magnitude = abs(result.magnitudes[closest_idx])
        assert abs(detected_magnitude - true_magnitude) / true_magnitude < 0.20, (
            f"Magnitude {detected_magnitude} not within 20% of {true_magnitude}"
        )

    def test_reproducibility(self):
        """Same input produces same detection output."""
        ts, _ = generate_level_shift_series(
            length=400, changepoint_indices=[200], magnitudes=[40.0], seed=42
        )
        result1 = detect_level_shift(ts)
        result2 = detect_level_shift(ts)
        assert result1.changepoint_indices == result2.changepoint_indices
        assert result1.magnitudes == result2.magnitudes
