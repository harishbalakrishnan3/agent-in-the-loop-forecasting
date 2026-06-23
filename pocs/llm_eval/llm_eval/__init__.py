"""MVP LLM-eval pipeline for the changepoint agent (POC — gate-exempt per CLAUDE.md).

Forms the eval pipeline end-to-end on the CURRENT agent code over the 6 committed scenarios:
batch-run -> join into Topic-1 golden records -> deterministic code-check evaluators -> a real
score -> push a golden dataset to LangSmith and run an experiment explorable in the UI.

No LLM-as-judge, no failure-mode taxonomy, no prompt-improvement loop (those are later topics).
NO edits to src/ailf — reuses run_scenario(..., credentials=RunCredentials(langsmith_tracing=...)).

See pocs/llm_eval/topic3_mvp_pipeline.md for the design + rationale.
"""

from __future__ import annotations

__all__ = ["scenarios", "golden", "evaluators", "batch", "langsmith_push"]
