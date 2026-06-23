"""Changepoint family taxonomy + the (held-out) ground-truth loader.

The 5 structural families + how their flat ``true_injected_boundaries`` decode (points for
step/holiday, interval pairs for ramp/clean_event). These family-name strings are CHANGEPOINT-
specific, which is exactly why this lives in the pipeline, not core (Principle VII).
"""

from __future__ import annotations

from typing import Any

from ailf.pipelines.changepoint.datasets import load_metadata

POINT_FAMILIES = {"full_history_step_regressor", "full_history_prophet_tuned_holidays"}
INTERVAL_FAMILIES = {"full_history_ramp_regressor", "full_history_clean_event"}


def family_channel(family: str | None) -> str:
    """'interval' (ramp/clean_event — agent-scored), 'point' (step/holiday — detector diagnostic),
    or 'none' (no family / fallback / objective-only)."""
    if family in INTERVAL_FAMILIES:
        return "interval"
    if family in POINT_FAMILIES:
        return "point"
    return "none"


def load_ground_truth(scenario_id: str) -> dict[str, Any]:
    """Held-out ground truth for a committed pipeline scenario (audit_only + split facts). Used by
    the optional regenerate path; the default replay path reads self-contained curated records."""
    for m in load_metadata()["scenarios"]:
        if m["scenario_id"] == scenario_id:
            a = m.get("audit_only", {})
            return {"scenario_id": scenario_id,
                    "expected_intervention_family": a.get("expected_intervention_family"),
                    "true_injected_boundaries": a.get("true_injected_boundaries", []),
                    "note": a.get("note", ""), "train_end": m["train_end"],
                    "n_changepoints_to_detect": m["n_changepoints_to_detect"],
                    "seasonal_period": m["seasonal_period"]}
    raise KeyError(f"Unknown scenario_id: {scenario_id!r}")
