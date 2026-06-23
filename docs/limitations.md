# Limitations

The report's result is deliberately mixed. The agent is useful, but not magic.

## The agent can choose the wrong repair family

The level-shift scenario is the clearest failure. The agent selected a ramp regressor because the
late history looked trend-like. The true repair family was a step regressor for permanent level
shifts.

This points to a diagnostic boundary: visual pattern description is not enough when abrupt and
gradual explanations are both plausible.

## Correct repairs are not always worth the cost

The recurring-event scenario is a marginal win. The agent selected the intended holiday/prior
tuning family, but full-history Prophet was already close. A production system should avoid paying
for an agentic loop when a cheap baseline is already good enough.

## The tool menu constrains possible repairs

The gradual-drift scenario improved but was not fully fixed. The agent chose the best available
family, but a single ramp could not express all post-transition structure.

## The current suite is synthetic

Synthetic data is useful because the injected ground truth is known. It is not a substitute for a
larger real-world benchmark. The next evaluation layer should include real production-style series
with careful audit labels.

## GitHub Pages does not host the app

This documentation site is static. The Streamlit UI must run as a Python server locally or on an app
hosting platform.
