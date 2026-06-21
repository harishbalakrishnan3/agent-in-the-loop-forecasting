"""End-to-end pipeline for the seasonalityV2 POC.

Orchestrates: dataset → stats → naive → agent loop → decision matrix → artefacts.

Leakage guard: test_df is NEVER passed to any function until after run_agent_loop returns.

Usage
-----
    # Run with defaults:
    uv run python -m pocs.changepoint.seasonalityV2.pipeline

    # Custom seed:
    uv run python -m pocs.changepoint.seasonalityV2.pipeline --seed 7

    # Debug (extra logging):
    uv run python -m pocs.changepoint.seasonalityV2.pipeline --seed 42 --debug
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import warnings
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Silence noisy loggers before importing prophet
# ---------------------------------------------------------------------------
logging.getLogger("prophet").setLevel(logging.ERROR)
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

# Add the POC directory to sys.path so same-dir imports work when run as __main__
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from agent import ProphetConfig, fit_and_score_test, run_agent_loop
from config import DEFAULT_SEED, load_config
from datasets import generate_dataset, split_dataset
from decision import build_decision_matrix, decision_matrix_to_dict, print_decision_matrix
from naive import run_naive_prophet
from stats import extract_stats, stats_to_dict
from viz import plot_results, viz_dataset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config_hash(df: pd.DataFrame, seed: int) -> str:
    """Deterministic short hash of dataset + seed for run_summary."""
    h = hashlib.md5(usedforsecurity=False)
    h.update(str(seed).encode())
    h.update(df["y"].values.tobytes())
    return h.hexdigest()[:8]


def _agent_val_mae_from_trace(trace: list) -> float:
    """Extract the val_mae of the accepted or best proposal from the trace."""
    scored = [r for r in trace if r.val_mae is not None]
    if not scored:
        return float("inf")
    accepted = [r for r in scored if r.decision == "accepted"]
    if accepted:
        return accepted[-1].val_mae
    return min(r.val_mae for r in scored)


def _build_run_summary(
    seed: int,
    config_hash: str,
    dm,
    accepted_config: ProphetConfig,
    trace: list,
) -> dict:
    scored = [r for r in trace if r.val_mae is not None]
    accepted = [r for r in trace if r.decision == "accepted"]

    return {
        "seed": seed,
        "dataset_config_hash": config_hash,
        "naive_val_mae": dm.naive_val_mae,
        "agent_val_mae": dm.agent_val_mae,
        "naive_test_mae": dm.naive_test_mae,
        "agent_test_mae": dm.agent_test_mae,
        "pct_improvement_val": dm.pct_improvement_val,
        "pct_improvement_test": dm.pct_improvement_test,
        "agent_beats_naive_on_val": dm.agent_beats_naive_on_val,
        "accepted_config": accepted_config.model_dump(),
        "n_iterations": len(trace),
        "n_accepted": len(accepted),
        "final_case": "accepted_beat_naive" if accepted else "best_proposal_no_beat",
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(seed: int = DEFAULT_SEED, debug: bool = False) -> Path:
    """Run the full pipeline and return the path to the run directory.

    Steps
    -----
    1  Generate dataset + split
    2  Save dataset.csv + viz_dataset.html
    3  Extract training-only stats → stats.json
    4  Naive Prophet baseline (val only — no test yet)
    5  Agent loop (never sees test_df or naive_val_mae)
    6  Save trace.json
    7  Final test evaluation (first and only time test_df is used)
    8  Decision matrix → decision_matrix.json + stdout
    9  Results visualisation → viz_results.html
    10 Run summary → run_summary.json
    """
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("pipeline")

    # -----------------------------------------------------------------------
    # 1. Dataset
    # -----------------------------------------------------------------------
    log.info(f"Generating dataset (seed={seed})...")
    df, meta = generate_dataset(seed=seed)
    train_df, val_df, test_df = split_dataset(df, meta)

    log.info(
        f"  train={len(train_df)}  val={len(val_df)}  test={len(test_df)} "
        f"  train_end={meta['train_end'].date()}  val_end={meta['val_end'].date()}"
    )

    # -----------------------------------------------------------------------
    # Run directory
    # -----------------------------------------------------------------------
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = _HERE / "runs" / f"{ts}-seed{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"  Run directory: {run_dir}")

    # -----------------------------------------------------------------------
    # 2. Artefacts: dataset.csv + viz_dataset.html
    # -----------------------------------------------------------------------
    df.to_csv(run_dir / "dataset.csv", index=False)
    log.info("  Saved dataset.csv")

    fig1 = viz_dataset(df, meta)
    fig1.write_html(str(run_dir / "viz_dataset.html"))
    log.info("  Saved viz_dataset.html")

    # -----------------------------------------------------------------------
    # 3. Stats extraction (training only — never val/test)
    # -----------------------------------------------------------------------
    log.info("Extracting training statistics...")
    bundle = extract_stats(train_df, list(meta["changepoints"].values()))
    stats_dict = stats_to_dict(bundle)
    (run_dir / "stats.json").write_text(json.dumps(stats_dict, indent=2))
    log.info(
        f"  seasonality_mode_signal={bundle.seasonality_mode_signal:.3f}  "
        f"post_last_cp_days={bundle.post_last_cp_days}  "
        f"variance_ratio={bundle.variance_ratio:.2f}"
    )

    # -----------------------------------------------------------------------
    # 4. Naive baseline (val only — test_df NOT passed here)
    # -----------------------------------------------------------------------
    log.info("Running naive Prophet baseline (val only)...")
    naive_result = run_naive_prophet(train_df, val_df, seed=seed)
    log.info(f"  naive val_mae={naive_result.val_mae:.4f}")

    # -----------------------------------------------------------------------
    # 5 & 6. Agent loop
    # -----------------------------------------------------------------------
    log.info("Starting agent loop...")
    cfg = load_config(seed=seed)
    log.info(f"  model_id={cfg.model_id}  region={cfg.aws_region}")

    accepted_config, trace = run_agent_loop(
        bundle, train_df, val_df, naive_result.val_mae, cfg
    )

    (run_dir / "trace.json").write_text(
        json.dumps([asdict(r) for r in trace], indent=2)
    )
    log.info(f"  Agent loop complete: {len(trace)} iteration(s)")
    for r in trace:
        log.info(
            f"    iter={r.iteration}  decision={r.decision}  "
            f"val_mae={f'{r.val_mae:.4f}' if r.val_mae is not None else 'N/A'}"
        )

    # -----------------------------------------------------------------------
    # 7. Final test evaluation (FIRST time test_df is used — leakage guard)
    # -----------------------------------------------------------------------
    log.info("Running final test evaluation...")
    naive_final = run_naive_prophet(train_df, val_df, test_df=test_df, seed=seed)
    agent_test_mae, agent_test_fc = fit_and_score_test(
        accepted_config, train_df, val_df, test_df
    )
    log.info(f"  naive test_mae={naive_final.test_mae:.4f}  agent test_mae={agent_test_mae:.4f}")

    # -----------------------------------------------------------------------
    # 8. Decision matrix
    # -----------------------------------------------------------------------
    agent_val_mae = _agent_val_mae_from_trace(trace)
    dm = build_decision_matrix(
        naive_val_mae=naive_result.val_mae,
        agent_val_mae=agent_val_mae,
        naive_test_mae=naive_final.test_mae,
        agent_test_mae=agent_test_mae,
    )
    print_decision_matrix(dm)
    (run_dir / "decision_matrix.json").write_text(
        json.dumps(decision_matrix_to_dict(dm), indent=2)
    )

    # -----------------------------------------------------------------------
    # 9. Results visualisation
    # -----------------------------------------------------------------------
    fig2 = plot_results(
        train_df, val_df, test_df,
        naive_final.test_forecast,
        agent_test_fc,
        meta, dm,
    )
    fig2.write_html(str(run_dir / "viz_results.html"))
    log.info("  Saved viz_results.html")

    # -----------------------------------------------------------------------
    # 10. Run summary
    # -----------------------------------------------------------------------
    config_hash = _config_hash(df, seed)
    summary = _build_run_summary(seed, config_hash, dm, accepted_config, trace)
    (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2))
    log.info("  Saved run_summary.json")

    log.info(f"\nRun complete. Artefacts: {run_dir}")
    log.info(f"agent_beats_naive_on_val = {dm.agent_beats_naive_on_val}")

    return run_dir


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="seasonalityV2 POC — agent beats naive Prophet"
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED,
        help=f"Random seed (default: {DEFAULT_SEED})"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable DEBUG logging"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_dir = run(seed=args.seed, debug=args.debug)
    print(f"\nAll artefacts written to: {run_dir}")
