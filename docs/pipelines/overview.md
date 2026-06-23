# Pipeline Overview

Pipelines are intentionally thin. Each pipeline plugs domain-specific pieces into the shared core.

| Pipeline | Status | Role |
| --- | --- | --- |
| Changepoint | Complete reference implementation | Agent-driven repair loop with scenarios, diagnostics, tools, UI, and reports. |
| Drift | Dataset and tooling path | Work toward drift-specific diagnostics and repair families. |
| Anomaly | Dataset and tooling path | Work toward anomaly/event contamination handling. |

The changepoint pipeline is the canonical path for understanding the full agent loop today.

## What a pipeline owns

A pipeline owns:

- dataset generation or loading,
- diagnostics,
- intervention tools,
- prompts,
- config defaults,
- pipeline-specific tests,
- run wiring into the shared core.

A pipeline should not duplicate:

- graph engine logic,
- event emission,
- common metrics,
- config resolution,
- report artifact handling,
- generic backtest discipline.

## Expected shape

```text
src/ailf/pipelines/<name>/
  __init__.py
  datasets.py
  diagnostics.py
  tools.py
  pipeline.py
  config.yaml
  prompts/
```

Not every early pipeline has every file yet. The changepoint pipeline shows the intended mature
shape.
