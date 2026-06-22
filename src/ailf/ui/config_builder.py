"""Build a ConfigOverride dict from the control-pane selections, and validate custom-CSV input.

PURE module (no Streamlit). The override dict round-trips through ``ConfigOverride.from_dict`` and
must satisfy ``resolve_config`` lockstep, so the canonical diagnostic/tool key lists are imported
from the pipeline rather than hardcoded (contracts/run_invocation.md, data-model §1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ailf.core.config.resolve import FALLBACK_TOOL
from ailf.pipelines.changepoint.diagnostics import DiagnosticsBundle
from ailf.pipelines.changepoint.interventions import structural_tool_names

# Canonical key lists — imported, never hardcoded, so the UI cannot drift out of lockstep.
DIAGNOSTIC_KEYS: tuple[str, ...] = DiagnosticsBundle.field_names()
STRUCTURAL_TOOL_KEYS: tuple[str, ...] = tuple(structural_tool_names())
FALLBACK_TOOL_KEY: str = FALLBACK_TOOL

DEFAULT_SEED = 1729
_SPLIT_TOLERANCE = 1e-6
REQUIRED_CSV_COLUMNS = ("ds", "y")


# --- Presentation metadata: human labels, plain-English help, and umbrella grouping -------------
# Keyed by the canonical backend key. ``label`` and ``help`` are shown in the control pane; the raw
# key is never shown to the user (it stays internal for the override + the event stream). Each group
# is an umbrella ordered for display; every diagnostic/tool key appears in exactly one group (a
# test asserts this stays in lockstep with the bundle/registry).

@dataclass(frozen=True)
class ItemMeta:
    label: str
    help: str


DIAGNOSTIC_META: dict[str, ItemMeta] = {
    "detected_changepoints": ItemMeta(
        "Detected changepoints",
        "All structural break points found in the training history (date + trend change at each).",
    ),
    "latest_changepoint": ItemMeta(
        "Most recent changepoint",
        "The most recent break — matters most for whether recent data still reflects the present regime.",
    ),
    "primary_changepoint": ItemMeta(
        "Primary changepoint",
        "The single most significant break, by trend-change magnitude.",
    ),
    "post_changepoint_history_len": ItemMeta(
        "History since last change",
        "How many data points exist after the latest changepoint.",
    ),
    "post_changepoint_shorter_than_season": ItemMeta(
        "Too little history for a full season",
        "True if the post-change history is shorter than one seasonal cycle, so seasonality may be unlearnable.",
    ),
    "seasonal_period": ItemMeta(
        "Seasonal period",
        "The assumed length of one seasonal cycle (e.g. 365 for daily data).",
    ),
    "segment_stats": ItemMeta(
        "Segment statistics",
        "Mean and spread of each stretch of the series between changepoints.",
    ),
    "permanent_shift_magnitude": ItemMeta(
        "Permanent shift size",
        "How far the latest segment's level sits from the first — a lasting level change.",
    ),
    "transient_event_score": ItemMeta(
        "Transient-vs-regime score",
        "Whether the last shift looks like a temporary spike that reverted, vs a lasting regime change.",
    ),
    "local_boundary_jumps": ItemMeta(
        "Jumps at change boundaries",
        "The size of the level jump right at each changepoint.",
    ),
    "candidate_event_blocks": ItemMeta(
        "Candidate event blocks",
        "Short windows that look like one-off events or outliers rather than regime changes.",
    ),
    "recurring_event_summary": ItemMeta(
        "Recurring calendar events",
        "Whether events recur on a calendar pattern (e.g. the same month each year).",
    ),
    "candidate_drift_intervals": ItemMeta(
        "Candidate drift intervals",
        "Stretches where the level drifts gradually rather than jumping.",
    ),
}

# Ordered umbrellas for the diagnostics. Each value is a list of canonical keys.
DIAGNOSTIC_GROUPS: list[tuple[str, list[str]]] = [
    ("📍 Detected changes", [
        "detected_changepoints", "latest_changepoint", "primary_changepoint",
    ]),
    ("📏 History around changes", [
        "post_changepoint_history_len", "post_changepoint_shorter_than_season", "seasonal_period",
    ]),
    ("📊 Segment & shift analysis", [
        "segment_stats", "permanent_shift_magnitude", "transient_event_score", "local_boundary_jumps",
    ]),
    ("🗓️ Events & drift patterns", [
        "candidate_event_blocks", "recurring_event_summary", "candidate_drift_intervals",
    ]),
]


TOOL_META: dict[str, ItemMeta] = {
    "recent_window": ItemMeta(
        "Retrain on recent window",
        "Drop older history and retrain only from a recent changepoint — good when the past no longer applies.",
    ),
    "full_history_step_regressor": ItemMeta(
        "Mark permanent level shifts",
        "Keep all data and add step markers at changepoints to model permanent jumps in level.",
    ),
    "full_history_ramp_regressor": ItemMeta(
        "Model gradual drift",
        "Keep all data and add ramps to capture gradual drift over a transition.",
    ),
    "full_history_clean_event": ItemMeta(
        "Clean out one-off events",
        "Keep all data but smooth over temporary event blocks so they don't distort the fit.",
    ),
    "full_history_prophet_tuned_holidays": ItemMeta(
        "Tune recurring calendar events",
        "Encode recurring events as holidays and tune the forecaster's bounded sensitivity priors.",
    ),
    FALLBACK_TOOL_KEY: ItemMeta(
        "Default forecast (always on)",
        "Plain forecast on all training history — the guaranteed-valid fallback; it can't be turned off.",
    ),
}

# Ordered umbrellas for the tools. The fallback sits in its own group and is rendered locked-on.
TOOL_GROUPS: list[tuple[str, list[str]]] = [
    ("🪟 Refocus on recent data", ["recent_window"]),
    ("🧩 Keep full history + targeted correction", [
        "full_history_step_regressor", "full_history_ramp_regressor",
        "full_history_clean_event", "full_history_prophet_tuned_holidays",
    ]),
    ("🛟 Safe default", [FALLBACK_TOOL_KEY]),
]


def default_diagnostics_enabled() -> dict[str, bool]:
    """All 13 diagnostics enabled — the default control-pane state."""
    return {k: True for k in DIAGNOSTIC_KEYS}


def default_tools_enabled() -> dict[str, bool]:
    """All 5 structural tools enabled (the fallback is always-on and added by the override)."""
    return {k: True for k in STRUCTURAL_TOOL_KEYS}


def to_override_dict(
    *,
    visual_model_id: str,
    decision_model_id: str,
    visual_analysis_enabled: bool,
    diagnostics_enabled: dict[str, bool],
    tools_enabled: dict[str, bool],
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Assemble the override dict consumed by ``ConfigOverride.from_dict`` (contract: run_invocation.md).

    - ``diagnostics`` carries EXACTLY the 13 canonical keys.
    - ``agent_tools`` carries the 5 structural keys plus the always-on fallback forced ``True``
      (the fallback may never be disabled — resolve.py guards this).
    - No ``split`` block: scenario runs use the golden split; custom-CSV runs pass fractions to
      ``run_scenario`` directly (research R5).
    """
    diagnostics = {k: bool(diagnostics_enabled.get(k, True)) for k in DIAGNOSTIC_KEYS}
    agent_tools = {k: bool(tools_enabled.get(k, True)) for k in STRUCTURAL_TOOL_KEYS}
    agent_tools[FALLBACK_TOOL_KEY] = True  # always-on; never user-toggled (FR-014)
    return {
        "models": {
            "visual_model_id": visual_model_id,
            "decision_model_id": decision_model_id,
        },
        "visual_analysis_enabled": bool(visual_analysis_enabled),
        "diagnostics": diagnostics,
        "agent_tools": agent_tools,
        "seed": int(seed),
    }


# --- Custom-CSV validation (T026, contract: custom_csv.md) --------------------------------------


@dataclass
class ValidationResult:
    """Outcome of pre-run validation: ``ok`` plus a list of human-readable error messages."""

    ok: bool
    errors: list[str] = field(default_factory=list)


def validate_split_fractions(train: float, val: float, test: float) -> ValidationResult:
    """The three fractions must sum to 1 within tolerance and each be positive (FR-009)."""
    errors: list[str] = []
    for name, frac in (("train", train), ("validation", val), ("test", test)):
        if frac is None or frac <= 0:
            errors.append(f"{name} fraction must be a positive number (got {frac}).")
    total = (train or 0) + (val or 0) + (test or 0)
    if abs(total - 1.0) > _SPLIT_TOLERANCE:
        errors.append(f"train + validation + test must sum to 1.0 (got {total:.4f}).")
    return ValidationResult(ok=not errors, errors=errors)


def validate_custom_series(
    df: "pd.DataFrame | None",
    *,
    train: float,
    val: float,
    test: float,
) -> ValidationResult:
    """Full custom-CSV contract check, run BEFORE any pipeline call (contract: custom_csv.md).

    Covers: a DataFrame is present; columns are exactly ``ds``/``y``; ``ds`` is datetime-parseable,
    chronologically sorted, and free of duplicate timestamps; ``y`` is numeric and non-null; the
    split fractions sum to 1; and there are enough rows for each segment to hold >= 1 row.
    """
    errors: list[str] = []

    if df is None:
        return ValidationResult(ok=False, errors=["No CSV uploaded."])

    # Columns must be exactly ds, y.
    cols = list(df.columns)
    if cols[:2] != list(REQUIRED_CSV_COLUMNS) or len(cols) != 2:
        errors.append(
            "CSV must have exactly two columns named 'ds' (time) and 'y' (value), in that order; "
            f"got {cols}."
        )
        # Without the right columns the remaining checks are meaningless.
        return ValidationResult(ok=False, errors=errors)

    n = len(df)
    if n == 0:
        return ValidationResult(ok=False, errors=["CSV has no rows."])

    # ds: datetime-parseable, sorted, unique.
    try:
        ds = pd.to_datetime(df["ds"])
    except (ValueError, TypeError):
        errors.append("Column 'ds' is not datetime-parseable.")
        ds = None
    if ds is not None:
        if ds.duplicated().any():
            errors.append("Column 'ds' contains duplicate timestamps.")
        if not ds.is_monotonic_increasing:
            errors.append("Column 'ds' must be sorted in chronological order.")

    # y: numeric, non-null.
    y_numeric = pd.to_numeric(df["y"], errors="coerce")
    if y_numeric.isna().any():
        errors.append("Column 'y' must be numeric with no missing/empty values.")

    # Split fractions.
    frac_result = validate_split_fractions(train, val, test)
    errors.extend(frac_result.errors)

    # Row-count feasibility (each segment >= 1 row after flooring, matching _series_split_from_df).
    if frac_result.ok:
        test_rows = max(1, int(test * n))
        val_rows = max(1, int(val * n))
        train_rows = n - test_rows - val_rows
        if train_rows < 1:
            errors.append(
                f"Not enough rows ({n}) for this split — each of train/validation/test needs "
                "at least 1 row. Add more rows or adjust the fractions."
            )

    return ValidationResult(ok=not errors, errors=errors)
