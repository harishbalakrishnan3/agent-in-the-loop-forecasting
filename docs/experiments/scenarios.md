# Scenario Suite

Each scenario is synthetic and seeded. Ground-truth boundaries and expected fixes are audit-only.

## Summary

| Scenario | Dataset pattern | Expected repair | Agent outcome |
| --- | --- | --- | --- |
| `level_shift_loses_seasonality` | Two permanent level shifts with short post-change seasonal history. | Step regressor. | Lost; chose ramp. |
| `gradual_drift_loses_seasonality` | Long gradual transition with short post-drift seasonal history. | Ramp regressor. | Won, but not fully fixed. |
| `temporary_event_not_regime_change` | Several reversible event blocks. | Event cleaning. | Strong win. |
| `many_temporary_events_long_history` | Six irregular event blocks over longer history. | Event cleaning. | Strongest win. |
| `prophet_prior_tuning_recurring_event` | Recurring event plus trend kinks. | Tuned holidays and priors. | Correct but marginal. |
| `sustained_anomaly_block` | 26-day elevated anomaly block in the fit window. | Event cleaning. | Strong win. |

## Level shift

The correct family is a step regressor: preserve full seasonal history and encode permanent level
changes. The agent instead chose a ramp. Its reasoning was understandable because the late segment
looked trend-like, but the hidden test favored the baseline.

## Gradual drift

The correct family is a ramp regressor. The agent chose it and improved the forecast, but remaining
error showed a limitation of the current tool menu. A single bounded ramp cannot represent all
uncertainty about post-transition seasonal shape and late turning points.

## Temporary event

The correct family is event cleaning. The abnormal blocks are reversible contamination, not a new
regime. The agent chose cleaning and substantially reduced hidden-test MAE.

## Many temporary events

This longer series contains repeated non-calendar events. A changepoint-window workflow is fragile
because it can extrapolate event blocks as persistent change. The agent again chose cleaning and
produced the largest gain.

## Recurring event

The recurring event is real structure, not an outlier. The correct family is tuned holidays and
Prophet priors. The agent chose the right family, but default Prophet was already close, so the gain
was small.

## Sustained anomaly block

The broad anomaly block can distort Prophet's trend estimate. Event cleaning preserves the baseline
and gives the agent a substantial hidden-test gain.
