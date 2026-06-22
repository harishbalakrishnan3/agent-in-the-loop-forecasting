"""Tests for the paper-figure export (src/ailf/figures.py).

Builds figures from synthetic run-artifact files (forecast_comparison.csv + metrics.json) and
asserts a valid vector file is produced — no agent run, no network.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from ailf import figures


@pytest.fixture
def run_dir(tmp_path):
    """A minimal run directory mirroring what run_scenario writes."""
    n = 400
    dates = pd.date_range("2021-01-01", periods=n, freq="D")
    fit_end, train_end = 280, 340  # train [0,280), val [280,340), test [340,400)
    rows = []
    for i, d in enumerate(dates):
        region = "train" if i < fit_end else ("val" if i < train_end else "test")
        is_fc = i >= train_end
        rows.append({
            "ds": d.strftime("%Y-%m-%d"),
            "y_actual": 100.0 + 0.05 * i + (i % 7),
            "region": region,
            "yhat_full_history": (100.0 + 0.05 * i) if is_fc else np.nan,
            "yhat_naive": (99.0 + 0.05 * i) if is_fc else np.nan,
            "yhat_agent": (100.5 + 0.05 * i) if is_fc else np.nan,
        })
    pd.DataFrame(rows).to_csv(tmp_path / "forecast_comparison.csv", index=False)
    (tmp_path / "metrics.json").write_text(json.dumps({
        "scenario_id": "synthetic_demo",
        "horizon": 60,
        "methods": {
            "full_history_prophet": {"mae": 2.10},
            "naive_workflow": {"mae": 2.40},
            "agent": {"mae": 1.80, "tool": "full_history_step_regressor"},
        },
        "winner": "agent",
    }))
    return tmp_path


def test_load_run_artifacts(run_dir):
    frame, metrics = figures.load_run_artifacts(run_dir)
    assert set(frame["region"]) == {"train", "val", "test"}
    assert metrics["winner"] == "agent"


@pytest.mark.parametrize("width", ["single", "double"])
def test_renders_pdf(run_dir, tmp_path, width):
    out = tmp_path / f"fig_{width}.pdf"
    path = figures.render_forecast_comparison_paper(run_dir, out, width=width)
    assert path.exists()
    head = path.read_bytes()[:5]
    assert head == b"%PDF-", "output is not a valid PDF"


def test_renders_svg_vector(run_dir, tmp_path):
    out = tmp_path / "fig.svg"
    figures.render_forecast_comparison_paper(run_dir, out, width="double")
    text = out.read_text()
    assert "<svg" in text  # genuine vector output


def test_missing_artifacts_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        figures.render_forecast_comparison_paper(tmp_path, tmp_path / "x.pdf")


def test_changepoint_markers_accepted(run_dir, tmp_path):
    out = tmp_path / "fig_cp.pdf"
    figures.render_forecast_comparison_paper(
        run_dir, out, changepoints=[{"ds": "2021-06-15", "trend_delta": 1.2}]
    )
    assert out.exists()
