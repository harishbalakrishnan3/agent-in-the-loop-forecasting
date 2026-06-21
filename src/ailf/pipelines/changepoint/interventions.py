"""Changepoint intervention tools — the 5 bounded structural tools + the always-on fallback.

Each tool is registered into the core ``ToolRegistry`` (contracts/tool_registry.md). An invoker is a
PURE ``(ToolContext, params) -> ToolResult`` mapping: it reconstructs a training frame + future
timestamps from the plain ``ToolContext`` (records + ISO strings + the full diagnostics dict) and
returns ``{"yhat": [...], "resolved_params": {...}}`` — no SeriesSplit/DiagnosticsBundle object or
Prophet handle crosses the boundary, so the tool can later be served over MCP unchanged (SC-011).

The POC's CPS_GRID/SPS_GRID/etc. become ``allowed`` data on ``ToolParamSchema``. Bounds enforcement
lives in the registry; the gate is the sole scoring authority (proposer/guardrail separation).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ailf.core.agent.registry import ToolContext, ToolParamSchema, ToolRegistry, ToolResult, ToolSpec
from ailf.pipelines.changepoint.baselines import fit_predict_prophet

# Bounded grids (promoted from the POC) — now allowed-value DATA on the tool param schemas.
CPS_GRID = [0.01, 0.05, 0.1, 0.5]
SPS_GRID = [1.0, 10.0]
HPS_GRID = [1.0, 10.0]
MODE_GRID = ["additive", "multiplicative"]
RANGE_GRID = [0.8, 0.9]

# The 5 structural tools (lockstep scopes config agent_tools to these + the fallback).
STRUCTURAL_TOOL_NAMES = [
    "recent_window",
    "full_history_step_regressor",
    "full_history_ramp_regressor",
    "full_history_clean_event",
    "full_history_prophet_tuned_holidays",
]
FALLBACK_TOOL_NAME = "full_history_default"


def structural_tool_names() -> list[str]:
    """The 5 structural tool names — the single source of truth for config lockstep (FR-012)."""
    return list(STRUCTURAL_TOOL_NAMES)


# --- ToolContext helpers -----------------------------------------------------------------------

def _train_frame(ctx: ToolContext) -> pd.DataFrame:
    rows = ctx["training"]
    return pd.DataFrame(
        {"ds": pd.to_datetime([r["ds"] for r in rows]), "y": [float(r["y"]) for r in rows]}
    )


def _future_ds(ctx: ToolContext) -> pd.Series:
    return pd.to_datetime(pd.Series(ctx["future"]))


def _diag(ctx: ToolContext) -> dict:
    return ctx.get("diagnostics", {})


def _step_regressor(ds: pd.Series, cp_ds: pd.Timestamp) -> np.ndarray:
    return (pd.to_datetime(ds).reset_index(drop=True) >= cp_ds).astype(float).to_numpy()


def _ramp_regressor(ds: pd.Series, start_ds: pd.Timestamp, end_ds: pd.Timestamp) -> np.ndarray:
    days = (pd.to_datetime(ds).reset_index(drop=True) - start_ds).dt.days.to_numpy(dtype=float)
    span = max(1.0, float((end_ds - start_ds).days))
    return np.clip(days / span, 0.0, 1.0)


def _ds_at(train: pd.DataFrame, idx: int) -> pd.Timestamp:
    return pd.Timestamp(train["ds"].iloc[idx])


# --- per-tool invokers (return ToolResult) -----------------------------------------------------

def _invoke_recent_window(ctx: ToolContext, params: dict) -> ToolResult:
    train, future, diag = _train_frame(ctx), _future_ds(ctx), _diag(ctx)
    anchor = params.get("window_start", "latest")
    cp = diag.get("latest_changepoint") if anchor == "latest" else diag.get("primary_changepoint")
    if cp is None:
        from ailf.core.agent.errors import ToolBoundsError

        raise ToolBoundsError("recent_window requires a detected changepoint")
    start = int(cp["index"])
    yhat = fit_predict_prophet(train.iloc[start:], future)
    return {"yhat": yhat.tolist(), "resolved_params": params}


def _invoke_step(ctx: ToolContext, params: dict) -> ToolResult:
    from ailf.core.agent.errors import ToolBoundsError

    train, future, diag = _train_frame(ctx), _future_ds(ctx), _diag(ctx)
    which = params.get("changepoints", "all_detected")
    if which == "primary":
        chosen = [diag["primary_changepoint"]["index"]] if diag.get("primary_changepoint") else []
    else:
        chosen = [c["index"] for c in diag.get("detected_changepoints", [])]
    chosen = [c for c in chosen if c < len(train)]
    if not chosen:
        raise ToolBoundsError("step regressor requires at least one in-range changepoint")
    regressors: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for i, cp_idx in enumerate(sorted(chosen)):
        cp_ds = _ds_at(train, cp_idx)
        regressors[f"step_{i}"] = (_step_regressor(train["ds"], cp_ds), _step_regressor(future, cp_ds))
    yhat = fit_predict_prophet(train, future, regressors=regressors)
    return {"yhat": yhat.tolist(), "resolved_params": params}


def _invoke_ramp(ctx: ToolContext, params: dict) -> ToolResult:
    from ailf.core.agent.errors import ToolBoundsError

    train, future, diag = _train_frame(ctx), _future_ds(ctx), _diag(ctx)
    which = params.get("intervals", "all_candidate")
    drifts = diag.get("candidate_drift_intervals", [])
    if not drifts:
        cps = [c["index"] for c in diag.get("detected_changepoints", [])]
        if len(cps) >= 2:
            intervals = [(min(cps), max(cps))]
        elif diag.get("primary_changepoint") is not None:
            p = diag["primary_changepoint"]["index"]
            intervals = [(max(0, p - 90), min(len(train) - 1, p + 90))]
        else:
            raise ToolBoundsError("ramp regressor requires a drift interval or changepoint")
    elif which == "primary":
        d = max(drifts, key=lambda x: abs(x["total_delta"]))
        intervals = [(d["start"], d["end"])]
    else:
        intervals = [(d["start"], d["end"]) for d in drifts]
    regressors: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for i, (s, e) in enumerate(intervals):
        s_ds, e_ds = _ds_at(train, s), _ds_at(train, e)
        regressors[f"ramp_{i}"] = (_ramp_regressor(train["ds"], s_ds, e_ds), _ramp_regressor(future, s_ds, e_ds))
    yhat = fit_predict_prophet(train, future, regressors=regressors)
    return {"yhat": yhat.tolist(), "resolved_params": params}


def _resolve_event_block(entry: object, blocks: list[dict]) -> dict:
    """Map one ``blocks`` selection entry to a candidate block (interventions contract).

    The agent references a candidate block one of three equivalent ways — a positional integer
    index, a ``{start_ds, end_ds}`` date dict, or a ``{start, end}`` integer-bound dict — all of
    which it can read straight off the ``candidate_event_blocks`` diagnostic. Every entry MUST
    resolve to an EXISTING candidate block (the tool only cleans detected event blocks); anything
    else is a NORMAL bounds rejection (re-prompt), never a crash.
    """
    from ailf.core.agent.errors import ToolBoundsError

    if isinstance(entry, bool):  # bool is an int subclass — exclude before the int branch
        raise ToolBoundsError(f"clean_event.blocks entry must be an index or block dict, got {entry!r}")
    if isinstance(entry, int):
        if not (0 <= entry < len(blocks)):
            raise ToolBoundsError(
                f"clean_event.blocks index out of range for {len(blocks)} candidate blocks: {entry!r}"
            )
        return blocks[entry]
    if isinstance(entry, dict):
        if "start_ds" in entry and "end_ds" in entry:
            match = next(
                (b for b in blocks if b["start_ds"] == entry["start_ds"] and b["end_ds"] == entry["end_ds"]),
                None,
            )
        elif "start" in entry and "end" in entry:
            match = next(
                (b for b in blocks if b["start"] == entry["start"] and b["end"] == entry["end"]), None
            )
        else:
            raise ToolBoundsError(
                f"clean_event.blocks dict must carry start_ds/end_ds or start/end, got {entry!r}"
            )
        if match is None:
            raise ToolBoundsError(
                f"clean_event.blocks entry matches no candidate_event_blocks: {entry!r}"
            )
        return match
    raise ToolBoundsError(f"clean_event.blocks entry must be an index or block dict, got {entry!r}")


def _invoke_clean_event(ctx: ToolContext, params: dict) -> ToolResult:
    from ailf.core.agent.errors import ToolBoundsError

    train, future, diag = _train_frame(ctx), _future_ds(ctx), _diag(ctx)
    blocks = diag.get("candidate_event_blocks", [])
    sel = params.get("blocks", "all_closed")
    if sel == "all_closed":
        chosen = [b for b in blocks if b["closed_before_origin"]]
    elif isinstance(sel, list):
        # The agent may reference candidate blocks by index OR by echoing the block dict it was
        # shown; resolve both against candidate_event_blocks (de-duped, order preserved).
        resolved = [_resolve_event_block(entry, blocks) for entry in sel]
        chosen = []
        for b in resolved:
            if b not in chosen:
                chosen.append(b)
        if any(not b["closed_before_origin"] for b in chosen):
            raise ToolBoundsError("clean_event may only clean blocks closed before the origin (FR-026a)")
    else:
        raise ToolBoundsError(f"clean_event.blocks must be 'all_closed' or a list, got {sel!r}")
    if not chosen:
        raise ToolBoundsError("clean_event requires at least one closed-before-origin block")
    y = train["y"].copy()
    for b in chosen:
        y.iloc[int(b["start"]) : int(b["end"])] = np.nan
    cleaned = train.copy()
    cleaned["y"] = y.interpolate("linear").bfill().ffill()
    yhat = fit_predict_prophet(cleaned, future)
    return {"yhat": yhat.tolist(), "resolved_params": params}


def _build_holidays(diag: dict) -> pd.DataFrame:
    rows = []
    for w in diag.get("recurring_event_summary", {}).get("windows", []):
        for ds in pd.date_range(pd.Timestamp(w["start_ds"]), pd.Timestamp(w["end_ds"]), freq="D"):
            rows.append({"holiday": "recurring_event", "ds": ds})
    return pd.DataFrame(rows).drop_duplicates() if rows else pd.DataFrame(columns=["holiday", "ds"])


def _invoke_tuned_holidays(ctx: ToolContext, params: dict) -> ToolResult:
    train, future, diag = _train_frame(ctx), _future_ds(ctx), _diag(ctx)
    tuned = {
        "changepoint_prior_scale": params["changepoint_prior_scale"],
        "seasonality_prior_scale": params["seasonality_prior_scale"],
        "seasonality_mode": params["seasonality_mode"],
        "changepoint_range": params["changepoint_range"],
        "holidays_prior_scale": params["holidays_prior_scale"],
    }
    holidays = _build_holidays(diag)
    yhat = fit_predict_prophet(train, future, holidays=holidays, params=tuned)
    return {"yhat": yhat.tolist(), "resolved_params": params}


def _invoke_full_history_default(ctx: ToolContext, params: dict) -> ToolResult:
    """Guaranteed-valid fallback: default Prophet on full training history (FR-016)."""
    train, future = _train_frame(ctx), _future_ds(ctx)
    yhat = fit_predict_prophet(train, future)
    return {"yhat": yhat.tolist(), "resolved_params": params}


def _holiday_precondition(ctx: ToolContext) -> str | None:
    """FR-031: the holiday tool is disallowed unless the pattern is calendar-recurring."""
    rec = _diag(ctx).get("recurring_event_summary", {})
    if not rec.get("is_calendar_recurring", False):
        return "recurring-event diagnostic says the pattern is not calendar-recurring (FR-031)"
    return None


def register_changepoint_registry() -> ToolRegistry:
    """Build the changepoint tool registry: 5 structural tools + the always-on fallback."""
    specs = [
        ToolSpec(
            name="recent_window",
            description="Retrain only from a recent changepoint window (drops older history).",
            params=[ToolParamSchema("window_start", "enum", allowed=["latest", "primary"], default="latest")],
            invoker=_invoke_recent_window,
        ),
        ToolSpec(
            name="full_history_step_regressor",
            description="Keep full history, add step regressor(s) at changepoint(s) for PERMANENT level shifts.",
            params=[ToolParamSchema("changepoints", "enum", allowed=["primary", "all_detected"], default="all_detected")],
            invoker=_invoke_step,
        ),
        ToolSpec(
            name="full_history_ramp_regressor",
            description="Keep full history, add clipped ramp regressor(s) for GRADUAL drift.",
            params=[ToolParamSchema("intervals", "enum", allowed=["primary", "all_candidate"], default="all_candidate")],
            invoker=_invoke_ramp,
        ),
        ToolSpec(
            name="full_history_clean_event",
            description="Keep full history, interpolate over TEMPORARY event blocks closed before the origin.",
            params=[ToolParamSchema("blocks", "block_list", allowed=None, default="all_closed")],
            invoker=_invoke_clean_event,
        ),
        ToolSpec(
            name="full_history_prophet_tuned_holidays",
            description="Encode the recurring calendar event as holidays + tune bounded Prophet priors.",
            params=[
                ToolParamSchema("changepoint_prior_scale", "float_grid", allowed=CPS_GRID, default=0.05),
                ToolParamSchema("seasonality_prior_scale", "float_grid", allowed=SPS_GRID, default=10.0),
                ToolParamSchema("holidays_prior_scale", "float_grid", allowed=HPS_GRID, default=10.0),
                ToolParamSchema("seasonality_mode", "str_choice", allowed=MODE_GRID, default="additive"),
                ToolParamSchema("changepoint_range", "float_grid", allowed=RANGE_GRID, default=0.8),
            ],
            invoker=_invoke_tuned_holidays,
            precondition=_holiday_precondition,
        ),
        ToolSpec(
            name=FALLBACK_TOOL_NAME,
            description="Guaranteed-valid fallback: default Prophet on full training history.",
            params=[],
            structural=False,
            invoker=_invoke_full_history_default,
        ),
    ]
    return ToolRegistry(specs)
