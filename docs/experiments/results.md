# Results

The report compares hidden-test forecast error across six stress scenarios. Lower is better; bold
marks the best method in each row.

## MAE

| Scenario | Agent | Full-history Prophet | Naive workflow | Agent tool | Agent change versus naive |
| --- | ---: | ---: | ---: | --- | ---: |
| Gradual drift | **4.56** | 7.32 | 7.32 | Ramp regressor | +37.7% |
| Level shift | 7.76 | **5.99** | **5.99** | Ramp regressor | -29.6% |
| Many events | **1.82** | 13.95 | 13.95 | Event cleaning | +86.9% |
| Recurring event | **1.67** | 1.79 | 1.79 | Tuned holidays | +7.0% |
| Sustained anomaly | **1.61** | 6.72 | 5.80 | Event cleaning | +72.3% |
| Temporary event | **1.53** | 10.41 | 10.41 | Event cleaning | +85.3% |

## RMSE

| Scenario | Agent | Full-history Prophet | Naive workflow | Agent tool | Agent change versus naive |
| --- | ---: | ---: | ---: | --- | ---: |
| Gradual drift | **5.83** | 9.39 | 9.39 | Ramp regressor | +38.0% |
| Level shift | 12.75 | **10.23** | **10.23** | Ramp regressor | -24.6% |
| Many events | **2.24** | 14.43 | 14.43 | Event cleaning | +84.4% |
| Recurring event | **2.08** | 2.21 | 2.21 | Tuned holidays | +6.3% |
| Sustained anomaly | **2.00** | 7.17 | 6.35 | Event cleaning | +68.5% |
| Temporary event | **1.96** | 11.84 | 11.84 | Event cleaning | +83.5% |

## Interpretation

### Where the agent earns its keep

The strongest results are event and anomaly cases. The baseline workflow treats event blocks as
regime changes; the agent can choose event cleaning instead. This is a qualitatively different
repair family, not just a better hyperparameter.

### Where the agent is correct but expensive

The recurring-event case is a small win. The agent selected tuned holidays, which is the intended
family, but default Prophet was already close. In production, this kind of case should probably be
filtered out by a cheap pre-agent decider.

### Where the agent fails

The level-shift case is the main miss. The agent chose a ramp because the late history looked like
an increasing trend, but the audit-only truth was a pair of permanent level shifts. This motivates
stronger diagnostics and prompts for distinguishing abrupt level changes from gradual drift.

### Where the current tool menu is too small

The gradual-drift case is a useful win but still not a full repair. The selected ramp helped, but a
single smooth transition cannot express every post-drift possibility. Richer piecewise or
saturating drift tools are natural next additions.
