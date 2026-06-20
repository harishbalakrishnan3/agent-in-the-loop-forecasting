"""Export level shift detection plots as static PNG images for reference.

Generates one PNG per dataset (D1–D10) showing:
- Raw time series (blue)
- Ground truth changepoints (green dashed)
- Detected changepoints (red dotted)
- Segment means (colored dashdot)

Requires: kaleido (uv add kaleido)
Output directory: pocs/changepoint/level_shift/plots/

Usage:
    uv run python -m pocs.changepoint.level_shift.export_plots
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import plotly.graph_objects as go

from pocs.changepoint.level_shift.datasets import (
    DATASET_CONFIGS,
    generate_level_shift_series,
)
from pocs.changepoint.level_shift.detector import detect_level_shift

OUTPUT_DIR = Path(__file__).parent / "plots" / "detection"


def _compute_segment_means(
    values, breakpoints: list[int]
) -> list[tuple[int, int, float]]:
    """Compute mean for each segment defined by breakpoints."""
    boundaries = [0] + sorted(breakpoints) + [len(values)]
    segments = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        seg_mean = values[start:end].mean()
        segments.append((start, end, float(seg_mean)))
    return segments


def build_single_figure(name: str, config: dict) -> go.Figure:
    """Build a standalone figure for one dataset."""
    ts, meta = generate_level_shift_series(**config)
    values = ts.values().flatten()
    dates = ts.time_index

    result = detect_level_shift(ts)

    fig = go.Figure()

    # Raw time series
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=values,
            mode="lines",
            name="Time Series",
            line=dict(color="steelblue", width=1.5),
        )
    )

    # Ground truth changepoints
    for i, cp_idx in enumerate(meta["changepoint_indices"]):
        cp_date = dates[cp_idx]
        fig.add_trace(
            go.Scatter(
                x=[cp_date, cp_date],
                y=[values.min() - 5, values.max() + 5],
                mode="lines",
                name=f"Ground Truth (idx={cp_idx}, mag={meta['magnitudes'][i]:+.1f})",
                line=dict(color="green", width=2, dash="dash"),
            )
        )

    # Detected changepoints
    for i, cp_idx in enumerate(result.changepoint_indices):
        cp_date = dates[cp_idx] if cp_idx < len(dates) else dates[-1]
        mag = result.magnitudes[i] if i < len(result.magnitudes) else 0
        fig.add_trace(
            go.Scatter(
                x=[cp_date, cp_date],
                y=[values.min() - 5, values.max() + 5],
                mode="lines",
                name=f"Detected (idx={cp_idx}, mag={mag:+.1f})",
                line=dict(color="red", width=2, dash="dot"),
            )
        )

    # Segment means
    segments = _compute_segment_means(values, result.changepoint_indices)
    colors = [
        "rgba(255,165,0,0.7)",
        "rgba(128,0,128,0.7)",
        "rgba(0,128,128,0.7)",
        "rgba(128,128,0,0.7)",
        "rgba(255,0,128,0.7)",
    ]
    for i, (start, end, seg_mean) in enumerate(segments):
        color = colors[i % len(colors)]
        fig.add_trace(
            go.Scatter(
                x=[dates[start], dates[min(end - 1, len(dates) - 1)]],
                y=[seg_mean, seg_mean],
                mode="lines",
                name=f"Segment mean={seg_mean:.1f}",
                line=dict(color=color, width=2, dash="dashdot"),
            )
        )

    n_cp = len(config.get("changepoint_indices", []))
    noise = config.get("noise_std", 5.0)
    detected = result.n_changepoints

    fig.update_layout(
        title=(
            f"Level Shift Detection — {name}<br>"
            f"<sub>Ground Truth CPs: {n_cp} | Detected: {detected} | "
            f"Noise σ={noise} | Penalty: {result.penalty}</sub>"
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

        # Convert Timestamps to strings for kaleido serialization
        for trace in fig.data:
            if trace.x is not None:
                trace.x = [str(x) for x in trace.x]

        png_path = OUTPUT_DIR / f"{name}.png"
        fig.write_image(str(png_path), scale=2)
        print(f"  ✓ {png_path.name}")

    print(f"\nDone! {len(DATASET_CONFIGS)} PNG files saved.")


if __name__ == "__main__":
    export_all()
