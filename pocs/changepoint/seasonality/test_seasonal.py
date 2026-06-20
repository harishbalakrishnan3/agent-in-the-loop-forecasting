"""POC proof tests: seasonality amplitude shift detection.

No __init__.py in this directory — pytest uses prepend mode, which adds
the directory to sys.path so same-dir imports work. Run with:

    uv run pytest pocs/changepoint/seasonality/

(NOT bare `uv run pytest` — pyproject.toml testpaths = ["tests"] so the
 POC dir is excluded from the default scan.)

Requires: ruptures  (uv add ruptures)
Env must be working: uv run python -c "import darts, ruptures" must succeed.

Design (plan.md C4)
-------------------
Tests sweep pen ∈ PENS rather than fixing pen=3.0, because the POC's job
is to *discover* a working penalty, not assert a known-good one. Each test
passes if at least one pen value in the sweep satisfies the goal.
test_working_pen_exists() is the combined proof: at least one pen satisfies
BOTH planted-found AND control-clean simultaneously.

Tolerance (plan.md C3)
-----------------------
±PERIOD (30 points) rather than ±5. PELT localises the break to the start
of the segment where the distributional shift becomes statistically
significant — this can lag the true break by up to a half-cycle.
If the C1 rolling-std fallback is used, the lag can be up to a full period;
the ±PERIOD window still covers it, but a "late" detection is a correct one.
"""

from __future__ import annotations

import sys
import os

# Ensure same-dir imports work regardless of how pytest is invoked.
sys.path.insert(0, os.path.dirname(__file__))

import pytest

from datasets_seasonal import generate_seasonal_shift, generate_control
from tools_seasonal import detect_seasonality_change

# ---------------------------------------------------------------------------
# Constants (match plan.md)
# ---------------------------------------------------------------------------

PERIOD = 30
PENS = [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _sweep(series, pens=PENS):
    """Run detect_seasonality_change for each penalty; return {pen: [breaks]}."""
    return {p: detect_seasonality_change(series, pen=p, min_size=PERIOD) for p in pens}


# ---------------------------------------------------------------------------
# Core proof tests
# ---------------------------------------------------------------------------

def test_planted_change_found():
    """Goal 2 (partial): at least one pen finds the planted break within ±PERIOD."""
    series, true_break = generate_seasonal_shift(seed=42)
    results = _sweep(series)

    passing_pens = [
        p for p, det in results.items()
        if len(det) == 1 and abs(det[0] - true_break) <= PERIOD
    ]

    assert passing_pens, (
        f"No pen in {PENS} found exactly one break within ±{PERIOD} of "
        f"true_break={true_break}.\n"
        f"Results: {results}\n"
        f"Hint (plan.md C1): if raw-signal fails, try the rolling-std fallback "
        f"in tools_seasonal.py."
    )


def test_no_false_positives():
    """Goal 3 (partial): at least one pen returns no breaks on the control series."""
    control = generate_control(seed=99)
    results = _sweep(control)

    clean_pens = [p for p, det in results.items() if det == []]

    assert clean_pens, (
        f"No pen in {PENS} gave a clean control series.\n"
        f"Results: {results}\n"
        f"Hint: increase min_size or reduce seasonality_amplitude noise."
    )


def test_working_pen_exists():
    """Combined proof (Goals 2 + 3): at least one pen satisfies BOTH conditions.

    This is the primary POC proof test. The working pen range should be
    noted as a comment in tools_seasonal.py (POC TUNING RESULTS block).
    """
    series, true_break = generate_seasonal_shift(seed=42)
    control = generate_control(seed=99)

    working = []
    sweep_report = {}

    for p in PENS:
        det_shift = detect_seasonality_change(series, pen=p, min_size=PERIOD)
        det_ctrl  = detect_seasonality_change(control, pen=p, min_size=PERIOD)

        planted_ok = len(det_shift) == 1 and abs(det_shift[0] - true_break) <= PERIOD
        ctrl_clean = det_ctrl == []

        sweep_report[p] = {
            "detected_in_shift": det_shift,
            "planted_ok": planted_ok,
            "ctrl_clean": ctrl_clean,
        }

        if planted_ok and ctrl_clean:
            working.append(p)

    assert working, (
        f"No single pen value in {PENS} satisfies BOTH goals simultaneously.\n"
        f"Sweep report:\n"
        + "\n".join(
            f"  pen={p}: planted_ok={v['planted_ok']}, ctrl_clean={v['ctrl_clean']}, "
            f"detected={v['detected_in_shift']}"
            for p, v in sweep_report.items()
        )
        + f"\n\ntrue_break={true_break}. "
        f"If planted_ok is always False, try the rolling-std fallback (plan.md C1)."
    )

    # Print working range for the developer to pin in tools_seasonal.py
    print(f"\n[POC RESULT] Working pen range: {working} — pin midpoint as default.")


# ---------------------------------------------------------------------------
# Optional / additional tests (run these after the core tests pass)
# ---------------------------------------------------------------------------

def test_early_break():
    """Break at length // 4 — detection should not be biased to the center."""
    series, true_break = generate_seasonal_shift(seed=7, break_index=90)
    assert true_break == 90

    results = _sweep(series)
    passing_pens = [
        p for p, det in results.items()
        if len(det) == 1 and abs(det[0] - true_break) <= PERIOD
    ]

    assert passing_pens, (
        f"No pen found the early break at {true_break}.\nResults: {results}"
    )


def test_late_break():
    """Break at 3 * length // 4 — mirror of test_early_break."""
    series, true_break = generate_seasonal_shift(seed=7, break_index=273)
    assert true_break == 273

    results = _sweep(series)
    passing_pens = [
        p for p, det in results.items()
        if len(det) == 1 and abs(det[0] - true_break) <= PERIOD
    ]

    assert passing_pens, (
        f"No pen found the late break at {true_break}.\nResults: {results}"
    )


def test_amplitude_decrease():
    """magnitude=-0.5 (halving) — confirm a decrease is also detectable."""
    series, true_break = generate_seasonal_shift(seed=7, magnitude=-0.5)

    results = _sweep(series)
    passing_pens = [
        p for p, det in results.items()
        if len(det) == 1 and abs(det[0] - true_break) <= PERIOD
    ]

    assert passing_pens, (
        f"No pen detected the amplitude decrease (magnitude=-0.5) at {true_break}.\n"
        f"Results: {results}\n"
        f"A halving produces a smaller variance change than a doubling — "
        f"may need a lower pen or the rolling-std fallback."
    )


# ---------------------------------------------------------------------------
# Validation tests (datasets_seasonal.py edge-case rejection)
# ---------------------------------------------------------------------------

def test_zero_magnitude_rejected():
    with pytest.raises(ValueError, match="non-zero"):
        generate_seasonal_shift(magnitude=0)


def test_break_too_early_rejected():
    """break_index < seasonality_period should be rejected."""
    with pytest.raises(ValueError, match="pre-break"):
        generate_seasonal_shift(break_index=5, seasonality_period=30)


def test_break_too_late_rejected():
    """break_index > length - seasonality_period should be rejected."""
    with pytest.raises(ValueError, match="room to develop"):
        generate_seasonal_shift(length=365, break_index=340, seasonality_period=30)
