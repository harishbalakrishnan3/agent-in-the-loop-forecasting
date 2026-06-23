"""Evaluation harness and LLM judge.

Runs the versioned golden eval set and the agent-level evals (diagnostic correctness,
tool-use, intervention quality, backtest discipline, constraint adherence, stability).
LLM-judge prompts are versioned (constitution Principle III).

This package is DOMAIN-AGNOSTIC (Principle I / VII): boundary-matching primitives, the evaluator
harness + compose seam, the LLM-judge scaffold, and the LangSmith push/experiment infra — all
parameterized by injected callables. Use-case specifics (changepoint families, record schema,
curated set, family-aware evaluators, judge content) live in the pipeline's own eval package
(e.g. ``ailf.pipelines.changepoint.eval``). Core MUST NOT import any pipeline.
"""

from ailf.core.eval.evaluators import (
    agent_is_winner,
    agent_minus_naive_mae,
    beat_naive,
    build_evaluator_set,
    record_of,
)
from ailf.core.eval.judge import Verdict, build_judge_model, make_rationale_judge
from ailf.core.eval.langsmith_push import (
    ensure_dataset,
    experiment_url,
    get_client,
    make_replay_target,
    run_experiment,
)
from ailf.core.eval.matching import (
    match_intervals,
    match_points,
    read_json,
    read_jsonl,
    write_jsonl,
)

__all__ = [
    "match_intervals", "match_points", "write_jsonl", "read_jsonl", "read_json",
    "record_of", "beat_naive", "agent_is_winner", "agent_minus_naive_mae", "build_evaluator_set",
    "build_judge_model", "Verdict", "make_rationale_judge",
    "get_client", "ensure_dataset", "make_replay_target", "run_experiment", "experiment_url",
]
