"""Interactive Plotly visualisations for changepoint scenarios.

Complements ``viz.py`` (matplotlib, headless) with browser-renderable charts.
All functions return ``go.Figure`` — call ``.show()`` or ``.write_html(path)``
on the result.

Usage
-----
    from ailf.pipelines.changepoint.viz_interactive import (
        plot_scenario_overview,
        plot_forecast_comparison,
    )

    # Quick dataset overview with changepoints marked
    fig = plot_scenario_overview("trend_reversal_old_history_poisons_forecast")
    fig.show()

    # After running the pipeline, compare all forecasts
    import json
    from pathlib import Path
    run_dir = Path("reports/changepoint/trend_reversal_old_history_poisons_forecast-1729")
    fig = plot_forecast_comparison(run_dir)
    fig.show()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "plotly is required for interactive visualisation. "
        "Install it with: pip install plotly"
    ) from exc

# ---------------------------------------------------------------------------
# Colour palette (consistent across plots)
# ---------------------------------------------------------------------------
_COLOURS = {
    "train":        "#1f77b4",   # blue
    "test":         "#2ca02c",   # green
    "cp":           "#d62728",   # red — true/detected changepoints
    "origin":       "#7f7f7f",   # grey — forecast origin
    "naive":        "#ff7f0e",   # orange
    "agent":        "#9467bd",   # purple
    "full_history": "#17becf",   # cyan
    "phase_bg":     "rgba(255, 165, 0, 0.08)",
}

_DATA_DIR = Path(__file__).resolve().parent / "data"
_CSV_DIR  = _DATA_DIR / "csv"
_META     = _DATA_DIR / "scenario_metadata.json"


def _load_meta(scenario_id: str) -> dict[str, Any]:
    meta = json.loads(_META.read_text())
    for s in meta["scenarios"]:
        if s["scenario_id"] == scenario_id:
            return s
    raise ValueError(f"Unknown scenario_id: {scenario_id!r}")


def _load_csv(scenario_id: str) -> pd.DataFrame:
    meta = _load_meta(scenario_id)
    path = _CSV_DIR / Path(meta["csv_path"]).name
    return pd.read_csv(path, parse_dates=["ds"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plot_scenario_overview(
    scenario_id: str,
    *,
    show_phases: bool = True,
    title: str | None = None,
) -> "go.Figure":
    """Interactive overview of a single scenario's raw series.

    Marks:
    - Train / test regions (colour-coded background)
    - Forecast origin (vertical dashed line)
    - True injected changepoint boundaries (audit_only — for exploration only)
    - Split boundaries (val start, test start)

    Parameters
    ----------
    scenario_id : str
        Must match a key in ``scenario_metadata.json``.
    show_phases : bool
        If True, shade the phase regions between true changepoint boundaries.
    title : str | None
        Override the chart title (default: scenario title from metadata).
    """
    meta = _load_meta(scenario_id)
    df   = _load_csv(scenario_id)

    train_end   = int(meta["train_end"])
    val_h       = int(meta["validation_horizon"])
    test_h      = int(meta["test_horizon"])
    fit_end     = train_end - val_h          # val starts here
    test_start  = train_end                  # test starts here
    test_end    = train_end + test_h

    true_cps    = meta.get("audit_only", {}).get("true_injected_boundaries", [])
    seasonal_p  = int(meta.get("seasonal_period", 7))

    fig = go.Figure()

    # ---- background shading for train / val / test ----
    ds = df["ds"]
    regions = [
        ("Train",      ds.iloc[0],          ds.iloc[fit_end - 1],    "rgba(31,119,180,0.05)"),
        ("Validation", ds.iloc[fit_end],     ds.iloc[train_end - 1],  "rgba(255,165,0,0.10)"),
        ("Test",       ds.iloc[test_start],  ds.iloc[test_end - 1],   "rgba(44,160,44,0.10)"),
    ]
    for label, x0, x1, colour in regions:
        fig.add_vrect(x0=x0, x1=x1, fillcolor=colour, line_width=0,
                      annotation_text=label, annotation_position="top left",
                      annotation=dict(font_size=11, font_color="grey"))

    # ---- phase shading between true CPs (audit_only) ----
    if show_phases and true_cps:
        boundaries = [0, *true_cps, len(df) - 1]
        phase_colours = [
            "rgba(31,119,180,0.06)",
            "rgba(214,39,40,0.06)",
            "rgba(148,103,189,0.06)",
        ]
        for i in range(len(boundaries) - 1):
            x0 = ds.iloc[boundaries[i]]
            x1 = ds.iloc[min(boundaries[i + 1], len(df) - 1)]
            fig.add_vrect(x0=x0, x1=x1,
                          fillcolor=phase_colours[i % len(phase_colours)],
                          line_width=0)

    # ---- raw series ----
    fig.add_trace(go.Scatter(
        x=ds.iloc[:test_end],
        y=df["y"].iloc[:test_end],
        mode="lines",
        name="Series",
        line=dict(color=_COLOURS["train"], width=1.2),
    ))

    # ---- true changepoint markers ----
    for idx in true_cps:
        fig.add_vline(
            x=ds.iloc[idx],
            line_dash="dash",
            line_color=_COLOURS["cp"],
            line_width=1.5,
            annotation_text=f"True CP (row {idx})",
            annotation_position="top right",
            annotation=dict(font_size=10, font_color=_COLOURS["cp"]),
        )

    # ---- forecast origin ----
    fig.add_vline(
        x=ds.iloc[train_end - 1],
        line_dash="dot",
        line_color=_COLOURS["origin"],
        line_width=2,
        annotation_text="Forecast origin",
        annotation_position="top left",
        annotation=dict(font_size=10, font_color=_COLOURS["origin"]),
    )

    fig.update_layout(
        title=title or meta.get("title", scenario_id),
        xaxis_title="Date",
        yaxis_title="y",
        template="plotly_white",
        height=480,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        annotations=[dict(
            text=(
                f"seasonal_period={seasonal_p} | "
                f"train={fit_end} | val={val_h} | test={test_h} | "
                f"true CPs={true_cps}"
            ),
            xref="paper", yref="paper", x=0, y=-0.12,
            showarrow=False, font=dict(size=10, color="grey"),
        )],
    )
    return fig


def plot_forecast_comparison(
    run_dir: str | Path,
    *,
    title: str | None = None,
) -> "go.Figure":
    """Compare naive vs agent vs full-history forecasts from a completed pipeline run.

    Reads ``metrics.json``, ``forecast_naive.csv``, ``forecast_agent.csv``,
    ``forecast_full_history.csv``, and the scenario CSV from ``effective_config.json``.

    Parameters
    ----------
    run_dir : str | Path
        Path to a run directory (e.g. ``reports/changepoint/<run_id>``).
    title : str | None
        Override the chart title.
    """
    run_dir = Path(run_dir)

    # Load metrics
    metrics = json.loads((run_dir / "metrics.json").read_text())
    scenario_id = metrics["scenario_id"]
    methods     = metrics["methods"]

    # Load scenario data
    meta = _load_meta(scenario_id)
    df   = _load_csv(scenario_id)
    ds   = df["ds"]

    train_end  = int(meta["train_end"])
    val_h      = int(meta["validation_horizon"])
    test_h     = int(meta["test_horizon"])
    fit_end    = train_end - val_h
    test_start = train_end
    test_end   = train_end + test_h

    # Load forecasts (pipeline writes these as columns in reports)
    def _load_fc(name: str) -> pd.DataFrame | None:
        p = run_dir / f"forecast_{name}.csv"
        return pd.read_csv(p, parse_dates=["ds"]) if p.exists() else None

    fc_full  = _load_fc("full_history")
    fc_naive = _load_fc("naive")
    fc_agent = _load_fc("agent")

    fig = go.Figure()

    # Background shading
    fig.add_vrect(x0=ds.iloc[fit_end], x1=ds.iloc[train_end - 1],
                  fillcolor="rgba(255,165,0,0.08)", line_width=0,
                  annotation_text="Val", annotation_position="top left",
                  annotation=dict(font_size=10, font_color="grey"))
    fig.add_vrect(x0=ds.iloc[test_start], x1=ds.iloc[test_end - 1],
                  fillcolor="rgba(44,160,44,0.08)", line_width=0,
                  annotation_text="Test", annotation_position="top left",
                  annotation=dict(font_size=10, font_color="grey"))

    # History (last 520 rows of train for readability)
    history_start = max(0, train_end - 520)
    fig.add_trace(go.Scatter(
        x=ds.iloc[history_start:train_end],
        y=df["y"].iloc[history_start:train_end],
        mode="lines", name="Train history",
        line=dict(color="#aec7e8", width=1.0),
    ))

    # Actuals (test)
    fig.add_trace(go.Scatter(
        x=ds.iloc[test_start:test_end],
        y=df["y"].iloc[test_start:test_end],
        mode="lines", name="Test actuals",
        line=dict(color="black", width=2.0),
    ))

    # Forecasts
    if fc_full is not None:
        mae_fh = methods.get("full_history_prophet", {}).get("mae", float("nan"))
        fig.add_trace(go.Scatter(
            x=fc_full["ds"], y=fc_full["yhat"],
            mode="lines", name=f"Full history Prophet (MAE={mae_fh:.2f})",
            line=dict(color=_COLOURS["full_history"], width=1.6, dash="dash"),
        ))

    if fc_naive is not None:
        mae_nw = methods.get("naive_workflow", {}).get("mae", float("nan"))
        sel    = methods.get("naive_workflow", {}).get("selected_window", "")
        fig.add_trace(go.Scatter(
            x=fc_naive["ds"], y=fc_naive["yhat"],
            mode="lines", name=f"Naive workflow (MAE={mae_nw:.2f}, {sel})",
            line=dict(color=_COLOURS["naive"], width=1.6),
        ))

    if fc_agent is not None:
        mae_ag = methods.get("agent", {}).get("mae", float("nan"))
        tool   = methods.get("agent", {}).get("tool", "agent")
        fig.add_trace(go.Scatter(
            x=fc_agent["ds"], y=fc_agent["yhat"],
            mode="lines", name=f"Agent: {tool} (MAE={mae_ag:.2f})",
            line=dict(color=_COLOURS["agent"], width=2.0),
        ))

    # Forecast origin
    fig.add_vline(
        x=ds.iloc[train_end - 1],
        line_dash="dot", line_color=_COLOURS["origin"], line_width=1.5,
    )

    winner = metrics.get("winner", "?")
    fig.update_layout(
        title=title or f"{scenario_id} — winner: {winner}",
        xaxis_title="Date",
        yaxis_title="y",
        template="plotly_white",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def plot_all_scenarios_summary() -> "go.Figure":
    """Bar chart comparing MAE across all scenarios and methods (requires completed runs).

    Looks for the most recent run directory for each scenario under
    ``reports/changepoint/``.
    """
    reports_root = Path("reports/changepoint")
    meta_list    = json.loads(_META.read_text())["scenarios"]

    rows = []
    for meta in meta_list:
        sid = meta["scenario_id"]
        run_dirs = sorted(reports_root.glob(f"{sid}-*"), reverse=True)
        if not run_dirs:
            continue
        metrics_path = run_dirs[0] / "metrics.json"
        if not metrics_path.exists():
            continue
        m = json.loads(metrics_path.read_text())
        for method, vals in m.get("methods", {}).items():
            rows.append({
                "scenario": sid.replace("_", " ")[:40],
                "method": method,
                "mae": vals.get("mae", float("nan")),
                "winner": m.get("winner") == method.replace("_workflow", "").replace("full_history_", ""),
            })

    if not rows:
        raise RuntimeError("No completed runs found under reports/changepoint/")

    df = pd.DataFrame(rows)
    scenarios = df["scenario"].unique().tolist()

    method_colours = {
        "full_history_prophet": _COLOURS["full_history"],
        "naive_workflow":       _COLOURS["naive"],
        "agent":                _COLOURS["agent"],
    }

    fig = go.Figure()
    for method, colour in method_colours.items():
        sub = df[df["method"] == method]
        fig.add_trace(go.Bar(
            name=method.replace("_", " "),
            x=sub["scenario"],
            y=sub["mae"],
            marker_color=colour,
        ))

    fig.update_layout(
        barmode="group",
        title="Test MAE by scenario and method",
        xaxis_title="Scenario",
        yaxis_title="MAE",
        template="plotly_white",
        height=480,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis=dict(tickangle=-25),
    )
    return fig
