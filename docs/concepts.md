# Concepts

## Analyst-in-the-loop forecasting

Prophet's original workflow is not fully automatic. A human analyst inspects suspicious forecasts,
diagnoses what went wrong, and adjusts the model or data. Examples include changing changepoint
priors, adding holidays, adding regressors, or fitting from a more relevant window.

This project automates that analyst role with a bounded LLM agent.

## Why the agent does not forecast

The agent is not asked to output future values. Direct numerical forecasting with a general-purpose
language model is not the goal. The system keeps forecasting inside deterministic forecasting tools
and uses the LLM for a task closer to analyst reasoning:

1. Read diagnostics.
2. Identify the likely failure mode.
3. Choose one allowed intervention.
4. Explain the choice.
5. Let the backtest gate decide.

## Failure modes

The project focuses on structural deviations that make simple forecasting pipelines fail silently.

| Failure mode | What happens | Example repair family |
| --- | --- | --- |
| Permanent level shift | The baseline changes abruptly and stays changed. | Step regressor. |
| Gradual drift | The series transitions over an interval. | Ramp regressor. |
| Temporary event | A reversible block contaminates the fit window. | Event cleaning. |
| Recurring event | Calendar structure is real but poorly encoded. | Holiday/prior tuning. |
| Sustained anomaly | A broad outlier block bends the trend estimate. | Event cleaning. |

## Bounded interventions

The decision model chooses exactly one intervention from a fixed menu. Parameters are restricted to
small, registry-enforced grids. A bad or out-of-bounds request is rejected as part of normal control
flow instead of crashing the pipeline.

The reference changepoint menu includes:

| Tool | Intended use |
| --- | --- |
| `recent_window` | Refit Prophet from a detected changepoint onward. |
| `full_history_step_regressor` | Encode permanent level shifts while preserving long history. |
| `full_history_ramp_regressor` | Encode gradual drift over a transition interval. |
| `full_history_clean_event` | Clean or downweight temporary event blocks. |
| `full_history_prophet_tuned_holidays` | Encode recurring events and tune Prophet priors. |
| `full_history_default` | Always-on fallback that guarantees a valid forecast. |

## The guardrail

The guardrail is deliberately deterministic. It backtests the proposed intervention on a validation
tail and accepts it only if it strictly beats the naive changepoint-window workflow.

The agent sees only an accept/reject signal. It does not see the validation score, hidden test data,
or audit-only ground truth. Rejected signatures are recorded and excluded on later attempts. The
loop runs for up to five iterations, and hidden test targets are read once after it terminates.

## What success means

The agent succeeds when it chooses a repair family the baseline workflow cannot express. This is why
event and anomaly scenarios show large gains: a fixed changepoint-window workflow treats reversible
contamination as a new regime, while the agent can choose cleaning instead.

The agent fails when its diagnosis maps to the wrong structural family. The level-shift scenario is
the clearest example: a ramp repair was visually plausible, but the correct family was a step
regressor.
