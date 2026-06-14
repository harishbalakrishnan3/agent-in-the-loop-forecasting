"""Deterministic, training-only diagnostics (T009, FR-013/014).

Every field is computed from the training frame alone — no test data, no audit_only info.
``to_agent_dict`` emits the agent-facing subset (strips nothing sensitive here since all of it
is training-derived, but excludes provenance keys that could bias the LLM).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from pocs.changepoint.detector import ChangepointSet, detect_changepoints


@dataclass
class EventBlock:
    start: int
    end: int  # exclusive
    start_ds: str
    end_ds: str
    duration: int
    mean_excess: float
    closed_before_origin: bool  # ends strictly before the forecast origin (FR-026a)


@dataclass
class DriftInterval:
    start: int
    end: int
    start_ds: str
    end_ds: str
    slope_per_step: float
    total_delta: float


@dataclass
class RecurringEventSummary:
    is_calendar_recurring: bool
    period_days: int | None
    windows: list[dict[str, str]]  # [{start_ds, end_ds}]
    dominant_month: int | None
    confidence: float


@dataclass
class DiagnosticsBundle:
    detected_changepoints: list[dict[str, Any]]
    latest_changepoint: dict[str, Any] | None
    primary_changepoint: dict[str, Any] | None
    post_changepoint_history_len: int
    post_changepoint_shorter_than_season: bool
    seasonal_period: int
    segment_stats: list[dict[str, float]]
    candidate_event_blocks: list[dict[str, Any]]
    recurring_event_summary: dict[str, Any]
    local_boundary_jumps: list[dict[str, Any]]
    candidate_drift_intervals: list[dict[str, Any]]
    transient_event_score: float
    permanent_shift_magnitude: float

    def to_agent_dict(self) -> dict[str, Any]:
        """Agent-facing view (all training-derived; safe to show to the ReAct node)."""
        return asdict(self)


def _segment_stats(y: np.ndarray, cp_indices: list[int]) -> list[dict[str, float]]:
    bounds = [0, *sorted(cp_indices), len(y)]
    out: list[dict[str, float]] = []
    for start, end in zip(bounds[:-1], bounds[1:], strict=True):
        seg = y[start:end]
        if len(seg) == 0:
            continue
        out.append(
            {"start": int(start), "end": int(end), "mean": float(np.mean(seg)), "std": float(np.std(seg))}
        )
    return out


def _deseasonalized_level(train_df: pd.DataFrame, seasonal_period: int) -> np.ndarray:
    """Series with ONLY seasonality removed (trend retained), for drift/slope analysis.

    Unlike ``_deseasonalized_residual``, this keeps the linear/level component so a gradual ramp
    is visible in the level rather than absorbed by a global trend term.
    """
    y = train_df["y"].to_numpy(dtype=float)
    t = np.arange(len(y), dtype=float)
    cols = [np.ones_like(t)]
    for period in (seasonal_period, 7.0):
        cols.append(np.sin(2 * np.pi * t / period))
        cols.append(np.cos(2 * np.pi * t / period))
    design = np.column_stack(cols)
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    seasonal = design[:, 1:] @ coef[1:]  # seasonal component only
    return y - seasonal


def _candidate_event_blocks(
    train_df: pd.DataFrame, level: np.ndarray, forecast_origin_idx: int
) -> list[EventBlock]:
    """Detect temporary events as short excursions from a LOCAL baseline.

    Uses the deseasonalized level minus a 91-day rolling-median baseline, so a gradual ramp or a
    permanent step (both slow vs. the baseline window) leaves no excursion, while short events
    spike above/below it. This avoids the false blocks a global-linear-trend residual produces on
    a curved ramp.
    """
    baseline = pd.Series(level).rolling(91, min_periods=1, center=True).median().to_numpy()
    residual = level - baseline
    center = float(np.median(residual))
    mad = float(np.median(np.abs(residual - center)) * 1.4826)
    threshold = max(8.0, 3.0 * mad)
    mask = np.abs(residual - center) > threshold

    blocks: list[EventBlock] = []
    i = 0
    n = len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        start = i
        while i < n and mask[i]:
            i += 1
        end = i  # exclusive
        duration = end - start
        if 3 <= duration <= 90:
            blocks.append(
                EventBlock(
                    start=int(start),
                    end=int(end),
                    start_ds=str(train_df["ds"].iloc[start].date()),
                    end_ds=str(train_df["ds"].iloc[end - 1].date()),
                    duration=int(duration),
                    mean_excess=float(np.mean(residual[start:end])),
                    closed_before_origin=bool(end < forecast_origin_idx),
                )
            )
    return blocks


def _recurring_event_summary(
    train_df: pd.DataFrame, blocks: list[EventBlock]
) -> RecurringEventSummary:
    if len(blocks) < 2:
        return RecurringEventSummary(False, None, [], None, 0.0)

    starts = [pd.Timestamp(train_df["ds"].iloc[b.start]) for b in blocks]
    months = [s.month for s in starts]
    years = [s.year for s in starts]
    month_counts = pd.Series(months).value_counts()
    dominant_month = int(month_counts.idxmax())
    dominant_fraction = float(month_counts.max() / len(starts))

    # Calendar-recurring: appears across >=3 distinct years and clusters in one month.
    is_recurring = len(set(years)) >= 3 and dominant_fraction >= 0.6
    windows = [{"start_ds": b.start_ds, "end_ds": b.end_ds} for b in blocks]
    return RecurringEventSummary(
        is_calendar_recurring=is_recurring,
        period_days=365 if is_recurring else None,
        windows=windows,
        dominant_month=dominant_month,
        confidence=dominant_fraction,
    )


def _local_boundary_jumps(y: np.ndarray, cp_indices: list[int], width: int = 14) -> list[dict[str, Any]]:
    jumps: list[dict[str, Any]] = []
    for cp in cp_indices:
        left = y[max(0, cp - width) : cp]
        right = y[cp : min(len(y), cp + width)]
        if len(left) < 3 or len(right) < 3:
            continue
        jumps.append({"index": int(cp), "jump": float(np.mean(right) - np.mean(left))})
    return jumps


def _change_concentration(smoothed: np.ndarray, start: int, end: int, window: int = 31) -> float:
    """Fraction of an interval's total level change occurring in its single largest sub-window.

    Near 1.0 => an abrupt step (change concentrated in one short window). Near 0 => a spread-out
    ramp. Used to distinguish a gradual drift from a sharp level shift. The window (~31d) matches
    the level smoothing so a single step is measured as one concentrated move rather than split.
    """
    seg = smoothed[start : end + 1]
    total = abs(seg[-1] - seg[0]) or 1e-9
    if len(seg) <= window:
        return 1.0
    largest = max(abs(seg[k + window] - seg[k]) for k in range(len(seg) - window))
    return float(largest / total)


def _slope_scan_drift_intervals(
    train_df: pd.DataFrame, level: np.ndarray, seasonal_period: int
) -> list[DriftInterval]:
    """Detect sustained GRADUAL ramps in the deseasonalized level (trend retained).

    A ramp shows a large net level change over a ~3-month window that is spread out (low
    concentration), unlike a sharp step (high concentration). This catches gradual drift the
    between-changepoint heuristic misses, while not misfiring on permanent level shifts.
    """
    n = len(level)
    if n < 120:
        return []
    smoothed = pd.Series(level).rolling(31, min_periods=1, center=True).mean().to_numpy()
    half = 45  # half-window: net change measured over ~90 days
    net = np.array([smoothed[min(n - 1, i + half)] - smoothed[max(0, i - half)] for i in range(n)])

    net_threshold = 15.0  # min |level change| over the window to flag a candidate-drift region
    concentration_max = 0.5  # above this, the change is too abrupt — it's a step, not a ramp
    min_delta = 25.0  # a genuine drift must move the level at least this much (rejects seasonal wiggle)
    mask = np.abs(net) >= net_threshold

    intervals: list[DriftInterval] = []
    i = 0
    while i < n:
        if not mask[i]:
            i += 1
            continue
        sign = np.sign(net[i])
        start = i
        while i < n and mask[i] and np.sign(net[i]) == sign:
            i += 1
        end = min(i, n - 1)
        duration = end - start
        total_delta = float(smoothed[end] - smoothed[start])
        if duration < 45 or abs(total_delta) < min_delta:
            continue
        if _change_concentration(smoothed, start, end) > concentration_max:
            continue  # abrupt step, not a gradual ramp
        intervals.append(
            DriftInterval(
                start=int(start),
                end=int(end),
                start_ds=str(train_df["ds"].iloc[start].date()),
                end_ds=str(train_df["ds"].iloc[end].date()),
                slope_per_step=float(total_delta / max(1, duration)),
                total_delta=total_delta,
            )
        )
    return intervals


def _candidate_drift_intervals(
    train_df: pd.DataFrame,
    cp_indices: list[int],
    boundary_jumps: list[dict[str, Any]],
    level: np.ndarray,
    seasonal_period: int,
) -> list[DriftInterval]:
    """Gradual-ramp candidates: between-changepoint spans + direct deseasonalized slope scan."""
    intervals: list[DriftInterval] = []
    jump_by_idx = {j["index"]: abs(j["jump"]) for j in boundary_jumps}
    y = train_df["y"].to_numpy(dtype=float)
    for start, end in zip(sorted(cp_indices)[:-1], sorted(cp_indices)[1:], strict=True):
        duration = end - start
        if duration < 45:
            continue
        pre = float(np.mean(y[max(0, start - 30) : start])) if start > 0 else float(y[0])
        post = float(np.mean(y[end : min(len(y), end + 30)])) if end < len(y) else float(y[-1])
        total_delta = post - pre
        max_jump = max(jump_by_idx.get(start, 0.0), jump_by_idx.get(end, 0.0))
        # Gradual = total level change is large but each boundary jump is small relative to it.
        if abs(total_delta) < 15.0 or max_jump >= 0.4 * abs(total_delta):
            continue
        intervals.append(
            DriftInterval(
                start=int(start),
                end=int(end),
                start_ds=str(train_df["ds"].iloc[start].date()),
                end_ds=str(train_df["ds"].iloc[end].date()),
                slope_per_step=float(total_delta / max(1, duration)),
                total_delta=float(total_delta),
            )
        )

    # Direct slope scan catches drifts not bracketed by detected changepoints.
    existing = [(d.start, d.end) for d in intervals]
    for d in _slope_scan_drift_intervals(train_df, level, seasonal_period):
        if not any(abs(d.start - s) < 60 and abs(d.end - e) < 60 for s, e in existing):
            intervals.append(d)
    return intervals


def compute_diagnostics(
    train_df: pd.DataFrame, *, changepoints: ChangepointSet, seasonal_period: int
) -> DiagnosticsBundle:
    """Build the full diagnostics bundle from training history only."""
    y = train_df["y"].to_numpy(dtype=float)
    n = len(y)
    cp_indices = changepoints.indices

    segs = _segment_stats(y, cp_indices)
    latest = changepoints.latest
    post_len = (n - latest.index) if latest is not None else n

    level = _deseasonalized_level(train_df, seasonal_period)
    event_blocks = _candidate_event_blocks(train_df, level, forecast_origin_idx=n)
    recurring = _recurring_event_summary(train_df, event_blocks)
    boundary_jumps = _local_boundary_jumps(y, cp_indices)
    drift_intervals = _candidate_drift_intervals(
        train_df, cp_indices, boundary_jumps, level, seasonal_period
    )

    # Transient score: how much the last segment reverts toward the first (event-like vs regime).
    transient = 0.0
    if len(segs) >= 3:
        before, middle, after = segs[-3], segs[-2], segs[-1]
        event_jump = abs(middle["mean"] - before["mean"])
        reversion = abs(after["mean"] - before["mean"])
        transient = float(event_jump / max(reversion, 1.0))

    permanent = float(abs(segs[-1]["mean"] - segs[0]["mean"])) if segs else 0.0

    def cp_dict(c: Any) -> dict[str, Any] | None:
        if c is None:
            return None
        return {"index": c.index, "ds": str(pd.Timestamp(c.ds).date()), "trend_delta": c.trend_delta}

    return DiagnosticsBundle(
        detected_changepoints=[cp_dict(c) for c in changepoints.changepoints],
        latest_changepoint=cp_dict(latest),
        primary_changepoint=cp_dict(changepoints.primary),
        post_changepoint_history_len=int(post_len),
        post_changepoint_shorter_than_season=bool(post_len < seasonal_period),
        seasonal_period=int(seasonal_period),
        segment_stats=segs,
        candidate_event_blocks=[asdict(b) for b in event_blocks],
        recurring_event_summary=asdict(recurring),
        local_boundary_jumps=boundary_jumps,
        candidate_drift_intervals=[asdict(d) for d in drift_intervals],
        transient_event_score=transient,
        permanent_shift_magnitude=permanent,
    )


def diagnostics_for_scenario(scenario: Any) -> DiagnosticsBundle:
    """Convenience: detect changepoints + compute diagnostics for a Scenario."""
    cps = detect_changepoints(
        scenario.split.train_df, n_changepoints_to_detect=scenario.n_changepoints_to_detect
    )
    return compute_diagnostics(
        scenario.split.train_df, changepoints=cps, seasonal_period=scenario.seasonal_period
    )
