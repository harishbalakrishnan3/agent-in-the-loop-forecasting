"""Strict JSON serialization + leakage guard for the serializable boundary (FR-029, Principle I).

``to_json`` is the single chokepoint for every recorded artifact. Unlike the POC's
``json.dumps(..., default=str)`` (which silently coerces numpy/Timestamp/handles to strings and
hides boundary leaks), this serializer RAISES on any non-JSON-native type, so a leak fails loudly.

``assert_no_leakage`` rejects payloads that carry hidden-test or audit-only fields — used to guard
every pre-final-evaluation event payload (research Decision 16, FR-029).
"""

from __future__ import annotations

import json
from typing import Any

# Keys that must never appear in a pre-final-evaluation event/agent payload.
_FORBIDDEN_KEY_SUBSTRINGS = (
    "test_metric",
    "test_metrics",
    "true_injected_boundaries",
    "expected_intervention_family",
    "audit_only",
)


class LeakageError(RuntimeError):
    """Raised when a payload carries hidden-test target values or audit-only ground truth."""


def _strict(obj: Any) -> Any:
    """``json.dumps`` default hook that REJECTS non-JSON-native types instead of coercing them."""
    raise TypeError(
        f"Non-JSON-serializable value of type {type(obj).__name__!r} crossed the serializable "
        f"boundary: {obj!r}. Convert to a plain JSON type (int/float/str/bool/list/dict/None) "
        f"before serializing — the boundary must be plain data (Principle I), not str-coerced."
    )


def to_json(obj: Any, *, indent: int | None = None, sort_keys: bool = False) -> str:
    """Serialize ``obj`` to JSON, raising ``TypeError`` on any non-JSON-native value.

    ``allow_nan=False`` so NaN/Infinity (not valid JSON) also fail loudly rather than emit
    non-standard tokens.
    """
    return json.dumps(
        obj, default=_strict, indent=indent, sort_keys=sort_keys, allow_nan=False
    )


def assert_no_leakage(payload: Any) -> None:
    """Raise ``LeakageError`` if a (possibly nested) payload carries forbidden keys.

    Applied to every pre-final-evaluation event payload so test targets and audit-only ground
    truth can never reach a UI/event consumer before final evaluation (FR-029).
    """

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).lower()
                if any(sub in lowered for sub in _FORBIDDEN_KEY_SUBSTRINGS):
                    raise LeakageError(
                        f"Payload key {key!r} is forbidden before final evaluation "
                        f"(leakage of hidden-test or audit-only data)."
                    )
                _walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                _walk(item)

    _walk(payload)
