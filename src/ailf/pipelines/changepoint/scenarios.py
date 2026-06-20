"""Scenario loading + pandas SeriesSplit adapter built from a core ``ResolvedSplit``.

Promoted from ``pocs/changepoint/scenarios.py``. The ``SeriesSplit`` accessor (train/fit/val/test
frames + forecast origin) keeps the POC arithmetic so the promoted detector/baselines/interventions
work unchanged, but its index partitions now come from a core ``ResolvedSplit`` (split math lives in
``ailf.core.backtest.split``). ``audit_only`` is kept in a separate struct that NEVER enters any
agent-facing data (FR-003/FR-033); tests read it directly from metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ailf.core.backtest.split import ResolvedSplit
from ailf.pipelines.changepoint.datasets import (
    ScenarioError,
    golden_split_from_metadata,
    load_metadata,
    load_series,
)

REQUIRED_SCENARIO_IDS = {
    "level_shift_loses_seasonality",
    "gradual_drift_loses_seasonality",
    "temporary_event_not_regime_change",
    "many_temporary_events_long_history",
    "prophet_prior_tuning_recurring_event",
}


@dataclass(frozen=True)
class SeriesSplit:
    """Pandas accessor over a series given a core ``ResolvedSplit`` (POC-compatible API)."""

    ds: pd.Series
    y: pd.Series
    resolved: ResolvedSplit

    @property
    def train_end(self) -> int:
        return self.resolved.train_end

    @property
    def fit_end(self) -> int:
        return self.resolved.fit_end

    @property
    def validation_horizon(self) -> int:
        return self.resolved.val_rows

    @property
    def test_horizon(self) -> int:
        return self.resolved.test_rows

    @property
    def train_df(self) -> pd.DataFrame:
        """Full training region [0, train_end) — the only data the agent may see."""
        return pd.DataFrame({"ds": self.ds.iloc[: self.train_end], "y": self.y.iloc[: self.train_end]})

    @property
    def fit_df(self) -> pd.DataFrame:
        return pd.DataFrame({"ds": self.ds.iloc[: self.fit_end], "y": self.y.iloc[: self.fit_end]})

    @property
    def val_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"ds": self.ds.iloc[self.fit_end : self.train_end], "y": self.y.iloc[self.fit_end : self.train_end]}
        )

    @property
    def test_df(self) -> pd.DataFrame:
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
    # Kept separate and NEVER passed to any agent node (FR-003/FR-033):
    audit_only: dict[str, Any] = field(default_factory=dict, repr=False)


def _scenario_from_meta(meta: dict[str, Any], resolved: ResolvedSplit | None = None) -> Scenario:
    frame = load_series(meta["scenario_id"], meta["csv_path"])
    n = len(frame)
    split_resolved = resolved if resolved is not None else golden_split_from_metadata(meta, n)
    if split_resolved.test_end > n:
        raise ScenarioError(
            f"Split for {meta['scenario_id']} needs {split_resolved.test_end} rows but only {n} exist."
        )
    series_split = SeriesSplit(
        ds=frame["ds"].reset_index(drop=True),
        y=frame["y"].astype(float).reset_index(drop=True),
        resolved=split_resolved,
    )
    return Scenario(
        scenario_id=meta["scenario_id"],
        title=meta.get("title", meta["scenario_id"]),
        split=series_split,
        n_changepoints_to_detect=int(meta["n_changepoints_to_detect"]),
        seasonal_period=int(meta.get("seasonal_period", 365)),
        audit_only=dict(meta.get("audit_only", {})),
    )


def load_all_scenarios() -> list[Scenario]:
    metadata = load_metadata()
    scenarios = [_scenario_from_meta(m) for m in metadata["scenarios"]]
    present = {s.scenario_id for s in scenarios}
    missing = REQUIRED_SCENARIO_IDS - present
    if missing:
        raise ScenarioError(f"Missing required scenarios in metadata: {sorted(missing)}")
    return scenarios


def load_scenario(scenario_id: str, *, resolved: ResolvedSplit | None = None) -> Scenario:
    metadata = load_metadata()
    for meta in metadata["scenarios"]:
        if meta["scenario_id"] == scenario_id:
            return _scenario_from_meta(meta, resolved=resolved)
    raise ScenarioError(f"Unknown scenario_id: {scenario_id}")
