"""Stability harness: run each FAILURE_MODES.md datapoint N times and record how the agent's
chosen tool + beat-naive verdict vary run-to-run.

WHY runs differ: the deterministic prelude (detect/diagnostics/baselines) is seeded
(pipeline.py:226-227) so it's identical every run, but the LLM has NO temperature and NO seed
(llm.py:145 — Opus rejects temperature; Bedrock Claude has no deterministic seed), so the agent's
*decisions* are genuinely nondeterministic. This measures that.

Parallelised with ProcessPoolExecutor (each worker is its own process, so the poc_dataset()
monkeypatch + the seeded prelude don't race). Each run uses a unique reports_root so distinct runs
of the same (scenario, seed) don't overwrite each other.

Run:  PYTHONPATH=pocs/llm_eval uv run python -m stability_check --repeats 5
"""

from __future__ import annotations

import argparse
import json
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

warnings.filterwarnings("ignore")

SCENARIOS = [
    "competence_clean_0_0", "competence_clean_0_1", "competence_clean_0_10",
    "competence_clean_0_4", "pipeline_t2_5_0", "pipeline_t2_5_6",
    "pipeline_t2_5_8", "tool_growing_7_1",
]


def _one_run(args: tuple[str, int]) -> dict:
    """Worker: run one scenario once (own process). Returns chosen tool + verdict, or the crash."""
    import logging
    logging.disable(logging.CRITICAL)
    sid, rep = args
    from llm_eval.poc_runner import poc_dataset
    from llm_eval.batch import build_credentials
    from ailf.pipelines.changepoint.pipeline import run_scenario
    reports_root = Path(f"reports/_stability/{sid}/rep{rep}")
    try:
        creds = build_credentials()
        with poc_dataset():
            report = run_scenario(sid, credentials=creds, reports_root=reports_root)
        fe = report.get("final_eval", {})
        agent_mae = fe.get("agent", {}).get("test_metrics", {}).get("mae")
        naive_mae = fe.get("naive_workflow", {}).get("test_metrics", {}).get("mae")
        full_mae = fe.get("full_history_prophet", {}).get("test_metrics", {}).get("mae")
        return {
            "sid": sid, "rep": rep, "ok": True,
            "chosen_tool": fe.get("agent", {}).get("tool"),
            "winner": report.get("winner"),
            "beat_naive_2way": (agent_mae is not None and naive_mae is not None and agent_mae < naive_mae),
            "agent_mae": round(agent_mae, 3) if agent_mae is not None else None,
            "naive_mae": round(naive_mae, 3) if naive_mae is not None else None,
            "full_mae": round(full_mae, 3) if full_mae is not None else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"sid": sid, "rep": rep, "ok": False,
                "crash": f"{type(exc).__name__}: {str(exc)[:80]}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    jobs = [(sid, r) for sid in SCENARIOS for r in range(args.repeats)]
    print(f"[stability] {len(SCENARIOS)} scenarios x {args.repeats} repeats = {len(jobs)} runs, "
          f"{args.workers} workers")
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_one_run, j): j for j in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            results.append(r)
            tag = r.get("chosen_tool") or r.get("crash")
            print(f"[stability] ({i}/{len(jobs)}) {r['sid']} rep{r['rep']}: {tag}")

    # aggregate per scenario
    print("\n" + "=" * 70)
    summary = {}
    for sid in SCENARIOS:
        runs = [r for r in results if r["sid"] == sid]
        from collections import Counter
        tools = Counter(r.get("chosen_tool") if r["ok"] else f"CRASH:{r['crash'].split(':')[0]}" for r in runs)
        winners = Counter(r.get("winner") if r["ok"] else "CRASH" for r in runs)
        beats = sum(1 for r in runs if r.get("ok") and r.get("beat_naive_2way"))
        summary[sid] = {"n": len(runs), "tools": dict(tools), "winners": dict(winners),
                        "beat_naive_2way": f"{beats}/{len([r for r in runs if r['ok']])}",
                        "runs": runs}
        print(f"{sid}")
        print(f"  chosen_tool distribution: {dict(tools)}")
        print(f"  winner distribution:      {dict(winners)}")
        print(f"  beat-naive (2way):        {beats}/{len([r for r in runs if r['ok']])}")
    out = Path("pocs/llm_eval/golden_records/stability.json")
    out.write_text(json.dumps(summary, indent=2))
    print(f"\n[stability] wrote {out}")


if __name__ == "__main__":
    main()
