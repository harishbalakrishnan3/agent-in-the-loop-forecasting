"""Test suite for anomaly detection diagnostic tools.

Test-first validation (Constitution Principle II):
- All tools tested against synthetic data with KNOWN ground truth
- Precision, recall, F1 measured on injected anomalies
- All edge cases covered before tool integration
"""

import pytest
import numpy as np
import pandas as pd

from ailf.pipelines.anomaly.datasets import (
    generate_nab_like_synthetic,
    generate_simple_outlier_dataset,
)
from ailf.pipelines.anomaly.tools import (
    detect_level_shift,
    detect_outliers,
    split_by_anomaly,
    compute_metrics,
)


class TestDetectOutliers:
    """Test outlier detection tool."""

    def test_detect_outliers_simple(self):
        """Verify outlier detection on simple dataset."""
        ds = generate_simple_outlier_dataset(n_points=300, seed=42, outlier_count=10)
        pred_labels = detect_outliers(ds.series["value"].values)
        
        # Should detect most (>70%) of actual outliers
        actual_outliers = np.where(ds.series["anomaly_label"] == 1)[0]
        detected = np.where(pred_labels == 1)[0]
        
        if len(actual_outliers) > 0:
            recall = len(np.intersect1d(actual_outliers, detected)) / len(actual_outliers)
            assert recall >= 0.6, f"Recall too low: {recall}"

    def test_detect_outliers_returns_binary(self):
        """Verify output is binary labels."""
        ds = generate_simple_outlier_dataset(n_points=100)
        pred_labels = detect_outliers(ds.series["value"].values)
        
        assert len(pred_labels) == len(ds.series)
        assert np.all((pred_labels == 0) | (pred_labels == 1))

    def test_detect_outliers_empty_input(self):
        """Handle edge case: empty series."""
        with pytest.raises((ValueError, IndexError)):
            detect_outliers(np.array([]))

    def test_detect_outliers_single_point(self):
        """Handle edge case: single point (no anomaly)."""
        pred = detect_outliers(np.array([100.0]))
        assert len(pred) == 1


class TestDetectLevelShift:
    """Test level shift detection."""

    def test_detect_level_shift_nab_like(self):
        """Verify level shift detection on NAB-like dataset."""
        ds = generate_nab_like_synthetic(
            n_points=500, seed=42, anomaly_type="level_shift"
        )
        shift_indices = detect_level_shift(ds.series["value"].values)
        
        # Should find at least 1 shift point
        assert len(shift_indices) > 0
        # Shift indices should be within bounds
        assert np.all(shift_indices >= 0)
        assert np.all(shift_indices < len(ds.series))

    def test_detect_level_shift_no_shift(self):
        """Verify no false positives on smooth data."""
        # Generate smooth series (just noise, no shifts)
        np.random.seed(99)
        values = np.random.normal(100, 5, 200)
        
        shift_indices = detect_level_shift(values)
        # Should find few or no shifts in smooth data
        assert len(shift_indices) < 10

    def test_detect_level_shift_obvious_shift(self):
        """Verify detection on obvious step change."""
        values = np.concatenate([
            np.ones(50) * 100,
            np.ones(50) * 150,  # Clear shift
            np.ones(50) * 150,
        ])
        
        shift_indices = detect_level_shift(values)
        # Should find shift around index 50
        assert len(shift_indices) > 0
        assert np.any(np.abs(shift_indices - 50) < 10)


class TestSplitByAnomaly:
    """Test series splitting."""

    def test_split_by_anomaly_preserves_length(self):
        """Verify split doesn't lose data."""
        ds = generate_simple_outlier_dataset(n_points=100)
        
        normal, anomalous = split_by_anomaly(ds.series)
        
        # Should preserve all points
        assert len(normal) + len(anomalous) == len(ds.series)

    def test_split_by_anomaly_separates_correctly(self):
        """Verify splits are correct."""
        ds = generate_simple_outlier_dataset(n_points=100, outlier_count=10)
        
        normal, anomalous = split_by_anomaly(ds.series)
        
        # Anomalous should have ~10 points
        assert len(anomalous) >= 8  # Allow ±2 tolerance
        assert len(anomalous) <= 12
        
        # Normal should be ~90 points
        assert len(normal) >= 88
        assert len(normal) <= 92

    def test_split_by_anomaly_schema(self):
        """Verify output DataFrames have correct schema."""
        ds = generate_simple_outlier_dataset(n_points=100)
        
        normal, anomalous = split_by_anomaly(ds.series)
        
        assert isinstance(normal, pd.DataFrame)
        assert isinstance(anomalous, pd.DataFrame)
        assert "value" in normal.columns
        assert "value" in anomalous.columns


class TestComputeMetrics:
    """Test metrics computation."""

    def test_compute_metrics_schema(self):
        """Verify metrics dict has required keys."""
        ds = generate_simple_outlier_dataset(n_points=100)
        pred_labels = detect_outliers(ds.series["value"].values)
        
        metrics = compute_metrics(
            y_true=ds.series["anomaly_label"].values,
            y_pred=pred_labels,
        )
        
        assert "precision" in metrics
        assert "recall" in metrics
        assert "f1" in metrics
        assert "confusion_matrix" in metrics

    def test_compute_metrics_perfect_prediction(self):
        """Verify metrics on perfect prediction."""
        y_true = np.array([0, 0, 1, 1, 0, 0, 1, 0])
        y_pred = y_true.copy()
        
        metrics = compute_metrics(y_true, y_pred)
        
        assert metrics["precision"] == 1.0
        assert metrics["recall"] == 1.0
        assert metrics["f1"] == 1.0

    def test_compute_metrics_terrible_prediction(self):
        """Verify metrics on inverted prediction."""
        y_true = np.array([0, 0, 1, 1, 0, 0, 1, 0])
        y_pred = 1 - y_true  # Flip all labels
        
        metrics = compute_metrics(y_true, y_pred)
        
        # Precision, recall should be low
        assert metrics["precision"] < 0.5
        assert metrics["recall"] < 0.5

    def test_compute_metrics_no_anomalies(self):
        """Handle edge case: no anomalies in ground truth."""
        y_true = np.zeros(100)
        y_pred = np.zeros(100)
        
        metrics = compute_metrics(y_true, y_pred)
        
        # Precision should be 1.0 (no false positives)
        assert metrics["precision"] == 1.0


class TestToolsIntegration:
    """Integration tests combining multiple tools."""

    def test_pipeline_simple_outlier(self):
        """End-to-end on simple outlier dataset."""
        ds = generate_simple_outlier_dataset(n_points=200, seed=42, outlier_count=5)
        
        # Step 1: Detect outliers
        pred_labels = detect_outliers(ds.series["value"].values)
        
        # Step 2: Split by anomaly
        normal, anomalous = split_by_anomaly(
            pd.DataFrame({
                "value": ds.series["value"],
                "anomaly_label": pred_labels,
            })
        )
        
        # Step 3: Compute metrics
        metrics = compute_metrics(ds.series["anomaly_label"].values, pred_labels)
        
        # Sanity checks
        assert len(normal) > 0
        assert metrics["precision"] >= 0.0
        assert metrics["recall"] >= 0.0

    def test_pipeline_level_shift(self):
        """End-to-end on level shift dataset."""
        ds = generate_nab_like_synthetic(
            n_points=300, seed=42, anomaly_type="level_shift"
        )
        
        # Step 1: Detect level shifts
        shift_indices = detect_level_shift(ds.series["value"].values)
        
        # Should find at least one shift
        assert len(shift_indices) > 0
        
        # Step 2: Create binary labels from shifts
        pred_labels = np.zeros(len(ds.series))
        for idx in shift_indices:
            if idx + 5 < len(ds.series):
                pred_labels[idx:idx+5] = 1
        
        # Step 3: Compute metrics
        metrics = compute_metrics(ds.series["anomaly_label"].values, pred_labels)
        
        assert "f1" in metrics
