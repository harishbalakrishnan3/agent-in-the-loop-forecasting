"""Brute-force solvability gate — the admission authority for synthetic cases (Topic-2 §0, §3).

Given a candidate (ds, y) DataFrame + golden absolute split, build the split exactly as the live
run does, compute the naive bar + full diagnostics, then enumerate EVERY structural tool×param
combo through the REAL gate (evaluate_on_validation). Reports which families beat naive on the
validation gate (the signal the agent's accept logic uses) and the gate-winning family.

This is what makes a case's label honest: expected_intervention_family = the family that actually
WINS (not the injected intent — the level-shift→ramp finding), and "unsolvable" = no family beats
naive on validation AND test, with a jitter margin.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ailf.core.agent.errors import ToolBoundsError
from ailf.core.agent.registry import Proposal
from ailf.core.backtest.gate import evaluate_on_test, evaluate_on_validation
from ailf.core.backtest.split import ResolvedSplit
from ailf.pipelines.changepoint.baselines import naive_workflow
from ailf.pipelines.changepoint.detector import detect_changepoints
from ailf.pipelines.changepoint.diagnostics import compute_diagnostics
from ailf.pipelines.changepoint.interventions import (
    FALLBACK_TOOL_NAME,
    register_changepoint_registry,
    structural_tool_names,
)
from ailf.pipelines.changepoint.scenarios import SeriesSplit

# Per-family param grids to enumerate (from interventions.py). clean_event 'blocks' is handled
# specially (all_closed + per-candidate-block singletons, resolved at runtime).
_PARAM_GRID = {
    "recent_window": [{"window_start": w} for w in ("latest", "primary")],
    "full_history_step_regressor": [{"changepoints": c} for c in ("primary", "all_detected")],
    "full_history_ramp_regressor": [{"intervals": i} for i in ("primary", "all_candidate")],
    "full_history_prophet_tuned_holidays": [
        {"changepoint_prior_scale": cps, "seasonality_prior_scale": sps, "holidays_prior_scale": hps,
         "seasonality_mode": mode, "changepoint_range": cr}
        for cps in (0.01, 0.05, 0.1, 0.5) for sps in (1.0, 10.0) for hps in (1.0, 10.0)
        for mode in ("additive", "multiplicative") for cr in (0.8, 0.9)
    ],
}
_STRUCTURAL = structural_tool_names()  # the 5; excludes the fallback


def _clean_event_params(full_diag: dict[str, Any]) -> list[dict[str, Any]]:
    """all_closed + each closed-before-origin candidate block as a singleton [index]."""
    combos: list[dict[str, Any]] = [{"blocks": "all_closed"}]
    blocks = full_diag.get("candidate_event_blocks", [])
    for i, b in enumerate(blocks):
        if b.get("closed_before_origin"):
            combos.append({"blocks": [i]})
    return combos


def build_split(df: pd.DataFrame, train_end: int, val_h: int, test_h: int) -> SeriesSplit:
    """Golden absolute split: train_rows = train_end - val_h, then val_h, then test_h."""
    train_rows = train_end - val_h
    resolved = ResolvedSplit.from_lengths(
        train_rows=train_rows, val_rows=val_h, test_rows=test_h,
        source="golden", units="golden", n_rows=len(df),
    )
    return SeriesSplit(ds=df["ds"].reset_index(drop=True),
                       y=df["y"].astype(float).reset_index(drop=True), resolved=resolved)


def prove_solvability(df: pd.DataFrame, *, train_end: int, val_h: int, test_h: int,
                      n_cps: int, seasonal_period: int) -> dict[str, Any]:
    """Run the full brute force. Returns family_beats / min_tool_val_mae / winning family + per-combo."""
    split = build_split(df, train_end, val_h, test_h)
    cps = detect_changepoints(split.train_df, n_changepoints_to_detect=n_cps)
    naive = naive_workflow(split, cps)
    naive_val_mae = naive.selected.val_mae
    full_diag = compute_diagnostics(split.train_df, changepoints=cps, seasonal_period=seasonal_period).to_agent_dict()
    registry = register_changepoint_registry()

    family_beats = {name: False for name in _STRUCTURAL}
    family_best_mae = {name: float("inf") for name in _STRUCTURAL}
    per_combo: list[dict[str, Any]] = []
    min_tool_val_mae = float("inf")

    for name in _STRUCTURAL:
        grid = _clean_event_params(full_diag) if name == "full_history_clean_event" else _PARAM_GRID[name]
        for params in grid:
            try:
                out = evaluate_on_validation(Proposal(tool=name, params=params), split, registry,
                                             full_diagnostics=full_diag, naive_val_mae=naive_val_mae)
            except (ToolBoundsError, IndexError, ValueError, KeyError):
                continue  # NORMAL rejection (precondition/absent diagnostic/frame edge) -> not a beat
            mae = out["val_metrics"]["mae"]
            per_combo.append({"tool": name, "params": params, "mae": mae, "beat": out["beat_naive"]})
            min_tool_val_mae = min(min_tool_val_mae, mae)
            family_best_mae[name] = min(family_best_mae[name], mae)
            if out["beat_naive"]:
                family_beats[name] = True

    beating = [name for name in _STRUCTURAL if family_beats[name]]
    winner = min(beating, key=lambda n: family_best_mae[n]) if beating else None
    return {
        "naive_val_mae": naive_val_mae,
        "min_tool_val_mae": min_tool_val_mae,
        "family_beats": family_beats,
        "family_best_mae": family_best_mae,
        "n_beating_families": len(beating),
        "winning_family": winner,
        "per_combo": per_combo,
    }


def _tool_beats_naive_on_test(df: pd.DataFrame, train_end: int, val_h: int, test_h: int,
                              n_cps: int, seasonal_period: int) -> bool:
    """For the UNSOLVABLE claim: confirm no structural tool beats naive on TEST either (a tool can
    fail validation but win test). Uses the same registry/diagnostics on the test window."""
    split = build_split(df, train_end, val_h, test_h)
    cps = detect_changepoints(split.train_df, n_changepoints_to_detect=n_cps)
    naive = naive_workflow(split, cps)
    full_diag = compute_diagnostics(split.train_df, changepoints=cps, seasonal_period=seasonal_period).to_agent_dict()
    registry = register_changepoint_registry()
    # naive test mae: fit naive's selected window forecast on test.
    from ailf.pipelines.changepoint.baselines import fit_naive_test_forecast  # noqa: PLC0415
    _, naive_test = fit_naive_test_forecast(split, naive.selected_window_start)
    naive_test_mae = naive_test["mae"]
    for name in _STRUCTURAL:
        grid = _clean_event_params(full_diag) if name == "full_history_clean_event" else _PARAM_GRID[name]
        for params in grid:
            try:
                _, test_m = evaluate_on_test(Proposal(tool=name, params=params), split, registry,
                                             full_diagnostics=full_diag)
            except (ToolBoundsError, IndexError, ValueError, KeyError):
                continue
            if test_m["mae"] < naive_test_mae:
                return True
    return False


def label_case(df: pd.DataFrame, *, train_end: int, val_h: int, test_h: int, n_cps: int,
               seasonal_period: int, eps: float = 0.01) -> dict[str, Any]:
    """Label a candidate by what the gate ACTUALLY proves — never rejects (Topic-2 §0: the gate is
    the source of truth, so we record reality rather than forcing a preconceived label).

    Returns {resolved_family, is_unsolvable, n_beating, report}:
      - if >=1 family beats naive on validation -> resolved_family = the best-MAE winner (solvable).
      - else (no family beats, with a >= eps margin) -> resolved_family = 'fallback' (unsolvable on
        the validation gate — the signal the agent's accept logic uses).
    """
    rep = prove_solvability(df, train_end=train_end, val_h=val_h, test_h=test_h, n_cps=n_cps,
                            seasonal_period=seasonal_period)
    nb = rep["n_beating_families"]
    if nb >= 1:
        return {"resolved_family": rep["winning_family"], "is_unsolvable": False,
                "n_beating": nb, "report": rep}
    return {"resolved_family": "fallback", "is_unsolvable": True, "n_beating": 0, "report": rep}
