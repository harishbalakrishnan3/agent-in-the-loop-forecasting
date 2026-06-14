"""Drift pipeline entry point.

Wires the DriftGenerator into a FastAPI application that exposes a Swagger UI
for runtime control of synthetic drift dataset generation.

Run with:
    uv run python -m ailf.pipelines.drift.pipeline
or:
    PYTHONPATH=src uvicorn ailf.pipelines.drift.pipeline:app --reload --port 8000

Swagger UI: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import pathlib
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from ailf.pipelines.drift.datasets import DriftGenerator, _VALID_TRENDS

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_CONFIG_PATH = pathlib.Path(__file__).parents[3] / "config" / "config.yml"

app = FastAPI(
    title="Drift Dataset Generator API",
    description=(
        "Runtime-configurable synthetic drift dataset generator for the "
        "Agent-in-the-Loop Forecasting project.\n\n"
        "Update `trend` via **PATCH /drift/config/trend**, then call "
        "**POST /drift/generate/{drift_type}** to produce a fresh dataset."
    ),
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Shared mutable state — one generator per process
# ---------------------------------------------------------------------------

class _AppState:
    def __init__(self) -> None:
        self.generator = DriftGenerator(config_path=_CONFIG_PATH)


_state = _AppState()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

TrendLiteral = Literal["flat", "linear", "exponential", "sine", "binary"]


class TrendUpdate(BaseModel):
    trend: TrendLiteral

    @field_validator("trend")
    @classmethod
    def must_be_valid(cls, v: str) -> str:
        if v not in _VALID_TRENDS:
            raise ValueError(
                f"trend must be one of {sorted(_VALID_TRENDS)}, got '{v}'"
            )
        return v


class ConfigResponse(BaseModel):
    trend: str
    n_points: int
    noise_std: float
    seed: int
    start_date: str
    freq: str


class GenerateRequest(BaseModel):
    seed: int = 42
    n_points: int | None = None
    # sudden
    drift_point: int | None = None
    magnitude: float | None = None
    # gradual
    drift_start: int | None = None
    drift_end: int | None = None
    # incremental
    slope: float | None = None
    # seasonal
    season_length: int | None = None
    amplitude_before: float | None = None
    amplitude_after: float | None = None
    change_point: int | None = None
    # recurring
    period: int | None = None
    duration: int | None = None
    # covariate / concept
    n_covariates: int = 1
    covariate_magnitude: float | None = None
    coef_before: float | None = None
    coef_after: float | None = None
    # shared overrides
    noise_std: float | None = None
    start_date: str | None = None
    freq: str | None = None


class DriftSpec(BaseModel):
    """A single drift component spec for combined_drift."""

    type: str
    drift_point: int | None = None
    magnitude: float | None = None
    drift_start: int | None = None
    drift_end: int | None = None
    slope: float | None = None
    season_length: int | None = None
    amplitude_before: float | None = None
    amplitude_after: float | None = None
    change_point: int | None = None
    period: int | None = None
    duration: int | None = None
    n_covariates: int | None = None
    covariate_magnitude: float | None = None
    coef_before: float | None = None
    coef_after: float | None = None


class CombinedGenerateRequest(BaseModel):
    drift_specs: list[DriftSpec]
    seed: int = 42
    n_points: int | None = None
    noise_std: float | None = None
    start_date: str | None = None
    freq: str | None = None


class GenerateResponse(BaseModel):
    data: list[dict[str, Any]]
    meta: dict[str, Any]


# ---------------------------------------------------------------------------
# Routes — Config
# ---------------------------------------------------------------------------

@app.get(
    "/drift/config",
    response_model=ConfigResponse,
    summary="Get current runtime configuration",
    tags=["config"],
)
def get_config() -> ConfigResponse:
    """Return the active configuration driving the drift generator."""
    gen = _state.generator
    cfg = gen._cfg  # noqa: SLF001
    return ConfigResponse(
        trend=gen.trend,
        n_points=cfg.get("n_points", 365),
        noise_std=cfg.get("noise_std", 1.0),
        seed=cfg.get("seed", 42),
        start_date=cfg.get("start_date", "2023-01-01"),
        freq=cfg.get("freq", "D"),
    )


@app.patch(
    "/drift/config/trend",
    response_model=ConfigResponse,
    summary="Update the trend at runtime",
    tags=["config"],
)
def update_trend(body: TrendUpdate) -> ConfigResponse:
    """Change the base-series trend without restarting the server.

    Valid values: `flat` · `linear` · `exponential`

    The new trend is applied immediately to all subsequent generate calls.
    """
    _state.generator.trend = body.trend
    return get_config()


# ---------------------------------------------------------------------------
# Routes — Generate
# ---------------------------------------------------------------------------

@app.post(
    "/drift/generate/{drift_type}",
    response_model=GenerateResponse,
    summary="Generate a synthetic drift dataset",
    tags=["generate"],
)
def generate_drift(drift_type: str, body: GenerateRequest) -> GenerateResponse:
    """Generate a Prophet-compatible dataset with the specified drift type.

    **drift_type** must be one of:
    `sudden` · `gradual` · `incremental` · `seasonal` · `recurring` · `covariate` · `concept`

    All body fields are optional; defaults are read from `src/config/config.yml`.

    Response includes:
    - **data** — list of `{ds, y[, x0, x1, …]}` records (ISO date strings)
    - **meta** — ground-truth injection location and parameters
    """
    gen = _state.generator
    common: dict[str, Any] = {"seed": body.seed}
    if body.n_points   is not None: common["n_points"]   = body.n_points
    if body.noise_std  is not None: common["noise_std"]  = body.noise_std
    if body.start_date is not None: common["start_date"] = body.start_date
    if body.freq       is not None: common["freq"]       = body.freq

    if drift_type == "sudden":
        kw = {**common}
        if body.drift_point is not None: kw["drift_point"] = body.drift_point
        if body.magnitude   is not None: kw["magnitude"]   = body.magnitude
        df, meta = gen.sudden_drift(**kw)

    elif drift_type == "gradual":
        kw = {**common}
        if body.drift_start is not None: kw["drift_start"] = body.drift_start
        if body.drift_end   is not None: kw["drift_end"]   = body.drift_end
        if body.magnitude   is not None: kw["magnitude"]   = body.magnitude
        df, meta = gen.gradual_drift(**kw)

    elif drift_type == "incremental":
        kw = {**common}
        if body.drift_start is not None: kw["drift_start"] = body.drift_start
        if body.slope       is not None: kw["slope"]       = body.slope
        df, meta = gen.incremental_drift(**kw)

    elif drift_type == "seasonal":
        kw = {**common}
        if body.season_length    is not None: kw["season_length"]    = body.season_length
        if body.amplitude_before is not None: kw["amplitude_before"] = body.amplitude_before
        if body.amplitude_after  is not None: kw["amplitude_after"]  = body.amplitude_after
        if body.change_point     is not None: kw["change_point"]     = body.change_point
        df, meta = gen.seasonal_drift(**kw)

    elif drift_type == "recurring":
        kw = {**common}
        if body.period    is not None: kw["period"]    = body.period
        if body.duration  is not None: kw["duration"]  = body.duration
        if body.magnitude is not None: kw["magnitude"] = body.magnitude
        df, meta = gen.recurring_drift(**kw)

    elif drift_type == "covariate":
        kw = {**common, "n_covariates": body.n_covariates}
        if body.drift_point         is not None: kw["drift_point"]         = body.drift_point
        if body.covariate_magnitude is not None: kw["covariate_magnitude"] = body.covariate_magnitude
        df, meta = gen.covariate_drift(**kw)

    elif drift_type == "concept":
        kw = {**common}
        if body.change_point is not None: kw["change_point"] = body.change_point
        if body.coef_before  is not None: kw["coef_before"]  = body.coef_before
        if body.coef_after   is not None: kw["coef_after"]   = body.coef_after
        df, meta = gen.concept_drift(**kw)

    else:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown drift_type '{drift_type}'. "
                "Must be one of: sudden, gradual, incremental, seasonal, "
                "recurring, covariate, concept."
            ),
        )

    df["ds"] = df["ds"].dt.strftime("%Y-%m-%d")
    return GenerateResponse(data=df.to_dict(orient="records"), meta=meta)


@app.post(
    "/drift/generate/combined",
    response_model=GenerateResponse,
    summary="Generate a dataset with combined (stacked) drift types",
    tags=["generate"],
)
def generate_combined(body: CombinedGenerateRequest) -> GenerateResponse:
    """Stack multiple drift types on a single shared base series.

    Send a list of ``drift_specs`` where each entry has a ``type`` field plus
    any per-drift overrides.  All drift effects accumulate on the same series
    (spec item 7).

    Example body::

        {
          "drift_specs": [
            {"type": "sudden", "drift_point": 100, "magnitude": 8.0},
            {"type": "gradual", "drift_start": 200, "drift_end": 300, "magnitude": 5.0}
          ],
          "seed": 42
        }
    """
    gen = _state.generator
    specs = [s.model_dump(exclude_none=True) for s in body.drift_specs]
    kw: dict[str, Any] = {"seed": body.seed}
    if body.n_points   is not None: kw["n_points"]   = body.n_points
    if body.noise_std  is not None: kw["noise_std"]  = body.noise_std
    if body.start_date is not None: kw["start_date"] = body.start_date
    if body.freq       is not None: kw["freq"]       = body.freq

    df, meta = gen.combined_drift(drift_specs=specs, **kw)
    df["ds"] = df["ds"].dt.strftime("%Y-%m-%d")
    return GenerateResponse(data=df.to_dict(orient="records"), meta=meta)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Launch the drift pipeline API server."""
    uvicorn.run(
        "ailf.pipelines.drift.pipeline:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
