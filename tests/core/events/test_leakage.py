"""T009 — strict JSON serializer + leakage helper (Constitution Principle I, test-first).

The serializer MUST raise on non-JSON-native types rather than silently coercing them (the POC's
``default=str`` would hide a boundary leak). ``assert_no_leakage`` guards pre-final event payloads.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ailf.core.events.leakage import LeakageError, assert_no_leakage, to_json


def test_to_json_serializes_plain_data():
    payload = {"a": 1, "b": [1.0, 2.0], "c": {"d": "x"}, "e": True, "f": None}
    text = to_json(payload)
    assert '"a": 1' in text
    assert '"d": "x"' in text


def test_to_json_raises_on_numpy_array():
    with pytest.raises(TypeError):
        to_json({"yhat": np.array([1.0, 2.0, 3.0])})


def test_to_json_raises_on_numpy_int_scalar():
    # np.int64 is NOT a Python int subclass → json must reject it (np.float64 IS a float subclass
    # and serializes natively to valid JSON, so it is intentionally allowed).
    with pytest.raises(TypeError):
        to_json({"v": np.int64(5)})


def test_to_json_raises_on_pandas_timestamp():
    with pytest.raises(TypeError):
        to_json({"ds": pd.Timestamp("2020-01-01")})


def test_to_json_raises_on_arbitrary_handle():
    class Handle:
        pass

    with pytest.raises(TypeError):
        to_json({"model": Handle()})


def test_assert_no_leakage_passes_clean_payload():
    assert_no_leakage({"observations": ["a"], "beat_naive": True})


def test_assert_no_leakage_flags_test_metric_keys():
    with pytest.raises(LeakageError):
        assert_no_leakage({"test_metrics": {"mae": 1.0}})


def test_assert_no_leakage_flags_audit_keys():
    with pytest.raises(LeakageError):
        assert_no_leakage({"true_injected_boundaries": [1, 2]})
