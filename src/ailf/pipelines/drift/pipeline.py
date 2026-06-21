"""Drift pipeline entry point.

Wires the DriftGenerator into a FastAPI application that exposes a Swagger UI
for runtime control of synthetic drift dataset generation, plus a Prophet
forecast endpoint and an interactive Plotly-powered UI.

Run with:
    uv run python -m ailf.pipelines.drift.pipeline
or:
    PYTHONPATH=src uvicorn ailf.pipelines.drift.pipeline:app --reload --port 8000

Swagger UI:       http://127.0.0.1:8000/docs
Forecast UI:      http://127.0.0.1:8000/forecast/ui
"""

from __future__ import annotations

import io
import pathlib
from typing import Any, Literal

import pandas as pd
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator

from ailf.pipelines.drift.dataset_generator import DriftGenerator, _VALID_TRENDS

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
# Forecast routes — SPEC item 2i / 2ii / 2iii / 13
# ---------------------------------------------------------------------------

# HTML for the interactive forecast UI (no CDN — Plotly.js inlined via plotly)
# SPEC §13: show Qwen agent reasoning before invoking Prophet.
_UI_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Drift Forecast UI</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 1040px; margin: 2rem auto; padding: 0 1rem; }
    h1 { color: #1a3a5c; }
    h2 { color: #2a5a9c; font-size: 1rem; margin-top: 1.5rem; }
    label { font-weight: bold; display: block; margin-top: 1rem; }
    input, select { width: 100%; padding: .4rem; margin-top: .25rem; box-sizing: border-box; }
    button { margin-top: 1.2rem; padding: .6rem 2rem; background: #1a3a5c; color: #fff;
              border: none; border-radius: 4px; cursor: pointer; font-size: 1rem; }
    button:hover { background: #2a5a9c; }
    #status { margin-top: 1rem; color: #c00; font-size: .9rem; }

    /* Reasoning panel */
    #reasoning-section { display: none; margin-top: 1.5rem; }
    #reasoning-badge {
      display: inline-block; padding: .2rem .6rem; border-radius: 3px;
      font-size: .75rem; font-weight: bold; margin-left: .5rem; vertical-align: middle;
    }
    .badge-qwen   { background: #d4edda; color: #155724; }
    .badge-cusum  { background: #fff3cd; color: #856404; }
    #reasoning-box {
      background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px;
      padding: 1rem; font-size: .82rem; line-height: 1.6; white-space: pre-wrap;
      max-height: 320px; overflow-y: auto; font-family: monospace;
    }
    .cp-list { margin-top: .5rem; }
    .cp-item {
      display: flex; gap: .5rem; align-items: baseline;
      padding: .2rem 0; border-bottom: 1px solid #e9ecef; font-size: .8rem;
    }
    .cp-type { font-weight: bold; min-width: 80px; }
    .cp-dir  { min-width: 60px; color: #6c757d; }
    .cp-conf { min-width: 50px; }
    .cp-reason { color: #495057; }

    #chart { margin-top: 1.5rem; }
  </style>
</head>
<body>
  <h1>📈 Prophet Forecast Explorer</h1>
  <p>Upload a CSV with <code>ds</code> (date) and <code>y</code> (value) columns. The agent
     detects changepoints &amp; drifts first, then fits Prophet on the training data.</p>

  <form id="fcastForm">
    <label for="csvFile">CSV file (ds, y columns required):</label>
    <input type="file" id="csvFile" accept=".csv" required>

    <label for="horizon">Prediction length (days):</label>
    <input type="number" id="horizon" value="90" min="1" max="3650">

    <label for="freqSel">Frequency:</label>
    <select id="freqSel">
      <option value="D" selected>Daily (D)</option>
      <option value="W">Weekly (W)</option>
      <option value="MS">Monthly start (MS)</option>
    </select>

    <button type="submit">🔍 Detect &amp; Forecast</button>
  </form>

  <div id="status"></div>

  <!-- Qwen / agent reasoning panel -->
  <section id="reasoning-section">
    <h2>
      🤖 Agent Analysis
      <span id="reasoning-badge" class="reasoning-badge"></span>
    </h2>
    <div id="reasoning-box"></div>
    <div class="cp-list" id="cp-list"></div>
  </section>

  <div id="chart"></div>

  <script src="/forecast/plotly.js"></script>
  <script>
    const form   = document.getElementById('fcastForm');
    const status = document.getElementById('status');
    const chart  = document.getElementById('chart');
    const reasoningSection = document.getElementById('reasoning-section');
    const reasoningBox     = document.getElementById('reasoning-box');
    const reasoningBadge   = document.getElementById('reasoning-badge');
    const cpList           = document.getElementById('cp-list');

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      status.textContent = '⏳ Step 1/2 — Agent detecting changepoints…';
      chart.innerHTML = '';
      reasoningSection.style.display = 'none';
      cpList.innerHTML = '';

      const file    = document.getElementById('csvFile').files[0];
      const horizon = document.getElementById('horizon').value;
      const freq    = document.getElementById('freqSel').value;

      if (!file) { status.textContent = 'Please select a CSV file.'; return; }

      const fd = new FormData();
      fd.append('file', file);
      fd.append('prediction_length', horizon);
      fd.append('freq', freq);

      try {
        const resp = await fetch('/forecast/analyze', { method: 'POST', body: fd });
        if (!resp.ok) {
          const err = await resp.json();
          status.textContent = '❌ ' + (err.detail || JSON.stringify(err));
          return;
        }
        const data = await resp.json();
        status.textContent = '';

        // Show reasoning panel
        showReasoning(data);

        // Render forecast chart
        renderChart(data);

      } catch (err) {
        status.textContent = '❌ Network error: ' + err.message;
      }
    });

    function showReasoning(d) {
      const source = d.detection_source || 'cusum';
      const isQwen = source === 'qwen';

      reasoningBadge.textContent = isQwen ? '✓ Qwen (' + (d.detection_model || '') + ')' : '⚠ CUSUM fallback';
      reasoningBadge.className   = 'reasoning-badge ' + (isQwen ? 'badge-qwen' : 'badge-cusum');

      reasoningBox.textContent = d.reasoning || '(no reasoning returned)';

      // Changepoints table
      const cps = d.changepoints || [];
      if (cps.length) {
        cpList.innerHTML = '<strong>Detected changepoints (' + cps.length + '):</strong>';
        cps.forEach(cp => {
          const row = document.createElement('div');
          row.className = 'cp-item';
          const conf = cp.confidence != null ? (cp.confidence * 100).toFixed(0) + '%' : '—';
          row.innerHTML =
            '<span class="cp-type">' + (cp.type || '?') + '</span>' +
            '<span class="cp-dir">' + (cp.direction || '?') + '</span>' +
            '<span>' + (cp.timestamp || 'idx ' + cp.index) + '</span>' +
            '<span class="cp-conf">' + conf + '</span>' +
            '<span class="cp-reason">' + (cp.reason || '') + '</span>';
          cpList.appendChild(row);
        });
      } else {
        cpList.innerHTML = '<em>No changepoints detected.</em>';
      }

      reasoningSection.style.display = 'block';
    }

    function renderChart(d) {
      const hist = {
        x: d.historical.ds,
        y: d.historical.y,
        mode: 'lines',
        name: 'Historical (actual)',
        line: { color: '#1a3a5c', width: 2, dash: 'solid' },
      };

      const ci_upper = {
        x: d.forecast.ds,
        y: d.forecast.yhat_upper,
        mode: 'lines',
        name: 'Upper bound',
        line: { width: 0, color: 'rgba(70,130,180,0)' },
        showlegend: false,
      };
      const ci_lower = {
        x: d.forecast.ds,
        y: d.forecast.yhat_lower,
        fill: 'tonexty',
        fillcolor: 'rgba(70,130,180,0.15)',
        mode: 'lines',
        name: '95% CI',
        line: { width: 0 },
      };
      const fcast = {
        x: d.forecast.ds,
        y: d.forecast.yhat,
        mode: 'lines',
        name: 'Forecast (Prophet)',
        line: { color: '#e05c00', width: 2, dash: 'dash' },
      };

      // Mark changepoints as vertical lines
      const shapes = (d.changepoints || []).map(cp => ({
        type: 'line',
        x0: cp.timestamp || '', x1: cp.timestamp || '',
        yref: 'paper', y0: 0, y1: 1,
        line: { color: 'rgba(220,53,69,0.45)', width: 1.5, dash: 'dot' },
      }));

      const layout = {
        title: 'Historical vs. Forecast  —  horizon: ' + d.prediction_length + ' days'
               + (d.changepoints && d.changepoints.length
                  ? '  |  ' + d.changepoints.length + ' changepoints (dotted red)'
                  : ''),
        xaxis: { title: 'Date', rangeslider: { visible: true } },
        yaxis: { title: 'y' },
        legend: { orientation: 'h', y: -0.2 },
        hovermode: 'x unified',
        shapes: shapes,
      };

      Plotly.newPlot('chart', [hist, ci_upper, ci_lower, fcast], layout,
                     {responsive: true});
    }
  </script>
</body>
</html>
"""


@app.get(
    "/forecast/ui",
    response_class=HTMLResponse,
    summary="Interactive Prophet forecast UI",
    tags=["forecast"],
    include_in_schema=False,
)
def forecast_ui() -> HTMLResponse:
    """Serve the interactive Plotly-powered forecast explorer.

    Upload a CSV with ``ds`` and ``y`` columns, choose a prediction horizon,
    and visualise historical data (solid) vs. Prophet forecast (dashed) with
    95% confidence intervals (shaded).
    """
    return HTMLResponse(content=_UI_HTML)


@app.get(
    "/forecast/plotly.js",
    include_in_schema=False,
    response_class=HTMLResponse,
)
def serve_plotly_js() -> HTMLResponse:
    """Serve the bundled Plotly.js from the installed plotly package (no CDN)."""
    import plotly
    js_path = pathlib.Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    if not js_path.exists():
        # Fallback: minified bundle name varies by version
        candidates = list(pathlib.Path(plotly.__file__).parent.rglob("plotly*.min.js"))
        if not candidates:
            raise HTTPException(status_code=500, detail="plotly.min.js not found in package")
        js_path = candidates[0]
    from fastapi.responses import FileResponse
    return FileResponse(str(js_path), media_type="application/javascript")


@app.post(
    "/forecast/upload",
    summary="Upload CSV, fit Prophet, return forecast JSON",
    tags=["forecast"],
)
async def forecast_upload(
    file: UploadFile = File(..., description="CSV file with `ds` (date) and `y` (numeric) columns"),
    prediction_length: int = Form(default=90, ge=1, le=3650, description="Forecast horizon in days"),
    freq: str = Form(default="D", description="Pandas frequency string: D, W, MS, …"),
) -> dict[str, Any]:
    """Fit a Prophet model on the uploaded time series and return forecast data.

    **Request** (multipart/form-data):
    - ``file`` — CSV with at minimum ``ds`` and ``y`` columns
    - ``prediction_length`` — number of periods to forecast (default 90)
    - ``freq`` — frequency string passed to ``make_future_dataframe`` (default ``D``)

    **Response**:
    ```json
    {
      "historical": {"ds": [...], "y": [...]},
      "forecast":   {"ds": [...], "yhat": [...], "yhat_lower": [...], "yhat_upper": [...]},
      "prediction_length": 90
    }
    ```

    Historical data is returned as-is (solid line in UI).
    Forecast data covers the future horizon (dashed line + CI shading in UI).
    """
    # -- Parse CSV -----------------------------------------------------------
    raw = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot parse CSV: {exc}") from exc

    missing = {"ds", "y"} - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"CSV missing required columns: {sorted(missing)}. Got: {list(df.columns)}",
        )

    try:
        df["ds"] = pd.to_datetime(df["ds"])
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot parse 'ds' as dates: {exc}") from exc

    try:
        df["y"] = pd.to_numeric(df["y"], errors="raise")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot parse 'y' as numeric: {exc}") from exc

    df = df.sort_values("ds").reset_index(drop=True)

    if len(df) < 2:
        raise HTTPException(status_code=422, detail="CSV must contain at least 2 rows.")

    # -- Fit Prophet ---------------------------------------------------------
    try:
        from prophet import Prophet  # lazy import — keeps startup fast

        model = Prophet(
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=True,
        )
        # Add any extra regressors present in the CSV
        regressor_cols = [c for c in df.columns if c not in ("ds", "y")]
        for col in regressor_cols:
            model.add_regressor(col)

        model.fit(df[["ds", "y"] + regressor_cols])
        future = model.make_future_dataframe(periods=prediction_length, freq=freq)
        for col in regressor_cols:
            # Carry last-known regressor value forward into the future
            future[col] = df[col].iloc[-1]
        forecast = model.predict(future)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Prophet error: {exc}") from exc

    # -- Split historical vs. future ----------------------------------------
    cutoff = df["ds"].max()
    hist_part = forecast[forecast["ds"] <= cutoff][["ds", "yhat", "yhat_lower", "yhat_upper"]]
    fut_part  = forecast[forecast["ds"] >  cutoff][["ds", "yhat", "yhat_lower", "yhat_upper"]]

    def _to_str_list(series: pd.Series) -> list[str]:
        return series.dt.strftime("%Y-%m-%d").tolist()

    return {
        "historical": {
            "ds": _to_str_list(df["ds"]),
            "y":  df["y"].tolist(),
        },
        "forecast": {
            "ds":         _to_str_list(fut_part["ds"]),
            "yhat":       fut_part["yhat"].round(4).tolist(),
            "yhat_lower": fut_part["yhat_lower"].round(4).tolist(),
            "yhat_upper": fut_part["yhat_upper"].round(4).tolist(),
        },
        "prediction_length": prediction_length,
        "freq": freq,
        "n_historical": len(df),
        "n_forecast": len(fut_part),
    }


# ---------------------------------------------------------------------------
# Shared CSV + Prophet helper (used by both upload and analyze endpoints)
# ---------------------------------------------------------------------------

async def _parse_csv_upload(file: UploadFile) -> pd.DataFrame:
    """Read and validate an uploaded CSV; returns a clean DataFrame (ds, y, ...)."""
    raw = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot parse CSV: {exc}") from exc

    missing = {"ds", "y"} - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"CSV missing required columns: {sorted(missing)}. Got: {list(df.columns)}",
        )
    try:
        df["ds"] = pd.to_datetime(df["ds"])
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot parse 'ds' as dates: {exc}") from exc
    try:
        df["y"] = pd.to_numeric(df["y"], errors="raise")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot parse 'y' as numeric: {exc}") from exc

    df = df.sort_values("ds").reset_index(drop=True)
    if len(df) < 2:
        raise HTTPException(status_code=422, detail="CSV must contain at least 2 rows.")
    return df


def _run_prophet(df: pd.DataFrame, prediction_length: int, freq: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit Prophet on df; return (fut_part, df) where fut_part is the forecast horizon rows."""
    from prophet import Prophet  # lazy import

    prophet_model = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=True,
    )
    regressor_cols = [c for c in df.columns if c not in ("ds", "y")]
    for col in regressor_cols:
        prophet_model.add_regressor(col)

    prophet_model.fit(df[["ds", "y"] + regressor_cols])
    future = prophet_model.make_future_dataframe(periods=prediction_length, freq=freq)
    for col in regressor_cols:
        future[col] = df[col].iloc[-1]

    forecast = prophet_model.predict(future)
    cutoff = df["ds"].max()
    fut_part = forecast[forecast["ds"] > cutoff][["ds", "yhat", "yhat_lower", "yhat_upper"]]
    return fut_part, df


# ---------------------------------------------------------------------------
# Forecast/analyze — SPEC §13: Qwen reasoning panel before Prophet
# ---------------------------------------------------------------------------

@app.post(
    "/forecast/analyze",
    summary="Detect changepoints with Qwen/CUSUM, then fit Prophet",
    tags=["forecast"],
)
async def forecast_analyze(
    file: UploadFile = File(..., description="CSV file with `ds` and `y` columns"),
    prediction_length: int = Form(default=90, ge=1, le=3650, description="Forecast horizon in days"),
    freq: str = Form(default="D", description="Pandas frequency string: D, W, MS, …"),
) -> dict[str, Any]:
    """Run the full agent pipeline: detect changepoints first, then forecast.

    **Step 1** — Qwen (via Ollama) analyses the uploaded series and returns its
    reasoning narrative and detected changepoints. Falls back to CUSUM if Ollama
    is unavailable.

    **Step 2** — Prophet is fitted and the forecast is returned together with
    the agent's findings so the UI can display both side-by-side.

    **Response** extends ``/forecast/upload`` with:
    - ``reasoning``         — Qwen/CUSUM narrative text
    - ``changepoints``      — list of detected changepoint dicts
    - ``detection_source``  — "qwen" | "cusum"
    - ``detection_model``   — model name used
    """
    from ailf.pipelines.drift.llm_reason import detect as qwen_detect

    # Parse CSV
    df = await _parse_csv_upload(file)

    # Step 1: Agent changepoint detection
    detection = qwen_detect(df)

    # Step 2: Prophet forecast
    try:
        fut_part, df = _run_prophet(df, prediction_length, freq)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Prophet error: {exc}") from exc

    def _to_str_list(series: pd.Series) -> list[str]:
        return series.dt.strftime("%Y-%m-%d").tolist()

    return {
        "historical": {
            "ds": _to_str_list(df["ds"]),
            "y":  df["y"].tolist(),
        },
        "forecast": {
            "ds":         _to_str_list(fut_part["ds"]),
            "yhat":       fut_part["yhat"].round(4).tolist(),
            "yhat_lower": fut_part["yhat_lower"].round(4).tolist(),
            "yhat_upper": fut_part["yhat_upper"].round(4).tolist(),
        },
        "prediction_length": prediction_length,
        "freq": freq,
        "n_historical": len(df),
        "n_forecast": len(fut_part),
        "reasoning":        detection.reasoning,
        "changepoints":     detection.changepoints,
        "detection_source": detection.source,
        "detection_model":  detection.model,
    }


# ---------------------------------------------------------------------------
# Changepoint pipeline endpoints — §12: call src/ailf/core/ from the UI
#
# All changepoint imports are LAZY (inside handler bodies) so that a missing
# langchain_aws or absent AWS creds does NOT break the drift API at load time.
# ---------------------------------------------------------------------------

_REPORTS_ROOT = pathlib.Path(__file__).parents[4] / "reports"

_VALID_SCENARIOS = frozenset({
    "level_shift_loses_seasonality",
    "gradual_drift_loses_seasonality",
    "temporary_event_not_regime_change",
    "many_temporary_events_long_history",
    "prophet_prior_tuning_recurring_event",
})


class ChangepointOverride(BaseModel):
    """Partial override for a changepoint pipeline run.

    All fields optional; unset fields inherit the config.yaml defaults.
    Do NOT include AWS credentials or API keys here — use .env.
    """
    models: dict[str, str] | None = None          # visual_model_id, decision_model_id, aws_region
    visual_analysis_enabled: bool | None = None
    diagnostics: dict[str, bool] | None = None    # per-diagnostic enable/disable
    agent_tools: dict[str, bool] | None = None    # per-tool enable/disable
    seed: int | None = None


class ChangepointRunRequest(BaseModel):
    scenario_id: str
    override: ChangepointOverride = ChangepointOverride()


class ChangepointRunResponse(BaseModel):
    status: str                        # "ok" | "error" | "unavailable"
    run_id: str | None = None
    metrics: dict[str, Any] | None = None
    final_eval: dict[str, Any] | None = None
    error: str | None = None
    cli_command: str | None = None     # always returned so UI can fall back


def _build_cli_command(scenario_id: str, override: ChangepointOverride) -> str:
    """Return the equivalent uv run CLI command string."""
    import json as _json
    ov: dict[str, Any] = {}
    if override.models:
        ov["models"] = override.models
    if override.visual_analysis_enabled is not None:
        ov["visual_analysis_enabled"] = override.visual_analysis_enabled
    if override.diagnostics:
        ov["diagnostics"] = override.diagnostics
    if override.agent_tools:
        ov["agent_tools"] = override.agent_tools
    if override.seed is not None:
        ov["seed"] = override.seed
    override_str = _json.dumps(ov) if ov else "{}"
    return (
        f"uv run python -m ailf.pipelines.changepoint.pipeline "
        f"--scenario {scenario_id} "
        f"--override '{override_str}'"
    )


@app.post(
    "/changepoint/run",
    response_model=ChangepointRunResponse,
    summary="Run the changepoint agent pipeline for a scenario",
    tags=["changepoint"],
)
def changepoint_run(body: ChangepointRunRequest) -> ChangepointRunResponse:
    """Invoke the full agent-in-the-loop changepoint pipeline for one scenario.

    Requires AWS Bedrock credentials in ``.env`` (``AWS_ACCESS_KEY_ID``,
    ``AWS_SECRET_ACCESS_KEY``) and ``langchain_aws`` installed.  When either is
    absent the endpoint returns ``status="unavailable"`` **and** the equivalent
    CLI command so the caller can run it manually.

    The completed run writes artifacts under ``reports/<run_id>/``:
    ``metrics.json``, ``agent_trace.json``, ``forecast_comparison.png``, etc.
    Retrieve them via **GET /changepoint/artifacts/{scenario_id}**.
    """
    if body.scenario_id not in _VALID_SCENARIOS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scenario '{body.scenario_id}'. "
                   f"Valid values: {sorted(_VALID_SCENARIOS)}",
        )

    cli = _build_cli_command(body.scenario_id, body.override)

    try:
        # Lazy import — must NOT be at module scope
        from ailf.pipelines.changepoint.pipeline import run_scenario  # noqa: PLC0415

        ov_dict: dict[str, Any] = {}
        if body.override.models:
            ov_dict["models"] = body.override.models
        if body.override.visual_analysis_enabled is not None:
            ov_dict["visual_analysis_enabled"] = body.override.visual_analysis_enabled
        if body.override.diagnostics:
            ov_dict["diagnostics"] = body.override.diagnostics
        if body.override.agent_tools:
            ov_dict["agent_tools"] = body.override.agent_tools
        if body.override.seed is not None:
            ov_dict["seed"] = body.override.seed

        from ailf.core.config.schema import ConfigOverride  # noqa: PLC0415
        override_obj = ConfigOverride.from_dict(ov_dict) if ov_dict else None

        result = run_scenario(body.scenario_id, override=override_obj, emit_events=True)

        return ChangepointRunResponse(
            status="ok",
            run_id=result.get("run_id"),
            metrics=result.get("metrics"),
            final_eval=result.get("final_eval"),
            cli_command=cli,
        )

    except (ImportError, ModuleNotFoundError) as exc:
        return ChangepointRunResponse(
            status="unavailable",
            error=f"Missing dependency: {exc}. Install langchain_aws or run via CLI.",
            cli_command=cli,
        )
    except Exception as exc:
        return ChangepointRunResponse(
            status="error",
            error=str(exc),
            cli_command=cli,
        )


class ArtifactSummary(BaseModel):
    run_id: str
    scenario_id: str
    has_metrics: bool
    has_trace: bool
    has_forecast_png: bool
    has_context_png: bool
    metrics: dict[str, Any] | None = None
    final_eval: dict[str, Any] | None = None
    agent_iterations: list[dict[str, Any]] | None = None


@app.get(
    "/changepoint/artifacts/{scenario_id}",
    response_model=list[ArtifactSummary],
    summary="List pre-computed changepoint run artifacts for a scenario",
    tags=["changepoint"],
)
def changepoint_artifacts(scenario_id: str) -> list[ArtifactSummary]:
    """Return a summary of any pre-computed run artifacts under ``reports/``.

    Reads ``metrics.json`` and ``agent_trace.json`` from every matching run
    directory.  Images are referenced by name only (no binary payload).

    Returns an empty list when no runs exist — run the pipeline first via
    **POST /changepoint/run** or the CLI command it returns.
    """
    import json as _json

    if scenario_id not in _VALID_SCENARIOS and scenario_id != "*":
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scenario '{scenario_id}'. "
                   f"Valid values: {sorted(_VALID_SCENARIOS)}",
        )

    results: list[ArtifactSummary] = []
    if not _REPORTS_ROOT.exists():
        return results

    pattern = f"{scenario_id}*" if scenario_id != "*" else "*"
    for run_dir in sorted(_REPORTS_ROOT.glob(pattern)):
        if not run_dir.is_dir():
            continue
        metrics: dict[str, Any] | None = None
        final_eval: dict[str, Any] | None = None
        agent_iters: list[dict[str, Any]] | None = None

        mpath = run_dir / "metrics.json"
        if mpath.exists():
            try:
                metrics = _json.loads(mpath.read_text())
                final_eval = metrics.get("final_eval")
            except Exception:
                pass

        tpath = run_dir / "agent_trace.json"
        if tpath.exists():
            try:
                trace = _json.loads(tpath.read_text())
                agent_iters = trace.get("iterations", [])
            except Exception:
                pass

        results.append(ArtifactSummary(
            run_id=run_dir.name,
            scenario_id=scenario_id,
            has_metrics=mpath.exists(),
            has_trace=tpath.exists(),
            has_forecast_png=(run_dir / "forecast_comparison.png").exists(),
            has_context_png=(run_dir / "agent_context.png").exists(),
            metrics=metrics,
            final_eval=final_eval,
            agent_iterations=agent_iters,
        ))

    return results


@app.get(
    "/changepoint/scenarios",
    response_model=list[str],
    summary="List valid changepoint scenario IDs",
    tags=["changepoint"],
)
def changepoint_scenarios() -> list[str]:
    """Return the list of committed changepoint scenario IDs."""
    return sorted(_VALID_SCENARIOS)


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
