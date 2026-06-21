"""Intervention strategies for level shift detection.

Takes detection output (LevelShiftResult) and configures Prophet
with an appropriate fix. Each strategy is a pure function that returns
an InterventionResult with the configured model and possibly modified data.

In production, the LLM agent replaces the deterministic select_strategy()
with reasoning. Here we hard-code rules for backtesting.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from prophet import Prophet

from pocs.changepoint.level_shift.detector import LevelShiftResult


@dataclass
class InterventionResult:
    """Result of applying an intervention strategy."""

    strategy_name: str
    model: Prophet
    training_data: pd.DataFrame
    description: str


def no_intervention(
    result: LevelShiftResult,
    df: pd.DataFrame,
) -> InterventionResult:
    """Baseline: Prophet with defaults, no intervention applied."""
    model = Prophet()
    return InterventionResult(
        strategy_name="no_intervention",
        model=model,
        training_data=df.copy(),
        description="Prophet with default settings, no intervention.",
    )


def inject_changepoints(
    result: LevelShiftResult,
    df: pd.DataFrame,
) -> InterventionResult:
    """Inject detected changepoints explicitly into Prophet.

    Use when: few large, unambiguous shifts.
    """
    changepoint_dates = pd.to_datetime(result.changepoint_dates)
    # Filter to only changepoints within training data range
    train_dates = pd.to_datetime(df["ds"])
    valid_cps = [d for d in changepoint_dates if train_dates.min() <= d <= train_dates.max()]

    model = Prophet(changepoints=valid_cps) if valid_cps else Prophet()

    return InterventionResult(
        strategy_name="inject_changepoints",
        model=model,
        training_data=df.copy(),
        description=(
            f"Injected {len(valid_cps)} explicit changepoint(s) into Prophet: "
            f"{[str(d.date()) for d in valid_cps]}"
        ),
    )


def trim_to_post_shift(
    result: LevelShiftResult,
    df: pd.DataFrame,
    buffer_days: int = 7,
) -> InterventionResult:
    """Train only on data after the most recent shift.

    Use when: recent regime change, old data is irrelevant.
    """
    if not result.changepoint_dates:
        return no_intervention(result, df)

    last_cp = pd.to_datetime(result.changepoint_dates[-1])
    cutoff = last_cp + pd.Timedelta(days=buffer_days)
    trimmed = df[pd.to_datetime(df["ds"]) >= cutoff].copy()

    # Need minimum data points for Prophet to fit
    if len(trimmed) < 30:
        trimmed = df.copy()
        desc = "Trim failed (insufficient post-shift data), using full history."
    else:
        desc = (
            f"Training only on data after {last_cp.date()} + {buffer_days}d buffer. "
            f"Trimmed from {len(df)} to {len(trimmed)} points."
        )

    model = Prophet()
    return InterventionResult(
        strategy_name="trim_to_post_shift",
        model=model,
        training_data=trimmed,
        description=desc,
    )


def add_step_regressor(
    result: LevelShiftResult,
    df: pd.DataFrame,
) -> InterventionResult:
    """Add a binary regressor column (0 before shift, 1 after).

    Use when: permanent level change that should be modeled explicitly.
    """
    if not result.changepoint_dates:
        return no_intervention(result, df)

    modified_df = df.copy()
    # Add step indicator for each detected changepoint
    for i, cp_date in enumerate(result.changepoint_dates):
        col_name = f"shift_{i}"
        modified_df[col_name] = (
            pd.to_datetime(modified_df["ds"]) >= pd.to_datetime(cp_date)
        ).astype(float)

    model = Prophet()
    for i in range(len(result.changepoint_dates)):
        model.add_regressor(f"shift_{i}")

    return InterventionResult(
        strategy_name="add_step_regressor",
        model=model,
        training_data=modified_df,
        description=(
            f"Added {len(result.changepoint_dates)} step-function regressor(s) "
            f"at detected changepoint(s)."
        ),
    )


def increase_sensitivity(
    result: LevelShiftResult,
    df: pd.DataFrame,
    prior_scale: float = 0.5,
) -> InterventionResult:
    """Increase Prophet's changepoint_prior_scale.

    Use when: subtle shift that Prophet's defaults miss.
    """
    model = Prophet(
        changepoint_prior_scale=prior_scale,
        n_changepoints=50,
    )
    return InterventionResult(
        strategy_name="increase_sensitivity",
        model=model,
        training_data=df.copy(),
        description=(
            f"Increased changepoint_prior_scale to {prior_scale} "
            f"and n_changepoints to 50 for subtle shift detection."
        ),
    )


def clean_temporary_event(
    result: LevelShiftResult,
    df: pd.DataFrame,
) -> InterventionResult:
    """Remove temporary spikes from training data.

    Use when: two detected shifts of opposite sign (cancel out) → transient event.
    Identifies spike by: consecutive shifts with magnitudes that nearly cancel.
    """
    if result.n_changepoints < 2:
        return no_intervention(result, df)

    modified_df = df.copy()
    dates = pd.to_datetime(modified_df["ds"])
    cleaned_ranges = []

    # Find pairs of shifts that cancel (spike up + spike down)
    i = 0
    while i < len(result.magnitudes) - 1:
        m1 = result.magnitudes[i]
        m2 = result.magnitudes[i + 1]
        # Check if they approximately cancel
        if abs(m1 + m2) / max(abs(m1), abs(m2)) < 0.4:
            # This is a temporary event — remove data in the spike window
            start_date = pd.to_datetime(result.changepoint_dates[i])
            end_date = pd.to_datetime(result.changepoint_dates[i + 1])
            mask = (dates >= start_date) & (dates < end_date)
            modified_df = modified_df[~mask].copy()
            cleaned_ranges.append((str(start_date.date()), str(end_date.date())))
            i += 2
        else:
            i += 1

    if not cleaned_ranges:
        return no_intervention(result, df)

    model = Prophet()
    return InterventionResult(
        strategy_name="clean_temporary_event",
        model=model,
        training_data=modified_df,
        description=(
            f"Removed {len(cleaned_ranges)} temporary event(s) from training data: "
            f"{cleaned_ranges}. Reduced from {len(df)} to {len(modified_df)} points."
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Strategy Selection (deterministic — LLM replaces this in production)
# ═══════════════════════════════════════════════════════════════════════════════

STRATEGIES = {
    "no_intervention": no_intervention,
    "inject_changepoints": inject_changepoints,
    "trim_to_post_shift": trim_to_post_shift,
    "add_step_regressor": add_step_regressor,
    "increase_sensitivity": increase_sensitivity,
    "clean_temporary_event": clean_temporary_event,
}


def select_strategy(result: LevelShiftResult, df: pd.DataFrame) -> str:
    """Deterministic strategy picker for backtesting.

    In production, the LLM agent replaces this with reasoning.

    Returns:
        Strategy name (key in STRATEGIES dict).
    """
    if result.n_changepoints == 0:
        return "no_intervention"

    # Check for temporary spike (two shifts that cancel)
    if result.n_changepoints == 2:
        m1, m2 = result.magnitudes[0], result.magnitudes[1]
        if abs(m1 + m2) / max(abs(m1), abs(m2)) < 0.4:
            return "clean_temporary_event"

    # Few large shifts → inject explicit changepoints
    if result.n_changepoints <= 2 and all(abs(m) > 20 for m in result.magnitudes):
        return "inject_changepoints"

    # Many shifts → trim to most recent regime
    if result.n_changepoints >= 3:
        return "trim_to_post_shift"

    # Subtle shifts → increase sensitivity
    if all(abs(m) < 15 for m in result.magnitudes):
        return "increase_sensitivity"

    # Default: add step regressor
    return "add_step_regressor"


def apply_intervention(
    result: LevelShiftResult,
    df: pd.DataFrame,
    strategy: str | None = None,
) -> InterventionResult:
    """Apply an intervention strategy to the data.

    Args:
        result: Detection output from detect_level_shift.
        df: Training data in Prophet format (columns: ds, y).
        strategy: Strategy name to apply. If None, uses select_strategy().

    Returns:
        InterventionResult with configured model and data.
    """
    if strategy is None:
        strategy = select_strategy(result, df)

    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}. Available: {list(STRATEGIES.keys())}")

    return STRATEGIES[strategy](result, df)
