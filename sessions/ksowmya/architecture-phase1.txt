# Architecture — Phase 1: Drift Synthetic Dataset Generator

## System Flow Diagram

```mermaid
flowchart TD
    subgraph Config["⚙️ Configuration Layer"]
        CFG["src/config/config.yml\n─────────────────\ntrend: linear\nn_points: 365\nseed: 42\nnoise_std: 1.0\n+ per-drift-type defaults"]
    end

    subgraph API["🌐 FastAPI Runtime Layer\nsrc/ailf/pipelines/drift/pipeline.py"]
        direction TB
        EP_GET["GET /drift/config\nRead active config"]
        EP_PATCH["PATCH /drift/config/trend\nUpdate trend at runtime"]
        EP_POST["POST /drift/generate/{drift_type}\nGenerate dataset"]
        SWAGGER["Swagger UI /docs\nOpenAPI /openapi.json"]
        STATE["_AppState singleton\n(mutable DriftGenerator)"]

        EP_GET --> STATE
        EP_PATCH --> STATE
        EP_POST --> STATE
        SWAGGER -. "auto-generated" .-> EP_GET
        SWAGGER -. "auto-generated" .-> EP_PATCH
        SWAGGER -. "auto-generated" .-> EP_POST
    end

    subgraph Generator["🔬 DriftGenerator\nsrc/ailf/pipelines/drift/datasets.py"]
        direction TB
        INIT["__init__(config_path, trend)\nLoads YAML → validates trend"]
        SUDDEN["sudden_drift()\nAbrupt mean shift"]
        GRADUAL["gradual_drift()\nSlow ramp shift"]
        INCREMENTAL["incremental_drift()\nAdditional slope"]
        SEASONAL["seasonal_drift()\nAmplitude change"]
        RECURRING["recurring_drift()\nPeriodic windows"]
        COVARIATE["covariate_drift()\nExogenous shift"]
        CONCEPT["concept_drift()\nRelationship reversal"]
    end

    subgraph Output["📦 Output"]
        DF["DataFrame\nds: datetime  y: float\n(+ x0, x1… for covariate/concept)"]
        META["Metadata dict\nground-truth injection\nlocation + magnitude"]
    end

    subgraph Tests["🧪 Tests\ntests/pipelines/drift/"]
        T_DS["test_datasets.py\nInjects known drift → asserts\nprecision/recall proxy\nreproducibility checks"]
        T_API["test_pipeline.py\nhttpx TestClient\nconfiguration endpoints\ngenerate endpoints\nSwagger reachability"]
    end

    CFG -->|"read at init"| INIT
    INIT --> SUDDEN & GRADUAL & INCREMENTAL & SEASONAL & RECURRING & COVARIATE & CONCEPT
    STATE -->|"holds"| INIT
    SUDDEN & GRADUAL & INCREMENTAL & SEASONAL & RECURRING & COVARIATE & CONCEPT --> DF
    SUDDEN & GRADUAL & INCREMENTAL & SEASONAL & RECURRING & COVARIATE & CONCEPT --> META

    T_DS -->|"imports"| Generator
    T_API -->|"imports"| API

    DF -->|"JSON records\nvia API"| EP_POST
    META -->|"JSON meta\nvia API"| EP_POST
```

## Component Responsibilities

| Component | Responsibility |
|-----------|---------------|
| `src/config/config.yml` | Single source of defaults; `trend` is the primary runtime knob |
| `DriftGenerator` | Pure, typed, seeded generator; returns `(DataFrame, metadata)` |
| `pipeline.py` (FastAPI) | Thin HTTP layer over `DriftGenerator`; exposes Swagger UI |
| `_AppState` | Singleton that holds the mutable generator so PATCH effects persist |
| `test_datasets.py` | TDD tests against injected ground truth (Principle II) |
| `test_pipeline.py` | TestClient tests for all HTTP endpoints |

## Drift Types Quick Reference

| Method | What changes | Key parameter |
|--------|-------------|---------------|
| `sudden_drift` | Abrupt mean shift | `drift_point`, `magnitude` |
| `gradual_drift` | Slow linear ramp | `drift_start`, `drift_end`, `magnitude` |
| `incremental_drift` | Growing trend slope | `drift_start`, `slope` |
| `seasonal_drift` | Seasonal amplitude | `change_point`, `amplitude_before/after` |
| `recurring_drift` | Periodic drift windows | `period`, `duration`, `magnitude` |
| `covariate_drift` | Exogenous variable distribution | `drift_point`, `covariate_magnitude` |
| `concept_drift` | Feature→target relationship | `change_point`, `coef_before/after` |

## Runtime Trend Update Flow

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI (pipeline.py)
    participant State as _AppState
    participant Gen as DriftGenerator

    Client->>API: PATCH /drift/config/trend {"trend":"exponential"}
    API->>State: state.generator.trend = "exponential"
    State->>Gen: trend attribute mutated
    API-->>Client: 200 {"trend":"exponential", ...}

    Client->>API: POST /drift/generate/sudden {"seed":42,"n_points":200}
    API->>State: state.generator.sudden_drift(seed=42, n_points=200)
    State->>Gen: sudden_drift uses trend="exponential" base
    Gen-->>State: (DataFrame, meta)
    State-->>API: (DataFrame, meta)
    API-->>Client: 200 {"data":[...],"meta":{...}}
```
