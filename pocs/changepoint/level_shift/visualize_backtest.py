"""Visualize backtest results: actual vs naive forecast vs intervention forecast.

For each dataset (D1–D15), generates a plot showing:
- Training data (blue)
- Actual test data (black)
- Naive Prophet forecast (orange dashed)
- Intervention Prophet forecast (green dashed)
- Detected changepoints (red vertical lines)

Usage:
    uv run python -m pocs.changepoint.level_shift.visualize_backtest
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from prophet import Prophet

from pocs.changepoint.level_shift.datasets import (
    DATASET_CONFIGS,
    generate_level_shift_series,
)
from pocs.changepoint.level_shift.detector import detect_level_shift
from pocs.changepoint.level_shift.interventions import (
    apply_intervention,
    select_strategy,
)

logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

OUTPUT_DIR = Path(__file__).parent / "plots" / "backtest"


def _fit_and_get_forecast(model: Prophet, train_df: pd.DataFrame, periods: int) -> pd.DataFrame:
    """Fit model and return full forecast DataFrame."""
    model.fit(train_df)
    future = model.make_future_dataframe(periods=periods)
    for regressor in model.extra_regressors:
        if regressor in train_df.columns:
            last_val = train_df[regressor].iloc[-1]
            future[regressor] = last_val
            future.loc[: len(train_df) - 1, regressor] = train_df[regressor].values
    return model.predict(future)


def build_backtest_figure(name: str, config: dict, train_ratio: float = 0.8) -> go.Figure:
    """Build a single figure comparing naive vs intervention forecast."""
    # Generate data
    ts, meta = generate_level_shift_series(**config)
    values = ts.values().flatten()
    dates = ts.time_index

    # Split
    n = len(values)
    train_end = int(n * train_ratio)
    forecast_horizon = n - train_end

    train_df = pd.DataFrame({"ds": dates[:train_end], "y": values[:train_end]})
    test_dates = dates[train_end:]
    test_actual = values[train_end:]

    # Naive forecast
    naive_model = Prophet()
    naive_fc = _fit_and_get_forecast(naive_model, train_df, forecast_horizon)
    naive_test = naive_fc.iloc[-forecast_horizon:]

    # Detection + intervention
    train_ts = ts[:train_end]
    result = detect_level_shift(train_ts)
    strategy = select_strategy(result, train_df)
    intervention = apply_intervention(result, train_df, strategy)
    interv_fc = _fit_and_get_forecast(intervention.model, intervention.training_data, forecast_horizon)
    interv_test = interv_fc.iloc[-forecast_horizon:]

    # Compute MAEs
    naive_mae = float(np.mean(np.abs(test_actual - naive_test["yhat"].values)))
    interv_mae = float(np.mean(np.abs(test_actual - interv_test["yhat"].values)))
    improvement = (naive_mae - interv_mae) / naive_mae * 100 if naive_mae > 0 else 0

    # Build figure
    fig = go.Figure()

    # Training data
    fig.add_trace(go.Scatter(
        x=dates[:train_end], y=values[:train_end],
        mode="lines", name="Training Data",
        line=dict(color="steelblue", width=1.5),
    ))

    # Actual test data
    fig.add_trace(go.Scatter(
        x=test_dates, y=test_actual,
        mode="lines", name="Actual (test)",
        line=dict(color="black", width=2),
    ))

    # Naive forecast
    fig.add_trace(go.Scatter(
        x=pd.to_datetime(naive_test["ds"]), y=naive_test["yhat"],
        mode="lines", name=f"Naive Prophet (MAE={naive_mae:.2f})",
        line=dict(color="orange", width=2, dash="dash"),
    ))

    # Intervention forecast
    fig.add_trace(go.Scatter(
        x=pd.to_datetime(interv_test["ds"]), y=interv_test["yhat"],
        mode="lines", name=f"Intervention: {strategy} (MAE={interv_mae:.2f})",
        line=dict(color="green", width=2, dash="dash"),
    ))

    # Detected changepoints
    for i, cp_idx in enumerate(result.changepoint_indices):
        if cp_idx < train_end:
            cp_date = dates[cp_idx]
            fig.add_trace(go.Scatter(
                x=[cp_date, cp_date],
                y=[values.min() - 5, values.max() + 5],
                mode="lines", name=f"Detected CP (idx={cp_idx})",
                line=dict(color="red", width=1.5, dash="dot"),
                showlegend=(i == 0),
            ))

    # Train/test split line
    split_date = str(dates[train_end])
    fig.add_trace(go.Scatter(
        x=[split_date, split_date],
        y=[values.min() - 5, values.max() + 5],
        mode="lines", name="Train/Test Split",
        line=dict(color="gray", width=1, dash="dash"),
        showlegend=False,
    ))

    # Layout
    winner = "Intervention" if improvement > 0 else "Naive"
    fig.update_layout(
        title=(
            f"{name}<br>"
            f"<sub>Strategy: {strategy} | Naive MAE: {naive_mae:.2f} | "
            f"Intervention MAE: {interv_mae:.2f} | "
            f"{'✓' if improvement > 0 else '✗'} {winner} wins ({improvement:+.1f}%)</sub>"
        ),
        xaxis_title="Date",
        yaxis_title="Value",
        hovermode="x unified",
        template="plotly_white",
        height=450,
        width=1000,
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
    )

    return fig


def export_all():
    """Export backtest comparison plots for all datasets."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Exporting backtest plots to: {OUTPUT_DIR.resolve()}")

    for name, config in DATASET_CONFIGS.items():
        print(f"  {name}...", end=" ")
        fig = build_backtest_figure(name, config)

        # Convert timestamps for kaleido
        for trace in fig.data:
            if trace.x is not None:
                trace.x = [str(x) for x in trace.x]

        png_path = OUTPUT_DIR / f"backtest_{name}.png"
        fig.write_image(str(png_path), scale=2)
        print("✓")

    print(f"\nDone! {len(DATASET_CONFIGS)} backtest plots saved.")


if __name__ == "__main__":
    export_all()
