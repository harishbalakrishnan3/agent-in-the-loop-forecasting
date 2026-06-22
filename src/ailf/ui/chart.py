"""Build the final interactive comparison graph (data-model §3, FR-024/025/026).

PURE module (returns a Plotly figure; does not call Streamlit). Consumes the run's
``forecast_comparison.csv`` frame (columns: ds, y_actual, region, yhat_full_history, yhat_naive,
yhat_agent), the detected-changepoints list, and the train/val boundaries, and produces:
  - a normalized frame whose ``region`` is one of train/val/test,
  - region boundary timestamps for shading,
  - a default view window (recent training context + the full forecast region),
  - the figure: 3 forecast traces + actuals, region shading, changepoint vlines, zoom/pan/hover, legend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

_DEFAULT_CONTEXT_POINTS = 520  # trailing training context shown before the forecast region

_TRACE_STYLE = {
    # name -> (column, dash, color)
    "Actuals": ("y_actual", "solid", "#2ca02c"),
    "Agent": ("yhat_agent", "dot", "#b57bee"),
    "Full-history Prophet": ("yhat_full_history", "dash", "#1a3a5c"),
    "Naive": ("yhat_naive", "dash", "#e05c00"),
}
_REGION_FILL = {
    "train": "rgba(120,120,120,0.06)",
    "val": "rgba(70,130,180,0.12)",
    "test": "rgba(44,160,44,0.10)",
}


@dataclass
class ChartData:
    frame: pd.DataFrame  # region normalized to train/val/test
    changepoints: list[dict[str, Any]]
    region_bounds: dict[str, Any]  # {val_start_ds, test_start_ds}
    view_window: tuple[Any, Any]  # (start_ds, end_ds)


def build_frame(
    csv_df: pd.DataFrame,
    *,
    changepoints: list[dict[str, Any]] | None = None,
    fit_end_ds: Any | None = None,
    train_end_ds: Any | None = None,
    context_points: int = _DEFAULT_CONTEXT_POINTS,
) -> ChartData:
    """Normalize regions to train/val/test, locate boundaries, set the view window, attach markers.

    Accepts a frame whose ``region`` is either {train, val, test} (already relabeled by the
    pipeline) or the legacy {train, forecast}. In the legacy case, ``forecast`` becomes ``test`` and,
    if ``fit_end_ds`` is given, training rows at/after ``fit_end_ds`` become ``val``.
    """
    frame = csv_df.copy()
    frame["ds"] = pd.to_datetime(frame["ds"])

    region = frame["region"].astype(str).copy()
    # Legacy "forecast" → "test".
    region = region.replace({"forecast": "test"})
    # Split the training region into train/val using the fit boundary, if provided and not already split.
    if fit_end_ds is not None and "val" not in set(region):
        fit_ds = pd.Timestamp(fit_end_ds)
        is_train = region == "train"
        region = region.where(~(is_train & (frame["ds"] >= fit_ds)), "val")
    frame["region"] = region

    # Boundaries for shading: first ds of the val and test regions.
    def _first_ds(reg: str) -> Any | None:
        sub = frame.loc[frame["region"] == reg, "ds"]
        return sub.iloc[0] if len(sub) else None

    val_start = _first_ds("val")
    test_start = _first_ds("test")
    if train_end_ds is not None and test_start is None:
        test_start = pd.Timestamp(train_end_ds)

    # View window: recent training context (context_points before the forecast region) → last ds.
    forecast_mask = frame["region"].isin(["test"]) | (
        (frame["region"] == "val") if val_start is not None else False
    )
    if forecast_mask.any():
        first_forecast_idx = frame.index[forecast_mask][0]
        start_idx = max(0, frame.index.get_loc(first_forecast_idx) - context_points)
        view_start = frame["ds"].iloc[start_idx]
    else:
        view_start = frame["ds"].iloc[0]
    view_end = frame["ds"].iloc[-1]

    cps = list(changepoints or [])
    # Keep only changepoints whose ds falls inside the frame's time range.
    lo, hi = frame["ds"].iloc[0], frame["ds"].iloc[-1]
    cps = [c for c in cps if c.get("ds") and lo <= pd.Timestamp(c["ds"]) <= hi]

    return ChartData(
        frame=frame,
        changepoints=cps,
        region_bounds={"val_start_ds": val_start, "test_start_ds": test_start},
        view_window=(view_start, view_end),
    )


def build_figure(data: ChartData):
    """Build the interactive Plotly figure from a ChartData (FR-024/025/026)."""
    import plotly.graph_objects as go  # local import keeps the module importable without plotly

    frame = data.frame
    fig = go.Figure()

    # Region shading (train/val/test) as background vrects.
    bounds = data.region_bounds
    x0 = frame["ds"].iloc[0]
    val_start = bounds.get("val_start_ds")
    test_start = bounds.get("test_start_ds")
    x_end = frame["ds"].iloc[-1]
    if val_start is not None:
        fig.add_vrect(x0=x0, x1=val_start, fillcolor=_REGION_FILL["train"], line_width=0, layer="below")
        fig.add_vrect(x0=val_start, x1=test_start or x_end, fillcolor=_REGION_FILL["val"], line_width=0, layer="below")
    if test_start is not None:
        fig.add_vrect(x0=test_start, x1=x_end, fillcolor=_REGION_FILL["test"], line_width=0, layer="below")

    # Forecast + actual traces (skip a trace whose column is entirely empty).
    for name, (col, dash, color) in _TRACE_STYLE.items():
        if col not in frame.columns or frame[col].notna().sum() == 0:
            continue
        fig.add_trace(
            go.Scatter(
                x=frame["ds"],
                y=frame[col],
                mode="lines",
                name=name,
                line={"dash": dash, "color": color},
                connectgaps=False,
            )
        )

    # Changepoint vlines with short annotations placed at the BOTTOM of each line, so they never
    # collide with the legend (which now sits in a reserved band above the plot).
    for cp in data.changepoints:
        fig.add_vline(
            x=pd.Timestamp(cp["ds"]),
            line={"color": "rgba(220,53,69,0.55)", "dash": "dot"},
            annotation_text=f"CP Δ={cp.get('trend_delta', 0):+.2f}",
            annotation_position="bottom right",
            annotation_font={"size": 10, "color": "rgba(220,53,69,0.9)"},
        )

    # Layout geometry — legend in its OWN reserved band at the top-left, above the plot:
    #   ┌─ legend (top band, reserved by the top margin) ─┐
    #   ├─ main plot (changepoint labels at the bottom) ──┤
    #   └─ rangeslider / minimap (thin) ──────────────────┘
    # A positive legend ``y`` above 1.0 is measured in PLOT-AREA fractions upward from the plot top;
    # with height=620, t=90, b=70 the plot area is ~460px, so y=1.06 puts the legend ~28px above the
    # plot — fully inside the 90px top margin, never clipped, never crowding the data.
    fig.update_layout(
        height=620,
        hovermode="x unified",
        legend={
            "orientation": "h",
            "yref": "paper", "yanchor": "bottom", "y": 1.04,
            "xanchor": "left", "x": 0.0,
            "font": {"size": 12},
        },
        margin={"l": 55, "r": 30, "t": 90, "b": 70},
        xaxis={
            "rangeslider": {"visible": True, "thickness": 0.07},
            "title": None,  # date axis is self-evident
        },
        yaxis={"title": "value"},
    )
    fig.update_xaxes(range=[data.view_window[0], data.view_window[1]])
    return fig
