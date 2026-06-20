"""T026 — detector tests.

Two parts:
1. Structural invariants on the committed fixtures (count honored, in-range, date-sorted).
2. KNOWN-injected-ground-truth precision/recall on a CLEAN single-changepoint synthetic series
   (Constitution Principle II). The adversarial committed fixtures deliberately place trend
   changepoints AWAY from the injected structural boundaries — that misalignment is the failure
   mode the agent exists to address — so they are NOT a valid recall target for the deterministic
   detector (research Decision 18, critic open-question #11). A clean single-shift series is.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ailf.pipelines.changepoint.detector import detect_changepoints
from ailf.pipelines.changepoint.scenarios import load_all_scenarios

_TOLERANCE = 15  # rows; matches diagnostics _local_boundary_jumps width (14)


@pytest.fixture(scope="module")
def scenarios():
    return load_all_scenarios()


def test_detector_returns_requested_count(scenarios):
    for sc in scenarios:
        cps = detect_changepoints(sc.split.train_df, n_changepoints_to_detect=sc.n_changepoints_to_detect)
        assert len(cps.changepoints) == sc.n_changepoints_to_detect, sc.scenario_id
        idx = cps.indices
        assert idx == sorted(idx)
        assert all(0 <= i < sc.split.train_end for i in idx)


def _clean_single_shift_series(n: int = 730, shift_at: int = 365, magnitude: float = 40.0):
    """A clean series with ONE sharp permanent level shift at ``shift_at`` (known ground truth)."""
    rng = np.random.default_rng(1729)
    t = np.arange(n)
    seasonal = 5.0 * np.sin(2 * np.pi * t / 365.0)
    level = np.where(t >= shift_at, magnitude, 0.0)
    y = 50.0 + seasonal + level + rng.normal(0, 1.0, n)
    ds = pd.date_range("2019-01-01", periods=n, freq="D")
    return pd.DataFrame({"ds": ds, "y": y})


def test_recall_on_clean_single_changepoint():
    shift_at = 365
    df = _clean_single_shift_series(shift_at=shift_at)
    cps = detect_changepoints(df, n_changepoints_to_detect=3)
    # Recall: at least one detected changepoint within tolerance of the true shift.
    assert any(abs(c - shift_at) <= _TOLERANCE for c in cps.indices), cps.indices


def test_low_false_positive_on_flat_noise():
    # A series with NO structural change: detected changepoints should carry tiny trend deltas.
    rng = np.random.default_rng(7)
    n = 730
    df = pd.DataFrame(
        {"ds": pd.date_range("2019-01-01", periods=n, freq="D"), "y": 50.0 + rng.normal(0, 1.0, n)}
    )
    cps = detect_changepoints(df, n_changepoints_to_detect=3)
    # No strong trend kink should be found on pure noise (all |delta| small).
    assert all(abs(c.trend_delta) < 1.0 for c in cps.changepoints), [
        (c.index, c.trend_delta) for c in cps.changepoints
    ]
