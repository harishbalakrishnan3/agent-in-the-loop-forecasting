# Changepoint Pipeline

The changepoint pipeline is the complete reference implementation for the project. It demonstrates
the full loop: diagnostics, bounded tool choice, backtest gating, hidden-test evaluation, event
streaming, and reporting.

## What it handles

The pipeline stresses Prophet on structural changes that are easy to misread:

- permanent level shifts,
- gradual drift,
- temporary event blocks,
- recurring events,
- sustained anomaly blocks.

## Baselines

Each run compares three methods:

| Method | Description |
| --- | --- |
| Full-history Prophet | Default Prophet fit on the whole history. |
| Naive changepoint workflow | Refit Prophet from detected changepoint windows and keep the validation winner. |
| Agent-in-the-loop | The accepted bounded intervention proposed by the agent. |

## Diagnostics

The report describes toggleable diagnostics such as:

- detected changepoints,
- latest and primary changepoints,
- post-changepoint history length,
- seasonal period,
- per-segment statistics,
- candidate event blocks,
- recurring-event summary,
- local boundary jumps,
- drift intervals,
- transient-event score,
- permanent-shift magnitude.

Diagnostics can be computed but hidden from the agent. This makes ablation studies possible.

## Intervention menu

The decision model chooses exactly one tool from the fixed menu.

| Tool | Repair family |
| --- | --- |
| `recent_window` | Refit from a changepoint onward. |
| `full_history_step_regressor` | Permanent level shift. |
| `full_history_ramp_regressor` | Gradual drift. |
| `full_history_clean_event` | Temporary event or anomaly contamination. |
| `full_history_prophet_tuned_holidays` | Recurring calendar event. |
| `full_history_default` | Always-on fallback. |

## Run it

```bash
uv run python -m ailf.pipelines.changepoint.pipeline --scenario temporary_event_not_regime_change
```

Run artifacts are written under `reports/changepoint/<run_id>/`.

## Current lesson

The pipeline shows that the agent helps most when the baseline workflow cannot express the right
repair family. It does well on reversible event contamination and sustained anomaly blocks because
cleaning is qualitatively different from refitting a changepoint window.

The main failure is level shift disambiguation. The agent described a plausible trend-like pattern
but chose a ramp regressor when the intended repair was a step regressor.
