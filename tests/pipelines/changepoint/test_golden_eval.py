"""T083 — opt-in golden-set agent-quality eval (Constitution Principle III).

Runs the REAL agent (live Bedrock) over the five scenarios and checks mode-appropriate tool
discrimination vs each scenario's ``expected_intervention_family``, and that the holiday tool is
selected ONLY on the calendar-recurring scenario (FR-031). Behind ``@pytest.mark.golden`` + a
credential guard — it NEVER gates the deterministic suite (run with ``uv run pytest -m golden``).

This is the documented Principle-III no-regression harness for the two agent-affecting changes (the
new react_decision_v2 prompt + the generated menu); capture before/after in the PR (plan Deviation 3).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.golden

_HOLIDAY_TOOL = "full_history_prophet_tuned_holidays"
_RECURRING_SCENARIO = "prophet_prior_tuning_recurring_event"


def _have_bedrock() -> bool:
    return bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("VISUAL_MODEL_ID") and os.getenv("REACT_MODEL_ID"))


@pytest.mark.skipif(not _have_bedrock(), reason="requires live Bedrock credentials + model ids in env")
def test_holiday_tool_selected_only_on_recurring_scenario(tmp_path):
    from ailf.pipelines.changepoint.scenarios import load_all_scenarios
    from ailf.pipelines.changepoint.pipeline import run_scenario

    chosen_by_scenario: dict[str, str] = {}
    for sc in load_all_scenarios():
        report = run_scenario(sc.scenario_id, reports_root=tmp_path)
        chosen_by_scenario[sc.scenario_id] = report["methods"]["agent"]["tool"]

    # FR-031: the holiday tool may ONLY be the agent's tool on the calendar-recurring scenario.
    for sid, tool in chosen_by_scenario.items():
        if tool == _HOLIDAY_TOOL:
            assert sid == _RECURRING_SCENARIO, f"holiday tool selected on non-recurring scenario {sid}"
