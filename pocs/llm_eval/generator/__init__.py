"""Topic-2 dataset generator for the LLM-eval POC (gate-exempt; pocs/llm_eval/).

Generates ~100 lever-tagged time-series cases with tracked ground truth:
  - synthetic-combined (competence / prompt-probe / pipeline-probe levers)
  - unsolvable (tool/capability lever — out-of-vocabulary structure, brute-force-verified)
  - real (objective-only — held-out future actuals are the ground truth)

Every synthetic case is admitted only by verify.py running the REAL detector + gate: its
expected_intervention_family is the family the gate proves WINS (not the injected intent), and
unsolvable cases are proven to have no tool beating naive. See pocs/llm_eval/topic2_dataset_generation.md.
"""
from __future__ import annotations

__all__ = ["base", "verify", "catalog", "export", "real"]
