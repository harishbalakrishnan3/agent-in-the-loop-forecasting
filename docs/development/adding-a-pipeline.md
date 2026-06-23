# Adding a Pipeline

A pipeline plugs one deviation family into the shared core. It should own domain-specific choices
without duplicating common agent, metrics, events, or reporting code.

## Minimum checklist

1. Define the dataset or loader.
2. Define diagnostics.
3. Define the bounded intervention tools.
4. Add versioned prompts.
5. Wire the pipeline into the core runtime.
6. Add deterministic tests.
7. Add at least one scenario with known audit-only ground truth.
8. Document the pipeline page under `docs/pipelines/`.

## Suggested layout

```text
src/ailf/pipelines/<name>/
  __init__.py
  datasets.py
  diagnostics.py
  tools.py
  pipeline.py
  config.yaml
  prompts/
    react_decision_v1.md
```

## Boundaries

Pipeline code should provide:

- diagnostic functions,
- tool implementations,
- scenario data,
- prompt text,
- config defaults.

Pipeline code should not reimplement:

- the graph engine,
- common metrics,
- event sinks,
- generic backtest splitting,
- run artifact writing.

## Evaluation expectation

A new pipeline should include stress cases where:

- the expected repair family is known but hidden from the agent,
- the naive baseline has a plausible failure,
- the hidden test fold is evaluated once,
- the output can be reproduced from a seed and config.
