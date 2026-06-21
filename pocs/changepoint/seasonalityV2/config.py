"""Configuration: bounded parameter grid and environment loading.

Single source of truth for all constants used across seasonalityV2.
No external dependencies beyond stdlib + python-dotenv.

Usage
-----
    from config import load_config, validate_config, VALID_GRID, DEFAULT_SEED

    cfg = load_config(seed=42)
    validate_config({"changepoint_prior_scale": 0.1, ...})  # raises ValueError if invalid
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Bounded parameter grid (spec FR-022)
# ---------------------------------------------------------------------------

CHANGEPOINT_PRIOR_SCALE_GRID: list[float] = [0.001, 0.01, 0.05, 0.1, 0.5]
SEASONALITY_PRIOR_SCALE_GRID: list[float] = [0.01, 0.1, 1.0, 10.0]
SEASONALITY_MODE_GRID: list[str]          = ["additive", "multiplicative"]
CHANGEPOINT_RANGE_GRID: list[float]       = [0.8, 0.9, 0.95]
N_CHANGEPOINTS_GRID: list[int]            = [10, 15, 25]

VALID_GRID: dict = {
    "changepoint_prior_scale": CHANGEPOINT_PRIOR_SCALE_GRID,
    "seasonality_prior_scale": SEASONALITY_PRIOR_SCALE_GRID,
    "seasonality_mode":        SEASONALITY_MODE_GRID,
    "changepoint_range":       CHANGEPOINT_RANGE_GRID,
    "n_changepoints":          N_CHANGEPOINTS_GRID,
}

# ---------------------------------------------------------------------------
# Global constants
# ---------------------------------------------------------------------------

MAX_AGENT_ITERATIONS: int = 5
DEFAULT_SEED: int          = 42
TRAIN_FRAC: float          = 0.70
VAL_FRAC: float            = 0.15
TEST_FRAC: float           = 0.15

# Default dataset parameters
DATASET_LENGTH: int             = 1095   # ≈ 3 years daily
SEASONALITY_PERIOD: int         = 30     # monthly seasonality
BASE_SEASONAL_AMPLITUDE: float  = 3.0
BASE_NOISE_STD: float           = 0.8
BASE_TREND_SLOPE: float         = 0.02   # units/day in first segment

# Changepoint injection indices (approximate; exact values computed in datasets.py)
CP_A_IDX: int = 200   # Level shift
CP_B_IDX: int = 420   # Trend kink
CP_C_IDX: int = 630   # Variance change
CP_D_IDX: int = 840   # Seasonality mode shift

# LLM retry settings
LLM_MAX_RETRIES: int    = 3
LLM_RETRY_DELAY_S: float = 2.0

# Default model (overridable via PROPHET_AGENT_MODEL_ID env var)
DEFAULT_MODEL_ID: str = "us.anthropic.claude-sonnet-4-5-20251002-v1:0"
DEFAULT_AWS_REGION: str = "us-east-1"


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class RunConfig:
    model_id: str
    aws_region: str
    langsmith_tracing: bool
    seed: int


class ConfigError(RuntimeError):
    """Raised when required environment variables are missing."""


def load_config(seed: int = DEFAULT_SEED) -> RunConfig:
    """Load runtime configuration from environment variables.

    Required env vars
    -----------------
    PROPHET_AGENT_MODEL_ID : Bedrock model identifier for the agent LLM.
    AWS_REGION             : AWS region for Bedrock.

    Optional env vars
    -----------------
    LANGSMITH_TRACING : "true" / "false" (default false).

    Raises
    ------
    ConfigError
        If any required env var is missing or empty.
    """
    model_id = os.getenv("PROPHET_AGENT_MODEL_ID", "").strip()
    aws_region = os.getenv("AWS_REGION", "").strip()

    missing = []
    if not model_id:
        missing.append("PROPHET_AGENT_MODEL_ID")
    if not aws_region:
        missing.append("AWS_REGION")

    if missing:
        # Fall back to defaults with a warning rather than hard-failing,
        # so the POC can be developed without full AWS credentials.
        import warnings
        warnings.warn(
            f"Missing env vars {missing} — using defaults. "
            f"Set them in .env before running the agent loop.",
            stacklevel=2,
        )
        model_id = model_id or DEFAULT_MODEL_ID
        aws_region = aws_region or DEFAULT_AWS_REGION

    langsmith_tracing = os.getenv("LANGSMITH_TRACING", "false").strip().lower() == "true"

    return RunConfig(
        model_id=model_id,
        aws_region=aws_region,
        langsmith_tracing=langsmith_tracing,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Grid validation
# ---------------------------------------------------------------------------

def validate_config(proposed: dict) -> None:
    """Validate that all keys in `proposed` fall within VALID_GRID.

    Parameters
    ----------
    proposed : dict
        Keys must be a subset of VALID_GRID keys. Values are checked
        against the allowed discrete set for each key.

    Raises
    ------
    ValueError
        If any value is out of bounds or any key is unrecognised.
        The message lists every violation found.
    """
    violations: list[str] = []

    for key, value in proposed.items():
        if key not in VALID_GRID:
            violations.append(f"  Unknown parameter '{key}' (not in VALID_GRID)")
            continue
        allowed = VALID_GRID[key]
        # Use approximate float comparison for float grids
        if isinstance(value, float):
            match = any(abs(value - a) < 1e-9 for a in allowed if isinstance(a, float))
        else:
            match = value in allowed
        if not match:
            violations.append(
                f"  '{key}' = {value!r} not in allowed grid {allowed}"
            )

    if violations:
        raise ValueError(
            "Prophet config contains out-of-bounds values:\n" + "\n".join(violations)
        )
