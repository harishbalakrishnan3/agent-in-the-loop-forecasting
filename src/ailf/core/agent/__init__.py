"""The bounded LLM analyst agent.

ReAct loop, tool registry, base Tool interface, and the thin provider wrapper (the only
place that talks to the LLM SDK). The agent reads diagnostics, calls tools, and proposes
interventions from a fixed bounded menu — it never forecasts and never silently mutates
the pipeline.
"""
