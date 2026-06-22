"""CLI for the 100-case POC eval (Topic 2 dataset + Topic 4 failure modes). Run from repo root:

    PYTHONPATH=pocs/llm_eval uv run python -m llm_eval.poc_cli all \
        --dataset-name changepoint-golden-100 --experiment-prefix changepoint-100-current

Subcommands:
  batch — run the agent over ALL generated POC scenarios (Bedrock, tracing ON).
  join  — build golden records (POC ground truth) -> poc_golden.jsonl + print score + taxonomy.
  score — print headline + failure-mode taxonomy from poc_golden.jsonl (NO LangSmith).
  eval  — push the 100-case dataset + run the experiment (incl. failure_mode evaluator).
  all   — batch -> join -> eval.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

POC_GOLDEN_JSONL = Path("pocs/llm_eval/golden_records/poc_golden.jsonl")


def _print_headline(records: list[dict]) -> None:
    from llm_eval.evaluators import summarize
    from llm_eval.failure_modes import classify_corpus
    s = summarize(records)
    tax = classify_corpus(records)
    print("\n" + "=" * 60)
    print(f"  SCORE — current agent over {s['n']} generated cases")
    print("=" * 60)
    print(f"  beat-naive rate (HEADLINE) : {s['beat_naive_count']}  ({s['beat_naive_rate']:.0%})")
    print(f"  3-way winner (diagnostic)  : {s['agent_is_winner_count']}")
    micro = s["interval_recall_micro"]
    print(f"  interval boundary recall   : {micro:.3f}" if micro is not None else "  interval boundary recall   : n/a")
    print("-" * 60)
    print("  FAILURE-MODE TAXONOMY (Topic 4):")
    for mode, cnt in sorted(tax["mode_counts"].items(), key=lambda kv: -kv[1]):
        print(f"    {mode:32} {cnt}")
    print(f"  -- capability gaps (toolset limit, not a bug) : {tax['capability_gaps']}")
    print(f"  -- behavioral failures (agent could do better): {tax['behavioral_failures']}")
    print(f"  -- pipeline blindness (diagnostics hid it)    : {tax['pipeline_blindness']}")
    print("  lever x class:", tax["lever_x_class"])
    print("=" * 60 + "\n")


def cmd_batch(args) -> list[str]:
    from llm_eval.poc_runner import run_all_poc
    dirs = run_all_poc()
    (POC_GOLDEN_JSONL.parent / "poc_run_dirs.json").write_text(json.dumps(dirs))
    return dirs


def cmd_join(args, run_dirs: list[str] | None = None) -> list[dict]:
    from llm_eval.golden import build_golden_record, write_jsonl
    from llm_eval.poc_runner import poc_ground_truth, poc_scenario_ids
    from llm_eval.batch import DEFAULT_REPORTS_ROOT
    if run_dirs is None:
        rr = args.reports_root or DEFAULT_REPORTS_ROOT
        run_dirs = [str(rr / f"{sid}-1729") for sid in poc_scenario_ids()
                    if (rr / f"{sid}-1729" / "agent_trace.json").exists()]
    records = []
    for d in run_dirs:
        try:
            records.append(build_golden_record(d, gt_loader=poc_ground_truth))
        except Exception as exc:  # noqa: BLE001
            print(f"[poc-cli] skip {d}: {type(exc).__name__}: {exc}")
    if not records:
        raise SystemExit("[poc-cli] no records built — run `batch` first.")
    write_jsonl(records, POC_GOLDEN_JSONL)
    print(f"[poc-cli] wrote {len(records)} golden records -> {POC_GOLDEN_JSONL}")
    _print_headline(records)
    return records


def _load() -> list[dict]:
    if not POC_GOLDEN_JSONL.exists():
        raise SystemExit(f"[poc-cli] {POC_GOLDEN_JSONL} missing — run `join` first.")
    return [json.loads(l) for l in POC_GOLDEN_JSONL.read_text().splitlines() if l.strip()]


def cmd_score(args) -> None:
    _print_headline(_load())


def cmd_eval(args) -> None:
    from llm_eval.langsmith_push import ensure_dataset, experiment_url, get_client, run_experiment
    records = _load()
    client = get_client()
    ensure_dataset(client, args.dataset_name, records)
    results = run_experiment(client, args.dataset_name, records,
                             experiment_prefix=args.experiment_prefix, max_concurrency=args.max_concurrency)
    _print_headline(records)
    print(f"[poc-cli] LangSmith experiment: {experiment_url(results) or 'see smith.langchain.com'}")


def cmd_all(args) -> None:
    run_dirs = cmd_batch(args)
    cmd_join(args, run_dirs=run_dirs)
    cmd_eval(args)


def main() -> None:
    load_dotenv()
    flags = argparse.ArgumentParser(add_help=False)
    flags.add_argument("--reports-root", type=Path, default=None)
    flags.add_argument("--dataset-name", default="changepoint-golden-100")
    flags.add_argument("--experiment-prefix", default="changepoint-100-current")
    flags.add_argument("--max-concurrency", type=int, default=4)
    p = argparse.ArgumentParser(description="100-case POC eval (Topic 2 + Topic 4).", parents=[flags])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("batch", "join", "score", "eval", "all"):
        sub.add_parser(name, parents=[flags])
    args = p.parse_args()
    {"batch": cmd_batch, "join": cmd_join, "score": cmd_score, "eval": cmd_eval, "all": cmd_all}[args.cmd](args)


if __name__ == "__main__":
    main()
