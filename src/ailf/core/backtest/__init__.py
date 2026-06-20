"""Backtest guardrail — the intervention gate + split resolver.

CURRENT CONTRACT (this feature): a **single validation-holdout gate** (``gate.py``). A proposed
intervention is accepted only if it strictly beats the naive baseline on the last ``val_rows`` of
training; the agent never sees the score; the hidden test is read only at final evaluation
(constitution Principle IV; see plan Deviation 2). ``split.py`` resolves the train/validation/test
partition (golden default + ratio/absolute override).

NOTE: a full rolling-origin backtest (Principles IV/V default) is a FUTURE extension — it is not
implemented here, to preserve POC parity (SC-001) and because no current pipeline needs it. The
single-holdout choice is documented and justified in writing in the plan.
"""
