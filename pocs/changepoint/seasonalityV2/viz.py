"""Plotly visualisations for the seasonalityV2 POC.

Two figures:
1. viz_dataset  — full series with 4 colour-coded changepoint markers + split shading
2. plot_results — train/val/test actuals + both Prophet forecasts + MAE annotations

Both extend the ref_viz_seasonal._build_figure pattern.

Usage
-----
    from viz import viz_dataset, plot_results

    fig1 = viz_dataset(df, meta)
    fig1.write_html("viz_dataset.html")

    fig2 = plot_results(train_df, val_df, test_df, naive_fc, agent_fc, meta, dm)
    fig2.write_html("viz_results.html")
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from config import SEASONALITY_PERIOD

# Colour scheme for changepoint types (consistent across both figures)
CP_COLOURS = {
    "A_level_shift":      "red",
    "B_trend_kink":       "orange",
    "C_variance_change":  "purple",
    "D_seasonality_mode": "green",
}

CP_LABELS = {
    "A_level_shift":      "A: Level shift",
    "B_trend_kink":       "B: Trend kink",
    "C_variance_change":  "C: Variance change",
    "D_seasonality_mode": "D: Seasonality mode",
}


def _add_changepoint_vlines(
    fig: go.Figure,
    changepoints: dict,
    times: pd.DatetimeIndex,
) -> None:
    """Add vertical dashed lines for each changepoint."""
    for cp_key, cp_ts in changepoints.items():
        colour = CP_COLOURS.get(cp_key, "grey")
        label  = CP_LABELS.get(cp_key, cp_key)
        fig.add_vline(
            x=pd.Timestamp(cp_ts).value,
            line_color=colour,
            line_dash="dash",
            line_width=1.5,
            annotation_text=label,
            annotation_position="top left",
            annotation_font_size=10,
            annotation_font_color=colour,
        )


def viz_dataset(
    df: pd.DataFrame,
    meta: dict,
    period: int = SEASONALITY_PERIOD,
) -> go.Figure:
    """Build an interactive Plotly figure of the full dataset.

    Shows:
    - Raw series (steelblue)
    - Rolling mean (orange dashed, window=period)
    - Rolling ±1 std band (filled, low opacity)
    - 4 colour-coded changepoint markers (A–D)
    - Shaded val region (light yellow) and test region (light red)

    Parameters
    ----------
    df : pd.DataFrame
        Full series, columns ``ds`` and ``y``.
    meta : dict
        Dataset metadata from ``generate_dataset()``.
    period : int
        Rolling window size (default = SEASONALITY_PERIOD).
    """
    times  = pd.to_datetime(df["ds"])
    values = pd.Series(df["y"].to_numpy(), index=times)

    rolling_mean = values.rolling(window=period, center=False).mean()
    rolling_std  = values.rolling(window=period, center=False).std()
    upper = rolling_mean + rolling_std
    lower = rolling_mean - rolling_std
    valid = rolling_mean.notna().to_numpy()

    fig = go.Figure()

    # --- Raw series ---
    fig.add_trace(go.Scatter(
        x=times, y=values,
        mode="lines", name="Series",
        line=dict(color="steelblue", width=1),
    ))

    # --- Std band (lower first so fill works) ---
    fig.add_trace(go.Scatter(
        x=times[valid], y=lower[valid],
        mode="lines", name="Rolling std (lower)",
        line=dict(width=0),
        showlegend=False, legendgroup="std",
    ))
    fig.add_trace(go.Scatter(
        x=times[valid], y=upper[valid],
        mode="lines", name="Rolling ±1 std",
        fill="tonexty",
        fillcolor="rgba(70, 130, 180, 0.12)",
        line=dict(width=0),
        legendgroup="std",
    ))

    # --- Rolling mean ---
    fig.add_trace(go.Scatter(
        x=times[valid], y=rolling_mean[valid],
        mode="lines", name=f"Rolling mean (w={period})",
        line=dict(color="darkorange", width=2, dash="dash"),
    ))

    # --- Val shading ---
    val_start = pd.Timestamp(meta["train_end"])
    val_end   = pd.Timestamp(meta["val_end"])
    fig.add_vrect(
        x0=val_start, x1=val_end,
        fillcolor="rgba(255, 255, 0, 0.10)",
        layer="below", line_width=0,
        annotation_text="Val", annotation_position="top left",
        annotation_font_size=10,
    )

    # --- Test shading ---
    test_end = times.iloc[-1]
    fig.add_vrect(
        x0=val_end, x1=test_end,
        fillcolor="rgba(255, 80, 80, 0.08)",
        layer="below", line_width=0,
        annotation_text="Test", annotation_position="top left",
        annotation_font_size=10,
    )

    # --- Changepoint markers ---
    _add_changepoint_vlines(fig, meta["changepoints"], times)

    fig.update_layout(
        title=f"Synthetic Dataset — seed={meta['seed']} | 4 structural changepoints",
        xaxis_title="Date",
        yaxis_title="Value",
        hovermode="x unified",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    return fig


def plot_results(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    naive_forecast: pd.DataFrame,   # columns: ds, yhat
    agent_forecast: pd.DataFrame,   # columns: ds, yhat
    meta: dict,
    dm,                              # DecisionMatrix
) -> go.Figure:
    """Build the comparative results figure.

    Shows:
    - Training history (steelblue solid)
    - Val actuals (grey dashed)
    - Test actuals (black solid)
    - Naive Prophet forecast over test horizon (red dashed)
    - Agent Prophet forecast over test horizon (green solid)
    - MAE annotations for both methods
    - Changepoint markers

    Parameters
    ----------
    naive_forecast, agent_forecast : pd.DataFrame
        Columns ``ds`` and ``yhat``. Must cover the test horizon.
    dm : DecisionMatrix
        For MAE annotation values.
    """
    fig = go.Figure()

    train_times = pd.to_datetime(train_df["ds"])
    val_times   = pd.to_datetime(val_df["ds"])
    test_times  = pd.to_datetime(test_df["ds"])

    # --- Training history ---
    fig.add_trace(go.Scatter(
        x=train_times, y=train_df["y"],
        mode="lines", name="Train actuals",
        line=dict(color="steelblue", width=1),
    ))

    # --- Val actuals ---
    fig.add_trace(go.Scatter(
        x=val_times, y=val_df["y"],
        mode="lines", name="Val actuals",
        line=dict(color="grey", width=1, dash="dot"),
    ))

    # --- Test actuals ---
    fig.add_trace(go.Scatter(
        x=test_times, y=test_df["y"],
        mode="lines", name="Test actuals",
        line=dict(color="black", width=2),
    ))

    # --- Naive forecast ---
    naive_times = pd.to_datetime(naive_forecast["ds"])
    fig.add_trace(go.Scatter(
        x=naive_times, y=naive_forecast["yhat"],
        mode="lines", name=f"Naive Prophet (MAE={dm.naive_test_mae:.2f})",
        line=dict(color="red", width=2, dash="dash"),
    ))

    # --- Agent forecast ---
    agent_times = pd.to_datetime(agent_forecast["ds"])
    fig.add_trace(go.Scatter(
        x=agent_times, y=agent_forecast["yhat"],
        mode="lines", name=f"Agent Prophet (MAE={dm.agent_test_mae:.2f})",
        line=dict(color="green", width=2),
    ))

    # --- Val shading ---
    fig.add_vrect(
        x0=val_times.iloc[0], x1=val_times.iloc[-1],
        fillcolor="rgba(255, 255, 0, 0.08)",
        layer="below", line_width=0,
        annotation_text="Val", annotation_position="top left",
        annotation_font_size=10,
    )

    # --- Test shading ---
    fig.add_vrect(
        x0=test_times.iloc[0], x1=test_times.iloc[-1],
        fillcolor="rgba(255, 80, 80, 0.06)",
        layer="below", line_width=0,
        annotation_text="Test", annotation_position="top left",
        annotation_font_size=10,
    )

    # --- Changepoint markers ---
    all_times = pd.concat([train_df["ds"], val_df["ds"], test_df["ds"]])
    _add_changepoint_vlines(fig, meta["changepoints"], pd.to_datetime(all_times))

    # --- MAE annotations ---
    ann_x = test_times.iloc[len(test_times) // 3]
    y_max = max(
        test_df["y"].max(),
        naive_forecast["yhat"].max(),
        agent_forecast["yhat"].max(),
    )
    fig.add_annotation(
        x=ann_x, y=y_max * 0.97,
        text=f"Naive MAE: {dm.naive_test_mae:.2f}",
        showarrow=False, font=dict(color="red", size=12),
        bgcolor="rgba(255,255,255,0.8)",
    )
    fig.add_annotation(
        x=ann_x, y=y_max * 0.91,
        text=f"Agent MAE: {dm.agent_test_mae:.2f}",
        showarrow=False, font=dict(color="green", size=12),
        bgcolor="rgba(255,255,255,0.8)",
    )
    improvement = dm.pct_improvement_test
    sign = "+" if improvement >= 0 else ""
    fig.add_annotation(
        x=ann_x, y=y_max * 0.85,
        text=f"Improvement: {sign}{improvement:.1f}%",
        showarrow=False, font=dict(color="darkgreen" if improvement > 0 else "darkred", size=11),
        bgcolor="rgba(255,255,255,0.8)",
    )

    fig.update_layout(
        title="Forecast Comparison — Naive Prophet vs Agent Prophet",
        xaxis_title="Date",
        yaxis_title="Value",
        hovermode="x unified",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    return fig
