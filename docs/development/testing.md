# Testing

The test strategy separates deterministic correctness from agent-quality evaluation.

## Deterministic tests

Run the full suite:

```bash
uv run pytest
```

Important areas:

| Area | What to test |
| --- | --- |
| Metrics | MAE, RMSE, WAPE, sMAPE, and edge cases. |
| Backtest | Split boundaries and hidden-test discipline. |
| Events | Payload shape and leakage prevention. |
| Config | Provider detection, schema validation, resolved config. |
| Pipelines | Dataset generation, tool behavior, diagnostic contracts. |
| UI | Chart frames, verdict rendering, config builder behavior. |

## Agent-quality tests

Agent behavior is evaluated with scenario suites and golden expectations. These tests should check:

- accepted tool family,
- hidden-test forecast error,
- guardrail behavior,
- explanation quality,
- robustness across repeated runs.

Live LLM-backed evaluations should remain opt-in unless credentials and cost controls are explicit.

## Leakage tests

The agent must not see:

- hidden test targets,
- audit-only metadata,
- expected repair families,
- numeric validation scores.

Tests around event payloads, prompt inputs, and run artifacts should guard that boundary.
