"""US5: drift overlay structure, tested headlessly (T027)."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from darts import TimeSeries

from ailf.core.datasets import Case
from ailf.core.datasets.viz import plot_drift_overlay, save_drift_overlay


def _synthetic_case(onset: int = 20, length: int = 60) -> Case:
    idx = pd.date_range("2015-01-01", periods=length, freq="D")
    v = np.arange(length, dtype=float)
    return Case(
        case_id="drift-mean_level-test",
        series=TimeSeries.from_times_and_values(idx, v),
        labels=[{"flavor": "mean_level", "onset_index": onset, "transition_width": 5,
                 "onset_time": idx[onset].isoformat(), "affected_component": "trend",
                 "magnitude": 5.0}],
        is_synthetic=True,
        labeled=True,
    )


def _real_case(length: int = 60) -> Case:
    idx = pd.date_range("2015-01-01", periods=length, freq="D")
    v = np.linspace(0, 10, length)
    return Case(
        case_id="real-test",
        series=TimeSeries.from_times_and_values(idx, v),
        labels=[],
        is_synthetic=False,
        labeled=False,
    )


def _trace_names(fig: go.Figure) -> set[str]:
    return {(t.name or "").lower() for t in fig.data}


def test_overlay_has_observations_rolling_mean_and_std_band() -> None:
    fig = plot_drift_overlay(_synthetic_case())
    assert isinstance(fig, go.Figure)
    names = _trace_names(fig)
    assert any("observ" in n for n in names)
    assert any("mean" in n for n in names)
    assert any("std" in n for n in names)


def test_synthetic_case_has_onset_marker() -> None:
    fig = plot_drift_overlay(_synthetic_case())
    # Onset marker rendered as a vertical line shape.
    assert len(fig.layout.shapes) >= 1


def test_real_case_has_no_onset_marker() -> None:
    fig = plot_drift_overlay(_real_case())
    assert len(fig.layout.shapes) == 0


def test_save_writes_png_and_html(tmp_path) -> None:
    png, html = save_drift_overlay(_synthetic_case(), tmp_path)
    assert png.exists() and png.suffix == ".png"
    assert html.exists() and html.suffix == ".html"
    assert "drift-mean_level-test" in png.name
