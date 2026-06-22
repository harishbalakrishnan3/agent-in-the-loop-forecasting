"""T014 — verdict derivation (data-model §4, FR-023). Mirrors reporting/artifacts winner logic."""

from __future__ import annotations

from ailf.ui.verdict import derive


def _fe(agent_mae, full_mae, naive_mae):
    return {
        "agent": {"test_metrics": {"mae": agent_mae}, "tool": "recent_window"},
        "full_history_prophet": {"test_metrics": {"mae": full_mae}},
        "naive_workflow": {"test_metrics": {"mae": naive_mae}},
    }


def test_agent_wins_with_positive_margin():
    v = derive(_fe(agent_mae=8.0, full_mae=10.0, naive_mae=10.0))
    assert v.winner == "agent"
    assert v.margin_vs_naive == 2.0
    assert "20.0%" in v.headline  # (10-8)/10 = 20%


def test_naive_wins_when_agent_worse():
    v = derive(_fe(agent_mae=12.0, full_mae=11.0, naive_mae=9.0))
    assert v.winner == "naive_workflow"
    assert v.margin_vs_naive == 9.0 - 12.0  # negative — agent worse than naive
    assert "did not beat" in v.headline.lower()


def test_full_history_wins():
    v = derive(_fe(agent_mae=10.0, full_mae=7.0, naive_mae=9.0))
    assert v.winner == "full_history_prophet"
    assert v.winner_label == "Full-history Prophet"


def test_carries_all_three_maes():
    v = derive(_fe(agent_mae=8.0, full_mae=9.0, naive_mae=10.0))
    assert (v.agent_mae, v.full_history_mae, v.naive_mae) == (8.0, 9.0, 10.0)


def test_tie_break_matches_backend_winner_ordering():
    # On a three-way tie, the backend's write_metrics_json uses
    # min(("full_history_prophet","naive_workflow","agent"), key=mae) → first wins.
    # The UI verdict MUST agree (FR-023), so the winner is full_history_prophet, not agent.
    v = derive(_fe(agent_mae=5.0, full_mae=5.0, naive_mae=5.0))
    assert v.winner == "full_history_prophet"
