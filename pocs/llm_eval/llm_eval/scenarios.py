"""The 6 committed changepoint scenarios + their (held-out) ground truth.

Ground truth lives in ``src/ailf/pipelines/changepoint/data/scenario_metadata.json`` under
``audit_only`` — NEVER passed to the agent. The MVP joins it back in OUTSIDE the agent, keyed by
scenario_id (Topic-1 §3 step 1). We read it directly via the ailf loader so there is no second
copy to drift.
"""

from __future__ import annotations

from typing import Any

from ailf.pipelines.changepoint.datasets import load_metadata

# The 5 structural families + how their flat true_injected_boundaries decode (Topic-1 §0/§4).
# POINT families: each int is one changepoint. INTERVAL families: read as [start,end) — ramp is a
# single pair, clean_event is consecutive pairs.
POINT_FAMILIES = {"full_history_step_regressor", "full_history_prophet_tuned_holidays"}
INTERVAL_FAMILIES = {"full_history_ramp_regressor", "full_history_clean_event"}


def _scenarios() -> list[dict[str, Any]]:
    return load_metadata()["scenarios"]


def scenario_ids() -> list[str]:
    """All 6 committed scenario ids (NOT scenarios.REQUIRED_SCENARIO_IDS — that omits the 6th,
    ``sustained_anomaly_block``). Order is metadata order, which is stable."""
    return [m["scenario_id"] for m in _scenarios()]


def load_ground_truth(scenario_id: str) -> dict[str, Any]:
    """Return the held-out ground truth + agent-visible split facts for one scenario.

    Raises KeyError if the scenario_id is unknown (fail loud — a typo must not silently score 0).
    """
    for m in _scenarios():
        if m["scenario_id"] == scenario_id:
            audit = m.get("audit_only", {})
            return {
                "scenario_id": scenario_id,
                "expected_intervention_family": audit.get("expected_intervention_family"),
                "true_injected_boundaries": audit.get("true_injected_boundaries", []),
                "note": audit.get("note", ""),
                # agent-visible split facts (used to build dataset example inputs + assert frame)
                "train_end": m["train_end"],
                "n_changepoints_to_detect": m["n_changepoints_to_detect"],
                "seasonal_period": m["seasonal_period"],
            }
    raise KeyError(f"Unknown scenario_id: {scenario_id!r}")


def family_channel(family: str | None) -> str:
    """'interval' (ramp/clean_event — agent-scored boundary recall), 'point' (step/holiday —
    detector diagnostic only), or 'none' (no family / objective-only)."""
    if family in INTERVAL_FAMILIES:
        return "interval"
    if family in POINT_FAMILIES:
        return "point"
    return "none"
