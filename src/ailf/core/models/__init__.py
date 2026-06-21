"""Model access layer.

CURRENT CONTRACT (this feature): ``llm.py`` is the thin LLM provider wrapper (the only module that
talks to the Bedrock SDK) — the visual + decision models the agent uses. It is the FR-001
"model-provider wrapper".

NOTE: a uniform FORECASTING-model interface (Seasonal Naive / Prophet / AutoARIMA / ETS, optional
Chronos / TimesFM, interchangeable) is DEFERRED — not in scope for this promotion (research
Decision 2). Prophet is currently the changepoint pipeline's forecasting mechanism and lives
pipeline-side. Models forecast; the agent never does.
"""
