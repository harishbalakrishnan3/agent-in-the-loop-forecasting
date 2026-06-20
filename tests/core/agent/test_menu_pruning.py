"""T066 — disabled tool absent from BOTH the advertised menu and the gate allowed-set (FR-014/SC-005)."""

from __future__ import annotations

from ailf.pipelines.changepoint.interventions import (
    FALLBACK_TOOL_NAME,
    STRUCTURAL_TOOL_NAMES,
    register_changepoint_registry,
)


def test_disabled_tool_absent_from_menu_and_allowed_set():
    enabled = set(STRUCTURAL_TOOL_NAMES) - {"full_history_prophet_tuned_holidays"}
    reg = register_changepoint_registry().for_run(enabled)
    menu_names = {m["name"] for m in reg.menu()}
    allowed = reg.allowed_names()
    assert "full_history_prophet_tuned_holidays" not in menu_names  # not advertised
    assert "full_history_prophet_tuned_holidays" not in allowed  # not gate-allowed
    # menu and allowed-set agree (same fact): removed from menu == rejected by gate
    assert menu_names == allowed


def test_all_structural_disabled_leaves_only_fallback():
    reg = register_changepoint_registry().for_run(set())
    assert reg.allowed_names() == {FALLBACK_TOOL_NAME}
    assert {m["name"] for m in reg.menu()} == {FALLBACK_TOOL_NAME}


def test_menu_entries_carry_bounded_schema():
    reg = register_changepoint_registry().for_run(set(STRUCTURAL_TOOL_NAMES))
    tuned = next(m for m in reg.menu() if m["name"] == "full_history_prophet_tuned_holidays")
    cps = next(p for p in tuned["params"] if p["name"] == "changepoint_prior_scale")
    assert cps["allowed"] == [0.01, 0.05, 0.1, 0.5]  # bounds advertised to the agent
