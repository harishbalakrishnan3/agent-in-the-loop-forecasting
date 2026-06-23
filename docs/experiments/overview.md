# Experiments Overview

The evaluation is deliberately controlled. Every dataset is synthetic, seeded, and generated with
audit-only ground truth. The agent never sees the injected boundaries or expected intervention
families.

## Methods compared

| Method | Description |
| --- | --- |
| Full-history Prophet | Default Prophet fit on the entire history. |
| Naive changepoint workflow | Refit Prophet from detected changepoint windows and select by validation error. |
| Agent-in-the-loop | The bounded intervention proposed by the agent and accepted by the backtest gate. |

## Metrics

The reported tables focus on hidden-test MAE and RMSE. Runs also record WAPE and sMAPE.

Lower is better for all reported metrics.

## High-level result

The agent wins five of six scenarios by MAE. The wins are not uniform:

- large gains on reversible event and anomaly contamination,
- useful but incomplete improvement on gradual drift,
- marginal gain on recurring events,
- one clear loss on permanent level shift.

This is the central conclusion: the agent helps when it selects a repair family unavailable to the
baseline workflow. It is not automatically better just because an LLM is in the loop.
