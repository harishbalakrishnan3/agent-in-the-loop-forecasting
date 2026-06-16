"""Round-trip serialization tests for the generic Case container (T004)."""

import numpy as np
import pandas as pd
import pytest
from darts import TimeSeries

from ailf.core.datasets import Case


def _series(length: int = 10) -> TimeSeries:
    idx = pd.date_range("2015-01-01", periods=length, freq="D")
    values = np.arange(length, dtype=float) * 1.5 + 3.0
    return TimeSeries.from_times_and_values(idx, values)


def test_case_round_trip_preserves_series_and_labels() -> None:
    case = Case(
        case_id="drift-mean_level-0000",
        series=_series(),
        labels=[{"flavor": "mean_level", "onset_index": 5, "magnitude": 2.0}],
        is_synthetic=True,
        labeled=True,
        config={"length": 10, "seed": 42},
        metadata={"note": "test"},
    )

    restored = Case.from_dict(case.to_dict())

    assert restored.case_id == case.case_id
    assert restored.is_synthetic is True
    assert restored.labeled is True
    assert restored.labels == case.labels
    assert restored.config == case.config
    assert restored.metadata == case.metadata
    assert restored.series == case.series
    np.testing.assert_array_equal(
        restored.series.values(), case.series.values()
    )
    assert list(restored.series.time_index) == list(case.series.time_index)


def test_case_to_dict_is_json_compatible() -> None:
    import json

    case = Case(
        case_id="drift-trend_slope-0001",
        series=_series(5),
        labels=[{"flavor": "trend_slope", "onset_index": 2}],
        is_synthetic=True,
        labeled=True,
        config=None,
        metadata={},
    )
    payload = case.to_dict()
    # Must serialize to JSON and back without custom encoders.
    reloaded = json.loads(json.dumps(payload))
    assert reloaded == payload


def test_unlabeled_real_case_round_trip() -> None:
    case = Case(
        case_id="real-air_passengers",
        series=_series(12),
        labels=[],
        is_synthetic=False,
        labeled=False,
        config=None,
        metadata={"qualitative_drift": "growing seasonal amplitude"},
    )
    restored = Case.from_dict(case.to_dict())
    assert restored.is_synthetic is False
    assert restored.labeled is False
    assert restored.labels == []
    assert restored.config is None
    assert restored.metadata["qualitative_drift"] == "growing seasonal amplitude"
    assert restored.series == case.series


def test_series_must_be_univariate() -> None:
    idx = pd.date_range("2015-01-01", periods=4, freq="D")
    multivar = TimeSeries.from_times_and_values(
        idx, np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]])
    )
    with pytest.raises(ValueError):
        Case(
            case_id="bad",
            series=multivar,
            labels=[],
            is_synthetic=True,
            labeled=False,
        )
