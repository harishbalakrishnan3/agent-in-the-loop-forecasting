"""Backtest module: compare naive Prophet vs intervention Prophet.

For each dataset (D1–D15):
1. Generate dataset
2. Split into train/test
3. Fit Prophet with defaults → forecast → Naive MAE
4. Run detection → apply intervention → forecast → Intervention MAE
5. Compute improvement percentage

Usage:
    uv run python -m pocs.changepoint.level_shift.backtest
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
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

# Suppress Prophet's verbose logging
logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

OUTPUT_DIR = Path(__file__).parent


@dataclass
class BacktestResult:
    """Result of a single dataset backtest."""

    dataset_id: str
    naive_mae: float
    intervention_mae: float
    strategy_used: str
    forecast_horizon: int
    train_size: int
    test_size: int
    improvement_pct: float
    description: str


def _compute_mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Error."""
    return float(np.mean(np.abs(actual - predicted)))


def _fit_and_forecast(
    model: Prophet,
    train_df: pd.DataFrame,
    forecast_horizon: int,
) -> np.ndarray:
    """Fit Prophet and return forecast values for the horizon."""
    model.fit(train_df)
    future = model.make_future_dataframe(periods=forecast_horizon)
    # If model has extra regressors, add them to future
    for regressor in model.extra_regressors:
        if regressor in train_df.columns:
            # Extend regressor: assume post-training stays at last value
            last_val = train_df[regressor].iloc[-1]
            future[regressor] = last_val
            future.loc[: len(train_df) - 1, regressor] = train_df[regressor].values
    forecast = model.predict(future)
    # Return only the forecast horizon portion
    return forecast["yhat"].iloc[-forecast_horizon:].values


def run_backtest(
    dataset_name: str,
    config: dict,
    forecast_horizon: int = 30,
    train_ratio: float = 0.8,
) -> BacktestResult:
    """Run naive vs intervention comparison on one dataset.

    Steps:
        1. Generate dataset from config
        2. Split into train/test
        3. Fit Prophet with defaults → Naive MAE
        4. Detect + intervene + fit → Intervention MAE
        5. Return comparison
    """
    # 1. Generate dataset
    ts, meta = generate_level_shift_series(**config)
    values = ts.values().flatten()
    dates = ts.time_index

    # 2. Split into train/test
    n = len(values)
    train_end = int(n * train_ratio)
    # Ensure we have enough test points for the forecast horizon
    if n - train_end < forecast_horizon:
        forecast_horizon = n - train_end

    train_df = pd.DataFrame({
        "ds": dates[:train_end],
        "y": values[:train_end],
    })
    test_actual = values[train_end: train_end + forecast_horizon]

    # 3. Naive Prophet (defaults)
    naive_model = Prophet()
    naive_forecast = _fit_and_forecast(naive_model, train_df, forecast_horizon)
    naive_mae = _compute_mae(test_actual, naive_forecast)

    # 4. Detection + Intervention
    train_ts = ts[:train_end]
    result = detect_level_shift(train_ts)
    strategy = select_strategy(result, train_df)
    intervention = apply_intervention(result, train_df, strategy)

    # Fit with intervention
    intervention_forecast = _fit_and_forecast(
        intervention.model,
        intervention.training_data,
        forecast_horizon,
    )
    intervention_mae = _compute_mae(test_actual, intervention_forecast)

    # 5. Compute improvement
    if naive_mae > 0:
        improvement_pct = (naive_mae - intervention_mae) / naive_mae * 100
    else:
        improvement_pct = 0.0

    return BacktestResult(
        dataset_id=dataset_name,
        naive_mae=round(naive_mae, 2),
        intervention_mae=round(intervention_mae, 2),
        strategy_used=strategy,
        forecast_horizon=forecast_horizon,
        train_size=len(intervention.training_data),
        test_size=forecast_horizon,
        improvement_pct=round(improvement_pct, 1),
        description=intervention.description,
    )


def run_all_backtests(
    forecast_horizon: int = 30,
    train_ratio: float = 0.8,
) -> pd.DataFrame:
    """Run backtest on all datasets (D1–D15).

    Returns:
        DataFrame with columns:
            dataset_id | naive_mae | intervention_mae | strategy_used | improvement_pct
    """
    results = []
    for name, config in DATASET_CONFIGS.items():
        print(f"  Running {name}...", end=" ")
        bt = run_backtest(name, config, forecast_horizon, train_ratio)
        print(f"naive={bt.naive_mae}, intervention={bt.intervention_mae}, "
              f"strategy={bt.strategy_used}, improvement={bt.improvement_pct}%")
        results.append(bt)

    df = pd.DataFrame([
        {
            "dataset_id": r.dataset_id,
            "naive_mae": r.naive_mae,
            "intervention_mae": r.intervention_mae,
            "strategy_used": r.strategy_used,
            "improvement_pct": r.improvement_pct,
            "forecast_horizon": r.forecast_horizon,
            "train_size": r.train_size,
        }
        for r in results
    ])
    return df


def main():
    """Run all backtests and save results."""
    print("Running backtests on all 15 datasets...")
    print("=" * 70)

    df = run_all_backtests()

    # Save to CSV
    csv_path = OUTPUT_DIR / "results.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n{'=' * 70}")
    print(f"Results saved to: {csv_path}")

    # Print summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"\n{'Dataset':<40} {'Naive MAE':>10} {'Interv MAE':>11} {'Improve':>8} {'Strategy':<25}")
    print("-" * 95)
    for _, row in df.iterrows():
        marker = "✓" if row["improvement_pct"] > 0 else "✗"
        print(
            f"{marker} {row['dataset_id']:<38} "
            f"{row['naive_mae']:>10.2f} "
            f"{row['intervention_mae']:>11.2f} "
            f"{row['improvement_pct']:>7.1f}% "
            f"{row['strategy_used']:<25}"
        )

    # Stats
    improved = df[df["improvement_pct"] > 0]
    print(f"\nImproved: {len(improved)}/{len(df)} datasets")
    print(f"Average improvement (where positive): {improved['improvement_pct'].mean():.1f}%")

    # Complex datasets specifically
    complex_datasets = df[df["dataset_id"].str.startswith(("D11", "D12", "D13", "D14", "D15"))]
    if not complex_datasets.empty:
        complex_improved = complex_datasets[complex_datasets["improvement_pct"] > 0]
        print(f"\nComplex datasets (D11-D15):")
        print(f"  Improved: {len(complex_improved)}/{len(complex_datasets)}")
        if not complex_improved.empty:
            print(f"  Average improvement: {complex_improved['improvement_pct'].mean():.1f}%")


if __name__ == "__main__":
    main()
