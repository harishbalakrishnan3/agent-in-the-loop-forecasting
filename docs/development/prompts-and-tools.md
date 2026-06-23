# Prompts and Tools

The agent is only as useful as the diagnostic information and tool menu it receives. This project
keeps both surfaces explicit and reviewable.

## Prompt roles

The report describes two prompt/model roles:

| Role | Input | Output |
| --- | --- | --- |
| Visual inspection | Training-only plot. | Structured observations. |
| Decision | Visual observations, numeric diagnostics, tool schemas. | One tool choice, parameters, and rationale. |

Prompts should not expose hidden test data, audit-only boundaries, or expected intervention labels.

## Tool schemas

Tools should be bounded:

- fixed parameter grids,
- explicit preconditions,
- serializable inputs and outputs,
- clear rejection behavior,
- stable names that map to a repair family.

## Rejection is normal

The tool registry should reject out-of-bounds or precondition-violating requests as ordinary control
flow. A rejection should produce a signature the agent can avoid on the next iteration.

## Prompt improvement targets

The report points to prompt and diagnostic improvements in two places:

- distinguish abrupt level shifts from gradual drift,
- compare tool families more sharply before choosing a repair.

Those are better next steps than simply making the forecasting model larger.
