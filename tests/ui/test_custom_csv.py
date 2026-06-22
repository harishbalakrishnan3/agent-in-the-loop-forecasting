"""T024 — custom-CSV validation (contract: custom_csv.md, FR-008/009/010; spec.md:92 edge case)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ailf.ui.config_builder import validate_custom_series, validate_split_fractions


def _good_df(n: int = 100) -> pd.DataFrame:
    return pd.DataFrame({
        "ds": pd.date_range("2021-01-01", periods=n, freq="D"),
        "y": np.arange(n, dtype=float),
    })


def test_accepts_conforming_frame():
    r = validate_custom_series(_good_df(), train=0.8, val=0.1, test=0.1)
    assert r.ok and r.errors == []


def test_missing_dataframe_rejected():
    r = validate_custom_series(None, train=0.8, val=0.1, test=0.1)
    assert not r.ok and any("No CSV" in e for e in r.errors)


def test_wrong_columns_rejected():
    df = pd.DataFrame({"date": [1, 2, 3], "value": [1.0, 2.0, 3.0]})
    r = validate_custom_series(df, train=0.8, val=0.1, test=0.1)
    assert not r.ok and any("ds" in e and "y" in e for e in r.errors)


def test_extra_columns_rejected():
    df = _good_df()
    df["extra"] = 1
    r = validate_custom_series(df, train=0.8, val=0.1, test=0.1)
    assert not r.ok


def test_unsorted_ds_rejected():
    df = _good_df(10)
    df = df.iloc[::-1].reset_index(drop=True)  # reverse chronological
    r = validate_custom_series(df, train=0.8, val=0.1, test=0.1)
    assert not r.ok and any("sorted" in e.lower() for e in r.errors)


def test_duplicate_ds_rejected():
    df = _good_df(10)
    df.loc[5, "ds"] = df.loc[4, "ds"]  # duplicate timestamp
    r = validate_custom_series(df, train=0.8, val=0.1, test=0.1)
    assert not r.ok and any("duplicate" in e.lower() for e in r.errors)


def test_null_y_rejected():
    df = _good_df(10)
    df.loc[3, "y"] = np.nan
    r = validate_custom_series(df, train=0.8, val=0.1, test=0.1)
    assert not r.ok and any("'y'" in e for e in r.errors)


def test_non_numeric_y_rejected():
    df = _good_df(10)
    df["y"] = df["y"].astype(object)
    df.loc[2, "y"] = "oops"
    r = validate_custom_series(df, train=0.8, val=0.1, test=0.1)
    assert not r.ok and any("'y'" in e for e in r.errors)


def test_fractions_not_summing_to_one_rejected():
    r = validate_custom_series(_good_df(), train=0.8, val=0.2, test=0.2)
    assert not r.ok and any("sum to 1" in e for e in r.errors)


def test_too_few_rows_for_split_rejected():
    r = validate_custom_series(_good_df(2), train=0.8, val=0.1, test=0.1)
    assert not r.ok and any("Not enough rows" in e for e in r.errors)


def test_validate_split_fractions_standalone():
    assert validate_split_fractions(0.8, 0.1, 0.1).ok
    assert not validate_split_fractions(0.8, 0.1, 0.2).ok
    assert not validate_split_fractions(-0.1, 0.6, 0.5).ok
