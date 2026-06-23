"""Pipeline-owned eval driver over the committed self-contained curated golden set.

Package-relative data loading (works from any CWD under ``python -m``). The default path REPLAYS
the committed schema-1.1 records — no agent re-run, no reads of pocs/ or reports/. Wires the
changepoint evaluators + (optional) judge into the domain-agnostic ``ailf.core.eval`` infra.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ailf.core.eval import (
    build_evaluator_set,
    ensure_dataset,
    experiment_url,
    get_client,
    read_json,
    read_jsonl,
    run_experiment,
)
from ailf.pipelines.changepoint.eval.evaluators import CHANGEPOINT_EVALUATORS, summarize
from ailf.pipelines.changepoint.eval.failure_modes import classify_corpus, classify_record
from ailf.pipelines.changepoint.eval.projector import example_inputs, example_metadata

_DATA_DIR = Path(__file__).resolve().parent / "data"
CURATED_JSONL = _DATA_DIR / "curated_golden.jsonl"
BASELINE_JSON = _DATA_DIR / "curated_baseline.json"


def load_curated_records() -> list[dict[str, Any]]:
    return read_jsonl(CURATED_JSONL)


def load_baseline() -> dict[str, Any]:
    return read_json(BASELINE_JSON)


def evaluator_set(with_judge: bool = False):
    """The changepoint evaluator list; append the LLM-judge (Bedrock) only when requested."""
    extra = None
    if with_judge:
        from ailf.pipelines.changepoint.eval.judge import build_rationale_judge  # noqa: PLC0415
        extra = [build_rationale_judge()]
    return build_evaluator_set(CHANGEPOINT_EVALUATORS, extra=extra)


def headline(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Score summary + failure-mode taxonomy (the report-emitting path, no LangSmith)."""
    return {"summary": summarize(records), "taxonomy": classify_corpus(records)}


def snapshot_dict(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-case verdicts + headline — the unit of regression tracking (matches the POC schema)."""
    cases = {r["scenario_id"]: {
        "beat_naive": bool(r["outcome"].get("beat_naive")),
        "chosen_tool": r["prediction"].get("chosen_tool"),
        "failure_modes": classify_record(r)["failure_mode_labels"],
        "agent_mae": (r["outcome"].get("agent_test_metrics") or {}).get("mae"),
    } for r in records}
    return {"summary": summarize(records), "cases": cases}


def push_experiment(*, dataset_name: str, experiment_prefix: str, with_judge: bool = False,
                    max_concurrency: int = 4, records: list[dict[str, Any]] | None = None):
    """Push a curated golden set to LangSmith and run ONE experiment (REPLAY target).

    ``records`` defaults to the committed self-contained set; pass freshly LIVE-re-run records
    (from ``live.run_curated_live``) to push the agent's CURRENT behavior for monitoring.
    Returns (results, records)."""
    records = records if records is not None else load_curated_records()
    client = get_client()
    ensure_dataset(client, dataset_name, records,
                   inputs_projector=example_inputs, metadata_builder=example_metadata,
                   description="changepoint curated 10-case regression golden set")
    results = run_experiment(client, dataset_name, records,
                             evaluators=evaluator_set(with_judge=with_judge),
                             experiment_prefix=experiment_prefix,
                             max_concurrency=(2 if with_judge else max_concurrency))
    return results, records


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Diff two snapshot dicts: headline delta + per-case improvements/regressions."""
    a, b = baseline["cases"], candidate["cases"]
    improved = [s for s, cb in b.items() if s in a and not a[s]["beat_naive"] and cb["beat_naive"]]
    regressed = [s for s, cb in b.items() if s in a and a[s]["beat_naive"] and not cb["beat_naive"]]
    return {"baseline_beat": baseline["summary"]["beat_naive_count"],
            "candidate_beat": candidate["summary"]["beat_naive_count"],
            "improved": improved, "regressed": regressed,
            "verdict": "REGRESSIONS PRESENT" if regressed else
                       ("net improvement" if improved else "no change in beat-naive")}
