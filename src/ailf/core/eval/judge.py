"""Domain-agnostic LLM-as-judge scaffold (promoted from the POC).

The judge's VERDICT is non-deterministic and is governed by the golden set, not unit tests
(Principle III); only the deterministic plumbing here (score contract, n/a + error handling, the
injected ``extract_fn`` seam) is unit-tested. NO use-case env names are read here — ``model_id`` /
``region`` are plain optional args supplied by the caller (the pipeline), keeping core use-case-free
(Principle I). The judge is Bedrock-locked via ``build_decision_model(..., llm_provider="bedrock")``,
so the live golden test gates on AWS credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field


class Verdict(BaseModel):
    verdict: str = Field(description="'adheres' or 'rationalizes'")
    reason: str = Field(default="", description="one-sentence justification")


def build_judge_model(model_id: str | None = None, region: str | None = None):
    """Build a (cheaper) judge model via the one provider seam (``ailf.core.models.llm``). Bedrock-
    locked. ``model_id``/``region`` are plain args — core does NOT read use-case env vars; the
    caller (pipeline) supplies them (e.g. from its config / env)."""
    from ailf.core.models.llm import ModelWrapper, build_decision_model  # noqa: PLC0415
    mid = model_id or "us.anthropic.claude-sonnet-4-6"
    reg = region or "us-west-2"
    return ModelWrapper(build_decision_model(mid, reg, llm_provider="bedrock"), mid)


def make_rationale_judge(*, prompt_dir: str | Path, prompt_name: str, version: int,
                         extract_fn: Callable[[dict], tuple[str, str, dict]],
                         schema: type[BaseModel] = Verdict, key: str = "rationale_adheres",
                         model=None, model_id: str | None = None, region: str | None = None):
    """Build a LangSmith evaluator that scores a free-text rationale via an LLM judge.

    ``extract_fn(record) -> (rationale_text, tool_argued_for, diagnostics)`` is injected by the
    pipeline so core stays domain-free. Contract (verbatim from the POC):
      - empty rationale text   -> {"score": None, "value": "n/a_no_rationale"}
      - model raises           -> {"score": None, "value": "judge_error:<Type>"}
      - verdict == "adheres"   -> score 1
      - any other verdict      -> score 0   (NEVER None — a malformed/garbage verdict is a 0, not n/a)
    ``model`` may be injected (tests pass a fake); otherwise it is built lazily on first call.
    """
    from ailf.core.eval.evaluators import record_of  # noqa: PLC0415
    from ailf.core.prompts.loader import load_prompt  # noqa: PLC0415

    state = {"model": model}

    def _evaluator(run, example) -> dict[str, Any]:
        rec = record_of(run, example)
        rationale, tool_argued, diag = extract_fn(rec)
        if not rationale:
            return {"key": key, "score": None, "value": "n/a_no_rationale"}
        import json as _json  # noqa: PLC0415
        prompt = load_prompt(prompt_dir, prompt_name, version, fill={
            "diagnostics": _json.dumps(diag, default=str),
            "chosen_tool": str(tool_argued),
            "rationale": rationale,
        })
        try:
            if state["model"] is None:
                state["model"] = build_judge_model(model_id, region)
            v = state["model"].invoke_structured_text(prompt=prompt, schema=schema)
        except Exception as exc:  # noqa: BLE001 — judge failure must not kill the eval
            return {"key": key, "score": None, "value": f"judge_error:{type(exc).__name__}"}
        adheres = str(v.verdict).strip().lower() == "adheres"
        return {"key": key, "score": 1 if adheres else 0,
                "comment": f"{v.verdict}: {v.reason}", "value": f"{prompt_name}_v{version}"}

    return _evaluator
