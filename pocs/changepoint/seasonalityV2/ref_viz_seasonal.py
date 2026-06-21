"""Interactive plotly visualisation for the seasonality amplitude shift POC.

Standalone script — not imported by any test. Run it to visually confirm
that the generated series shows an unambiguous amplitude change at the
injected break (goal 1 of the POC).

Usage
-----
    # Opens interactive figure in the browser (default):
    uv run python pocs/changepoint/seasonalityV2/ref_viz_seasonal.py

    # Save as HTML to reports/ (for headless / remote environments):
    uv run python pocs/changepoint/seasonalityV2/ref_viz_seasonal.py --save

    # Explore a different parameter combination without editing the file:
    uv run python pocs/changepoint/seasonalityV2/ref_viz_seasonal.py \\
        --break-index 120 --magnitude 1.5 --seed 7 --period 30

    # Also show the PELT detection result (requires ruptures):
    uv run python pocs/changepoint/seasonalityV2/ref_viz_seasonal.py --detect
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
import plotly.graph_objects as go

# Same-directory import — works when run directly or via pytest collect
# (no __init__.py in this dir so pytest uses prepend mode, adding the dir to sys.path).
sys.path.insert(0, os.path.dirname(__file__))
from ref_datasets_seasonal import generate_seasonal_shift, generate_control  # noqa: E402


def _build_figure(
    series,
    break_index: int | None,
    period: int,
    detected_breaks: list[int] | None = None,
    title: str | None = None,
) -> go.Figure:
    """Build and return the plotly figure (does not show or save).

    Traces
    ------
    1. Raw series values (thin solid line)
    2. Rolling mean (dashed, window=period)
    3. Rolling std lower band (filled area group)
    4. Rolling std upper band (fills between lower and upper)
    5. Vertical line at injected break_index (red dashed)
    6. Optional vertical lines at PELT-detected breaks (green dashed)
    """
    times = series.time_index
    values = pd.Series(series.values().ravel(), index=times)

    rolling_mean = values.rolling(window=period, center=False).mean()
    rolling_std  = values.rolling(window=period, center=False).std()
    upper = rolling_mean + rolling_std
    lower = rolling_mean - rolling_std

    # Trim NaN leading edge (first `period - 1` points)
    valid = rolling_mean.notna()

    fig = go.Figure()

    # --- Trace 1: raw series ---
    fig.add_trace(go.Scatter(
        x=times,
        y=values,
        mode="lines",
        name="Series",
        line=dict(color="steelblue", width=1),
        opacity=1.0,
    ))

    # --- Trace 3: rolling std lower band (add before upper so fill works) ---
    fig.add_trace(go.Scatter(
        x=times[valid],
        y=lower[valid],
        mode="lines",
        name="Rolling std band",
        line=dict(width=0),
        showlegend=True,
        legendgroup="std_band",
    ))

    # --- Trace 4: rolling std upper band (fills back to lower) ---
    fig.add_trace(go.Scatter(
        x=times[valid],
        y=upper[valid],
        mode="lines",
        name="Rolling ±1 std",
        fill="tonexty",
        fillcolor="rgba(70, 130, 180, 0.15)",
        line=dict(width=0),
        legendgroup="std_band",
    ))

    # --- Trace 2: rolling mean ---
    fig.add_trace(go.Scatter(
        x=times[valid],
        y=rolling_mean[valid],
        mode="lines",
        name=f"Rolling mean (w={period})",
        line=dict(color="darkorange", width=2, dash="dash"),
    ))

    # --- Injected break marker ---
    if break_index is not None:
        break_time = times[break_index]
        fig.add_vline(
            x=break_time.value if hasattr(break_time, "value") else str(break_time),
            line_color="red",
            line_dash="dash",
            line_width=2,
            annotation_text=f"Injected break (idx={break_index})",
            annotation_position="top right",
        )

    # --- PELT-detected break markers ---
    if detected_breaks:
        for det_idx in detected_breaks:
            if 0 <= det_idx < len(times):
                det_time = times[det_idx]
                fig.add_vline(
                    x=det_time.value if hasattr(det_time, "value") else str(det_time),
                    line_color="green",
                    line_dash="dot",
                    line_width=2,
                    annotation_text=f"PELT detected (idx={det_idx})",
                    annotation_position="top left",
                )

    _title = title or (
        f"Seasonality Amplitude Shift — break at index {break_index}"
        if break_index is not None
        else "Control Series (no injected changepoint)"
    )
    fig.update_layout(
        title=_title,
        xaxis_title="Time",
        yaxis_title="Value",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        template="plotly_white",
    )

    return fig


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive visualisation: seasonality amplitude shift POC"
    )
    parser.add_argument("--length",      type=int,   default=365,         help="Series length")
    parser.add_argument("--break-index", type=int,   default=None,        help="Break index (default: length//2)")
    parser.add_argument("--magnitude",   type=float, default=1.0,         help="Amplitude change (1.0 = double)")
    parser.add_argument("--seed",        type=int,   default=42,          help="Random seed")
    parser.add_argument("--period",      type=int,   default=30,          help="Seasonality period")
    parser.add_argument("--amplitude",   type=float, default=5.0,         help="Base seasonal amplitude")
    parser.add_argument("--noise",       type=float, default=0.5,         help="Base noise std")
    parser.add_argument("--save",        action="store_true",              help="Save HTML to reports/ instead of opening browser")
    parser.add_argument("--detect",      action="store_true",              help="Overlay PELT detection result (requires ruptures)")
    parser.add_argument("--pen",         type=float, default=3.0,         help="PELT penalty (used with --detect)")
    parser.add_argument("--control",     action="store_true",              help="Show the control (no-change) series instead")
    args = parser.parse_args()

    if args.control:
        series = generate_control(
            length=args.length,
            seasonality_period=args.period,
            seasonality_amplitude=args.amplitude,
            base_noise=args.noise,
            seed=args.seed,
        )
        break_index = None
        title = "Control Series (no injected changepoint)"
    else:
        series, break_index = generate_seasonal_shift(
            length=args.length,
            break_index=args.break_index,
            magnitude=args.magnitude,
            seasonality_period=args.period,
            seasonality_amplitude=args.amplitude,
            base_noise=args.noise,
            seed=args.seed,
        )
        title = None  # auto-generated from break_index

    detected_breaks = None
    if args.detect:
        try:
            from ref_tools_seasonal import detect_seasonality_change
            detected_breaks = detect_seasonality_change(series, pen=args.pen, min_size=args.period)
            print(f"PELT detected breaks (pen={args.pen}): {detected_breaks}")
            if break_index is not None:
                for d in detected_breaks:
                    offset = d - break_index
                    print(f"  offset from true break: {offset:+d} (tolerance ±{args.period})")
        except ImportError as e:
            print(f"Warning: {e} — skipping detection overlay.")

    fig = _build_figure(series, break_index, args.period, detected_breaks, title)

    if args.save:
        out_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "reports"
        )
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "poc_seasonality_shift.html")
        fig.write_html(out_path)
        print(f"Saved: {out_path}")
    else:
        fig.show()


if __name__ == "__main__":
    main()
