"""Live agent re-run over the curated set (for MONITORING: change a prompt/tool -> re-run -> score).

Self-contained in src/ailf (no pocs/ import): the 10 curated CSVs + ``curated_metadata.json`` live
under ``eval/data/``. A local contextmanager temporarily points the changepoint dataset loader at
that curated metadata/CSV dir (save/restore — no core/pipeline module is edited), then drives
``run_scenario`` over the curated scenarios with golden absolute splits. Crashes are captured as
self-contained crash records (recovered from the partial events.jsonl), matching the committed
schema so they re-enter scoring as failures.

This is the live counterpart to ``runner.py`` (which REPLAYS the committed records). Use it after a
pipeline change to re-measure the agent and push a fresh experiment.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import ailf.pipelines.changepoint.datasets as _ds_mod
from ailf.core.config.schema import ConfigOverride, RunCredentials
from ailf.pipelines.changepoint.eval.record import build_golden_record, decode_ground_truth_events
from ailf.pipelines.changepoint.eval.scenarios import family_channel

_DATA_DIR = Path(__file__).resolve().parent / "data"
_CURATED_METADATA = _DATA_DIR / "curated_metadata.json"
_CURATED_CSV_DIR = _DATA_DIR / "csv"
DEFAULT_REPORTS_ROOT = Path("reports/changepoint")
_SEED = 1729


@contextmanager
def curated_dataset():
    """Temporarily point the changepoint loader at the curated metadata + CSV dir (save/restore)."""
    saved = (_ds_mod._METADATA_PATH, _ds_mod._CSV_DIR, _ds_mod._DATA_DIR)
    _ds_mod._METADATA_PATH = _CURATED_METADATA
    _ds_mod._CSV_DIR = _CURATED_CSV_DIR
    _ds_mod._DATA_DIR = _DATA_DIR
    try:
        yield
    finally:
        _ds_mod._METADATA_PATH, _ds_mod._CSV_DIR, _ds_mod._DATA_DIR = saved


def curated_metadata() -> list[dict[str, Any]]:
    return json.loads(_CURATED_METADATA.read_text())["scenarios"]


def curated_scenario_ids() -> list[str]:
    return [m["scenario_id"] for m in curated_metadata()]


def ground_truth(scenario_id: str) -> dict[str, Any]:
    """Held-out ground truth + split facts for a curated scenario (from curated_metadata.json)."""
    for m in curated_metadata():
        if m["scenario_id"] == scenario_id:
            a = m.get("audit_only", {})
            return {"scenario_id": scenario_id,
                    "expected_intervention_family": a.get("expected_intervention_family"),
                    "true_injected_boundaries": a.get("true_injected_boundaries", []),
                    "note": a.get("note", ""), "train_end": m["train_end"],
                    "n_changepoints_to_detect": m["n_changepoints_to_detect"],
                    "seasonal_period": m["seasonal_period"],
                    "intended_failure_lever": m.get("intended_failure_lever"),
                    "dev_or_test": m.get("dev_or_test"), "source_bucket": m.get("source_bucket"),
                    "ground_truth_kind": m.get("ground_truth_kind"),
                    "authored_intent_family": a.get("authored_intent_family"),
                    "gate_winner_family": a.get("gate_winner_family")}
    raise KeyError(f"Unknown curated scenario_id: {scenario_id!r}")


def build_credentials() -> RunCredentials:
    """Bedrock + LangSmith creds from the env (profile-aware), forcing the Bedrock provider."""
    if os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is set — unset it so the agent uses Bedrock (so LangSmith "
                           "auto-traces the LangGraph node tree).")
    import boto3  # noqa: PLC0415
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2"
    session = boto3.Session(profile_name=os.getenv("AWS_PROFILE") or None)
    region = os.getenv("AWS_REGION") or session.region_name or region
    c = session.get_credentials()
    fc = c.get_frozen_credentials() if c else None
    if fc and fc.token:  # temporary creds can't ride the typed BYO path -> ambient chain
        os.environ.setdefault("AWS_ACCESS_KEY_ID", fc.access_key or "")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", fc.secret_key or "")
        os.environ["AWS_SESSION_TOKEN"] = fc.token
        aws = {}
    elif fc:
        aws = {"aws_access_key_id": fc.access_key, "aws_secret_access_key": fc.secret_key, "aws_region": region}
    else:
        raise RuntimeError("No AWS credentials resolved for Bedrock. Set AWS_PROFILE or AWS_ACCESS_KEY_ID/SECRET.")
    return RunCredentials(**aws, langsmith_tracing=bool(os.getenv("LANGSMITH_API_KEY")),
                          langsmith_api_key=os.getenv("LANGSMITH_API_KEY"),
                          langsmith_project=os.getenv("LANGSMITH_PROJECT", "agent-in-the-loop-forecasting"))


def _recover_from_events(run_dir: Path) -> dict[str, Any]:
    """Recover proposals + split from a crashed run's partial events.jsonl (no agent_trace.json)."""
    path = Path(run_dir) / "events.jsonl"
    if not path.exists():
        return {"proposals": [], "n_iterations": 0, "repeated_blocked_tool": False,
                "split": {"train_end": None, "fit_end": None}, "last_stage": None}
    decisions, validations, split, last_stage = {}, {}, {"train_end": None, "fit_end": None}, None
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        last_stage = ev.get("stage", last_stage)
        payload = ev.get("payload", {})
        if isinstance(payload, dict) and "$ref" in payload:
            ref = Path(run_dir) / payload["$ref"].split("/", 1)[-1]
            payload = json.loads(ref.read_text()) if ref.exists() else {}
        stage = ev.get("stage")
        if stage == "split_built":
            d = (payload.get("provenance", payload) or {}).get("derived", {})
            split = {"train_end": d.get("train_end"), "fit_end": d.get("fit_end")}
        elif stage == "decision_iteration" and payload.get("i") is not None:
            decisions[payload["i"]] = payload
        elif stage == "validation_outcome" and payload.get("i") is not None:
            validations[payload["i"]] = payload
    proposals = []
    for i in sorted(decisions):
        prop = decisions[i].get("proposal", {})
        v = validations.get(i, {})
        proposals.append({"i": i, "tool": prop.get("tool"), "params": prop.get("params"),
                          "rejected_reason": v.get("rejected_reason")})
    tool_counts = Counter(p["tool"] for p in proposals if p["tool"])
    repeated = any(cnt >= 2 and all("precondition failed" in (p["rejected_reason"] or "")
                                    for p in proposals if p["tool"] == tool)
                   for tool, cnt in tool_counts.items())
    return {"proposals": proposals, "n_iterations": len(decisions),
            "repeated_blocked_tool": bool(repeated), "split": split, "last_stage": last_stage}


def build_crash_record(scenario_id: str, exception: BaseException, run_dir: Path, gt: dict) -> dict[str, Any]:
    """Synthesize a self-contained crash golden record (scores as a failure, carries crash_info)."""
    rec = _recover_from_events(run_dir)
    exc_type, msg = type(exception).__name__, str(exception)
    crash_stage = ("validation" if exc_type == "IndexError"
                   else "final_eval" if "precondition failed" in msg else "unknown")
    family = gt.get("expected_intervention_family")
    return {
        "record_schema_version": "1.0-crash", "run_id": f"{scenario_id}-{_SEED}",
        "scenario_id": scenario_id, "seed": _SEED,
        "ground_truth": {
            "expected_intervention_family": family, "family_channel": family_channel(family),
            "true_injected_boundaries_raw": gt.get("true_injected_boundaries", []),
            "ground_truth_events": decode_ground_truth_events(family, gt.get("true_injected_boundaries", [])),
            "n_changepoints_to_detect": gt.get("n_changepoints_to_detect"),
            "seasonal_period": gt.get("seasonal_period"), "note": gt.get("note", ""),
            "intended_failure_lever": gt.get("intended_failure_lever"), "dev_or_test": gt.get("dev_or_test"),
            "source_bucket": gt.get("source_bucket"), "ground_truth_kind": gt.get("ground_truth_kind"),
            "authored_intent_family": gt.get("authored_intent_family"), "gate_winner_family": gt.get("gate_winner_family")},
        "prediction": {"chosen_tool": None, "chosen_tool_params": {}, "final_case": "crashed",
                       "is_fallback": False, "n_iterations": rec["n_iterations"], "detected_changepoints": [],
                       "candidate_event_blocks": [], "candidate_drift_intervals": [], "split": rec["split"],
                       "proposals_recovered": rec["proposals"]},
        "outcome": {"winner": None, "beat_naive": False, "agent_is_winner": False, "horizon": None,
                    "agent_test_metrics": {}, "naive_test_metrics": {}, "full_history_prophet_test_metrics": {},
                    "agent_minus_naive_mae": 0.0},
        "crash_info": {"exception_type": exc_type, "message": msg, "crash_stage": crash_stage,
                       "n_iterations": rec["n_iterations"], "repeated_blocked_tool": rec["repeated_blocked_tool"],
                       "last_stage": rec["last_stage"]},
        "judged_iteration": _judged_from_proposals(rec["proposals"]),
    }


def _judged_from_proposals(proposals: list[dict]) -> dict[str, Any]:
    """Best-effort judged_iteration for a crash (events carry no rationale text) -> empty so the
    judge yields n/a, consistent with the committed crash records."""
    return {"rationale": "", "tool_argued_for": "", "diag": {}}


def run_curated_live(scenario_ids: list[str] | None = None, *,
                     reports_root: Path | None = None) -> list[dict[str, Any]]:
    """Re-run the AGENT over the curated scenarios (Bedrock, tracing on) and return fresh golden
    records (self-contained schema-1.1; crashes captured). This is the monitoring path: it reflects
    the CURRENT pipeline behavior, so a prompt/tool fix shows up in the records + score."""
    from ailf.pipelines.changepoint.pipeline import run_scenario  # noqa: PLC0415
    creds = build_credentials()
    reports_root = reports_root or DEFAULT_REPORTS_ROOT
    sids = scenario_ids or curated_scenario_ids()
    records: list[dict[str, Any]] = []
    with curated_dataset():
        for k, sid in enumerate(sids, 1):
            print(f"[live] ({k}/{len(sids)}) running {sid} ...")
            run_dir = Path(reports_root) / f"{sid}-{_SEED}"
            try:
                run_scenario(sid, credentials=creds, reports_root=reports_root,
                             override=ConfigOverride(seed=_SEED))
                records.append(build_golden_record(run_dir, gt_loader=ground_truth))
            except Exception as exc:  # noqa: BLE001 — capture crash as a failure record
                print(f"[live]   ERROR on {sid}: {type(exc).__name__}: {exc}")
                records.append(build_crash_record(sid, exc, run_dir, ground_truth(sid)))
    return records
