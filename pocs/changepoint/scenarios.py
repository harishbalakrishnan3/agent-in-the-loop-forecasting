"""Scenario + split loading from committed CSV fixtures (T006).

Reads ``data/scenario_metadata.json`` and the per-scenario ``ds,y`` CSVs. ``audit_only`` is
kept in a separate struct that NEVER enters agent-facing data (FR-003). Splits are validated
with clear errors (edge cases). The runtime never generates synthetic data (FR-001/004).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from pocs.changepoint.config import DATA_DIR, REPO_ROOT

METADATA_PATH = DATA_DIR / "scenario_metadata.json"

REQUIRED_SCENARIO_IDS = {
    "level_shift_loses_seasonality",
    "gradual_drift_loses_seasonality",
    "temporary_event_not_regime_change",
    "many_temporary_events_long_history",
    "prophet_prior_tuning_recurring_event",
}


class ScenarioError(RuntimeError):
    """Raised on missing fixtures or invalid split configuration."""


@dataclass(frozen=True)
class SeriesSplit:
    """Index partitions over the full series. Test indices are used only at final evaluation."""

    ds: pd.Series  # full timestamp index (datetime64)
    y: pd.Series  # full values (float)
    train_end: int
    validation_horizon: int
    test_horizon: int

    @property
    def fit_end(self) -> int:
        """End (exclusive) of the inner-fit region used when scoring on the validation holdout."""
        return self.train_end - self.validation_horizon

    @property
    def train_df(self) -> pd.DataFrame:
        """Full training region [0, train_end) — the only data the agent may see."""
        return pd.DataFrame({"ds": self.ds.iloc[: self.train_end], "y": self.y.iloc[: self.train_end]})

    @property
    def fit_df(self) -> pd.DataFrame:
        """Inner-fit region [0, fit_end) for validation scoring."""
        return pd.DataFrame({"ds": self.ds.iloc[: self.fit_end], "y": self.y.iloc[: self.fit_end]})

    @property
    def val_df(self) -> pd.DataFrame:
        """Validation holdout [fit_end, train_end) — last validation_horizon rows of training."""
        return pd.DataFrame(
            {"ds": self.ds.iloc[self.fit_end : self.train_end], "y": self.y.iloc[self.fit_end : self.train_end]}
        )

    @property
    def test_df(self) -> pd.DataFrame:
        """Hidden test [train_end, train_end + test_horizon) — read only at final evaluation."""
        end = self.train_end + self.test_horizon
        return pd.DataFrame({"ds": self.ds.iloc[self.train_end : end], "y": self.y.iloc[self.train_end : end]})

    @property
    def forecast_origin(self) -> pd.Timestamp:
        return pd.Timestamp(self.ds.iloc[self.train_end - 1])


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    title: str
    split: SeriesSplit
    n_changepoints_to_detect: int
    seasonal_period: int
    # Kept separate and NEVER passed to any agent node:
    audit_only: dict[str, Any] = field(default_factory=dict, repr=False)


def _load_metadata() -> dict[str, Any]:
    if not METADATA_PATH.exists():
        raise ScenarioError(f"Scenario metadata not found at {METADATA_PATH}")
    return json.loads(METADATA_PATH.read_text())


def _build_split(frame: pd.DataFrame, meta: dict[str, Any]) -> SeriesSplit:
    train_end = int(meta["train_end"])
    val_h = int(meta["validation_horizon"])
    test_h = int(meta["test_horizon"])
    n = len(frame)

    if not (train_end > val_h > 0):
        raise ScenarioError(
            f"Invalid split for {meta['scenario_id']}: require train_end>validation_horizon>0, "
            f"got train_end={train_end}, validation_horizon={val_h}"
        )
    if train_end + test_h > n:
        raise ScenarioError(
            f"Invalid split for {meta['scenario_id']}: train_end+test_horizon={train_end + test_h} "
            f"exceeds available rows={n}"
        )

    return SeriesSplit(
        ds=frame["ds"].reset_index(drop=True),
        y=frame["y"].astype(float).reset_index(drop=True),
        train_end=train_end,
        validation_horizon=val_h,
        test_horizon=test_h,
    )


def _scenario_from_meta(meta: dict[str, Any]) -> Scenario:
    csv_path = REPO_ROOT / meta["csv_path"]
    if not csv_path.exists():
        raise ScenarioError(f"CSV fixture not found for {meta['scenario_id']}: {csv_path}")
    frame = pd.read_csv(csv_path, parse_dates=["ds"])
    if list(frame.columns[:2]) != ["ds", "y"]:
        raise ScenarioError(f"{csv_path} must have columns ds,y; got {list(frame.columns)}")

    return Scenario(
        scenario_id=meta["scenario_id"],
        title=meta.get("title", meta["scenario_id"]),
        split=_build_split(frame, meta),
        n_changepoints_to_detect=int(meta["n_changepoints_to_detect"]),
        seasonal_period=int(meta.get("seasonal_period", 365)),
        audit_only=dict(meta.get("audit_only", {})),
    )


def load_all_scenarios() -> list[Scenario]:
    """Load all scenarios; assert the five required ids are present (FR-005)."""
    metadata = _load_metadata()
    scenarios = [_scenario_from_meta(m) for m in metadata["scenarios"]]
    present = {s.scenario_id for s in scenarios}
    missing = REQUIRED_SCENARIO_IDS - present
    if missing:
        raise ScenarioError(f"Missing required scenarios in metadata: {sorted(missing)}")
    return scenarios


def load_scenario(scenario_id: str) -> Scenario:
    for scenario in load_all_scenarios():
        if scenario.scenario_id == scenario_id:
            return scenario
    raise ScenarioError(f"Unknown scenario_id: {scenario_id}")
