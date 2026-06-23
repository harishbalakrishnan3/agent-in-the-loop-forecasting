# Roadmap

The next step is not a larger forecaster. The report points toward a better analyst interface around
Prophet.

## Diagnostics

- Stronger abrupt-versus-gradual change diagnostics.
- Better transition-shape summaries.
- Seasonal coverage checks after detected changes.
- More robust event-block and recurrence detection.

## Tools

- Piecewise drift repairs.
- Saturating drift repairs.
- More event-cleaning variants.
- Better separation between recurring events and one-off contamination.

## Agent control

- Prompts that force sharper tool-family comparison.
- A cheap pre-agent decider that skips the loop when default Prophet is already good enough.
- More robust retry behavior when a candidate fails the gate.

## Evaluation

- Larger scenario suite.
- Repeated-run stability checks.
- Real-world benchmark cases.
- Explanation-quality rubric.
- Cost and latency reporting.

## Product surface

- Better Streamlit result inspection.
- Clearer run comparison views.
- Exportable reports for accepted and rejected interventions.
- Hosted demo that does not require local setup.
