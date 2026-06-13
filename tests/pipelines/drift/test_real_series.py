"""US4: real demo series load through the same Case interface, unlabeled (T025)."""

import pandas as pd

from ailf.core.datasets import Case
from ailf.pipelines.drift.datasets import (
    list_real_series,
    load_air_passengers,
    load_mauna_loa_co2,
)


def test_air_passengers_is_unlabeled_case() -> None:
    case = load_air_passengers()
    assert isinstance(case, Case)
    assert case.is_synthetic is False
    assert case.labeled is False
    assert case.labels == []
    assert case.series.is_univariate
    assert case.metadata["qualitative_drift"]


def test_mauna_loa_co2_is_regular_monthly_no_gaps() -> None:
    case = load_mauna_loa_co2()
    assert case.is_synthetic is False
    assert case.labeled is False
    assert case.labels == []
    assert case.metadata["qualitative_drift"]
    # Regular monthly frequency, no missing values (Edge Case: real-series gaps).
    assert case.series.freq_str in {"MS", "M", "ME"}
    df = case.series.to_dataframe()
    assert df.isna().sum().sum() == 0
    # Index is strictly regular monthly.
    diffs = pd.Series(case.series.time_index).diff().dropna().dt.days
    assert diffs.between(28, 31).all()


def test_list_real_series_enumerates_about_two() -> None:
    names = list_real_series()
    assert len(names) == 2
    assert "air_passengers" in names
    assert "mauna_loa_co2" in names
