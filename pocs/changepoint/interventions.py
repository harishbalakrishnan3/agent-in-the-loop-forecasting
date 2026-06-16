"""Bounded intervention menu — the six tools with declared grids (T022, FR-026..029).

Each tool builds a forecast for an arbitrary target horizon (validation holdout or hidden test)
from a fitted Prophet. The ReAct node picks the tool + high-level params; this module enforces
bounds and (for tuning tools) sweeps the bounded grid on the validation holdout, keeping the
best combination. An out-of-bounds request raises ``InterventionError`` (rejected pre-validation).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from pocs.changepoint.diagnostics import DiagnosticsBundle
from pocs.changepoint.forecasting import fit_predict_prophet, metrics
from pocs.changepoint.scenarios import SeriesSplit

TOOL_NAMES = [
    "recent_window",
    "full_history_step_regressor",
    "full_history_ramp_regressor",
    "full_history_clean_event",
    "full_history_prophet_tuned_holidays",
]

# Bounded grids (contracts/intervention_menu.md).
CPS_GRID = [0.01, 0.05, 0.1, 0.5]
SPS_GRID = [1.0, 10.0]
HPS_GRID = [1.0, 10.0]
MODE_GRID = ["additive", "multiplicative"]
RANGE_GRID = [0.8, 0.9]


class InterventionError(ValueError):
    """Raised when a proposal is out of bounds / disallowed — rejected before validation."""


@dataclass
class Proposal:
    tool: str
    params: dict[str, Any]

    @property
    def action_signature(self) -> str:
        return f"{self.tool}|{json.dumps(self.params, sort_keys=True)}"


# --- helpers -----------------------------------------------------------------------------------

def _slice(split: SeriesSplit, start: int, end: int) -> pd.DataFrame:
    return pd.DataFrame({"ds": split.ds.iloc[start:end], "y": split.y.iloc[start:end]})


def _step_regressor(ds: pd.Series, cp_ds: pd.Timestamp) -> np.ndarray:
    return (pd.to_datetime(ds).reset_index(drop=True) >= cp_ds).astype(float).to_numpy()


def _ramp_regressor(ds: pd.Series, start_ds: pd.Timestamp, end_ds: pd.Timestamp) -> np.ndarray:
    days = (pd.to_datetime(ds).reset_index(drop=True) - start_ds).dt.days.to_numpy(dtype=float)
    span = max(1.0, float((end_ds - start_ds).days))
    return np.clip(days / span, 0.0, 1.0)


def _ds_at(split: SeriesSplit, idx: int) -> pd.Timestamp:
    return pd.Timestamp(split.ds.iloc[idx])


# --- per-tool forecast builders --------------------------------------------------------------
# Each returns yhat over the target horizon given the region to fit [0 or window_start, fit_end_idx)
# and the future_ds to predict.

def _forecast_recent_window(
    split: SeriesSplit, diag: DiagnosticsBundle, params: dict[str, Any], fit_end: int, future_ds: pd.Series
) -> np.ndarray:
    anchor = params.get("window_start", "latest")
    if anchor not in ("latest", "primary"):
        raise InterventionError(f"recent_window.window_start must be latest|primary, got {anchor!r}")
    cp = diag.latest_changepoint if anchor == "latest" else diag.primary_changepoint
    if cp is None:
        raise InterventionError("recent_window requires a detected changepoint")
    start = int(cp["index"])
    train = _slice(split, start, fit_end)
    return fit_predict_prophet(train, future_ds)


def _forecast_step(
    split: SeriesSplit, diag: DiagnosticsBundle, params: dict[str, Any], fit_end: int, future_ds: pd.Series
) -> np.ndarray:
    which = params.get("changepoints", "all_detected")
    detected = diag.detected_changepoints
    if which == "primary":
        chosen = [diag.primary_changepoint["index"]] if diag.primary_changepoint else []
    elif which == "all_detected":
        chosen = [c["index"] for c in detected]
    else:
        raise InterventionError(f"step.changepoints must be primary|all_detected, got {which!r}")
    chosen = [c for c in chosen if c < fit_end]
    if not chosen:
        raise InterventionError("step regressor requires at least one in-range changepoint")

    train = _slice(split, 0, fit_end)
    regressors: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for i, cp_idx in enumerate(sorted(chosen)):
        cp_ds = _ds_at(split, cp_idx)
        regressors[f"step_{i}"] = (_step_regressor(train["ds"], cp_ds), _step_regressor(future_ds, cp_ds))
    return fit_predict_prophet(train, future_ds, regressors=regressors)


def _forecast_ramp(
    split: SeriesSplit, diag: DiagnosticsBundle, params: dict[str, Any], fit_end: int, future_ds: pd.Series
) -> np.ndarray:
    which = params.get("intervals", "all_candidate")
    drifts = diag.candidate_drift_intervals
    if not drifts:
        # Fallback: ramp across the span between the two detected changepoints (or around primary),
        # so the tool is usable even when the drift heuristic finds nothing.
        cps = [c["index"] for c in diag.detected_changepoints]
        if len(cps) >= 2:
            intervals = [(min(cps), max(cps))]
        elif diag.primary_changepoint is not None:
            p = diag.primary_changepoint["index"]
            intervals = [(max(0, p - 90), min(fit_end - 1, p + 90))]
        else:
            raise InterventionError("ramp regressor requires a drift interval or changepoint")
    elif which == "primary":
        d = max(drifts, key=lambda x: abs(x["total_delta"]))
        intervals = [(d["start"], d["end"])]
    elif which == "all_candidate":
        intervals = [(d["start"], d["end"]) for d in drifts]
    else:
        raise InterventionError(f"ramp.intervals must be primary|all_candidate, got {which!r}")

    train = _slice(split, 0, fit_end)
    regressors: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for i, (s, e) in enumerate(intervals):
        s_ds, e_ds = _ds_at(split, s), _ds_at(split, e)
        regressors[f"ramp_{i}"] = (_ramp_regressor(train["ds"], s_ds, e_ds), _ramp_regressor(future_ds, s_ds, e_ds))
    return fit_predict_prophet(train, future_ds, regressors=regressors)


def _forecast_clean_event(
    split: SeriesSplit, diag: DiagnosticsBundle, params: dict[str, Any], fit_end: int, future_ds: pd.Series
) -> np.ndarray:
    blocks = diag.candidate_event_blocks
    sel = params.get("blocks", "all_closed")
    if sel == "all_closed":
        chosen = [b for b in blocks if b["closed_before_origin"]]
    elif isinstance(sel, list):
        chosen = [blocks[i] for i in sel if 0 <= i < len(blocks)]
        bad = [b for b in chosen if not b["closed_before_origin"]]
        if bad:
            raise InterventionError("clean_event may only clean blocks closed strictly before the origin (FR-026a)")
    else:
        raise InterventionError(f"clean_event.blocks must be 'all_closed' or a list, got {sel!r}")
    if not chosen:
        raise InterventionError("clean_event requires at least one closed-before-origin block")

    train = _slice(split, 0, fit_end).copy()
    y = train["y"].copy()
    for b in chosen:
        s, e = int(b["start"]), int(b["end"])
        if e <= fit_end:
            y.iloc[s:e] = np.nan
    train["y"] = y.interpolate("linear").bfill().ffill()
    return fit_predict_prophet(train, future_ds)


def _build_holidays(diag: DiagnosticsBundle) -> pd.DataFrame:
    rows = []
    for w in diag.recurring_event_summary.get("windows", []):
        start = pd.Timestamp(w["start_ds"])
        end = pd.Timestamp(w["end_ds"])
        for ds in pd.date_range(start, end, freq="D"):
            rows.append({"holiday": "recurring_event", "ds": ds})
    return pd.DataFrame(rows).drop_duplicates() if rows else pd.DataFrame(columns=["holiday", "ds"])


def _validate_tuning_params(params: dict[str, Any], *, with_holidays: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cps = params.get("changepoint_prior_scale", 0.05)
    sps = params.get("seasonality_prior_scale", 10.0)
    mode = params.get("seasonality_mode", "additive")
    rng = params.get("changepoint_range", 0.8)
    if cps not in CPS_GRID:
        raise InterventionError(f"changepoint_prior_scale {cps} not in {CPS_GRID}")
    if sps not in SPS_GRID:
        raise InterventionError(f"seasonality_prior_scale {sps} not in {SPS_GRID}")
    if mode not in MODE_GRID:
        raise InterventionError(f"seasonality_mode {mode} not in {MODE_GRID}")
    if rng not in RANGE_GRID:
        raise InterventionError(f"changepoint_range {rng} not in {RANGE_GRID}")
    out.update(changepoint_prior_scale=cps, seasonality_prior_scale=sps, seasonality_mode=mode, changepoint_range=rng)
    if with_holidays:
        hps = params.get("holidays_prior_scale", 10.0)
        if hps not in HPS_GRID:
            raise InterventionError(f"holidays_prior_scale {hps} not in {HPS_GRID}")
        out["holidays_prior_scale"] = hps
    return out


def _forecast_tuned(
    split: SeriesSplit, diag: DiagnosticsBundle, params: dict[str, Any], fit_end: int, future_ds: pd.Series, *, with_holidays: bool
) -> np.ndarray:
    tuned = _validate_tuning_params(params, with_holidays=with_holidays)
    train = _slice(split, 0, fit_end)
    holidays = _build_holidays(diag) if with_holidays else None
    return fit_predict_prophet(train, future_ds, holidays=holidays, params=tuned)


_BUILDERS = {
    "recent_window": _forecast_recent_window,
    "full_history_step_regressor": _forecast_step,
    "full_history_ramp_regressor": _forecast_ramp,
    "full_history_clean_event": _forecast_clean_event,
    "full_history_prophet_tuned_holidays": lambda *a: _forecast_tuned(*a, with_holidays=True),
}


def check_proposal_allowed(proposal: Proposal, diag: DiagnosticsBundle) -> None:
    """Reject unknown tools and the holiday tool when the pattern is not calendar-recurring (FR-031)."""
    if proposal.tool not in TOOL_NAMES:
        raise InterventionError(f"Unknown tool {proposal.tool!r}")
    if proposal.tool == "full_history_prophet_tuned_holidays":
        if not diag.recurring_event_summary.get("is_calendar_recurring", False):
            raise InterventionError(
                "full_history_prophet_tuned_holidays disallowed: recurring-event diagnostic says "
                "the pattern is not calendar-recurring (FR-031)"
            )


def forecast_for_proposal(
    proposal: Proposal, split: SeriesSplit, diag: DiagnosticsBundle, *, fit_end: int, future_ds: pd.Series
) -> np.ndarray:
    """Build the forecast for a proposal over ``future_ds``, fitting on data up to ``fit_end``."""
    check_proposal_allowed(proposal, diag)
    builder = _BUILDERS[proposal.tool]
    return builder(split, diag, proposal.params, fit_end, future_ds)


def evaluate_on_validation(proposal: Proposal, split: SeriesSplit, diag: DiagnosticsBundle) -> dict[str, float]:
    """Fit on fit region, score on the validation holdout (no test access)."""
    val = split.val_df
    yhat = forecast_for_proposal(proposal, split, diag, fit_end=split.fit_end, future_ds=val["ds"])
    return metrics(val["y"].to_numpy(), yhat)


def evaluate_on_test(proposal: Proposal, split: SeriesSplit, diag: DiagnosticsBundle) -> tuple[np.ndarray, dict[str, float]]:
    """Final eval: fit on full train, forecast + score on hidden test (only call at final stage)."""
    test = split.test_df
    yhat = forecast_for_proposal(proposal, split, diag, fit_end=split.train_end, future_ds=test["ds"])
    return yhat, metrics(test["y"].to_numpy(), yhat)
