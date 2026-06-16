"""Anomaly (outlier) dataset generation.

Seeded, knob-driven synthetic series with known outliers, plus loaders for standard
datasets. Build generic Darts plumbing in `ailf.core.datasets`; keep only
outlier-specific generation here.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from darts.utils.timeseries_generation import gaussian_timeseries


@dataclass
class AnomalyDataset:
    """Container for anomaly detection dataset."""

    name: str
    """Human-readable name."""

    series: pd.DataFrame
    """DataFrame with columns: value, anomaly_label (0/1 for normal/anomaly)."""

    description: str
    """What this dataset represents and why anomalies are meaningful."""

    anomaly_count: int
    """Number of labeled anomalies in the series."""

    period: Optional[int] = None
    """Seasonality period (if applicable)."""

    source: str = "unknown"
    """Where the data came from (synthetic, real-world, benchmark)."""


def generate_simple_outlier_dataset(
    n_points: int = 300, seed: int = 42, outlier_count: int = 10
) -> AnomalyDataset:
    """Generate synthetic time-series with point outliers.

    Simple baseline: normal distribution with random spike anomalies.
    Good for fast testing and POC validation.

    Args:
        n_points: Length of series.
        seed: Random seed for reproducibility.
        outlier_count: Number of outlier points to inject.

    Returns:
        AnomalyDataset with labeled outliers.

    Example:
        >>> ds = generate_simple_outlier_dataset(n_points=300, seed=42, outlier_count=15)
        >>> assert len(ds.series) == 300
        >>> assert ds.anomaly_count == 15
    """
    np.random.seed(seed)

    # Baseline: normal distribution N(100, 10)
    values = np.random.normal(100, 10, n_points)
    anomaly_labels = np.zeros(n_points, dtype=int)

    # Inject outliers: 3-5x std above/below mean
    outlier_indices = np.random.choice(n_points, size=outlier_count, replace=False)
    for idx in outlier_indices:
        direction = np.random.choice([-1, 1])
        values[idx] = 100 + direction * np.random.uniform(30, 50)
        anomaly_labels[idx] = 1

    timestamps = pd.date_range(start="2020-01-01", periods=n_points, freq="D")
    result_df = pd.DataFrame(
        {
            "value": values,
            "anomaly_label": anomaly_labels,
        },
        index=timestamps,
    )

    return AnomalyDataset(
        name="Simple Outlier (Gaussian + spikes)",
        series=result_df,
        description="Baseline Gaussian series with random outlier spikes. Fast baseline for testing.",
        anomaly_count=outlier_count,
        source="synthetic_simple",
    )


def generate_nab_like_synthetic(
    n_points: int = 500,
    seed: int = 42,
    anomaly_ratio: float = 0.1,
    anomaly_type: str = "point",
) -> AnomalyDataset:
    """Generate synthetic time-series similar to NAB (Numenta Anomaly Benchmark).

    Uses Darts generators for reproducibility with controlled anomalies.

    Args:
        n_points: Number of points to generate.
        seed: Random seed for reproducibility.
        anomaly_ratio: Fraction of points that are anomalies (0.0-1.0).
        anomaly_type: "point" (impulse), "level_shift", or "trend".

    Returns:
        AnomalyDataset with synthetic series + anomaly labels.

    Example:
        >>> ds = generate_nab_like_synthetic(n_points=500, seed=42, anomaly_type="point")
        >>> assert len(ds.series) == 500
        >>> assert ds.anomaly_count > 0
    """
    np.random.seed(seed)

    # Generate baseline: gaussian noise using Darts
    ts = gaussian_timeseries(
        length=n_points,
        mean=100,
        std=10,
    )

    # Convert to numpy (shape is (n, 1, 1), flatten to 1D)
    values = ts.all_values().flatten()

    # Create anomaly labels
    n_anomalies = max(1, int(n_points * anomaly_ratio))
    anomaly_indices = np.random.choice(
        n_points, size=n_anomalies, replace=False
    )
    anomaly_labels = np.zeros(n_points, dtype=int)

    if anomaly_type == "point":
        # Impulse anomalies: shift by 3-5x std
        std = np.std(values)
        for idx in anomaly_indices:
            values[idx] += np.random.choice([-1, 1]) * np.random.uniform(3, 5) * std
            anomaly_labels[idx] = 1

    elif anomaly_type == "level_shift":
        # Level shifts: step change for consecutive points
        for idx in anomaly_indices:
            if idx + 5 < n_points:
                shift = np.random.choice([-1, 1]) * np.random.uniform(2, 4) * np.std(values)
                values[idx : idx + 5] += shift
                anomaly_labels[idx : idx + 5] = 1

    elif anomaly_type == "trend":
        # Trend anomalies: reversal of trend for a segment
        for idx in anomaly_indices:
            if idx + 10 < n_points:
                values[idx : idx + 10] -= np.arange(10) * 2
                anomaly_labels[idx : idx + 10] = 1

    # Create result DataFrame
    timestamps = pd.date_range(start="2020-01-01", periods=n_points, freq="D")
    result_df = pd.DataFrame(
        {
            "value": values,
            "anomaly_label": anomaly_labels,
        },
        index=timestamps,
    )

    return AnomalyDataset(
        name=f"Synthetic NAB-like ({anomaly_type})",
        series=result_df,
        description=(
            f"Synthetic time-series with {anomaly_type} anomalies. "
            f"Generated with seed={seed} for reproducibility."
        ),
        anomaly_count=int(anomaly_labels.sum()),
        period=7,
        source="synthetic_darts",
    )


def generate_contextual_anomaly_dataset(seed: int = 42) -> AnomalyDataset:
    """Generate seasonal time-series with contextual anomalies.

    Contextual anomalies are normal values but unusual given context.
    Example: temperature reading 20°C in winter is normal, but anomalous in summer.

    Args:
        seed: Random seed.

    Returns:
        AnomalyDataset with contextual anomalies.

    Example:
        >>> ds = generate_contextual_anomaly_dataset(seed=42)
        >>> assert len(ds.series) == 365
        >>> assert ds.anomaly_count > 0
    """
    np.random.seed(seed)

    n_points = 365
    timestamps = pd.date_range(start="2020-01-01", periods=n_points, freq="D")

    # Seasonal baseline: ~20 + 10*sin(2π*t/365) + noise
    t = np.arange(n_points)
    seasonal = 20 + 10 * np.sin(2 * np.pi * t / 365)
    noise = np.random.normal(0, 1, n_points)
    values = seasonal + noise

    # Contextual anomalies: summer with low values (context is seasonal)
    anomaly_labels = np.zeros(n_points, dtype=int)
    summer_indices = np.where((t > 150) & (t < 240))[0]
    anomaly_indices = np.random.choice(
        summer_indices, size=10, replace=False
    )
    for idx in anomaly_indices:
        values[idx] = values[idx] - 8  # Drop by ~8°C in summer (anomalous)
        anomaly_labels[idx] = 1

    result_df = pd.DataFrame(
        {
            "value": values,
            "anomaly_label": anomaly_labels,
        },
        index=timestamps,
    )

    return AnomalyDataset(
        name="Contextual Anomaly (Seasonal)",
        series=result_df,
        description=(
            "Seasonal time-series (e.g., temperature) with contextual anomalies. "
            "Summer dips are unusual for the season."
        ),
        anomaly_count=int(anomaly_labels.sum()),
        period=365,
        source="synthetic_contextual",
    )


def get_available_datasets() -> dict[str, callable]:
    """Return dict of available dataset generators.

    Usage:
        >>> loaders = get_available_datasets()
        >>> dataset = loaders["simple_outlier"](seed=42)
    """
    return {
        "simple_outlier": generate_simple_outlier_dataset,
        "nab_like_point": lambda seed=42: generate_nab_like_synthetic(
            seed=seed, anomaly_type="point"
        ),
        "nab_like_level_shift": lambda seed=42: generate_nab_like_synthetic(
            seed=seed, anomaly_type="level_shift"
        ),
        "nab_like_trend": lambda seed=42: generate_nab_like_synthetic(
            seed=seed, anomaly_type="trend"
        ),
        "contextual": generate_contextual_anomaly_dataset,
    }


def split_dataset(
    dataset: AnomalyDataset, train_ratio: float = 0.7, val_ratio: float = 0.15
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split dataset into train/val/test sets.

    Preserves temporal order (no shuffling) as is standard for time-series.

    Args:
        dataset: AnomalyDataset to split.
        train_ratio: Fraction for training (0.0-1.0).
        val_ratio: Fraction for validation. Rest goes to test.

    Returns:
        Tuple of (train_df, val_df, test_df).

    Example:
        >>> ds = generate_simple_outlier_dataset(n_points=100)
        >>> train, val, test = split_dataset(ds)
        >>> assert len(train) + len(val) + len(test) == 100
    """
    n = len(dataset.series)
    train_end = int(n * train_ratio)
    val_end = train_end + int(n * val_ratio)

    train = dataset.series.iloc[:train_end]
    val = dataset.series.iloc[train_end:val_end]
    test = dataset.series.iloc[val_end:]

    return train, val, test
