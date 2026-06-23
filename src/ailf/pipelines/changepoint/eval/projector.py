"""The changepoint seams injected into ``ailf.core.eval.langsmith_push.ensure_dataset``.

``example_inputs`` exposes ONLY agent-visible fields (ground truth excluded — FR-003 boundary);
``example_metadata`` adds the family/role/failure-mode labels so the LangSmith panel is filterable.
"""

from __future__ import annotations

from typing import Any

from ailf.pipelines.changepoint.eval.curated import CURATED_ROLE
from ailf.pipelines.changepoint.eval.evaluators import failure_mode_metadata


def example_inputs(rec: dict[str, Any]) -> dict[str, Any]:
    """Agent-visible fields only — ground truth must NOT leak into the dataset inputs (FR-003)."""
    g = rec["ground_truth"]
    return {"scenario_id": rec["scenario_id"], "seed": rec["seed"],
            "n_changepoints_to_detect": g.get("n_changepoints_to_detect"),
            "seasonal_period": g.get("seasonal_period")}


def example_metadata(rec: dict[str, Any]) -> dict[str, Any]:
    """Filterable LangSmith metadata: family channel + expected family + curated role + failure mode."""
    g = rec["ground_truth"]
    md = {"family_channel": g["family_channel"],
          "expected_intervention_family": g["expected_intervention_family"]}
    if rec["scenario_id"] in CURATED_ROLE:
        md["curated_role"] = CURATED_ROLE[rec["scenario_id"]]
    md.update(failure_mode_metadata(rec))
    return md
