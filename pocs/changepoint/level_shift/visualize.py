"""Interactive Plotly visualization for level shift datasets and detection results.

Displays all 10 datasets (D1–D10) with:
- Raw time series
- Ground truth changepoint lines (green)
- Detected changepoint lines (red)
- Segment means (horizontal dashed lines)
- Dropdown to switch between datasets

Usage:
    uv run python pocs/changepoint/level_shift/visualize.py
"""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from pocs.changepoint.level_shift.datasets import (
    DATASET_CONFIGS,
    generate_level_shift_series,
)
from pocs.changepoint.level_shift.detector import detect_level_shift


def _compute_segment_means(
    values, breakpoints: list[int]
) -> list[tuple[int, int, float]]:
    """Compute mean for each segment defined by breakpoints.

    Returns list of (start_idx, end_idx, mean_value) tuples.
    """
    boundaries = [0] + sorted(breakpoints) + [len(values)]
    segments = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        seg_mean = values[start:end].mean()
        segments.append((start, end, float(seg_mean)))
    return segments


def build_figure() -> go.Figure:
    """Build the interactive Plotly figure with dropdown for all datasets."""

    fig = go.Figure()

    dataset_names = list(DATASET_CONFIGS.keys())
    all_traces = []  # track which traces belong to which dataset

    for ds_idx, (name, config) in enumerate(DATASET_CONFIGS.items()):
        # Generate dataset
        ts, meta = generate_level_shift_series(**config)
        values = ts.values().flatten()
        dates = ts.time_index

        # Run detection
        result = detect_level_shift(ts)

        # Determine visibility (only first dataset visible initially)
        visible = ds_idx == 0
        traces_for_this_dataset = []

        # --- Trace 1: Raw time series ---
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
        traces_for_this_dataset.append(len(fig.data) - 1)

        # --- Trace 2+: Ground truth changepoints (green vertical lines) ---
        for i, cp_idx in enumerate(meta["changepoint_indices"]):
            cp_date = dates[cp_idx]
            fig.add_trace(
                go.Scatter(
                    x=[cp_date, cp_date],
                    y=[values.min() - 5, values.max() + 5],
                    mode="lines",
                    name=f"Ground Truth (idx={cp_idx}, mag={meta['magnitudes'][i]:+.1f})",
                    line=dict(color="green", width=2, dash="dash"),
                    visible=visible,
                    hovertemplate=f"Ground Truth<br>Index: {cp_idx}<br>Magnitude: {meta['magnitudes'][i]:+.1f}<extra></extra>",
                )
            )
            traces_for_this_dataset.append(len(fig.data) - 1)

        # --- Trace 3+: Detected changepoints (red vertical lines) ---
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
                    visible=visible,
                    hovertemplate=f"Detected<br>Index: {cp_idx}<br>Magnitude: {mag:+.1f}<extra></extra>",
                )
            )
            traces_for_this_dataset.append(len(fig.data) - 1)

        # --- Trace 4+: Segment means (horizontal dashed lines) ---
        segments = _compute_segment_means(values, result.changepoint_indices)
        colors = ["rgba(255,165,0,0.7)", "rgba(128,0,128,0.7)", "rgba(0,128,128,0.7)",
                  "rgba(128,128,0,0.7)", "rgba(255,0,128,0.7)"]
        for i, (start, end, seg_mean) in enumerate(segments):
            color = colors[i % len(colors)]
            fig.add_trace(
                go.Scatter(
                    x=[dates[start], dates[min(end - 1, len(dates) - 1)]],
                    y=[seg_mean, seg_mean],
                    mode="lines",
                    name=f"Segment mean={seg_mean:.1f}",
                    line=dict(color=color, width=2, dash="dashdot"),
                    visible=visible,
                    hovertemplate=f"Segment [{start}:{end}]<br>Mean: {seg_mean:.1f}<extra></extra>",
                )
            )
            traces_for_this_dataset.append(len(fig.data) - 1)

        all_traces.append(traces_for_this_dataset)

    # --- Build dropdown menu ---
    buttons = []
    total_traces = len(fig.data)

    for ds_idx, name in enumerate(dataset_names):
        # Set visibility: only traces for this dataset are visible
        visibility = [False] * total_traces
        for trace_idx in all_traces[ds_idx]:
            visibility[trace_idx] = True

        # Get metadata for subtitle
        config = DATASET_CONFIGS[name]
        n_cp = len(config.get("changepoint_indices", []))
        noise = config.get("noise_std", 5.0)

        buttons.append(
            dict(
                method="update",
                label=name,
                args=[
                    {"visible": visibility},
                    {"title": f"Level Shift Detection — {name}<br>"
                     f"<sub>Changepoints: {n_cp} | Noise σ={noise}</sub>"},
                ],
            )
        )

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
        title=f"Level Shift Detection — {dataset_names[0]}<br>"
              f"<sub>Changepoints: {len(DATASET_CONFIGS[dataset_names[0]].get('changepoint_indices', []))} | "
              f"Noise σ={DATASET_CONFIGS[dataset_names[0]].get('noise_std', 5.0)}</sub>",
        xaxis_title="Date",
        yaxis_title="Value",
        hovermode="x unified",
        template="plotly_white",
        height=600,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.25,
            xanchor="center",
            x=0.5,
        ),
    )

    return fig


def main():
    """Generate and display the interactive visualization."""
    print("Generating datasets and running detection...")
    fig = build_figure()
    print("Opening interactive plot in browser...")
    fig.show()


if __name__ == "__main__":
    main()
