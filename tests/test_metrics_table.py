"""Tests for the LaTeX results-table generator (src/ailf/metrics_table.py)."""

from __future__ import annotations

import json

import pytest

from ailf import metrics_table as mt


def _write_run(root, scenario_id, agent_mae, full_mae, naive_mae, tool):
    d = root / f"{scenario_id}-1729"
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps({
        "scenario_id": scenario_id,
        "horizon": 60,
        "methods": {
            "full_history_prophet": {"mae": full_mae, "rmse": full_mae + 1},
            "naive_workflow": {"mae": naive_mae, "rmse": naive_mae + 1},
            "agent": {"mae": agent_mae, "rmse": agent_mae + 1, "tool": tool},
        },
        "winner": min(
            [("agent", agent_mae), ("full_history_prophet", full_mae), ("naive_workflow", naive_mae)],
            key=lambda kv: kv[1],
        )[0],
    }))
    return d


@pytest.fixture
def reports(tmp_path):
    _write_run(tmp_path, "level_shift_loses_seasonality", 7.8, 6.0, 6.0, "full_history_ramp_regressor")
    _write_run(tmp_path, "temporary_event_not_regime_change", 1.5, 10.4, 10.4, "full_history_clean_event")
    return tmp_path


def test_collect_metrics_sorted(reports):
    runs = mt.collect_metrics(reports)
    assert [r["scenario_id"] for r in runs] == sorted(r["scenario_id"] for r in runs)
    assert len(runs) == 2


def test_table_has_booktabs_rules_and_rows(reports):
    tex = mt.build_latex_table(mt.collect_metrics(reports), metric="mae")
    for rule in ("\\toprule", "\\midrule", "\\bottomrule", "\\begin{table}", "\\end{table}"):
        assert rule in tex
    # Friendly scenario labels, not raw ids.
    assert "Level shift" in tex and "Temporary event" in tex


def test_winner_is_bolded(reports):
    tex = mt.build_latex_table(mt.collect_metrics(reports), metric="mae")
    # Agent wins the temporary-event row (1.5) → its value is bold; loses level-shift (7.8) → not.
    assert "\\textbf{1.50}" in tex
    assert "\\textbf{7.80}" not in tex
    assert "\\textbf{6.00}" in tex  # full/naive tie at 6.00; the winner column is bolded


def test_delta_vs_naive_sign(reports):
    tex = mt.build_latex_table(mt.collect_metrics(reports), metric="mae")
    assert "-30.0\\%" in tex   # level shift: (6.0-7.8)/6.0 = -30%
    assert "+85.6\\%" in tex   # temporary event: (10.4-1.5)/10.4 ≈ +85.6%


def test_empty_reports_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        mt.collect_metrics(tmp_path)


def test_rmse_metric_header(reports):
    tex = mt.build_latex_table(mt.collect_metrics(reports), metric="rmse")
    assert "(RMSE)" in tex