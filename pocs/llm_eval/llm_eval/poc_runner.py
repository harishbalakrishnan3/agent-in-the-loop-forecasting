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


def run_all_poc(scenario_ids: list[str] | None = None, *, reports_root: Path | None = None) -> list[str]:
    """Run the agent over POC scenarios via the metadata path (exact golden splits). Returns run dirs."""
    from ailf.pipelines.changepoint.pipeline import run_scenario  # noqa: PLC0415
    from llm_eval.batch import DEFAULT_REPORTS_ROOT, build_credentials

    creds = build_credentials()
    reports_root = reports_root or DEFAULT_REPORTS_ROOT
    sids = scenario_ids or poc_scenario_ids()
    run_dirs: list[str] = []
    with poc_dataset():
        for k, sid in enumerate(sids, 1):
            print(f"[poc-batch] ({k}/{len(sids)}) running {sid}...")
            try:
                report = run_scenario(sid, credentials=creds, reports_root=reports_root)
                run_dirs.append(report["run_dir"])
            except Exception as exc:  # noqa: BLE001 — one bad case shouldn't kill the whole batch
                print(f"[poc-batch]   ERROR on {sid}: {type(exc).__name__}: {exc}")
    return run_dirs
