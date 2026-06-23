"""Run the changepoint agent over the POC-generated dataset using EXACT golden absolute splits.

The pipeline's metadata-path branch (run_scenario without series_df) reads the committed metadata
via module-level path constants in ailf...datasets. Rather than the series_df ratio path (which
floor-rounds train_end and would break the Topic-1 train_end assertion for LONG series), we point
those path constants at the POC dataset for the duration of the run — no core edits, exact splits.

This keeps run_scenario's golden_split_from_metadata path, so realized train_end == our metadata
train_end exactly.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import ailf.pipelines.changepoint.datasets as ds_mod

POC_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
POC_METADATA = POC_DATA_DIR / "scenario_metadata.json"
POC_CSV_DIR = POC_DATA_DIR / "csv"


@contextmanager
def poc_dataset():
    """Temporarily point ailf's changepoint loader at the POC dataset (metadata + CSV dir)."""
    saved = (ds_mod._METADATA_PATH, ds_mod._CSV_DIR, ds_mod._DATA_DIR)
    ds_mod._METADATA_PATH = POC_METADATA
    ds_mod._CSV_DIR = POC_CSV_DIR
    ds_mod._DATA_DIR = POC_DATA_DIR
    try:
        yield
    finally:
        ds_mod._METADATA_PATH, ds_mod._CSV_DIR, ds_mod._DATA_DIR = saved


def poc_scenario_ids() -> list[str]:
    return [m["scenario_id"] for m in json.loads(POC_METADATA.read_text())["scenarios"]]


def poc_ground_truth(scenario_id: str) -> dict:
    for m in json.loads(POC_METADATA.read_text())["scenarios"]:
        if m["scenario_id"] == scenario_id:
            a = m["audit_only"]
            return {"scenario_id": scenario_id,
                    "expected_intervention_family": a.get("expected_intervention_family"),
                    "true_injected_boundaries": a.get("true_injected_boundaries", []),
                    "note": a.get("note", ""), "train_end": m["train_end"],
                    "n_changepoints_to_detect": m["n_changepoints_to_detect"],
                    "seasonal_period": m["seasonal_period"],
                    "intended_failure_lever": m.get("intended_failure_lever"),
                    "dev_or_test": m.get("dev_or_test"),
                    "source_bucket": m.get("source_bucket"),
                    "ground_truth_kind": m.get("ground_truth_kind"),
                    "authored_intent_family": a.get("authored_intent_family"),
                    "gate_winner_family": a.get("gate_winner_family")}
    raise KeyError(f"Unknown POC scenario_id: {scenario_id!r}")


def _recover_from_events(run_dir: Path) -> dict:
    """Recover the agent's proposals + split from a crashed run's partial events.jsonl.

    A crash leaves no agent_trace.json/metrics.json (written only on success), but FileEventSink
    flushes each event, so decision_iteration / validation_outcome / split_built survive. Returns
    {proposals, n_iterations, repeated_blocked_tool, split, last_stage}."""
    path = Path(run_dir) / "events.jsonl"
    if not path.exists():
        return {"proposals": [], "n_iterations": 0, "repeated_blocked_tool": False,
                "split": {"train_end": None, "fit_end": None}, "last_stage": None}
    decisions: dict[int, dict] = {}
    validations: dict[int, dict] = {}
    split = {"train_end": None, "fit_end": None}
    last_stage = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        last_stage = ev.get("stage", last_stage)
        payload = ev.get("payload", {})
        if isinstance(payload, dict) and "$ref" in payload:  # offloaded large payload
            ref = Path(run_dir) / payload["$ref"].split("/", 1)[-1]
            payload = json.loads(ref.read_text()) if ref.exists() else {}
        stage = ev.get("stage")
        if stage == "split_built":
            derived = (payload.get("provenance", payload) or {}).get("derived", {})
            split = {"train_end": derived.get("train_end"), "fit_end": derived.get("fit_end")}
        elif stage == "decision_iteration":
            i = payload.get("i")
            if i is not None:
                decisions[i] = payload
        elif stage == "validation_outcome":
            i = payload.get("i")
            if i is not None:
                validations[i] = payload
    proposals = []
    for i in sorted(decisions):
        prop = decisions[i].get("proposal", {})
        v = validations.get(i, {})
        proposals.append({"i": i, "tool": prop.get("tool"), "params": prop.get("params"),
                          "action_signature": prop.get("action_signature"),
                          "rejected_reason": v.get("rejected_reason"), "beat_naive": v.get("beat_naive")})
    # repeated_blocked_tool: same TOOL proposed >=2x (params may differ — the agent tweaks priors),
    # and EVERY one of those repeats was precondition-rejected. Keys on tool name, NOT action_signature
    # (identical-params would miss the real loop, where the agent retries the same blocked tool with
    # different params).
    from collections import Counter
    tool_counts = Counter(p["tool"] for p in proposals if p["tool"])
    repeated = any(
        cnt >= 2 and all(
            "precondition failed" in (p["rejected_reason"] or "")
            for p in proposals if p["tool"] == tool
        )
        for tool, cnt in tool_counts.items()
    )
    return {"proposals": proposals, "n_iterations": len(decisions),
            "repeated_blocked_tool": bool(repeated), "split": split, "last_stage": last_stage}


def build_crash_record(scenario_id: str, exception: BaseException, run_dir: Path, gt: dict) -> dict:
    """Synthesize a golden record for a CRASHED run so it scores as a failure (beat_naive=False) and
    carries a crash_info block the failure-mode classifier keys off. Recovers proposals from the
    partial events.jsonl. Shape matches build_golden_record so evaluators/summarize don't KeyError."""
    from llm_eval.golden import decode_ground_truth_events
    from llm_eval.scenarios import family_channel

    rec = _recover_from_events(run_dir)
    exc_type = type(exception).__name__
    msg = str(exception)
    # crash_stage: ToolBoundsError ("precondition failed") escapes from final_evaluation (bug#3);
    # IndexError escapes from validation_node (bug#1).
    if exc_type == "IndexError":
        crash_stage = "validation"
    elif "precondition failed" in msg:
        crash_stage = "final_eval"
    else:
        crash_stage = "unknown"

    family = gt.get("expected_intervention_family")
    return {
        "record_schema_version": "1.0-crash",
        "run_id": f"{scenario_id}-1729",
        "scenario_id": scenario_id,
        "seed": 1729,
        "ground_truth": {
            "expected_intervention_family": family,
            "family_channel": family_channel(family),
            "true_injected_boundaries_raw": gt.get("true_injected_boundaries", []),
            "ground_truth_events": decode_ground_truth_events(family, gt.get("true_injected_boundaries", [])),
            "n_changepoints_to_detect": gt.get("n_changepoints_to_detect"),
            "seasonal_period": gt.get("seasonal_period"),
            "note": gt.get("note", ""),
            "intended_failure_lever": gt.get("intended_failure_lever"),
            "dev_or_test": gt.get("dev_or_test"),
            "source_bucket": gt.get("source_bucket"),
            "ground_truth_kind": gt.get("ground_truth_kind"),
            "authored_intent_family": gt.get("authored_intent_family"),
            "gate_winner_family": gt.get("gate_winner_family"),
        },
        "prediction": {
            "chosen_tool": None,                  # run never accepted/scored a tool
            "chosen_tool_params": {},
            "final_case": "crashed",
            "is_fallback": False,
            "n_iterations": rec["n_iterations"],
            "detected_changepoints": [],
            "candidate_event_blocks": [],         # evaluators read these directly -> must exist
            "candidate_drift_intervals": [],
            "split": rec["split"],
            "proposals_recovered": rec["proposals"],   # informational; no evaluator reads it
        },
        "outcome": {
            "winner": None,
            "beat_naive": False,                  # scores the case as a failure
            "agent_is_winner": False,
            "horizon": None,
            "agent_test_metrics": {},
            "naive_test_metrics": {},
            "full_history_prophet_test_metrics": {},
            "agent_minus_naive_mae": 0.0,
        },
        "crash_info": {
            "exception_type": exc_type,
            "message": msg,
            "crash_stage": crash_stage,
            "n_iterations": rec["n_iterations"],
            "repeated_blocked_tool": rec["repeated_blocked_tool"],
            "last_stage": rec["last_stage"],
        },
        "trace_path": None,
        "metrics_path": None,
    }


def run_all_poc(scenario_ids: list[str] | None = None, *,
                reports_root: Path | None = None) -> tuple[list[str], list[dict]]:
    """Run the agent over POC scenarios via the metadata path (exact golden splits).

    Returns (run_dirs, crash_records): successful runs leave a run dir; a crashed run is captured
    as a synthesized crash golden record (recovered from its partial events.jsonl) so it re-enters
    the corpus and scores as a failure."""
    from ailf.pipelines.changepoint.pipeline import run_scenario  # noqa: PLC0415
    from llm_eval.batch import DEFAULT_REPORTS_ROOT, build_credentials

    creds = build_credentials()
    reports_root = reports_root or DEFAULT_REPORTS_ROOT
    sids = scenario_ids or poc_scenario_ids()
    run_dirs: list[str] = []
    crash_records: list[dict] = []
    with poc_dataset():
        for k, sid in enumerate(sids, 1):
            print(f"[poc-batch] ({k}/{len(sids)}) running {sid}...")
            try:
                report = run_scenario(sid, credentials=creds, reports_root=reports_root)
                run_dirs.append(report["run_dir"])
            except Exception as exc:  # noqa: BLE001 — capture the crash as a failure record
                print(f"[poc-batch]   ERROR on {sid}: {type(exc).__name__}: {exc}")
                try:
                    rec = build_crash_record(sid, exc, Path(reports_root) / f"{sid}-1729", poc_ground_truth(sid))
                    crash_records.append(rec)
                    print(f"[poc-batch]   captured crash record ({rec['crash_info']['exception_type']}/"
                          f"{rec['crash_info']['crash_stage']}, repeated_blocked={rec['crash_info']['repeated_blocked_tool']})")
                except Exception as cap_exc:  # noqa: BLE001
                    print(f"[poc-batch]   could not capture crash record for {sid}: {cap_exc}")
    return run_dirs, crash_records
