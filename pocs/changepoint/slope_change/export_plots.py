"""Export slope-change plots as static PNG images for reference/reports.

Generates one PNG per dataset (S1–S10) showing:
- Raw time series (blue)
- Ground-truth slope-change markers (green dashed)
- (Phase 5) Prophet detected changepoints (red dotted) + forecast-vs-actual (orange)

Requires: kaleido (already in pyproject.toml).
Output directory: pocs/changepoint/slope_change/plots/

Self-contained: imports only plotly and local datasets/prophet_eval modules.

Usage:
    uv run python -m pocs.changepoint.slope_change.export_plots
"""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go

from pocs.changepoint.slope_change.datasets import (
    DATASET_CONFIGS,
    generate_slope_change_series,
)

try:
    from pocs.changepoint.slope_change.prophet_eval import forecast_holdout

    _HAVE_PROPHET = True
except Exception:  # pragma: no cover
    _HAVE_PROPHET = False

OUTPUT_DIR = Path(__file__).parent / "plots"


def build_single_figure(name: str, config: dict) -> go.Figure:
    """Build a standalone figure for one dataset."""
    ts, meta = generate_slope_change_series(**config)
    values = ts.values().flatten()
    dates = ts.time_index
    y_lo, y_hi = float(values.min()), float(values.max())

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dates, y=values, mode="lines", name="Time Series",
            line=dict(color="steelblue", width=1.5),
        )
    )

    for i, cp_idx in enumerate(meta["changepoint_indices"]):
        delta = meta["slope_deltas"][i]
        fig.add_trace(
            go.Scatter(
                x=[dates[cp_idx], dates[cp_idx]],
                y=[y_lo, y_hi],
                mode="lines",
                name=f"Ground Truth (idx={cp_idx}, Δslope={delta:+.2f})",
                line=dict(color="green", width=2, dash="dash"),
            )
        )

    detected_n = 0
    mape_txt = ""
    if _HAVE_PROPHET:
        try:
            overlay = forecast_holdout(ts)
        except Exception:
            overlay = None
        if overlay is not None:
            train_end = overlay["train_end_index"]
            fig.add_trace(
                go.Scatter(
                    x=dates[train_end:], y=overlay["forecast"], mode="lines",
                    name="Prophet forecast (held-out)",
                    line=dict(color="orange", width=2),
                )
            )
            for cp_idx in overlay["detected_changepoint_indices"]:
                d = dates[cp_idx] if cp_idx < len(dates) else dates[-1]
                fig.add_trace(
                    go.Scatter(
                        x=[d, d], y=[y_lo, y_hi], mode="lines",
                        name=f"Prophet CP (idx={cp_idx})",
                        line=dict(color="red", width=1.5, dash="dot"),
                    )
                )
            detected_n = len(overlay["detected_changepoint_indices"])
            mape_txt = f" | held-out MAPE={overlay['mape']:.1f}%"

    n_cp = len(config.get("changepoint_indices", []))
    noise = config.get("noise_std", 0.0)
    fig.update_layout(
        title=(
            f"Slope-Change — {name}<br>"
            f"<sub>Ground-truth slope changes: {n_cp} | Prophet CPs: {detected_n} | "
            f"Noise σ={noise}{mape_txt}</sub>"
        ),
        xaxis_title="Date",
        yaxis_title="Value",
        hovermode="x unified",
        template="plotly_white",
        height=500,
        width=1000,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
    )
    return fig


def export_all():
    """Export all dataset visualizations as PNG files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Exporting plots to: {OUTPUT_DIR.resolve()}")
    for name, config in DATASET_CONFIGS.items():
        fig = build_single_figure(name, config)
        # Convert Timestamps to strings for kaleido serialization.
        for trace in fig.data:
            if trace.x is not None:
                trace.x = [str(x) for x in trace.x]
        png_path = OUTPUT_DIR / f"{name}.png"
        fig.write_image(str(png_path), scale=2)
        print(f"  ✓ {png_path.name}")
    print(f"\nDone! {len(DATASET_CONFIGS)} PNG files saved.")


if __name__ == "__main__":
    export_all()
