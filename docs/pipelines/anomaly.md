# Anomaly Pipeline

The anomaly path focuses on reversible contamination: outlier blocks, temporary events, and
sustained anomalies that should not be interpreted as permanent regime changes.

## Current evidence

The report's strongest wins come from event and anomaly cases:

| Scenario | Agent tool | MAE improvement versus naive |
| --- | --- | --- |
| Temporary event | Event cleaning | 85.3% |
| Many temporary events | Event cleaning | 86.9% |
| Sustained anomaly block | Event cleaning | 72.3% |

The common pattern is that the series returns to its baseline after the contaminated region. A
changepoint-window workflow mistakes that block for a persistent change; cleaning preserves the
long history and avoids bending the trend around the contamination.

## Mature anomaly goals

A dedicated anomaly pipeline should eventually provide:

- richer event-block detection,
- recurring versus one-off event separation,
- robust contamination scoring,
- cleaning and downweighting variants,
- tests that separate reversible contamination from permanent shifts.

## Relationship to changepoints

An anomaly is often detected near the same boundary as a changepoint. The agent's value is in
choosing the right interpretation before the gate scores the proposal.
