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


def cmd_batch(args) -> tuple[list[str], list[dict]]:
    from llm_eval.poc_runner import run_all_poc
    dirs, crashes = run_all_poc()
    (POC_GOLDEN_JSONL.parent / "poc_run_dirs.json").write_text(json.dumps(dirs))
    return dirs, crashes


def _discover_crashes(reports_root) -> list[dict]:
    """Build crash records for scenarios that have a partial run dir (events.jsonl) but NO
    agent_trace.json — i.e. the agent run crashed. Recovers from the existing artifacts; no re-run.
    The crash cause is recovered from events (last stage) + a probe of the failing tool."""
    from llm_eval.poc_runner import build_crash_record, poc_ground_truth, poc_scenario_ids
    crashes = []
    for sid in poc_scenario_ids():
        d = reports_root / f"{sid}-1729"
        if (d / "agent_trace.json").exists() or not (d / "events.jsonl").exists():
            continue
        # Reconstruct the exception by replaying the deterministic prelude + the agent's recovered
        # proposal through the gate (no Bedrock) so we get the real exception type/message.
        exc = _reproduce_crash(sid, d)
        crashes.append(build_crash_record(sid, exc, d, poc_ground_truth(sid)))
    return crashes


def _reproduce_crash(sid: str, run_dir):
    """Deterministically reproduce a crashed scenario's exception (no LLM) so the captured record
    has the true exception type/message. Replays the recovered proposals through the gate."""
    import pandas as pd
    from llm_eval.poc_runner import _recover_from_events, poc_ground_truth
    from generator.verify import build_split
    from ailf.pipelines.changepoint.detector import detect_changepoints
    from ailf.pipelines.changepoint.diagnostics import compute_diagnostics
    from ailf.pipelines.changepoint.baselines import naive_workflow
    from ailf.pipelines.changepoint.interventions import register_changepoint_registry
    from ailf.core.agent.registry import Proposal
    from ailf.core.backtest.gate import evaluate_on_validation, evaluate_on_test
    gt = poc_ground_truth(sid)
    rec = _recover_from_events(run_dir)
    df = pd.read_csv(f"pocs/llm_eval/data/csv/{sid}.csv", parse_dates=["ds"])
    split = build_split(df, gt["train_end"], 120, 120)
    cps = detect_changepoints(split.train_df, n_changepoints_to_detect=gt["n_changepoints_to_detect"])
    fd = compute_diagnostics(split.train_df, changepoints=cps, seasonal_period=365).to_agent_dict()
    nb = naive_workflow(split, cps).selected.val_mae
    reg = register_changepoint_registry()
    last = RuntimeError("unknown crash")
    for p in rec["proposals"]:
        if not p.get("tool"):
            continue
        try:
            evaluate_on_validation(Proposal(tool=p["tool"], params=p["params"] or {}), split, reg,
                                   full_diagnostics=fd, naive_val_mae=nb)
        except Exception as e:  # noqa: BLE001
            last = e  # capture the real exception (IndexError or ToolBoundsError)
    # bug#3: if the looped tool was precondition-blocked, final eval re-invokes it -> reproduce on test
    if rec["proposals"]:
        first = rec["proposals"][0]
        if first.get("tool"):
            try:
                evaluate_on_test(Proposal(tool=first["tool"], params=first["params"] or {}), split, reg,
                                 full_diagnostics=fd)
            except Exception as e:  # noqa: BLE001
                last = e
    return last


def cmd_join(args, run_dirs: list[str] | None = None, crash_records: list[dict] | None = None) -> list[dict]:
    from llm_eval.golden import build_golden_record, write_jsonl
    from llm_eval.poc_runner import poc_ground_truth, poc_scenario_ids
    from llm_eval.batch import DEFAULT_REPORTS_ROOT
    rr = args.reports_root or DEFAULT_REPORTS_ROOT
    if run_dirs is None:
        run_dirs = [str(rr / f"{sid}-1729") for sid in poc_scenario_ids()
                    if (rr / f"{sid}-1729" / "agent_trace.json").exists()]
    records = []
    for d in run_dirs:
        try:
            records.append(build_golden_record(d, gt_loader=poc_ground_truth))
        except Exception as exc:  # noqa: BLE001
            print(f"[poc-cli] skip {d}: {type(exc).__name__}: {exc}")
    # crash records: from batch (passed in) OR discovered from partial run dirs on a standalone join.
    crashes = crash_records if crash_records is not None else _discover_crashes(rr)
    records.extend(crashes)
    if crashes:
        print(f"[poc-cli] captured {len(crashes)} crashed cases as failure records.")
    if not records:
        raise SystemExit("[poc-cli] no records built — run `batch` first.")
    write_jsonl(records, POC_GOLDEN_JSONL)
    print(f"[poc-cli] wrote {len(records)} golden records ({len(records)-len(crashes)} completed + "
          f"{len(crashes)} crashed) -> {POC_GOLDEN_JSONL}")
    _print_headline(records)
    return records


def _load() -> list[dict]:
    if not POC_GOLDEN_JSONL.exists():
        raise SystemExit(f"[poc-cli] {POC_GOLDEN_JSONL} missing — run `join` first.")
    return [json.loads(l) for l in POC_GOLDEN_JSONL.read_text().splitlines() if l.strip()]


def cmd_score(args) -> None:
    _print_headline(_load())


SNAP_DIR = POC_GOLDEN_JSONL.parent / "snapshots"


def _snapshot_dict(records: list[dict]) -> dict:
    """Per-case verdicts + headline, the unit of regression tracking."""
    from llm_eval.evaluators import summarize
    from llm_eval.failure_modes import classify_record
    cases = {}
    for r in records:
        cases[r["scenario_id"]] = {
            "beat_naive": bool(r["outcome"].get("beat_naive")),
            "chosen_tool": r["prediction"].get("chosen_tool"),
            "failure_modes": classify_record(r)["failure_mode_labels"],
            "agent_mae": (r["outcome"].get("agent_test_metrics") or {}).get("mae"),
        }
    return {"summary": summarize(records), "cases": cases}


def cmd_snapshot(args) -> None:
    """Save the current score + per-case verdicts under a label (for before/after comparison)."""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    snap = _snapshot_dict(_load())
    path = SNAP_DIR / f"{args.label}.json"
    path.write_text(json.dumps(snap, indent=2))
    print(f"[poc-cli] snapshot '{args.label}' saved -> {path}")
    _print_headline(_load())


def cmd_compare(args) -> None:
    """Diff two snapshots: headline delta + per-case improvements and REGRESSIONS."""
    a = json.loads((SNAP_DIR / f"{args.baseline}.json").read_text())
    b = json.loads((SNAP_DIR / f"{args.candidate}.json").read_text())
    sa, sb = a["summary"], b["summary"]
    print("\n" + "=" * 64)
    print(f"  COMPARE  baseline='{args.baseline}'  ->  candidate='{args.candidate}'")
    print("=" * 64)
    print(f"  beat-naive : {sa['beat_naive_count']}  ->  {sb['beat_naive_count']}  "
          f"({sb['beat_naive_rate']-sa['beat_naive_rate']:+.1%})")
    ra = sa.get("interval_recall_micro"); rb = sb.get("interval_recall_micro")
    if ra is not None and rb is not None:
        print(f"  interval recall : {ra:.3f}  ->  {rb:.3f}  ({rb-ra:+.3f})")
    improved, regressed, tool_changed = [], [], []
    for sid, cb in b["cases"].items():
        ca = a["cases"].get(sid)
        if ca is None:
            continue
        if (not ca["beat_naive"]) and cb["beat_naive"]:
            improved.append(sid)
        if ca["beat_naive"] and (not cb["beat_naive"]):
            regressed.append(sid)
        if ca["chosen_tool"] != cb["chosen_tool"]:
            tool_changed.append((sid, ca["chosen_tool"], cb["chosen_tool"]))
    print("-" * 64)
    print(f"  ✅ IMPROVED (fail->beat naive): {len(improved)}")
    for s in improved: print(f"       + {s}")
    print(f"  🔴 REGRESSED (beat->fail naive): {len(regressed)}")
    for s in regressed: print(f"       - {s}  [REGRESSION]")
    print(f"  ↺ tool changed: {len(tool_changed)}")
    for s, t0, t1 in tool_changed[:12]: print(f"       {s}: {t0} -> {t1}")
    verdict = "REGRESSIONS PRESENT" if regressed else ("net improvement" if improved else "no change in beat-naive")
    print("-" * 64)
    print(f"  VERDICT: {verdict}")
    print("=" * 64 + "\n")


def cmd_eval(args) -> None:
    from llm_eval.langsmith_push import ensure_dataset, experiment_url, get_client, run_experiment
    records = _load()
    client = get_client()
    ensure_dataset(client, args.dataset_name, records)
    results = run_experiment(client, args.dataset_name, records,
                             experiment_prefix=args.experiment_prefix, max_concurrency=args.max_concurrency,
                             with_judge=getattr(args, "judge", False))
    _print_headline(records)
    print(f"[poc-cli] LangSmith experiment: {experiment_url(results) or 'see smith.langchain.com'}")


def cmd_all(args) -> None:
    run_dirs, crashes = cmd_batch(args)
    cmd_join(args, run_dirs=run_dirs, crash_records=crashes)
    cmd_eval(args)


def main() -> None:
    load_dotenv()
    flags = argparse.ArgumentParser(add_help=False)
    flags.add_argument("--reports-root", type=Path, default=None)
    flags.add_argument("--dataset-name", default="changepoint-golden-100")
    flags.add_argument("--experiment-prefix", default="changepoint-100-current")
    flags.add_argument("--max-concurrency", type=int, default=4)
    flags.add_argument("--judge", action="store_true",
                       help="also run the LLM-as-judge (rationale adherence); calls Bedrock per case")
    p = argparse.ArgumentParser(description="100-case POC eval (Topic 2 + Topic 4).", parents=[flags])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("batch", "join", "score", "eval", "all"):
        sub.add_parser(name, parents=[flags])
    snap = sub.add_parser("snapshot", parents=[flags]); snap.add_argument("label")
    cmp = sub.add_parser("compare", parents=[flags])
    cmp.add_argument("baseline"); cmp.add_argument("candidate")
    args = p.parse_args()
    {"batch": cmd_batch, "join": cmd_join, "score": cmd_score, "eval": cmd_eval, "all": cmd_all,
     "snapshot": cmd_snapshot, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    main()
