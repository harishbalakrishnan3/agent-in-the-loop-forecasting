"""Export changepoint POC scenario fixtures as CSV + metadata.

This keeps the spec-kit implementation decoupled from synthetic generation while preserving
the exact scenarios used during exploration.

Run:
    uv run python pocs/changepoint/export_scenario_csvs.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from changepoint_agent_poc import (
    SEASONAL_PERIOD,
    VALIDATION_HORIZON,
    make_gradual_drift_scenario,
    make_level_shift_scenario,
    make_many_temporary_events_scenario,
    make_prophet_hyperparameter_scenario,
    make_temporary_event_scenario,
)


DATA_DIR = Path("pocs/changepoint/data")
CSV_DIR = DATA_DIR / "csv"
METADATA_PATH = DATA_DIR / "scenario_metadata.json"


EXPECTED_INTERVENTIONS = {
    "level_shift_loses_seasonality": "full_history_step_regressor",
    "gradual_drift_loses_seasonality": "full_history_ramp_regressor",
    "temporary_event_not_regime_change": "full_history_clean_event",
    "many_temporary_events_long_history": "full_history_clean_event",
    "prophet_prior_tuning_recurring_event": "full_history_prophet_tuned_holidays",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scenario_metadata(scenario: Any, csv_path: Path) -> dict[str, Any]:
    frame = scenario.frame
    train_end = int(scenario.train_end)
    test_horizon = int(scenario.test_horizon)
    test_end = train_end + test_horizon
    return {
        "scenario_id": scenario.name,
        "title": scenario.title,
        "csv_path": str(csv_path),
        "schema": {
            "date_column": "ds",
            "target_column": "y",
            "frequency": "D",
        },
        "row_count": int(len(frame)),
        "date_range": {
            "start": str(frame["ds"].iloc[0].date()),
            "end": str(frame["ds"].iloc[-1].date()),
        },
        "train_end": train_end,
        "test_horizon": test_horizon,
        "validation_horizon": VALIDATION_HORIZON,
        "n_changepoints_to_detect": int(scenario.n_bkps),
        "seasonal_period": SEASONAL_PERIOD,
        "split_dates": {
            "train_start": str(frame["ds"].iloc[0].date()),
            "train_end_inclusive": str(frame["ds"].iloc[train_end - 1].date()),
            "test_start": str(frame["ds"].iloc[train_end].date()),
            "test_end_inclusive": str(frame["ds"].iloc[test_end - 1].date()),
        },
        "csv_sha256": sha256_file(csv_path),
        "agent_exposure_policy": {
            "agent_may_see_columns": ["ds", "y"],
            "agent_may_see_rows": f"0:{train_end}",
            "agent_must_not_see_audit_only": True,
            "agent_must_not_see_test_targets": True,
        },
        "audit_only": {
            "note": scenario.note,
            "true_injected_boundaries": list(map(int, scenario.true_changepoints)),
            "expected_intervention_family": EXPECTED_INTERVENTIONS[scenario.name],
        },
    }


def main() -> None:
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = [
        make_level_shift_scenario(),
        make_gradual_drift_scenario(),
        make_temporary_event_scenario(),
        make_many_temporary_events_scenario(),
        make_prophet_hyperparameter_scenario(),
    ]

    metadata = {
        "schema_version": "1.0",
        "description": (
            "CSV fixtures for the agent-in-the-loop changepoint forecasting POC. "
            "Audit-only fields must never be passed to the agent."
        ),
        "scenarios": [],
    }

    for scenario in scenarios:
        csv_path = CSV_DIR / f"{scenario.name}.csv"
        scenario.frame.to_csv(csv_path, index=False, date_format="%Y-%m-%d")
        metadata["scenarios"].append(scenario_metadata(scenario, csv_path))

    METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Wrote {len(scenarios)} scenario CSVs under {CSV_DIR}")
    print(f"Wrote metadata to {METADATA_PATH}")


if __name__ == "__main__":
    main()
