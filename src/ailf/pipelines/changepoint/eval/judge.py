"""Changepoint LLM-judge content (promoted from the POC).

Supplies the changepoint ``extract_fn`` (reads the INLINE ``judged_iteration`` from a self-contained
schema-1.1 record — never disk) and wires it through the domain-agnostic
``ailf.core.eval.make_rationale_judge`` with the package-relative versioned prompt and the
pipeline's model id / region (the env/config fallback lives HERE, not in core — Principle I).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ailf.core.eval import make_rationale_judge

# Versioned judge prompt lives in the changepoint pipeline's prompts/ (Principle III).
_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_PROMPT_NAME = "rationale_constraint_adherence"
_PROMPT_VERSION = 1


def _rationale_and_diag(rec: dict[str, Any]) -> tuple[str, str, dict]:
    """Read the inlined judge inputs from a schema-1.1 record. Returns ('', '', {}) when absent
    (e.g. a crash record) so the judge yields score=None (n/a) rather than calling the model."""
    ji = rec.get("judged_iteration")
    if not ji or not ji.get("rationale"):
        return "", "", {}
    return ji.get("rationale", ""), ji.get("tool_argued_for", ""), ji.get("diag", {})


def _model_id() -> str:
    # env/config fallback lives in the PIPELINE, not core. REACT_MODEL_ID matches the agent's decision model.
    return os.getenv("REACT_MODEL_ID") or "us.anthropic.claude-sonnet-4-6"


def _region() -> str:
    return os.getenv("AWS_REGION") or "us-west-2"


def build_rationale_judge():
    """The changepoint rationale-adherence LLM-judge evaluator (Bedrock-locked via core)."""
    return make_rationale_judge(
        prompt_dir=_PROMPTS_DIR, prompt_name=_PROMPT_NAME, version=_PROMPT_VERSION,
        extract_fn=_rationale_and_diag, model_id=_model_id(), region=_region(),
    )
