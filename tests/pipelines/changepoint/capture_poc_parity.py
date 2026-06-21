"""T007 — Capture the POC parity oracle from the UN-PROMOTED POC.

Runs the deterministic pieces of ``pocs/changepoint`` (detector + the two baselines) over all
five committed scenarios with the fixed seed and records the reference values the promoted core
path must reproduce (SC-001). This is the trustworthy oracle: it is captured BEFORE any module is
promoted, then the promoted path is asserted against it (see ``tests/core/parity``).

Run with:
    uv run python -m tests.pipelines.changepoint.capture_poc_parity

Writes ``tests/pipelines/changepoint/fixtures/poc_parity_reference.json`` (committed).
Deterministic: seeds RNG before any Prophet fit, matching ``pocs/changepoint/run_poc.py``.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np

from pocs.changepoint.baselines import (
    fit_full_history_test_forecast,
    fit_naive_test_forecast,
    full_history_prophet,
    naive_workflow,
)
from pocs.changepoint.config import SEED
from pocs.changepoint.detector import detect_changepoints
from pocs.changepoint.scenarios import load_all_scenarios

_REFERENCE_PATH = Path(__file__).resolve().parent / "fixtures" / "poc_parity_reference.json"


def capture() -> dict:
    """Capture deterministic reference values for every committed scenario."""
    scenarios = {}
    for scenario in load_all_scenarios():
        # Seed FRESH before each scenario so the result is independent of scenario ordering and of
        # RNG state left by a prior scenario's Prophet fits (makes the oracle position-independent).
        random.seed(SEED)
        np.random.seed(SEED)
        split = scenario.split
        cps = detect_changepoints(
            split.train_df, n_changepoints_to_detect=scenario.n_changepoints_to_detect
        )
        detected = [
            {"index": c.index, "trend_delta": float(c.trend_delta)} for c in cps.changepoints
        ]

        full = full_history_prophet(split)
        naive = naive_workflow(split, cps)

        # Hidden-test metrics for the two deterministic baselines (the agent is non-deterministic
        # and is NOT part of the parity oracle).
        _, full_test = fit_full_history_test_forecast(split)
        _, naive_test = fit_naive_test_forecast(split, naive.selected_window_start)

        scenarios[scenario.scenario_id] = {
            "n_changepoints_to_detect": scenario.n_changepoints_to_detect,
            "seasonal_period": scenario.seasonal_period,
            "train_end": split.train_end,
            "fit_end": split.fit_end,
            "validation_horizon": split.validation_horizon,
            "test_horizon": split.test_horizon,
            "detected_changepoints": detected,
            "full_history_prophet_val_metrics": full.val_metrics,
            "naive_candidates": [c.summary_dict() for c in naive.candidates],
            "naive_selected_window_start": naive.selected_window_start,
            "full_history_prophet_test_metrics": full_test,
            "naive_workflow_test_metrics": naive_test,
        }

    return {"seed": SEED, "scenarios": scenarios}


def main() -> None:
    reference = capture()
    _REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REFERENCE_PATH.write_text(json.dumps(reference, indent=2, sort_keys=True))
    print(f"Wrote parity oracle: {_REFERENCE_PATH}")
    for sid, ref in reference["scenarios"].items():
        print(
            f"  {sid}: cps={[c['index'] for c in ref['detected_changepoints']]} "
            f"naive_win={ref['naive_selected_window_start']} "
            f"naive_test_mae={ref['naive_workflow_test_metrics']['mae']:.3f}"
        )


if __name__ == "__main__":
    main()
