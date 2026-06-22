"""T015 — chart-frame assembly: region relabeling + changepoint markers (data-model §3, FR-024/025)."""

from __future__ import annotations

import pandas as pd

from ailf.ui.chart import build_frame


def _legacy_frame():
    """A forecast_comparison.csv-shaped frame using the LEGACY train/forecast labels."""
    dates = pd.date_range("2021-01-01", periods=10, freq="D")
    rows = []
    for i, d in enumerate(dates):
        forecast = i >= 7  # last 3 rows are the forecast (test) region
        rows.append({
            "ds": d.strftime("%Y-%m-%d"),
            "y_actual": float(i),
            "region": "forecast" if forecast else "train",
            "yhat_full_history": float(i) + 0.5 if forecast else float("nan"),
            "yhat_naive": float(i) + 0.4 if forecast else float("nan"),
            "yhat_agent": float(i) + 0.3 if forecast else float("nan"),
        })
    return pd.DataFrame(rows)


def test_legacy_forecast_relabeled_to_test_and_val_split_out():
    df = _legacy_frame()
    # fit_end at index 5 → rows [5,7) become "val"; rows [7,10) become "test"; [0,5) stay "train".
    fit_end_ds = pd.Timestamp("2021-01-06")  # the 6th day (index 5)
    data = build_frame(df, changepoints=[], fit_end_ds=fit_end_ds, context_points=100)
    regions = set(data.frame["region"])
    assert regions == {"train", "val", "test"}
    assert (data.frame["region"] == "test").sum() == 3
    assert (data.frame["region"] == "val").sum() == 2


def test_region_bounds_located():
    df = _legacy_frame()
    data = build_frame(df, fit_end_ds=pd.Timestamp("2021-01-06"), context_points=100)
    assert data.region_bounds["val_start_ds"] == pd.Timestamp("2021-01-06")
    assert data.region_bounds["test_start_ds"] == pd.Timestamp("2021-01-08")


def test_changepoints_filtered_to_frame_range():
    df = _legacy_frame()
    cps = [
        {"index": 3, "ds": "2021-01-04", "trend_delta": 1.5},   # in range
        {"index": 99, "ds": "2025-01-01", "trend_delta": 9.9},  # out of range — dropped
    ]
    data = build_frame(df, changepoints=cps, fit_end_ds=pd.Timestamp("2021-01-06"))
    assert len(data.changepoints) == 1
    assert data.changepoints[0]["ds"] == "2021-01-04"


def test_view_window_uses_recent_context():
    df = _legacy_frame()
    data = build_frame(df, fit_end_ds=pd.Timestamp("2021-01-06"), context_points=2)
    start, end = data.view_window
    # forecast region (val) starts at index 5; 2 points of context → index 3.
    assert start == pd.Timestamp("2021-01-04")
    assert end == pd.Timestamp("2021-01-10")


def test_already_normalized_frame_passes_through():
    df = _legacy_frame()
    df["region"] = df["region"].replace({"forecast": "test"})
    df.loc[5:6, "region"] = "val"
    data = build_frame(df)  # no fit_end_ds needed; already has train/val/test
    assert set(data.frame["region"]) == {"train", "val", "test"}
