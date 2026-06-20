"""Interactive Plotly visualization for slope-change datasets.

Displays all 10 datasets (S1–S10) with:
- Raw time series
- Ground-truth slope-change markers (green dashed vertical lines)
- (Phase 5) Prophet's detected changepoints (red dotted) and the
  forecast-vs-actual overlay over the held-out horizon
- Dropdown to switch between datasets

Self-contained: imports only plotly and the local datasets/prophet_eval modules.

Usage:
    uv run python -m pocs.changepoint.slope_change.visualize
"""

from __future__ import annotations

import plotly.graph_objects as go

from pocs.changepoint.slope_change.datasets import (
    DATASET_CONFIGS,
    generate_slope_change_series,
)

# Prophet evaluation is optional at viz time; if it imports/fits cleanly we
# overlay detected changepoints + forecast (Phase 5). Datasets + ground truth
# always render.
try:
    from pocs.changepoint.slope_change.prophet_eval import (
        TRAIN_FRACTION,
        forecast_holdout,
    )

    _HAVE_PROPHET = True
except Exception:  # pragma: no cover - viz still works without Prophet
    _HAVE_PROPHET = False


def _add_dataset_traces(fig: go.Figure, name: str, config: dict, visible: bool) -> list[int]:
    """Add all traces for one dataset; return the indices of those traces."""
    ts, meta = generate_slope_change_series(**config)
    values = ts.values().flatten()
    dates = ts.time_index
    trace_ids: list[int] = []

    # --- Raw series ---
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=values,
            mode="lines",
            name="Time Series",
            line=dict(color="steelblue", width=1),
            visible=visible,
            hovertemplate="Date: %{x}<br>Value: %{y:.1f}<extra></extra>",
        )
    )
    trace_ids.append(len(fig.data) - 1)

    # --- Ground-truth slope-change markers ---
    y_lo, y_hi = float(values.min()), float(values.max())
    for i, cp_idx in enumerate(meta["changepoint_indices"]):
        cp_date = dates[cp_idx]
        delta = meta["slope_deltas"][i]
        fig.add_trace(
            go.Scatter(
                x=[cp_date, cp_date],
                y=[y_lo, y_hi],
                mode="lines",
                name=f"Ground Truth (idx={cp_idx}, Δslope={delta:+.2f})",
                line=dict(color="green", width=2, dash="dash"),
                visible=visible,
                hovertemplate=(
                    f"Ground Truth slope change<br>Index: {cp_idx}"
                    f"<br>Δslope: {delta:+.3f}<extra></extra>"
                ),
            )
        )
        trace_ids.append(len(fig.data) - 1)

    # --- Prophet overlay (Phase 5): detected CPs + forecast-vs-actual ---
    if _HAVE_PROPHET:
        try:
            overlay = forecast_holdout(ts)
        except Exception:
            overlay = None
        if overlay is not None:
            train_end = overlay["train_end_index"]
            fc_dates = dates[train_end:]
            # Forecast line over the held-out horizon.
            fig.add_trace(
                go.Scatter(
                    x=fc_dates,
                    y=overlay["forecast"],
                    mode="lines",
                    name="Prophet forecast (held-out)",
                    line=dict(color="orange", width=2),
                    visible=visible,
                    hovertemplate="Forecast: %{y:.1f}<extra></extra>",
                )
            )
            trace_ids.append(len(fig.data) - 1)
            # Detected changepoints.
            for cp_idx in overlay["detected_changepoint_indices"]:
                cp_date = dates[cp_idx] if cp_idx < len(dates) else dates[-1]
                fig.add_trace(
                    go.Scatter(
                        x=[cp_date, cp_date],
                        y=[y_lo, y_hi],
                        mode="lines",
                        name=f"Prophet CP (idx={cp_idx})",
                        line=dict(color="red", width=1.5, dash="dot"),
                        visible=visible,
                        hovertemplate=f"Prophet changepoint<br>Index: {cp_idx}<extra></extra>",
                    )
                )
                trace_ids.append(len(fig.data) - 1)

    return trace_ids


def build_figure() -> go.Figure:
    """Build the interactive Plotly figure with a dropdown over all datasets."""
    fig = go.Figure()
    dataset_names = list(DATASET_CONFIGS.keys())
    all_traces: list[list[int]] = []

    for ds_idx, (name, config) in enumerate(DATASET_CONFIGS.items()):
        visible = ds_idx == 0
        all_traces.append(_add_dataset_traces(fig, name, config, visible))

    # --- Dropdown menu ---
    total = len(fig.data)
    buttons = []
    for ds_idx, name in enumerate(dataset_names):
        vis = [False] * total
        for t in all_traces[ds_idx]:
            vis[t] = True
        config = DATASET_CONFIGS[name]
        n_cp = len(config.get("changepoint_indices", []))
        noise = config.get("noise_std", 0.0)
        buttons.append(
            dict(
                method="update",
                label=name,
                args=[
                    {"visible": vis},
                    {
                        "title": f"Slope-Change — {name}<br>"
                        f"<sub>Slope changes: {n_cp} | Noise σ={noise}</sub>"
                    },
                ],
            )
        )

    first = dataset_names[0]
    first_cfg = DATASET_CONFIGS[first]
    fig.update_layout(
        updatemenus=[
            dict(
                active=0,
                buttons=buttons,
                direction="down",
                showactive=True,
                x=0.0,
                xanchor="left",
                y=1.15,
                yanchor="top",
            )
        ],
        title=f"Slope-Change — {first}<br>"
        f"<sub>Slope changes: {len(first_cfg.get('changepoint_indices', []))} | "
        f"Noise σ={first_cfg.get('noise_std', 0.0)}</sub>",
        xaxis_title="Date",
        yaxis_title="Value",
        hovermode="x unified",
        template="plotly_white",
        height=600,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
    )
    return fig


def main():
    """Generate datasets and display the interactive visualization."""
    print("Generating datasets" + (" + Prophet overlays" if _HAVE_PROPHET else "") + "...")
    fig = build_figure()
    print("Opening interactive plot in browser...")
    fig.show()


if __name__ == "__main__":
    main()
