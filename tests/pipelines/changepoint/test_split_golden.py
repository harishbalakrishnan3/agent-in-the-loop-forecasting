"""T024 — golden-reproduction test: the promoted split derives the POC's exact indices.

Gates SC-001 before any other split work: for all five committed scenarios the SeriesSplit adapter
built from the core ResolvedSplit must yield train_end / fit_end / test indices identical to the
POC's SeriesSplit.
"""

from __future__ import annotations

import pytest

from ailf.pipelines.changepoint.scenarios import load_all_scenarios
from pocs.changepoint.scenarios import load_all_scenarios as poc_load_all


@pytest.fixture(scope="module")
def poc_by_id():
    return {s.scenario_id: s for s in poc_load_all()}


def test_promoted_split_matches_poc_indices(poc_by_id):
    for scenario in load_all_scenarios():
        poc = poc_by_id[scenario.scenario_id]
        s, p = scenario.split, poc.split
        assert s.train_end == p.train_end, scenario.scenario_id
        assert s.fit_end == p.fit_end, scenario.scenario_id
        assert s.validation_horizon == p.validation_horizon, scenario.scenario_id
        assert s.test_horizon == p.test_horizon, scenario.scenario_id
        # Frame contents identical (ds + y) for train and test regions.
        assert s.train_df["y"].tolist() == p.train_df["y"].tolist(), scenario.scenario_id
        assert s.test_df["y"].tolist() == p.test_df["y"].tolist(), scenario.scenario_id
        assert s.forecast_origin == p.forecast_origin, scenario.scenario_id


def test_audit_only_present_in_metadata_but_off_the_scenario_agent_surface():
    # audit_only is loaded (for tests) but is a separate field, never folded into split/agent data.
    scenario = next(
        s for s in load_all_scenarios() if s.scenario_id == "level_shift_loses_seasonality"
    )
    assert "true_injected_boundaries" in scenario.audit_only
    # The SeriesSplit carries no audit fields.
    assert not hasattr(scenario.split, "audit_only")
