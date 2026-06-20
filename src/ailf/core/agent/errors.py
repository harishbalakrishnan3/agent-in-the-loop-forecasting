"""Core agent exceptions (data-model.md → Exceptions).

Kept in one import-light module (no langgraph/langchain) so every layer can raise/catch them
without pulling heavy deps. ``ConfigError``/``SplitError`` live with their owning modules
(``core.config.resolve`` / ``core.backtest.split``); the agent-loop-facing ones live here.
"""

from __future__ import annotations


class ToolBoundsError(ValueError):
    """A proposed tool param is out of bounds, or the tool is unknown/disabled for the run.

    This is a NORMAL in-loop rejection (append the action signature, re-prompt) — NOT a stage
    failure, so it never emits a terminal error event (FR-023, FR-032).
    """


class StageError(RuntimeError):
    """A genuine stage failure (e.g. the visual-first ordering invariant violated when visual is
    enabled, or a tool invocation crash). Emits a terminal error event and fails the run fast
    (FR-032). Distinct from normal in-loop control flow.
    """
