"""Test suite for anomaly dataset generators.

Test-first validation per Constitution Principle II:
- Verify all generators produce correct schema and lengths.
- Ensure reproducibility (same seed = same data).
- Validate anomaly counts and splits.
"""

import pytest
import pandas as pd
import numpy as np

from ailf.pipelines.anomaly.datasets import (
    AnomalyDataset,
    generate_simple_outlier_dataset,
    generate_nab_like_synthetic,
    generate_contextual_anomaly_dataset,
    split_dataset,
    get_available_datasets,
)


class TestSimpleOutlierDataset:
    """Test the simple outlier generator."""

    def test_simple_outlier_length(self):
        """Verify output has correct length."""
        ds = generate_simple_outlier_dataset(n_points=300, seed=42)
        assert len(ds.series) == 300

    def test_simple_outlier_schema(self):
        """Verify DataFrame has required columns."""
        ds = generate_simple_outlier_dataset(n_points=100)
        assert "value" in ds.series.columns
        assert "anomaly_label" in ds.series.columns

    def test_simple_outlier_anomaly_count(self):
        """Verify correct number of anomalies injected."""
        ds = generate_simple_outlier_dataset(
            n_points=300, seed=42, outlier_count=10
        )
        assert ds.anomaly_count == 10

    def test_simple_outlier_reproducibility(self):
        """Verify same seed produces same data."""
        ds1 = generate_simple_outlier_dataset(n_points=100, seed=42)
        ds2 = generate_simple_outlier_dataset(n_points=100, seed=42)
        pd.testing.assert_frame_equal(ds1.series, ds2.series)

    def test_simple_outlier_metadata(self):
        """Verify metadata fields populated."""
        ds = generate_simple_outlier_dataset(n_points=50, seed=99)
        assert ds.name
        assert ds.description
        assert ds.source == "synthetic_simple"


class TestNabLikeSynthetic:
    """Test NAB-like synthetic generator."""

    def test_nab_like_length(self):
        """Verify output length."""
        ds = generate_nab_like_synthetic(n_points=500, seed=42)
        assert len(ds.series) == 500

    def test_nab_like_anomaly_ratio(self):
        """Verify anomaly ratio is respected."""
        ds = generate_nab_like_synthetic(
            n_points=500, seed=42, anomaly_ratio=0.1
        )
        actual_ratio = ds.anomaly_count / len(ds.series)
        # Allow ±10% tolerance
        assert 0.05 <= actual_ratio <= 0.15

    def test_nab_like_point_anomalies(self):
        """Verify point anomaly type."""
        ds = generate_nab_like_synthetic(
            n_points=200, seed=42, anomaly_type="point"
        )
        assert ds.anomaly_count > 0
        assert "point" in ds.name.lower()

    def test_nab_like_level_shift(self):
        """Verify level shift anomaly type."""
        ds = generate_nab_like_synthetic(
            n_points=200, seed=42, anomaly_type="level_shift"
        )
        assert ds.anomaly_count > 0
        assert "level_shift" in ds.name.lower()

    def test_nab_like_trend(self):
        """Verify trend anomaly type."""
        ds = generate_nab_like_synthetic(
            n_points=200, seed=42, anomaly_type="trend"
        )
        assert ds.anomaly_count > 0
        assert "trend" in ds.name.lower()

    def test_nab_like_reproducibility(self):
        """Verify reproducibility with same seed."""
        ds1 = generate_nab_like_synthetic(
            n_points=300, seed=42, anomaly_type="point"
        )
        ds2 = generate_nab_like_synthetic(
            n_points=300, seed=42, anomaly_type="point"
        )
        pd.testing.assert_frame_equal(ds1.series, ds2.series)


class TestContextualAnomalyDataset:
    """Test contextual anomaly generator."""

    def test_contextual_length(self):
        """Verify output has correct length (365 days)."""
        ds = generate_contextual_anomaly_dataset(seed=42)
        assert len(ds.series) == 365

    def test_contextual_seasonality(self):
        """Verify period is set."""
        ds = generate_contextual_anomaly_dataset(seed=42)
        assert ds.period == 365

    def test_contextual_anomalies_present(self):
        """Verify anomalies are injected."""
        ds = generate_contextual_anomaly_dataset(seed=42)
        assert ds.anomaly_count > 0

    def test_contextual_reproducibility(self):
        """Verify reproducibility."""
        ds1 = generate_contextual_anomaly_dataset(seed=42)
        ds2 = generate_contextual_anomaly_dataset(seed=42)
        pd.testing.assert_frame_equal(ds1.series, ds2.series)


class TestSplitDataset:
    """Test split_dataset utility."""

    def test_split_preserves_total_length(self):
        """Verify sum of splits equals original length."""
        ds = generate_simple_outlier_dataset(n_points=1000)
        train, val, test = split_dataset(ds, train_ratio=0.7, val_ratio=0.15)
        assert len(train) + len(val) + len(test) == len(ds.series)

    def test_split_respects_ratios(self):
        """Verify split ratios are correct."""
        ds = generate_simple_outlier_dataset(n_points=1000)
        train, val, test = split_dataset(ds, train_ratio=0.7, val_ratio=0.15)
        assert len(train) == 700
        assert len(val) == 150
        assert len(test) == 150

    def test_split_custom_ratios(self):
        """Verify custom ratios work."""
        ds = generate_simple_outlier_dataset(n_points=1000)
        train, val, test = split_dataset(ds, train_ratio=0.6, val_ratio=0.2)
        assert len(train) == 600
        assert len(val) == 200
        assert len(test) == 200


class TestAvailableDatasets:
    """Test dataset registry."""

    def test_available_datasets_registry(self):
        """Verify registry contains expected loaders."""
        loaders = get_available_datasets()
        assert "simple_outlier" in loaders
        assert "nab_like_point" in loaders
        assert "nab_like_level_shift" in loaders
        assert "contextual" in loaders

    def test_available_datasets_callable(self):
        """Verify registry entries are callable."""
        loaders = get_available_datasets()
        for name, loader in loaders.items():
            ds = loader(seed=42)
            assert isinstance(ds, AnomalyDataset)
            assert len(ds.series) > 0
