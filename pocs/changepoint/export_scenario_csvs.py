"""OPTIONAL fixture generator for the changepoint POC (NOT on the runtime path — FR-004).

Reconstructs the synthetic scenarios from the original rough exploration so the committed CSVs
are reproducible. Because each series uses a seeded ``np.random.default_rng`` and all
events/shifts sit at fixed indices, generating a LONGER series yields byte-identical leading rows
to a shorter one — so we can extend the data while preserving the original [0:900)/[0:1610) values.

The split layout moves the forecast origin forward by one test horizon so the VALIDATION window
coincides with the original rough-script TEST window:
  short scenarios: len 1000, train_end 880, validation_horizon 120, test_horizon 120
  long scenarios:  len 1730, train_end 1610, validation_horizon 120, test_horizon 120

Usage:
    uv run python -m pocs.changepoint.export_scenario_csvs --verify   # check repro at old lengths
    uv run python -m pocs.changepoint.export_scenario_csvs            # write extended CSVs + metadata
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from pocs.changepoint.config import DATA_DIR, REPO_ROOT

CSV_DIR = DATA_DIR / "csv"
METADATA_PATH = DATA_DIR / "scenario_metadata.json"

# New split layout (validation == original rough test window).
SHORT_LEN, SHORT_TRAIN_END = 1000, 880
LONG_LEN, LONG_TRAIN_END = 1730, 1610
VALIDATION_HORIZON = 120
TEST_HORIZON = 120
SEASONAL_PERIOD = 365

# Original committed lengths/train_ends (for --verify reproduction).
OLD_SHORT_LEN, OLD_LONG_LEN = 900, 1610


def _base_signal(length: int, seed: int) -> pd.DataFrame:
    """Trend + annual + weekly seasonality + noise (identical formula to the rough script)."""
    rng = np.random.default_rng(seed)
    t = np.arange(length)
    ds = pd.date_range("2019-01-01", periods=length, freq="D")
    annual = 22.0 * np.sin(2 * np.pi * t / 365.0) + 7.0 * np.cos(2 * np.pi * t / 365.0)
    weekly = 2.5 * np.sin(2 * np.pi * t / 7.0)
    trend = 0.018 * t
    noise = rng.normal(0.0, 1.7, length)
    y = 100.0 + trend + annual + weekly + noise
    return pd.DataFrame({"ds": ds, "y": y})


def make_level_shift(length: int) -> pd.DataFrame:
    df = _base_signal(length, seed=7)
    for cp, lift in [(610, 32.0), (700, 28.0)]:
        df.loc[df.index >= cp, "y"] += lift
    return df


def make_gradual_drift(length: int) -> pd.DataFrame:
    df = _base_signal(length, seed=29)
    start, end, lift = 540, 720, 58.0
    t = np.arange(len(df))
    ramp = np.clip((t - start) / (end - start), 0.0, 1.0)
    df["y"] += lift * ramp
    return df


def make_temporary_event(length: int) -> pd.DataFrame:
    df = _base_signal(length, seed=13)
    for start, end, lift in [(250, 268, 32.0), (420, 444, 42.0), (575, 615, 58.0)]:
        df.loc[(df.index >= start) & (df.index < end), "y"] += lift
    return df


def make_many_temporary_events(length: int) -> pd.DataFrame:
    df = _base_signal(length, seed=47)
    for start, end, lift in [
        (92, 105, 30.0),
        (286, 317, 36.0),
        (548, 566, 28.0),
        (852, 901, 40.0),
        (1320, 1344, 34.0),
        (1441, 1482, 62.0),
    ]:
        df.loc[(df.index >= start) & (df.index < end), "y"] += lift
    return df


def make_prophet_recurring(length: int) -> pd.DataFrame:
    df = _base_signal(length, seed=71)
    t = np.arange(length)
    for cp, slope_delta in [(875, 0.055), (1250, -0.035)]:
        mask = df.index >= cp
        df.loc[mask, "y"] += slope_delta * (t[mask] - cp)
    # Recurring Feb 12 – Mar 5 event each year (faithful to the rough generator: 2019–2023).
    for year in [2019, 2020, 2021, 2022, 2023]:
        start = int((pd.Timestamp(year=year, month=2, day=12) - df["ds"].iloc[0]).days)
        end = int((pd.Timestamp(year=year, month=3, day=5) - df["ds"].iloc[0]).days)
        if 0 <= start < length:
            df.loc[(df.index >= start) & (df.index < min(end, length)), "y"] += 44.0
    return df


@dataclass
class ScenarioSpec:
    scenario_id: str
    title: str
    make: callable
    length: int
    train_end: int
    n_changepoints_to_detect: int
    note: str
    true_injected_boundaries: list[int]
    expected_intervention_family: str


SPECS = [
    ScenarioSpec(
        "level_shift_loses_seasonality",
        "Multiple permanent level shifts with short post-change seasonal history",
        make_level_shift, SHORT_LEN, SHORT_TRAIN_END, 2,
        "Two real structural level shifts occur in training, with the latest close to the "
        "forecast origin. Truncating to detected changepoint windows removes the annual seasonal history.",
        [610, 700], "full_history_step_regressor",
    ),
    ScenarioSpec(
        "gradual_drift_loses_seasonality",
        "Gradual drift over a long transition with short post-drift seasonal history",
        make_gradual_drift, SHORT_LEN, SHORT_TRAIN_END, 2,
        "A structural level transition unfolds gradually over many days. Treating the transition "
        "as one or two abrupt changepoints either discards seasonal history or uses the wrong "
        "intervention shape.",
        [540, 720], "full_history_ramp_regressor",
    ),
    ScenarioSpec(
        "temporary_event_not_regime_change",
        "Multiple temporary event/outlier blocks misread as changepoints",
        make_temporary_event, SHORT_LEN, SHORT_TRAIN_END, 2,
        "The series returns to the old regime after short event blocks. Treating the latest "
        "detected change as a new permanent regime discards useful history.",
        [250, 268, 420, 444, 575, 615], "full_history_clean_event",
    ),
    ScenarioSpec(
        "many_temporary_events_long_history",
        "Six temporary events over longer history misread as changepoints",
        make_many_temporary_events, LONG_LEN, LONG_TRAIN_END, 6,
        "Six irregular, non-calendar event blocks contaminate a longer history. Their start dates "
        "and widths intentionally differ. The latest event sits inside the validation tail, "
        "encouraging a changepoint-window workflow to believe the event continues into the "
        "forecast period even though the series reverts.",
        [92, 105, 286, 317, 548, 566, 852, 901, 1320, 1344, 1441, 1482], "full_history_clean_event",
    ),
    ScenarioSpec(
        "prophet_prior_tuning_recurring_event",
        "Recurring event plus trend kinks needs Prophet prior tuning",
        make_prophet_recurring, LONG_LEN, LONG_TRAIN_END, 6,
        "A sharp recurring calendar event and two trend kinks stress Prophet defaults. The "
        "intervention should preserve long history, encode the recurring event as holidays, and "
        "tune changepoint_prior_scale/holiday_prior_scale on historical folds.",
        [875, 1250], "full_history_prophet_tuned_holidays",
    ),
]


def _sha256(df: pd.DataFrame) -> str:
    csv_bytes = _csv_text(df).encode()
    return hashlib.sha256(csv_bytes).hexdigest()


def _csv_text(df: pd.DataFrame) -> str:
    out = df.copy()
    out["ds"] = out["ds"].dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False)


def _old_length(spec: ScenarioSpec) -> int:
    return OLD_SHORT_LEN if spec.length == SHORT_LEN else OLD_LONG_LEN


def verify() -> bool:
    """Regenerate at the ORIGINAL lengths and confirm sha256 matches the committed metadata."""
    meta = json.loads(METADATA_PATH.read_text())
    committed = {s["scenario_id"]: s.get("csv_sha256") for s in meta["scenarios"]}
    ok = True
    for spec in SPECS:
        df = spec.make(_old_length(spec))
        got = _sha256(df)
        want = committed.get(spec.scenario_id)
        match = got == want
        ok = ok and match
        print(f"{'OK ' if match else 'MISMATCH'} {spec.scenario_id}: got {got[:12]} want {str(want)[:12]}")
    return ok


def write_all() -> None:
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    scenarios_meta = []
    for spec in SPECS:
        df = spec.make(spec.length)
        csv_path = CSV_DIR / f"{spec.scenario_id}.csv"
        csv_path.write_text(_csv_text(df))
        test_start = spec.train_end
        test_end = spec.train_end + TEST_HORIZON
        scenarios_meta.append(
            {
                "scenario_id": spec.scenario_id,
                "title": spec.title,
                "csv_path": str(csv_path.relative_to(REPO_ROOT)),
                "schema": {"date_column": "ds", "target_column": "y", "frequency": "D"},
                "row_count": spec.length,
                "date_range": {
                    "start": str(df["ds"].iloc[0].date()),
                    "end": str(df["ds"].iloc[-1].date()),
                },
                "train_end": spec.train_end,
                "test_horizon": TEST_HORIZON,
                "validation_horizon": VALIDATION_HORIZON,
                "n_changepoints_to_detect": spec.n_changepoints_to_detect,
                "seasonal_period": SEASONAL_PERIOD,
                "split_dates": {
                    "train_start": str(df["ds"].iloc[0].date()),
                    "train_end_inclusive": str(df["ds"].iloc[spec.train_end - 1].date()),
                    "test_start": str(df["ds"].iloc[test_start].date()),
                    "test_end_inclusive": str(df["ds"].iloc[test_end - 1].date()),
                },
                "csv_sha256": _sha256(df),
                "agent_exposure_policy": {
                    "agent_may_see_columns": ["ds", "y"],
                    "agent_may_see_rows": f"0:{spec.train_end}",
                    "agent_must_not_see_audit_only": True,
                    "agent_must_not_see_test_targets": True,
                },
                "audit_only": {
                    "note": spec.note,
                    "true_injected_boundaries": spec.true_injected_boundaries,
                    "expected_intervention_family": spec.expected_intervention_family,
                },
            }
        )

    metadata = {
        "schema_version": "1.1",
        "description": (
            "CSV fixtures for the agent-in-the-loop changepoint forecasting POC. The forecast "
            "origin is placed so the validation window coincides with the original exploration's "
            "test window. Audit-only fields must never be passed to the agent."
        ),
        "scenarios": scenarios_meta,
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2))
    print(f"Wrote {len(SPECS)} CSVs to {CSV_DIR} and metadata to {METADATA_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate/verify changepoint POC fixtures.")
    parser.add_argument("--verify", action="store_true", help="Reproduce committed CSVs at old lengths (no writes)")
    args = parser.parse_args()
    if args.verify:
        print("OK" if verify() else "VERIFY FAILED")
    else:
        write_all()


if __name__ == "__main__":
    main()
