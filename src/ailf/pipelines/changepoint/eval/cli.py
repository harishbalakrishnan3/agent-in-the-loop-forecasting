"""CLI for the changepoint curated eval (promoted from the POC poc_cli eval/score/snapshot/compare).

Replays the committed self-contained curated golden set — no agent re-run, no pocs/ or reports/
dependency. Run from anywhere:

    uv run python -m ailf.pipelines.changepoint.eval.cli push \
        --dataset-name changepoint-curated-srcmerge --experiment-prefix curated-src-merge

Subcommands:
  score   — print headline + failure-mode taxonomy (no LangSmith; the report-emitting path)
  push    — push the curated set + run ONE LangSmith experiment (REPLAY)
  snapshot <label> — save per-case verdicts under data/snapshots/<label>.json
  compare <baseline> <candidate> — diff two snapshots, flag regressions
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from ailf.pipelines.changepoint.eval import runner

_SNAP_DIR = runner._DATA_DIR / "snapshots"


def _print_headline(records) -> None:
    h = runner.headline(records)
    s, tax = h["summary"], h["taxonomy"]
    print("\n" + "=" * 60)
    print(f"  SCORE — curated regression set ({s['n']} cases)")
    print("=" * 60)
    print(f"  beat-naive rate (HEADLINE) : {s['beat_naive_count']}  ({s['beat_naive_rate']:.0%})")
    print(f"  3-way winner (diagnostic)  : {s['agent_is_winner_count']}")
    micro = s["interval_recall_micro"]
    print(f"  interval boundary recall   : {micro:.3f}" if micro is not None else
          "  interval boundary recall   : n/a")
    print("-" * 60)
    print("  FAILURE-MODE TAXONOMY:")
    for mode, cnt in sorted(tax["mode_counts"].items(), key=lambda kv: -kv[1]):
        print(f"    {mode:30} {cnt}")
    print("=" * 60 + "\n")


def cmd_score(args) -> None:
    _print_headline(runner.load_curated_records())


def cmd_push(args) -> None:
    # --live re-runs the AGENT over the curated set first (monitoring: reflects the CURRENT pipeline);
    # otherwise REPLAY the committed records.
    records = None
    if getattr(args, "live", False):
        from ailf.pipelines.changepoint.eval.live import run_curated_live  # noqa: PLC0415
        records = run_curated_live()
    results, records = runner.push_experiment(
        dataset_name=args.dataset_name, experiment_prefix=args.experiment_prefix,
        with_judge=args.judge, max_concurrency=args.max_concurrency, records=records)
    _print_headline(records)
    print(f"[eval] LangSmith experiment: {runner.experiment_url(results) or 'see smith.langchain.com'}")


def cmd_run(args) -> None:
    """LIVE re-run the agent over the curated set (or one --scenario) and print the score.
    This is the monitoring path: reflects the CURRENT pipeline (a prompt/tool fix shows up here)."""
    from ailf.pipelines.changepoint.eval.live import run_curated_live  # noqa: PLC0415
    sids = [args.scenario] if args.scenario else None
    records = run_curated_live(sids)
    _print_headline(records)


def cmd_inspect(args) -> None:
    """LIVE re-run the agent on ONE curated datapoint and print its golden record + per-evaluator
    scores (the single-datapoint deep-dive, from the src path)."""
    from ailf.pipelines.changepoint.eval.live import run_curated_live  # noqa: PLC0415
    rec = run_curated_live([args.scenario])[0]
    print(json.dumps({"scenario_id": rec["scenario_id"],
                      "chosen_tool": rec["prediction"].get("chosen_tool"),
                      "outcome": rec["outcome"], "crash_info": rec.get("crash_info")}, indent=2, default=str))
    for ev in runner.evaluator_set(with_judge=args.judge):
        out = ev({"outputs": rec}, None)
        print(f"  {out['key']:30} score={out.get('score')}  {out.get('comment') or out.get('value') or ''}")


def cmd_snapshot(args) -> None:
    _SNAP_DIR.mkdir(parents=True, exist_ok=True)
    recs = runner.load_curated_records()
    (_SNAP_DIR / f"{args.label}.json").write_text(json.dumps(runner.snapshot_dict(recs), indent=2))
    print(f"[eval] snapshot '{args.label}' saved -> {_SNAP_DIR / (args.label + '.json')}")
    _print_headline(recs)


def cmd_compare(args) -> None:
    a = json.loads((_SNAP_DIR / f"{args.baseline}.json").read_text())
    b = json.loads((_SNAP_DIR / f"{args.candidate}.json").read_text())
    r = runner.compare(a, b)
    print("\n" + "=" * 60)
    print(f"  COMPARE  {args.baseline} -> {args.candidate}")
    print(f"  beat-naive : {r['baseline_beat']} -> {r['candidate_beat']}")
    print(f"  ✅ improved (fail->beat): {len(r['improved'])}  {r['improved']}")
    print(f"  🔴 regressed (beat->fail): {len(r['regressed'])}  {r['regressed']}")
    print(f"  VERDICT: {r['verdict']}")
    print("=" * 60 + "\n")


def main() -> None:
    load_dotenv()
    flags = argparse.ArgumentParser(add_help=False)
    flags.add_argument("--dataset-name", default="changepoint-curated-srcmerge")
    flags.add_argument("--experiment-prefix", default="curated-src-merge")
    flags.add_argument("--judge", action="store_true", help="also run the LLM-as-judge (Bedrock)")
    flags.add_argument("--live", action="store_true",
                       help="(push) re-run the agent over the curated set first, instead of replaying")
    flags.add_argument("--max-concurrency", type=int, default=4)
    p = argparse.ArgumentParser(description="Changepoint curated eval CLI.", parents=[flags])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("score", "push"):
        sub.add_parser(name, parents=[flags])
    run = sub.add_parser("run", parents=[flags], help="LIVE re-run the agent over the curated set + score")
    run.add_argument("--scenario", default=None, help="restrict to one curated scenario id")
    insp = sub.add_parser("inspect", parents=[flags], help="LIVE re-run ONE datapoint + show all evaluator scores")
    insp.add_argument("scenario")
    snap = sub.add_parser("snapshot", parents=[flags]); snap.add_argument("label")
    cmp = sub.add_parser("compare", parents=[flags])
    cmp.add_argument("baseline"); cmp.add_argument("candidate")
    args = p.parse_args()
    {"score": cmd_score, "push": cmd_push, "run": cmd_run, "inspect": cmd_inspect,
     "snapshot": cmd_snapshot, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    main()
