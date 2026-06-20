"""Anomaly detection diagnostic tools.

Pure, typed functions the agent can call. Distinguish isolated outliers from
structural changes. All tested against synthetic data with KNOWN ground truth
(precision/recall/F1) before agent integration.

Tools:
- detect_outliers() — flag spike/impulse anomalies
- detect_level_shift() — identify where series level changes
- split_by_anomaly() — partition series into normal/anomalous regions
- compute_metrics() — precision, recall, F1 on ground truth
"""

from typing import Tuple
import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from sklearn.metrics import precision_score, recall_score, f1_score, confusion_matrix


def detect_outliers(
    values: np.ndarray, threshold_std: float = 3.0
) -> np.ndarray:
    """Detect spike/impulse anomalies using statistical thresholding.

    A point is an outlier if it deviates > threshold_std from local median.
    Robust to trends (uses local sliding window).

    Args:
        values: 1D array of time-series values.
        threshold_std: Number of local std devs from median to flag as outlier.

    Returns:
        Binary array (0=normal, 1=anomaly).

    Example:
        >>> values = np.array([100, 101, 102, 200, 103, 104, 105])
        >>> labels = detect_outliers(values, threshold_std=2.5)
        >>> labels[3] == 1  # Index 3 (value 200) is flagged
        True
    """
    if len(values) == 0:
        raise ValueError("Empty input array")
    
    if len(values) == 1:
        return np.array([0], dtype=int)

    # Use rolling median + MAD (median absolute deviation) for robustness
    window_size = min(15, max(5, len(values) // 10))
    
    labels = np.zeros(len(values), dtype=int)
    
    for i in range(len(values)):
        # Local window
        start = max(0, i - window_size // 2)
        end = min(len(values), i + window_size // 2 + 1)
        local_vals = values[start:end]
        
        if len(local_vals) <= 1:
            continue
        
        median = np.median(local_vals)
        mad = np.median(np.abs(local_vals - median))
        
        # Prevent division by zero
        if mad == 0:
            mad = np.std(local_vals) if np.std(local_vals) > 0 else 1.0
        
        # Flag if deviates significantly
        z_score = np.abs(values[i] - median) / (mad + 1e-6)
        if z_score > threshold_std:
            labels[i] = 1
    
    return labels


def detect_level_shift(
    values: np.ndarray, min_shift_magnitude: float = 1.5, window_size: int = 5
) -> np.ndarray:
    """Detect where series level changes (step anomalies).

    Uses mean shift detection on rolling windows to find structural breaks.
    Reports indices where shifts are detected.

    Args:
        values: 1D array of time-series values.
        min_shift_magnitude: Minimum shift size (in absolute difference) to detect.
        window_size: Window for computing local statistics.

    Returns:
        Array of indices where level shifts are detected.

    Example:
        >>> values = np.concatenate([np.ones(50)*100, np.ones(50)*150])
        >>> shifts = detect_level_shift(values, min_shift_magnitude=1.0)
        >>> np.any(np.abs(shifts - 50) < 15)  # Shift detected near index 50
        True
    """
    if len(values) < window_size * 2:
        return np.array([], dtype=int)
    
    # Compute rolling mean difference: how much does each point differ from recent history?
    shift_indices = []
    
    for i in range(window_size, len(values) - window_size):
        # Mean before and after window center
        before = np.mean(values[max(0, i-window_size):i])
        after = np.mean(values[i:min(len(values), i+window_size)])
        
        shift_magnitude = np.abs(after - before)
        
        # Flag if shift is significant relative to local variance
        local_std = np.std(values[max(0, i-window_size*2):min(len(values), i+window_size*2)])
        local_std = max(local_std, 1.0)  # Prevent division issues
        
        normalized_shift = shift_magnitude / local_std
        
        if normalized_shift > min_shift_magnitude:
            # Avoid duplicates (cluster nearby shifts)
            if len(shift_indices) == 0 or i - shift_indices[-1] > window_size:
                shift_indices.append(i)
    
    return np.array(shift_indices, dtype=int)


def split_by_anomaly(
    series: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split series into normal and anomalous regions.

    Uses anomaly_label column (0=normal, 1=anomaly).

    Args:
        series: DataFrame with columns 'value' and 'anomaly_label'.

    Returns:
        Tuple of (normal_df, anomalous_df).

    Example:
        >>> df = pd.DataFrame({
        ...     'value': [100, 101, 200, 102, 103],
        ...     'anomaly_label': [0, 0, 1, 0, 0]
        ... })
        >>> normal, anom = split_by_anomaly(df)
        >>> len(normal), len(anom)
        (4, 1)
    """
    if "anomaly_label" not in series.columns:
        raise ValueError("Series must have 'anomaly_label' column")
    
    normal = series[series["anomaly_label"] == 0]
    anomalous = series[series["anomaly_label"] == 1]
    
    return normal, anomalous


def compute_metrics(
    y_true: np.ndarray, y_pred: np.ndarray
) -> dict:
    """Compute precision, recall, F1 against ground truth.

    Args:
        y_true: Ground truth binary labels.
        y_pred: Predicted binary labels.

    Returns:
        Dict with keys: precision, recall, f1, confusion_matrix.

    Example:
        >>> y_true = np.array([0, 0, 1, 1, 0])
        >>> y_pred = np.array([0, 0, 1, 0, 0])
        >>> m = compute_metrics(y_true, y_pred)
        >>> m['recall'] == 0.5
        True
    """
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have same length")
    
    if len(np.unique(y_true)) == 1 and len(np.unique(y_pred)) == 1:
        # Edge case: only one class present
        if y_true[0] == y_pred[0]:
            return {
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
            }
        else:
            return {
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
            }
    
    # Prevent warnings on degenerate cases
    with np.errstate(divide='ignore', invalid='ignore'):
        precision = precision_score(y_true, y_pred, zero_division=0)
        recall = recall_score(y_true, y_pred, zero_division=0)
        f1 = f1_score(y_true, y_pred, zero_division=0)
    
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
    }
