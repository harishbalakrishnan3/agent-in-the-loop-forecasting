"""T075 — per-stage payload shapes conform to the documented contract (FR-027/SC-010)."""

from __future__ import annotations

from ailf.core.events import payloads as ev


def test_config_resolved_shape():
    p = ev.config_resolved({"seed": 1}, hidden_diagnostics=["d"], removed_tools=["t"], visual_enabled=True)
    assert set(p) == {"effective_config", "hidden_diagnostics", "removed_tools", "visual_analysis_enabled"}


def test_split_built_shape():
    assert set(ev.split_built({"source": "golden"})) == {"provenance"}


def test_changepoint_detection_shape():
    p = ev.changepoint_detection([{"index": 5, "ds": "2020-01-01", "trend_delta": -0.3}])
    assert p["n_detected"] == 1
    assert set(p["detected"][0]) == {"index", "ds", "trend_delta"}


def test_baseline_payloads_carry_only_val_metrics():
    full = ev.baseline_full_history_prophet({"mae": 1.0})
    assert set(full) == {"val_metrics"}
    naive = ev.baseline_naive_workflow(
        {"candidates": [{"label": "x", "val_metrics": {"mae": 1.0}, "extra": {"window_start": 0}}], "selected_window_start": 0}
    )
    assert naive["selected_window_start"] == 0
    assert naive["candidates"][0]["window_start"] == 0


def test_validation_outcome_omits_val_metrics():
    p = ev.validation_outcome({"i": 1, "proposal": {"action_signature": "sig"}, "beat_naive": False,
                               "val_result": {"rejected_reason": "bounds"}})
    assert "val_metrics" not in p  # agent never sees the score (FR-025)
    assert p["beat_naive"] is False
    assert p["rejected_reason"] == "bounds"


def test_decision_iteration_shape():
    p = ev.decision_iteration(
        {"i": 2, "proposal": {"tool": "t", "params": {}, "action_signature": "t|{}", "rationale": "r", "expected_effect": "e"}},
        menu=["t", "fallback"],
    )
    assert p["i"] == 2 and p["proposal"]["tool"] == "t" and p["menu"] == ["t", "fallback"]


def test_final_evaluation_shape_carries_test_metrics():
    p = ev.final_evaluation("accepted_beat_naive", {"tool": "t", "params": {}}, {"agent": {"mae": 1.0}})
    assert set(p) == {"final_case", "chosen", "test_metrics_by_method"}
