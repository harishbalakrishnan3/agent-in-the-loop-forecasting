# Drift Synthetic Dataset Generator

**Session:** `ksowmya` · **Phase:** 1 — Dataset Generation

---

## Overview

A seeded, knob-driven synthetic time-series generator that injects seven types of
distribution drift into a base series. Every generated dataset returns:

- a **Prophet-compatible DataFrame** (`ds`, `y`, optional covariates)  
- a **metadata dict** with the ground-truth injection location and magnitude  
  (used for precision / recall evaluation of the drift-detection tool)

The generator's `trend` parameter (`flat | linear | exponential`) can be changed
**at runtime** via a FastAPI endpoint without restarting the server.

---

## Architecture

See [`architecture-phase1.md`](./architecture-phase1.md) for the full Mermaid diagram.

```
src/config/config.yml            ← defaults (trend, noise, per-drift knobs)
src/ailf/pipelines/drift/
    datasets.py                  ← DriftGenerator (pure, typed, seeded)
    pipeline.py                  ← FastAPI app (Swagger UI at /docs)
tests/pipelines/drift/
    test_datasets.py             ← TDD tests with injected ground truth
    test_api.py                  ← HTTP endpoint tests (httpx TestClient)
```

---

## Setup

```bash
# Preferred (uv) — reads pyproject.toml + uv.lock
uv sync

# Alternative (pip) — uses requirements.txt with all pinned transitive deps
pip install -r requirements.txt

# Copy environment file (add API keys if needed later)
cp .env.example .env
```

> **Note:** `SiD2ReGenerator` (referenced in SPEC-dataset.md) was not found on
> PyPI. The dataset generator uses **Darts / numpy / pandas** as mandated by the
> project constitution (§ Technology & Architecture Constraints).

---

## Running the API Server

```bash
uv run uvicorn ailf.pipelines.drift.pipeline:app --reload --port 8000
```

- **Swagger UI:** <http://127.0.0.1:8000/docs>  
- **OpenAPI JSON:** <http://127.0.0.1:8000/openapi.json>

---

## Changing the Trend at Runtime

The `trend` parameter controls the base series shape (`flat`, `linear`, or
`exponential`). Update it without restarting:

```bash
# Set trend to exponential
curl -X PATCH http://127.0.0.1:8000/drift/config/trend \
     -H "Content-Type: application/json" \
     -d '{"trend": "exponential"}'

# Read current config
curl http://127.0.0.1:8000/drift/config
```

Or use the **Swagger UI** at `/docs` → `PATCH /drift/config/trend`.

---

## Generating a Dataset via the API

```bash
# Sudden drift at index 150, magnitude 12
curl -X POST http://127.0.0.1:8000/drift/generate/sudden \
     -H "Content-Type: application/json" \
     -d '{"seed": 42, "n_points": 365, "drift_point": 150, "magnitude": 12.0}'
```

**Supported drift types** (path parameter):

| `drift_type` | Key request body fields |
|---|---|
| `sudden` | `drift_point`, `magnitude` |
| `gradual` | `drift_start`, `drift_end`, `magnitude` |
| `incremental` | `drift_start`, `slope` |
| `seasonal` | `season_length`, `amplitude_before`, `amplitude_after`, `change_point` |
| `recurring` | `period`, `duration`, `magnitude` |
| `covariate` | `n_covariates`, `drift_point`, `covariate_magnitude` |
| `concept` | `change_point`, `coef_before`, `coef_after` |

All fields are optional — defaults come from `src/config/config.yml`.

**Response shape:**
```json
{
  "data": [{"ds": "2023-01-01", "y": 1.23}, ...],
  "meta": {"drift_type": "sudden", "drift_point": 150, "magnitude": 12.0, "seed": 42}
}
```

---

## Using `DriftGenerator` Directly (Python)

```python
from pathlib import Path
from ailf.pipelines.drift.datasets import DriftGenerator

gen = DriftGenerator(config_path=Path("src/config/config.yml"))

# Sudden drift — injected at index 100, magnitude 10
df, meta = gen.sudden_drift(seed=42, n_points=365, drift_point=100, magnitude=10.0)
print(df.head())
print(meta)  # {"drift_type": "sudden", "drift_point": 100, "magnitude": 10.0, "seed": 42}

# Override trend for this generator instance
gen.trend = "exponential"
df2, _ = gen.gradual_drift(seed=0, drift_start=80, drift_end=200, magnitude=5.0)
```

---

## Running Tests

```bash
# All drift tests
uv run pytest tests/pipelines/drift -v

# Dataset tests only
uv run pytest tests/pipelines/drift/test_datasets.py -v

# API tests only
uv run pytest tests/pipelines/drift/test_api.py -v

# Full test suite
uv run pytest
```

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| `(DataFrame, metadata)` return type | Metadata carries injected ground truth for precision/recall eval (constitution Principle II) |
| Local `np.random.default_rng(seed)` per call | Avoids global RNG state; each call is independently reproducible (constitution Principle V) |
| Mutable `trend` on the generator instance | Allows the API layer to update runtime state without file I/O |
| `_AppState` singleton in `api.py` | One generator per process; PATCH effects persist across requests |
| `pyyaml` for config | Lightweight, no extra dependencies; YAML is human-readable |
| TDD test order | Tests written before implementation per constitution Principle II (non-negotiable) |
| `requirements.txt` with pinned deps | Full transitive pin-set for `pip` compatibility; uv.lock remains canonical for `uv sync` |

---

## Configuration Reference (`src/config/config.yml`)

```yaml
drift:
  trend: linear          # flat | linear | exponential  ← runtime-mutable
  n_points: 365
  seed: 42
  noise_std: 1.0
  start_date: "2023-01-01"
  freq: "D"              # pandas freq string
  sudden:
    drift_point: 182
    magnitude: 10.0
  gradual:
    drift_start: 100
    drift_end: 265
    magnitude: 8.0
  incremental:
    drift_start: 100
    slope: 0.05
  seasonal:
    season_length: 7
    amplitude_before: 3.0
    amplitude_after: 8.0
    change_point: 182
  recurring:
    period: 90
    duration: 20
    magnitude: 6.0
  covariate:
    n_covariates: 1
    drift_point: 182
    covariate_magnitude: 5.0
  concept:
    change_point: 182
    coef_before: 1.5
    coef_after: -1.5
```
