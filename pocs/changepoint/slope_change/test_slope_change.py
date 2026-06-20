"""Tests for the slope-change POC.

Generator tests verify the planted ground truth (slope changes at the right
places, continuous trend, reproducibility, control flatness, metadata schema,
seasonality, input validation). The Prophet-evaluation smoke tests confirm the
naive baseline succeeds on a simple dataset and breaks down on a complex one.

Run: uv run pytest pocs/changepoint/slope_change/ -v
"""

from __future__ import annotations

import numpy as np
import pytest
from darts import TimeSeries

from pocs.changepoint.slope_change.datasets import (
    DATASET_CONFIGS,
    generate_all_datasets,
    generate_slope_change_series,
)

REQUIRED_METADATA_FIELDS = {
    "dataset_id",
    "length",
    "changepoint_indices",
    "changepoint_dates",
    "slope_deltas",
    "slopes_per_segment",
    "type",
    "noise_std",
    "base_level",
    "initial_slope",
    "seasonality_period",
    "seasonality_amplitude",
    "seed",
}


def _segment_slope(values: np.ndarray, start: int, end: int) -> float:
    """Least-squares slope of values[start:end] vs. index."""
    idx = np.arange(start, end)
    seg = values[start:end]
    return float(np.polyfit(idx, seg, 1)[0])


# ─────────────────────────────────────────────────────────────────────────────
# T008 — output type / length / reproducibility
# ─────────────────────────────────────────────────────────────────────────────

def test_output_type_and_length():
    ts, meta = generate_slope_change_series(
        length=300, changepoint_indices=[150], slope_deltas=[0.5], dataset_id="t"
    )
    assert isinstance(ts, TimeSeries)
    assert len(ts) == 300
    assert meta["length"] == 300


def test_reproducibility():
    cfg = dict(length=300, changepoint_indices=[150], slope_deltas=[0.5], seed=7)
    a, _ = generate_slope_change_series(**cfg)
    b, _ = generate_slope_change_series(**cfg)
    np.testing.assert_array_equal(a.values(), b.values())

    c, _ = generate_slope_change_series(**{**cfg, "seed": 8})
    assert not np.array_equal(a.values(), c.values())


# ─────────────────────────────────────────────────────────────────────────────
# T009 — slope changes at planted indices; trend is continuous (no level jump)
# ─────────────────────────────────────────────────────────────────────────────

def test_slope_changes_at_indices():
    # Noise-free so segment slopes are exact.
    ts, meta = generate_slope_change_series(
        length=400,
        initial_slope=0.1,
        changepoint_indices=[200],
        slope_deltas=[0.5],
        noise_std=0.0,
    )
    values = ts.values().flatten()
    slope_before = _segment_slope(values, 10, 190)
    slope_after = _segment_slope(values, 210, 390)
    # Slope after - before ≈ slope_delta.
    assert slope_after - slope_before == pytest.approx(0.5, abs=1e-6)
    assert meta["slopes_per_segment"] == pytest.approx([0.1, 0.6])


def test_trend_is_continuous():
    # No level jump at the changepoint: the step across the cp is ~the local
    # slope, not a discontinuous jump.
    ts, _ = generate_slope_change_series(
        length=400,
        initial_slope=0.1,
        changepoint_indices=[200],
        slope_deltas=[0.5],
        noise_std=0.0,
    )
    values = ts.values().flatten()
    step_at_cp = abs(values[200] - values[199])
    # The new per-step slope is 0.6; a level shift would jump by a large
    # magnitude. Assert the step is on the order of the slope (< 1.0).
    assert step_at_cp < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# T010 — control flatness, metadata schema, seasonality presence
# ─────────────────────────────────────────────────────────────────────────────

def test_control_constant_slope():
    ts, meta = generate_all_datasets()["S9_no_changepoint"]
    assert meta["changepoint_indices"] == []
    assert meta["slope_deltas"] == []
    assert len(meta["slopes_per_segment"]) == 1  # single constant-slope segment
    # Noise-free re-gen to confirm a single constant slope across the series.
    cfg = {**DATASET_CONFIGS["S9_no_changepoint"], "noise_std": 0.0}
    clean, _ = generate_slope_change_series(**cfg)
    v = clean.values().flatten()
    assert _segment_slope(v, 10, 240) == pytest.approx(_segment_slope(v, 250, 490), abs=1e-6)


def test_metadata_schema():
    for name, (ts, meta) in generate_all_datasets().items():
        assert set(meta.keys()) == REQUIRED_METADATA_FIELDS, name
        assert meta["type"] == "slope_change"
        assert len(meta["changepoint_indices"]) == len(meta["slope_deltas"])
        # changepoint_dates align with indices.
        dates = ts.time_index
        for idx, d in zip(meta["changepoint_indices"], meta["changepoint_dates"]):
            assert str(dates[idx]) == d


def test_seasonality_component_present():
    # FR-003: seasonal term materially changes the series vs. amplitude=0.
    base_cfg = dict(
        length=400,
        initial_slope=0.1,
        changepoint_indices=[200],
        slope_deltas=[0.5],
        noise_std=0.0,
        seasonality_period=7,
        seed=1,
    )
    seasonal, _ = generate_slope_change_series(**base_cfg, seasonality_amplitude=15.0)
    flat, _ = generate_slope_change_series(**base_cfg, seasonality_amplitude=0.0)
    diff = np.abs(seasonal.values().flatten() - flat.values().flatten())
    assert diff.max() > 5.0  # seasonal swing is clearly present

    # And S6 in the catalog actually configures seasonality.
    s6 = DATASET_CONFIGS["S6_with_seasonality"]
    assert s6["seasonality_period"] is not None
    assert s6["seasonality_amplitude"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# T005 — input validation (incl. near-boundary rejection)
# ─────────────────────────────────────────────────────────────────────────────

def test_validation_rejects_invalid_config():
    # (a) length mismatch
    with pytest.raises(ValueError):
        generate_slope_change_series(
            length=400, changepoint_indices=[200], slope_deltas=[0.5, 0.5]
        )
    # (b) near-boundary index (inside first/last min_segment points)
    with pytest.raises(ValueError):
        generate_slope_change_series(
            length=400, changepoint_indices=[5], slope_deltas=[0.5], min_segment=20
        )
    with pytest.raises(ValueError):
        generate_slope_change_series(
            length=400, changepoint_indices=[395], slope_deltas=[0.5], min_segment=20
        )
    # (c) non-increasing indices
    with pytest.raises(ValueError):
        generate_slope_change_series(
            length=400, changepoint_indices=[200, 150], slope_deltas=[0.5, 0.5]
        )


# ─────────────────────────────────────────────────────────────────────────────
# T022 / T023 — naive Prophet evaluation smoke (simple passes, complex fails)
# ─────────────────────────────────────────────────────────────────────────────

# Prophet fitting is slow; keep these as a small, focused smoke set.
from pocs.changepoint.slope_change.prophet_eval import (  # noqa: E402
    FAIL_MAPE,
    PASS_MAPE,
    SlopeChangeEvalResult,
    evaluate_dataset,
)


def _result_fully_populated(r: SlopeChangeEvalResult) -> bool:
    return all(
        getattr(r, f) is not None
        for f in (
            "dataset_id", "train_end_index", "horizon", "n_true_changepoints",
            "detected_changepoint_indices", "detected_changepoint_dates",
            "matched_true_indices", "detection_precision", "detection_recall",
            "mae", "rmse", "mape", "classification",
        )
    )


def test_eval_result_schema_populated():
    ts, meta = generate_all_datasets()["S1_single_gentle"]
    r = evaluate_dataset(ts, meta)
    assert _result_fully_populated(r)
    assert r.horizon > 0
    assert r.classification in {"pass", "borderline", "fail"}


def test_simple_dataset_passes():
    # A gentle single slope change well inside training should be easy.
    ts, meta = generate_all_datasets()["S2_single_sharp"]
    r = evaluate_dataset(ts, meta)
    assert r.mape < FAIL_MAPE  # comfortably below the failure band
    assert r.classification == "pass"


def test_complex_dataset_fails():
    # A strong late slope change Prophet's default changepoints can't reach.
    ts, meta = generate_all_datasets()["S10_frequent_changes"]
    r = evaluate_dataset(ts, meta)
    assert r.mape > PASS_MAPE  # not a clean pass
    assert r.classification == "fail"
