"""Streamlined agent UI — the single presentation-facing front-end (feature 006).

A thin client over the changepoint agent pipeline: it builds a config override from the
control-pane selections, runs the pipeline on a background worker thread, streams the typed
event stream live over an in-memory queue, and renders a final verdict + interactive graph.

Pure, importable helpers (config_builder, event_view, verdict, chart, models, run_controller)
hold all non-trivial logic so they are unit-testable without launching Streamlit; ``app`` is the
thin Streamlit shell. The UI is a front-end consumer, NOT a pipeline (Constitution Principle I).
"""
