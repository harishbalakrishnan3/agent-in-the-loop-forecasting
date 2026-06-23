"""Generate-then-verify driver: instantiate recipe families into ~100 admitted cases, write CSVs +
POC scenario_metadata.json (mirrors export_scenario_csvs.py shape so the MVP loader/runner work).

Each instance: build a base_signal(seed) + run its recipe at the first knob the gate ADMITS in the
intended bucket (re-rolling knobs; skip-and-log if none lands). The gold expected_intervention_family
is the GATE-WINNER (authored intent recorded separately). Seeds are disjoint per dev/test/fresh.
"""

from __future__ import annotations

import argparse
import hashlib
import json

import pandas as pd

from generator import base, catalog
from generator.verify import label_case

# Target counts per recipe-family (index into catalog.RECIPE_FAMILIES order). Tuned to ~100 total
# once real.py adds ~10. dev:test ~60:40 within each family.
PER_FAMILY = {
    0: 11, 1: 11, 2: 11,   # competence (33)
    3: 13, 4: 12,          # prompt (25)
    5: 10, 6: 10,          # pipeline (20)
    7: 5, 8: 4, 9: 3,      # tool / unsolvable (12) ; real.py adds the rest of the bucket
}
SEED_BASE = {"dev": 1000, "test": 2000, "fresh": 3000}


def _sha256(df: pd.DataFrame) -> str:
    out = df.copy()
    out["ds"] = out["ds"].dt.strftime("%Y-%m-%d")
    return hashlib.sha256(out.to_csv(index=False).encode()).hexdigest()


def _csv_text(df: pd.DataFrame) -> str:
    out = df.copy()
    out["ds"] = out["ds"].dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False)


def _dev_or_test(i: int, total: int) -> str:
    return "dev" if i < round(total * 0.6) else "test"


def _seed_for(fam_idx: int, i: int, partition: str) -> int:
    """Deterministic per-case seed (no Python hash() — it's salted per process, breaking repro)."""
    return SEED_BASE.get(partition, 1000) + fam_idx * 50 + i


def _build_one(fam: dict, fam_idx: int, i: int, partition: str) -> tuple:
    """Instantiate one case and LABEL it by what the gate actually proves (never rejects).

    Picks the knob whose gate outcome best matches the recipe's INTENT (for unsolvable families,
    the largest knob that the gate still calls 'fallback'; for solvable families, the first knob
    that yields a clear single-family winner) — but always returns a labeled case.
    Returns (df, gt_events, resolved_family, report).
    """
    seed = _seed_for(fam_idx, i, "dev" if partition in ("dev", "test") else partition)
    recipe = fam["make"](i)
    want_unsolvable = fam["draft"] == "fallback"
    last = None
    for knob in fam["knobs"]:
        df = base.base_signal(fam["len"], seed)
        gt_events = recipe(df, knob)
        res = label_case(df, train_end=fam["te"], val_h=base.VALIDATION_HORIZON,
                         test_h=base.TEST_HORIZON, n_cps=fam["n_cps"],
                         seasonal_period=base.SEASONAL_PERIOD)
        last = (df, gt_events, res["resolved_family"], res["report"])
        if want_unsolvable and res["is_unsolvable"]:
            return last  # found a knob the gate confirms is out-of-vocabulary
        if (not want_unsolvable) and not res["is_unsolvable"]:
            return last  # found a knob the gate confirms is solvable
    return last  # fall back to the last knob's labeling (still a valid, gate-labeled case)


def _gt_to_boundaries(gt_events: list[dict], family: str | None) -> list[int]:
    """Flatten decoded GT events back to the flat true_injected_boundaries the MVP join re-decodes.
    For fallback / objective the boundaries are empty."""
    if family in ("full_history_step_regressor", "full_history_prophet_tuned_holidays"):
        return [e["index"] for e in gt_events if e["kind"] == "point"]
    if family in ("full_history_ramp_regressor", "full_history_clean_event"):
        out: list[int] = []
        for e in gt_events:
            if e["kind"] == "interval":
                out += [e["start"], e["end"]]
        return out
    return []


def write_all(partition: str = "dev") -> dict:
    base.CSV_DIR.mkdir(parents=True, exist_ok=True)
    scenarios_meta: list[dict] = []
    skipped: list[str] = []
    for fam_idx, fam in enumerate(catalog.RECIPE_FAMILIES):
        n = PER_FAMILY[fam_idx]
        for i in range(n):
            part = _dev_or_test(i, n) if partition == "dev" else partition
            base_id = f"{fam['lever']}_{fam['note'].split()[0].lower()}_{fam_idx}_{i}"
            df, gt_events, resolved_family, report = _build_one(fam, fam_idx, i, part)
            # for unsolvable, resolved is 'fallback'; boundaries empty
            boundaries = _gt_to_boundaries(gt_events, resolved_family)
            sid = base_id
            csv_path = base.CSV_DIR / f"{sid}.csv"
            csv_path.write_text(_csv_text(df))
            te = fam["te"]
            scenarios_meta.append({
                "scenario_id": sid,
                "title": f"{fam['lever']}: {fam['note']}",
                "csv_path": str(csv_path.relative_to(base.REPO_ROOT)),
                "schema": {"date_column": "ds", "target_column": "y", "frequency": "D"},
                "row_count": fam["len"],
                "train_end": te,
                "test_horizon": base.TEST_HORIZON,
                "validation_horizon": base.VALIDATION_HORIZON,
                "n_changepoints_to_detect": fam["n_cps"],
                "seasonal_period": base.SEASONAL_PERIOD,
                "csv_sha256": _sha256(df),
                # eval/lever fields:
                "intended_failure_lever": fam["lever"],
                "dev_or_test": part,
                "source_bucket": fam["bucket"],
                "ground_truth_kind": "objective_only" if resolved_family == "fallback" else "boundary_and_objective",
                "audit_only": {
                    "note": fam["note"],
                    "true_injected_boundaries": boundaries,
                    "expected_intervention_family": resolved_family,
                    "authored_intent_family": fam["draft"],
                    "gate_winner_family": report.get("winning_family"),
                    "naive_val_mae": round(report["naive_val_mae"], 4),
                },
            })
            print(f"[gen] OK {sid}: family={resolved_family} (authored={fam['draft']})")
    return {"scenarios": scenarios_meta, "skipped": skipped}


def merge_and_write_metadata(generated: dict) -> None:
    """Write POC scenario_metadata.json (synthetic + any real cases appended by real.py later)."""
    metadata = {
        "schema_version": "2.0-poc-llm-eval",
        "description": "LLM-eval POC golden dataset: lever-tagged synthetic + unsolvable cases, "
                       "each admitted by the brute-force solvability gate. audit_only must never reach the agent.",
        "scenarios": generated["scenarios"],
    }
    base.METADATA_PATH.write_text(json.dumps(metadata, indent=2))
    print(f"\n[gen] wrote {len(generated['scenarios'])} cases -> {base.METADATA_PATH} "
          f"({len(generated['skipped'])} skipped)")


def main() -> None:
    p = argparse.ArgumentParser(description="Generate the LLM-eval POC dataset (synthetic + unsolvable).")
    p.add_argument("--partition", default="dev", help="dev (mixes dev/test) | fresh (generalization)")
    args = p.parse_args()
    gen = write_all(partition=args.partition)
    merge_and_write_metadata(gen)


if __name__ == "__main__":
    main()
