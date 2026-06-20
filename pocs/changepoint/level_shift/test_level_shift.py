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


# ═══════════════════════════════════════════════════════════════════════════════
# COMPLEX DATASET TESTS (D11–D15)
# ═══════════════════════════════════════════════════════════════════════════════


class TestComplexDatasets:
    """Tests for D11–D15 complex datasets and their detection behavior."""

    TOLERANCE = 5

    def test_d11_seasonality_stops_at_shift(self):
        """D11: seasonality is present before shift, absent after."""
        ts, meta = generate_level_shift_series(
            length=500,
            changepoint_indices=[250],
            magnitudes=[30.0],
            noise_std=3.0,
            seasonality_period=7,
            seasonality_amplitude=10.0,
            seasonality_end_index=250,
            seed=60,
        )
        values = ts.values().flatten()
        # Before shift: should have seasonal variation
        before_std = np.std(values[50:250] - np.mean(values[50:250]))
        # After shift: only noise remains (no seasonality)
        after_values = values[260:490]
        after_std = np.std(after_values - np.mean(after_values))
        # Before should have higher variability due to seasonality
        assert before_std > after_std, (
            f"Expected more variability before shift (has seasonality). "
            f"Before std={before_std:.2f}, After std={after_std:.2f}"
        )
        assert meta["seasonality_end_index"] == 250

    def test_d11_detection_finds_shift(self):
        """D11: detector still finds the level shift despite seasonality change."""
        ts, meta = generate_level_shift_series(
            length=500,
            changepoint_indices=[250],
            magnitudes=[30.0],
            noise_std=3.0,
            seasonality_period=7,
            seasonality_amplitude=10.0,
            seasonality_end_index=250,
            seed=60,
        )
        result = detect_level_shift(ts)
        assert result.n_changepoints >= 1
        assert any(
            abs(d - 250) <= self.TOLERANCE for d in result.changepoint_indices
        ), f"Missed shift in D11. Detected: {result.changepoint_indices}"

    def test_d12_spike_is_temporary(self):
        """D12: spike reverts — values return to baseline after spike_duration."""
        ts, meta = generate_level_shift_series(
            length=500,
            changepoint_indices=[],
            magnitudes=[],
            spike_indices=[200],
            spike_magnitudes=[50.0],
            spike_duration=20,
            noise_std=5.0,
            seed=61,
        )
        values = ts.values().flatten()
        # During spike: mean should be elevated
        spike_mean = np.mean(values[200:220])
        # Before and after spike: mean should be similar (baseline)
        before_mean = np.mean(values[100:200])
        after_mean = np.mean(values[220:400])
        assert spike_mean > before_mean + 30, (
            f"Spike not elevated enough. Spike mean={spike_mean:.1f}, Before={before_mean:.1f}"
        )
        assert abs(after_mean - before_mean) < 10, (
            f"Spike didn't revert. Before={before_mean:.1f}, After={after_mean:.1f}"
        )
        assert meta["spike_indices"] == [200]
        assert meta["spike_duration"] == 20

    def test_d12_detection_sees_two_shifts(self):
        """D12: PELT detects spike start and end as two changepoints."""
        ts, _ = generate_level_shift_series(
            length=500,
            changepoint_indices=[],
            magnitudes=[],
            spike_indices=[200],
            spike_magnitudes=[50.0],
            spike_duration=20,
            noise_std=5.0,
            seed=61,
        )
        result = detect_level_shift(ts)
        # PELT should see at least 2 changepoints (spike up + spike down)
        assert result.n_changepoints >= 2, (
            f"Expected ≥2 changepoints for spike. Got {result.n_changepoints}"
        )

    def test_d13_shift_with_strong_trend(self):
        """D13: level shift is detectable despite underlying trend."""
        ts, meta = generate_level_shift_series(
            length=500,
            base_slope=0.15,
            changepoint_indices=[250],
            magnitudes=[20.0],
            noise_std=5.0,
            seed=62,
        )
        result = detect_level_shift(ts)
        # Should detect at least the level shift
        assert result.n_changepoints >= 1, (
            f"Missed shift in trending data. Got {result.n_changepoints} changepoints"
        )

    def test_d14_finds_large_shifts(self):
        """D14: detector finds the large-magnitude shifts among mixed."""
        ts, meta = generate_level_shift_series(
            length=600,
            changepoint_indices=[100, 250, 400, 500],
            magnitudes=[40.0, 5.0, -30.0, 8.0],
            noise_std=4.0,
            seed=63,
        )
        result = detect_level_shift(ts)
        # Should at least find the two large shifts (±40, ±30)
        large_shifts_found = sum(
            1 for d in result.changepoint_indices
            if any(abs(d - true) <= self.TOLERANCE for true in [100, 400])
        )
        assert large_shifts_found >= 2, (
            f"Expected to find at least 2 large shifts (at 100, 400). "
            f"Detected: {result.changepoint_indices}"
        )

    def test_d14_subtle_shifts_harder(self):
        """D14: subtle shifts (mag=5, 8) may be missed — documenting behavior."""
        ts, _ = generate_level_shift_series(
            length=600,
            changepoint_indices=[100, 250, 400, 500],
            magnitudes=[40.0, 5.0, -30.0, 8.0],
            noise_std=4.0,
            seed=63,
        )
        result = detect_level_shift(ts)
        # Document: subtle shifts at 250 (mag=5) and 500 (mag=8) are harder
        # This test just verifies the detector runs and returns valid output
        assert result.n_changepoints >= 2  # at minimum finds the large ones
        assert all(0 <= idx < 600 for idx in result.changepoint_indices)

    def test_d15_noise_regime_change(self):
        """D15: noise variance changes at the changepoint."""
        ts, meta = generate_level_shift_series(
            length=500,
            changepoint_indices=[250],
            magnitudes=[25.0],
            noise_std=3.0,
            noise_std_after=15.0,
            seed=64,
        )
        values = ts.values().flatten()
        # Variance after shift should be much higher
        before_std = np.std(values[50:250])
        after_std = np.std(values[260:490])
        assert after_std > before_std * 2, (
            f"Expected higher variance after shift. "
            f"Before std={before_std:.2f}, After std={after_std:.2f}"
        )
        assert meta["noise_std_after"] == 15.0

    def test_d15_detection_finds_shift(self):
        """D15: detector finds the mean shift despite noise regime change."""
        ts, _ = generate_level_shift_series(
            length=500,
            changepoint_indices=[250],
            magnitudes=[25.0],
            noise_std=3.0,
            noise_std_after=15.0,
            seed=64,
        )
        result = detect_level_shift(ts)
        assert result.n_changepoints >= 1
        assert any(
            abs(d - 250) <= self.TOLERANCE * 2 for d in result.changepoint_indices
        ), f"Missed shift in D15. Detected: {result.changepoint_indices}"

    def test_all_complex_datasets_generate(self):
        """All D11–D15 configs generate without errors."""
        from pocs.changepoint.level_shift.datasets import DATASET_CONFIGS

        complex_datasets = {
            k: v for k, v in DATASET_CONFIGS.items() if k.startswith("D1") and len(k) > 10
        }
        # Filter to just D11-D15
        complex_datasets = {
            k: v for k, v in DATASET_CONFIGS.items()
            if k.startswith(("D11", "D12", "D13", "D14", "D15"))
        }
        assert len(complex_datasets) == 5, f"Expected 5 complex datasets, got {len(complex_datasets)}"
        for name, config in complex_datasets.items():
            ts, meta = generate_level_shift_series(**config)
            assert len(ts) == config["length"], f"{name} wrong length"
            assert meta["dataset_id"] == config["dataset_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# INTERVENTION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestInterventions:
    """Tests for intervention strategy functions and selection logic."""

    def _make_detection_result(self, n_cp=1, indices=None, dates=None, magnitudes=None):
        """Helper: build a LevelShiftResult for testing."""
        if indices is None:
            indices = [250]
        if dates is None:
            dates = ["2023-09-08"]
        if magnitudes is None:
            magnitudes = [40.0]
        return LevelShiftResult(
            changepoint_indices=indices,
            changepoint_dates=dates,
            magnitudes=magnitudes,
            n_changepoints=n_cp,
            method="pelt_l2",
            penalty="bic",
        )

    def _make_prophet_df(self, length=400):
        """Helper: build a simple Prophet DataFrame."""
        dates = pd.date_range("2023-01-01", periods=length, freq="D")
        values = np.random.default_rng(42).normal(100, 5, length)
        return pd.DataFrame({"ds": dates, "y": values})

    def test_no_intervention_returns_default_prophet(self):
        """no_intervention returns unmodified Prophet and data."""
        from prophet import Prophet
        from pocs.changepoint.level_shift.interventions import no_intervention

        result = self._make_detection_result(n_cp=0, indices=[], dates=[], magnitudes=[])
        df = self._make_prophet_df()
        ir = no_intervention(result, df)
        assert ir.strategy_name == "no_intervention"
        assert isinstance(ir.model, Prophet)
        assert len(ir.training_data) == len(df)

    def test_inject_changepoints_sets_changepoints(self):
        """inject_changepoints passes detected dates to Prophet."""
        from pocs.changepoint.level_shift.interventions import inject_changepoints

        result = self._make_detection_result(
            n_cp=1, indices=[250], dates=["2023-09-08"], magnitudes=[40.0]
        )
        df = self._make_prophet_df()
        ir = inject_changepoints(result, df)
        assert ir.strategy_name == "inject_changepoints"
        assert ir.model.changepoints is not None
        assert len(ir.model.changepoints) == 1

    def test_trim_to_post_shift_reduces_data(self):
        """trim_to_post_shift uses only data after the last changepoint."""
        from pocs.changepoint.level_shift.interventions import trim_to_post_shift

        result = self._make_detection_result(
            n_cp=1, indices=[100], dates=["2023-04-11"], magnitudes=[30.0]
        )
        df = self._make_prophet_df(length=400)
        ir = trim_to_post_shift(result, df)
        assert ir.strategy_name == "trim_to_post_shift"
        # Should have fewer rows than original
        assert len(ir.training_data) < len(df)
        # All remaining dates should be after changepoint + buffer
        min_date = pd.to_datetime(ir.training_data["ds"]).min()
        assert min_date >= pd.Timestamp("2023-04-11")

    def test_trim_fallback_on_insufficient_data(self):
        """trim_to_post_shift falls back to full data if <30 points remain."""
        from pocs.changepoint.level_shift.interventions import trim_to_post_shift

        # Changepoint near the end — only ~20 points after
        result = self._make_detection_result(
            n_cp=1, indices=[380], dates=["2024-01-16"], magnitudes=[30.0]
        )
        df = self._make_prophet_df(length=400)
        ir = trim_to_post_shift(result, df)
        # Should fall back to full data
        assert len(ir.training_data) == len(df)

    def test_add_step_regressor_adds_columns(self):
        """add_step_regressor adds binary regressor columns to the DataFrame."""
        from pocs.changepoint.level_shift.interventions import add_step_regressor

        result = self._make_detection_result(
            n_cp=2,
            indices=[100, 300],
            dates=["2023-04-11", "2023-10-28"],
            magnitudes=[30.0, -20.0],
        )
        df = self._make_prophet_df()
        ir = add_step_regressor(result, df)
        assert ir.strategy_name == "add_step_regressor"
        assert "shift_0" in ir.training_data.columns
        assert "shift_1" in ir.training_data.columns
        # Regressor is 0 before, 1 after changepoint
        assert ir.training_data["shift_0"].iloc[0] == 0.0
        assert ir.training_data["shift_0"].iloc[-1] == 1.0

    def test_increase_sensitivity_sets_prior_scale(self):
        """increase_sensitivity raises changepoint_prior_scale."""
        from pocs.changepoint.level_shift.interventions import increase_sensitivity

        result = self._make_detection_result(
            n_cp=1, indices=[250], dates=["2023-09-08"], magnitudes=[10.0]
        )
        df = self._make_prophet_df()
        ir = increase_sensitivity(result, df, prior_scale=0.8)
        assert ir.strategy_name == "increase_sensitivity"
        assert ir.model.changepoint_prior_scale == 0.8
        assert ir.model.n_changepoints == 50

    def test_clean_temporary_event_removes_spike(self):
        """clean_temporary_event removes data between canceling shifts."""
        from pocs.changepoint.level_shift.interventions import clean_temporary_event

        # Two shifts that cancel: +50 then -48 (ratio < 0.4)
        result = self._make_detection_result(
            n_cp=2,
            indices=[200, 220],
            dates=["2023-07-20", "2023-08-09"],
            magnitudes=[50.0, -48.0],
        )
        df = self._make_prophet_df()
        ir = clean_temporary_event(result, df)
        assert ir.strategy_name == "clean_temporary_event"
        # Data should be shorter (spike rows removed)
        assert len(ir.training_data) < len(df)
        # The removed window is ~20 days (Jul 20 to Aug 9)
        removed_count = len(df) - len(ir.training_data)
        assert removed_count > 0

    def test_clean_temporary_event_noop_when_no_cancel(self):
        """clean_temporary_event does nothing if shifts don't cancel."""
        from pocs.changepoint.level_shift.interventions import clean_temporary_event

        # Two shifts that DON'T cancel: +50 and +30
        result = self._make_detection_result(
            n_cp=2,
            indices=[200, 350],
            dates=["2023-07-20", "2023-12-17"],
            magnitudes=[50.0, 30.0],
        )
        df = self._make_prophet_df()
        ir = clean_temporary_event(result, df)
        # Should fall back to no_intervention
        assert ir.strategy_name == "no_intervention"

    def test_select_strategy_no_changepoints(self):
        """select_strategy returns no_intervention when no shifts detected."""
        from pocs.changepoint.level_shift.interventions import select_strategy

        result = self._make_detection_result(n_cp=0, indices=[], dates=[], magnitudes=[])
        df = self._make_prophet_df()
        assert select_strategy(result, df) == "no_intervention"

    def test_select_strategy_temporary_spike(self):
        """select_strategy picks clean_temporary_event for canceling pairs."""
        from pocs.changepoint.level_shift.interventions import select_strategy

        result = self._make_detection_result(
            n_cp=2,
            indices=[200, 220],
            dates=["2023-07-20", "2023-08-09"],
            magnitudes=[50.0, -48.0],
        )
        df = self._make_prophet_df()
        assert select_strategy(result, df) == "clean_temporary_event"

    def test_select_strategy_large_shifts(self):
        """select_strategy picks inject_changepoints for few large shifts."""
        from pocs.changepoint.level_shift.interventions import select_strategy

        result = self._make_detection_result(
            n_cp=1, indices=[250], dates=["2023-09-08"], magnitudes=[40.0]
        )
        df = self._make_prophet_df()
        assert select_strategy(result, df) == "inject_changepoints"

    def test_select_strategy_many_shifts(self):
        """select_strategy picks trim_to_post_shift for 3+ changepoints."""
        from pocs.changepoint.level_shift.interventions import select_strategy

        result = self._make_detection_result(
            n_cp=3,
            indices=[100, 250, 400],
            dates=["2023-04-11", "2023-09-08", "2024-02-04"],
            magnitudes=[25.0, -15.0, 30.0],
        )
        df = self._make_prophet_df()
        assert select_strategy(result, df) == "trim_to_post_shift"

    def test_select_strategy_subtle_shift(self):
        """select_strategy picks increase_sensitivity for small magnitude."""
        from pocs.changepoint.level_shift.interventions import select_strategy

        result = self._make_detection_result(
            n_cp=1, indices=[250], dates=["2023-09-08"], magnitudes=[10.0]
        )
        df = self._make_prophet_df()
        assert select_strategy(result, df) == "increase_sensitivity"

    def test_apply_intervention_dispatches_correctly(self):
        """apply_intervention calls the right strategy function."""
        from pocs.changepoint.level_shift.interventions import apply_intervention

        result = self._make_detection_result(
            n_cp=1, indices=[250], dates=["2023-09-08"], magnitudes=[10.0]
        )
        df = self._make_prophet_df()
        ir = apply_intervention(result, df, strategy="increase_sensitivity")
        assert ir.strategy_name == "increase_sensitivity"

    def test_apply_intervention_auto_selects(self):
        """apply_intervention with strategy=None uses select_strategy."""
        from pocs.changepoint.level_shift.interventions import apply_intervention

        result = self._make_detection_result(n_cp=0, indices=[], dates=[], magnitudes=[])
        df = self._make_prophet_df()
        ir = apply_intervention(result, df)
        assert ir.strategy_name == "no_intervention"

    def test_apply_intervention_invalid_strategy_raises(self):
        """apply_intervention raises ValueError for unknown strategy."""
        from pocs.changepoint.level_shift.interventions import apply_intervention

        result = self._make_detection_result()
        df = self._make_prophet_df()
        with pytest.raises(ValueError, match="Unknown strategy"):
            apply_intervention(result, df, strategy="nonexistent")

    def test_all_strategies_return_intervention_result(self):
        """Every strategy function returns a valid InterventionResult."""
        from prophet import Prophet
        from pocs.changepoint.level_shift.interventions import (
            STRATEGIES,
            InterventionResult,
        )

        result = self._make_detection_result(
            n_cp=2,
            indices=[200, 220],
            dates=["2023-07-20", "2023-08-09"],
            magnitudes=[50.0, -48.0],
        )
        df = self._make_prophet_df()
        for name, func in STRATEGIES.items():
            ir = func(result, df)
            assert isinstance(ir, InterventionResult), f"{name} didn't return InterventionResult"
            assert isinstance(ir.model, Prophet), f"{name} model is not Prophet"
            assert isinstance(ir.training_data, pd.DataFrame), f"{name} data is not DataFrame"
            assert "ds" in ir.training_data.columns, f"{name} data missing 'ds'"
            assert "y" in ir.training_data.columns, f"{name} data missing 'y'"


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestBacktest:
    """Tests for the backtest harness (no Prophet fitting — fast tests)."""

    def test_compute_mae_zero_error(self):
        """MAE of identical arrays is 0."""
        from pocs.changepoint.level_shift.backtest import _compute_mae

        actual = np.array([1.0, 2.0, 3.0])
        assert _compute_mae(actual, actual) == 0.0

    def test_compute_mae_known_value(self):
        """MAE computation with known answer."""
        from pocs.changepoint.level_shift.backtest import _compute_mae

        actual = np.array([10.0, 20.0, 30.0])
        predicted = np.array([12.0, 18.0, 33.0])
        # |10-12| + |20-18| + |30-33| = 2 + 2 + 3 = 7 / 3 ≈ 2.333
        expected = 7.0 / 3.0
        assert abs(_compute_mae(actual, predicted) - expected) < 1e-10

    def test_backtest_result_fields(self):
        """BacktestResult has all expected fields."""
        from pocs.changepoint.level_shift.backtest import BacktestResult

        br = BacktestResult(
            dataset_id="test",
            naive_mae=5.0,
            intervention_mae=3.0,
            strategy_used="trim_to_post_shift",
            forecast_horizon=30,
            train_size=400,
            test_size=30,
            improvement_pct=40.0,
            description="test",
        )
        assert br.improvement_pct == 40.0
        assert br.naive_mae > br.intervention_mae

    def test_improvement_pct_calculation(self):
        """Improvement % is computed correctly: (naive - intervention) / naive * 100."""
        naive_mae = 10.0
        intervention_mae = 6.0
        improvement = (naive_mae - intervention_mae) / naive_mae * 100
        assert improvement == 40.0

    def test_negative_improvement_means_hurt(self):
        """Negative improvement means intervention made things worse."""
        naive_mae = 5.0
        intervention_mae = 15.0
        improvement = (naive_mae - intervention_mae) / naive_mae * 100
        assert improvement == -200.0

    def test_run_backtest_single_dataset(self):
        """run_backtest produces valid result on a single dataset."""
        from pocs.changepoint.level_shift.backtest import run_backtest
        from pocs.changepoint.level_shift.datasets import DATASET_CONFIGS

        # Use D8 (no changepoint) — fast and deterministic
        config = DATASET_CONFIGS["D8_no_changepoint"]
        result = run_backtest("D8_no_changepoint", config, forecast_horizon=10)
        assert result.dataset_id == "D8_no_changepoint"
        assert result.naive_mae >= 0
        assert result.intervention_mae >= 0
        assert result.strategy_used == "no_intervention"
        assert result.forecast_horizon == 10
        # No-op intervention: both MAEs should be equal
        assert abs(result.naive_mae - result.intervention_mae) < 0.01

    def test_run_backtest_returns_improvement(self):
        """run_backtest computes improvement_pct correctly relative to MAEs."""
        from pocs.changepoint.level_shift.backtest import run_backtest
        from pocs.changepoint.level_shift.datasets import DATASET_CONFIGS

        config = DATASET_CONFIGS["D8_no_changepoint"]
        result = run_backtest("D8_no_changepoint", config, forecast_horizon=10)
        if result.naive_mae > 0:
            expected_pct = (result.naive_mae - result.intervention_mae) / result.naive_mae * 100
            assert abs(result.improvement_pct - round(expected_pct, 1)) < 0.2
