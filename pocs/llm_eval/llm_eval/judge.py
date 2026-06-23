"""LLM-as-judge evaluator (showcase) — rationale constraint-adherence.

The ONE dimension our deterministic evaluators cannot score: is the agent's free-text *rationale*
sound, or did it rationalize around a diagnostic constraint? Reference-free (no golden rationale
text) — the judge grades the rationale against the diagnostics the agent was actually shown.

Targets the pattern seen in the real `tool_*` traces: the agent reads
`is_calendar_recurring == false` and then argues for `full_history_prophet_tuned_holidays` anyway.
Uses the cheaper decision model (Sonnet) and a VERSIONED prompt (constitution Principle III).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "judge_prompts"
_JUDGE_PROMPT = "rationale_constraint_adherence"
_JUDGE_VERSION = 1


class _Verdict(BaseModel):
    verdict: str = Field(description="'adheres' or 'rationalizes'")
    reason: str = Field(default="", description="one-sentence justification")


def _judge_model():
    """Build the (cheaper) decision/Sonnet model via the same Bedrock path the agent uses."""
    from ailf.core.models.llm import ModelWrapper, build_decision_model  # noqa: PLC0415
    model_id = os.getenv("REACT_MODEL_ID") or "us.anthropic.claude-sonnet-4-6"
    region = os.getenv("AWS_REGION", "us-west-2")
    return ModelWrapper(build_decision_model(model_id, region, llm_provider="bedrock"), model_id)


def _rationale_and_diag(rec: dict) -> tuple[str, str, dict]:
    """Pull the rationale to judge + the tool it argued for + key diagnostic fields from the trace.

    We judge the MOST CONSTRAINT-RELEVANT iteration: if ANY iteration proposed the
    precondition-gated `full_history_prophet_tuned_holidays`, judge THAT one's rationale (that's
    where rationalization shows up) — otherwise judge the first iteration. (The agent's *final*
    chosen_tool may differ because it pivoted after rejections; the rationalization lives in the
    blocked iterations.) Returns (rationale, tool_argued_for, diag)."""
    tp = rec.get("trace_path")
    if not (tp and Path(tp).exists()):
        return "", "", {}
    t = json.loads(Path(tp).read_text())
    its = t.get("iterations", [])
    if not its:
        return "", "", {}
    gated = next((it for it in its
                  if it["proposal"].get("tool") == "full_history_prophet_tuned_holidays"), None)
    chosen_it = gated or its[0]
    rationale = chosen_it["proposal"].get("rationale", "")
    tool = chosen_it["proposal"].get("tool", "")
    d = t.get("diagnostics", {})
    diag = {
        "recurring_event_summary": d.get("recurring_event_summary"),
        "transient_event_score": d.get("transient_event_score"),
        "permanent_shift_magnitude": d.get("permanent_shift_magnitude"),
        "candidate_drift_intervals_count": len(d.get("candidate_drift_intervals", [])),
        "candidate_event_blocks_count": len(d.get("candidate_event_blocks", [])),
    }
    return rationale, tool, diag


def judge_rationale_adherence(run, example) -> dict[str, Any]:
    """LangSmith evaluator: score=1 if the rationale ADHERES to the diagnostics, 0 if it RATIONALIZES.
    score=None (n/a) when there's no rationale text to judge (e.g. crash records)."""
    from ailf.core.prompts.loader import load_prompt  # noqa: PLC0415
    rec = getattr(run, "outputs", None) or (run.get("outputs") if isinstance(run, dict) else None) or {}
    rationale, tool_argued, diag = _rationale_and_diag(rec)
    if not rationale:
        return {"key": "rationale_adheres", "score": None, "value": "n/a_no_rationale"}
    prompt = load_prompt(_PROMPT_DIR, _JUDGE_PROMPT, _JUDGE_VERSION, fill={
        "diagnostics": json.dumps(diag, default=str),
        "chosen_tool": tool_argued,  # the tool THIS rationale argued for (may be a rejected iteration)
        "rationale": rationale,
    })
    try:
        v = _judge_model().invoke_structured_text(prompt=prompt, schema=_Verdict)
    except Exception as exc:  # noqa: BLE001 — judge failure shouldn't kill the eval
        return {"key": "rationale_adheres", "score": None, "value": f"judge_error:{type(exc).__name__}"}
    adheres = v.verdict.strip().lower() == "adheres"
    return {"key": "rationale_adheres", "score": 1 if adheres else 0,
            "comment": f"{v.verdict}: {v.reason}",
            "value": _JUDGE_PROMPT + f"_v{_JUDGE_VERSION}"}
