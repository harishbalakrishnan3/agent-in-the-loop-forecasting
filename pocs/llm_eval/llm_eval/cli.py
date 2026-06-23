"""CLI for the MVP eval pipeline. Run from the REPO ROOT so run_scenario's reports/ path and the
ailf imports resolve, e.g.:

    PYTHONPATH=pocs/llm_eval uv run python -m llm_eval.cli all \
        --dataset-name changepoint-golden-6 --experiment-prefix changepoint-current-code

Subcommands (each independently runnable):
  batch  — run the agent over the 6 scenarios on Bedrock (tracing ON); write run dirs.
  join   — build golden records from existing run dirs; write golden_records/golden.jsonl + print score.
  score  — join + print the headline locally (NO LangSmith). The smallest thing that scores.
  push   — push the golden dataset to LangSmith.
  eval   — push + run the experiment + print headline + URL.
  all    — batch -> join -> push -> eval.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

GOLDEN_JSONL = Path("pocs/llm_eval/golden_records/golden.jsonl")


def _discover_run_dirs(seed: int, reports_root: Path, seed_runs: int = 1) -> list[str]:
    """Find run dirs for each scenario across seeds [seed, seed+seed_runs) (layout
    <scenario_id>-<seed>). batch.run_all names dirs by cfg.seed = 1729+rep, so multi-seed repeats
    are enumerated here rather than silently dropped."""
    from llm_eval.scenarios import scenario_ids
    dirs = []
    for sid in scenario_ids():
        found_any = False
        for s in range(seed, seed + max(1, seed_runs)):
            d = reports_root / f"{sid}-{s}"
            if (d / "agent_trace.json").exists():
                dirs.append(str(d))
                found_any = True
        if not found_any:
            print(f"[cli] WARNING: no run dir for {sid} near {reports_root}/{sid}-{seed} (run `batch` first).")
    return dirs


def _print_headline(records: list[dict]) -> None:
    from llm_eval.evaluators import summarize
    s = summarize(records)
    print("\n" + "=" * 56)
    print("  SCORE — current changepoint agent, 6 committed scenarios")
    print("=" * 56)
    print(f"  beat-naive rate (HEADLINE) : {s['beat_naive_count']}  ({s['beat_naive_rate']:.0%})")
    print(f"  3-way winner (diagnostic)  : {s['agent_is_winner_count']}")
    print(f"  chose-authored-family (dx) : {s['chose_authored_family_count']}  (authored intent; caveat)")
    micro = s["interval_recall_micro"]
    micro_s = f"{micro:.3f}" if micro is not None else "n/a"
    print(f"  interval boundary recall   : {micro_s}  (micro over {s['interval_family_n']} interval families)")
    print("=" * 56 + "\n")


def cmd_batch(args) -> list[str]:
    from llm_eval.batch import run_all, DEFAULT_REPORTS_ROOT
    return run_all(seed_runs=args.seed_runs, reports_root=args.reports_root or DEFAULT_REPORTS_ROOT)


def cmd_join(args, run_dirs: list[str] | None = None) -> list[dict]:
    from llm_eval.batch import DEFAULT_REPORTS_ROOT
    from llm_eval.golden import build_all, write_jsonl
    # Prefer the dirs batch actually produced (passed by cmd_all); else discover by seed.
    if run_dirs is None:
        run_dirs = _discover_run_dirs(args.seed, args.reports_root or DEFAULT_REPORTS_ROOT,
                                      seed_runs=args.seed_runs)
    if not run_dirs:
        raise SystemExit("[cli] no run dirs found — run `batch` first.")
    records = build_all(run_dirs)
    write_jsonl(records, GOLDEN_JSONL)
    print(f"[cli] wrote {len(records)} golden records -> {GOLDEN_JSONL}")
    _print_headline(records)
    return records


def _load_records() -> list[dict]:
    if not GOLDEN_JSONL.exists():
        raise SystemExit(f"[cli] {GOLDEN_JSONL} missing — run `join` first.")
    return [json.loads(line) for line in GOLDEN_JSONL.read_text().splitlines() if line.strip()]


def cmd_score(args) -> None:
    _print_headline(cmd_join(args) if args.rejoin else _load_records())


def cmd_push(args) -> None:
    from llm_eval.langsmith_push import ensure_dataset, get_client
    client = get_client()
    ensure_dataset(client, args.dataset_name, _load_records())


def cmd_eval(args) -> None:
    from llm_eval.langsmith_push import ensure_dataset, experiment_url, get_client, run_experiment
    client = get_client()
    records = _load_records()
    ensure_dataset(client, args.dataset_name, records)
    results = run_experiment(client, args.dataset_name, records,
                             experiment_prefix=args.experiment_prefix,
                             max_concurrency=args.max_concurrency)
    _print_headline(records)
    url = experiment_url(results)
    print(f"[cli] LangSmith experiment: {url or 'see smith.langchain.com'}")


def cmd_all(args) -> None:
    run_dirs = cmd_batch(args)        # thread the realized run dirs straight into join
    cmd_join(args, run_dirs=run_dirs)
    cmd_eval(args)


def main() -> None:
    load_dotenv()
    # Flags live on a shared PARENT parser inherited by every subcommand, so they work in EITHER
    # position (`cli.py all --dataset-name X` and `cli.py --dataset-name X all` both parse).
    flags = argparse.ArgumentParser(add_help=False)
    flags.add_argument("--seed", type=int, default=1729, help="seed used to locate run dirs (join/score)")
    flags.add_argument("--seed-runs", type=int, default=1, help="repeats per scenario (batch)")
    flags.add_argument("--reports-root", type=Path, default=None)
    flags.add_argument("--dataset-name", default="changepoint-golden-6")
    flags.add_argument("--experiment-prefix", default="changepoint-current-code")
    flags.add_argument("--max-concurrency", type=int, default=4)
    flags.add_argument("--rejoin", action="store_true", help="(score) rebuild records before printing")

    p = argparse.ArgumentParser(description="MVP LLM-eval pipeline for the changepoint agent.",
                                parents=[flags])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("batch", "join", "score", "push", "eval", "all"):
        sub.add_parser(name, parents=[flags])
    args = p.parse_args()
    {"batch": cmd_batch, "join": cmd_join, "score": cmd_score,
     "push": cmd_push, "eval": cmd_eval, "all": cmd_all}[args.cmd](args)


if __name__ == "__main__":
    main()
