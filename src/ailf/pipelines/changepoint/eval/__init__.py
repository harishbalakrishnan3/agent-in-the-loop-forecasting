"""Changepoint-specific eval (Principle VII: pipelines own their eval).

The domain-agnostic eval machinery lives in ``ailf.core.eval`` (matching, evaluator harness, judge
scaffold, LangSmith infra). THIS package supplies the changepoint specifics: the family taxonomy,
the golden-record schema + builder, the curated 10-case golden set, the family-aware evaluators,
the failure-mode taxonomy, the judge content + versioned prompt, the reimplemented split (breaking
the POC generator dependency), and the run-driver + CLI that pushes the curated set to LangSmith.
"""
from __future__ import annotations
