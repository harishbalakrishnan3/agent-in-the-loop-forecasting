# Evaluation Protocol

The evaluation is designed to test the agent without letting it overfit to validation scores,
hidden-test targets, or audit-only metadata.

## Data visibility

The agent can see only:

- training data,
- diagnostics derived from training data,
- optional visual observations from a training-only plot,
- tool schemas,
- prior rejected proposal signatures,
- accept/reject feedback.

The agent cannot see:

- validation metric values,
- hidden-test targets,
- injected boundaries,
- expected intervention families.

## Split discipline

The reported runs reserve:

- final 120 rows for hidden testing,
- preceding 120 rows for validation,
- earlier rows for training.

The final test fold is evaluated once after the loop terminates.

## Acceptance rule

The proposed intervention must strictly beat the naive changepoint-window workflow on the
validation tail. Otherwise, the proposal signature is recorded, the candidate is rejected, and the
agent is re-prompted until the five-iteration cap is reached.

## Scoring

The final comparison includes:

1. full-history Prophet,
2. naive changepoint workflow,
3. accepted agent intervention.

The verdict is the lowest hidden-test MAE. RMSE, WAPE, and sMAPE are also recorded for audit.

## Tool-family evaluation

In addition to numeric forecast error, the experiment checks whether the accepted tool family
matches the audit-only expected intervention. In the report suite, the agent selects the expected
family in five of six scenarios. The miss is the level-shift case.
