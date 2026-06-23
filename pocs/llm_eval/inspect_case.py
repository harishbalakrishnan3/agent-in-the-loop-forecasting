"""Run the full LLM-eval pipeline on ONE datapoint and print every output + score.

Pipeline per datapoint: run the agent (Bedrock, golden split) -> join trace+ground-truth into a
golden record -> run all 7 evaluators -> classify failure mode -> print everything.

Usage (from repo root):
  # live (re-runs the agent on Bedrock — needs AWS creds in .env):
  PYTHONPATH=pocs/llm_eval uv run python -m inspect_case competence_clean_0_0
  # replay (no Bedrock — score the trace already in poc_golden.jsonl):
  PYTHONPATH=pocs/llm_eval uv run python -m inspect_case competence_clean_0_4 --replay
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

POC_GOLDEN = Path("pocs/llm_eval/golden_records/poc_golden.jsonl")


def _live_record(sid: str) -> dict:
    import logging
    logging.disable(logging.CRITICAL)
    from llm_eval.poc_runner import run_all_poc, poc_ground_truth, build_crash_record
    from llm_eval.golden import build_golden_record
    from llm_eval.batch import DEFAULT_REPORTS_ROOT
    run_dirs, crashes = run_all_poc([sid])
    if crashes:
        return crashes[0]
    return build_golden_record(run_dirs[0], gt_loader=poc_ground_truth)


def _replay_record(sid: str) -> dict:
    for line in POC_GOLDEN.read_text().splitlines():
        if line.strip() and json.loads(line)["scenario_id"] == sid:
            return json.loads(line)
    raise SystemExit(f"{sid} not in {POC_GOLDEN} — run the batch first or use live mode.")


def _show(rec: dict, with_judge: bool = False) -> None:
    from llm_eval.evaluators import all_evaluators
    from llm_eval.failure_modes import classify_record
    ALL_EVALUATORS = all_evaluators(with_judge=with_judge)

    g, p, o = rec["ground_truth"], rec["prediction"], rec["outcome"]
    print("\n" + "=" * 72)
    print(f"  DATAPOINT: {rec['scenario_id']}   (lever={g.get('intended_failure_lever')}, "
          f"bucket={g.get('source_bucket')})")
    print("=" * 72)

    print("\n--- GROUND TRUTH (held out from the agent) ---")
    print(f"  expected_intervention_family (gate-winner): {g.get('expected_intervention_family')}")
    print(f"  authored_intent_family                    : {g.get('authored_intent_family')}")
    print(f"  ground_truth_kind                         : {g.get('ground_truth_kind')}")
    print(f"  true_injected_boundaries                  : {g.get('true_injected_boundaries_raw')}")
    print(f"  note                                      : {g.get('note')}")

    print("\n--- AGENT PREDICTION (what the agent did) ---")
    print(f"  chosen_tool   : {p.get('chosen_tool')}")
    print(f"  chosen_params : {p.get('chosen_tool_params')}")
    print(f"  final_case    : {p.get('final_case')}")
    print(f"  n_iterations  : {p.get('n_iterations')}")
    if rec.get("crash_info"):
        print(f"  CRASH         : {rec['crash_info']}")

    print("\n--- OUTCOME (test-set metrics) ---")
    print(f"  agent MAE          : {o.get('agent_test_metrics', {}).get('mae')}")
    print(f"  naive MAE          : {o.get('naive_test_metrics', {}).get('mae')}")
    print(f"  full_history MAE   : {o.get('full_history_prophet_test_metrics', {}).get('mae')}")
    print(f"  winner             : {o.get('winner')}")
    print(f"  beat_naive (2-way) : {o.get('beat_naive')}")

    print("\n--- EVALUATOR OUTPUTS (the LLM-eval scores for this datapoint) ---")
    class _O:
        def __init__(self, d): self.outputs = d
    run = ex = _O(rec)
    for ev in ALL_EVALUATORS:
        r = ev(run, ex)
        score = r.get("score")
        val = r.get("value")
        cmt = r.get("comment", "")
        score_s = "n/a" if score is None else (f"{score:.3f}" if isinstance(score, float) else str(score))
        print(f"  {r['key']:30} score={score_s:8}{(' value='+str(val)) if val else ''}")
        if cmt:
            print(f"  {'':30}   {cmt}")

    print("\n--- FAILURE-MODE DIAGNOSIS (Topic 4) ---")
    c = classify_record(rec)
    print(f"  failure_mode_labels : {c['failure_mode_labels']}")
    print(f"  is_behavioral_failure={c['is_behavioral_failure']}  "
          f"is_capability_gap={c['is_capability_gap']}  is_pipeline_blindness={c['is_pipeline_blindness']}")
    print("=" * 72 + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", help="scenario_id, e.g. competence_clean_0_0")
    ap.add_argument("--replay", action="store_true", help="score the stored trace (no Bedrock)")
    ap.add_argument("--judge", action="store_true",
                    help="also run the LLM-as-judge (rationale adherence); calls Bedrock")
    args = ap.parse_args()
    rec = _replay_record(args.scenario) if args.replay else _live_record(args.scenario)
    _show(rec, with_judge=args.judge)


if __name__ == "__main__":
    main()
