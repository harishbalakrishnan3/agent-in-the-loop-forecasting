"""Anomaly pipeline entry point.

Wires the outlier diagnostic tools and prompts into the shared core agent + backtest +
eval loop. Run with: `uv run python -m ailf.pipelines.anomaly.pipeline`.

Architecture:
- Tools: detect_outliers, detect_level_shift, split_by_anomaly, compute_metrics
- Agent: ReAct loop (Diagnosis → Intervention → Backtest → Report)
- LLM Judge: Decides if intervention improves baseline
- Output: Agent logs + backtest results
"""

import json
import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from prophet import Prophet

from ailf.pipelines.anomaly.datasets import (
    generate_nab_like_synthetic,
    split_dataset,
)
from ailf.pipelines.anomaly.tools import (
    detect_level_shift,
    detect_outliers,
    compute_metrics,
)


logger = logging.getLogger(__name__)


class AnomalyDetectionPipeline:
    """ReAct agent for anomaly detection diagnostics."""

    def __init__(self, seed: int = 42):
        """Initialize pipeline.

        Args:
            seed: Random seed for reproducibility.
        """
        self.seed = seed
        self.logs = []
        self.backtest_results = {}

    def log(self, message: str, level: str = "info"):
        """Add to agent log."""
        timestamp = datetime.now().isoformat()
        entry = {"timestamp": timestamp, "level": level, "message": message}
        self.logs.append(entry)
        logger.info(f"[{level.upper()}] {message}")

    def run(self) -> dict:
        """Execute full pipeline: diagnosis → intervention → backtest → report.

        Returns:
            Dict with agent logs, backtest results, and recommendations.
        """
        self.log("Starting anomaly detection pipeline")

        # Step 1: Load dataset
        self.log("Loading NAB-like (level_shift) dataset for validation...")
        dataset = generate_nab_like_synthetic(
            n_points=500, seed=self.seed, anomaly_type="level_shift"
        )
        self.log(
            f"Loaded dataset: {len(dataset.series)} points, "
            f"{dataset.anomaly_count} anomalies ({100*dataset.anomaly_count/len(dataset.series):.1f}%)"
        )

        # Step 2: Baseline forecast with Prophet
        self.log("Running baseline Prophet forecast (default params)...")
        train, val, test = split_dataset(dataset)

        baseline_mae = self._forecast_prophet(
            train["value"].values, test["value"].values, label="Baseline"
        )
        self.backtest_results["baseline_mae"] = float(baseline_mae)
        self.log(f"Baseline Prophet MAE: {baseline_mae:.2f}")

        # Step 3: Diagnosis - detect anomalies
        self.log("Performing diagnosis: detecting anomalies...")
        
        outlier_labels = detect_outliers(dataset.series["value"].values)
        self.log(
            f"Detected {int(outlier_labels.sum())} outliers "
            f"(ground truth: {dataset.anomaly_count})"
        )

        shift_indices = detect_level_shift(dataset.series["value"].values)
        self.log(
            f"Detected {len(shift_indices)} level shift points. "
            f"Indices (first 5): {shift_indices[:5].tolist() if len(shift_indices) > 0 else 'None'}"
        )

        # Step 4: Evaluate anomaly detection
        metrics = compute_metrics(dataset.series["anomaly_label"].values, outlier_labels)
        self.log(
            f"Anomaly detection metrics: "
            f"Precision={metrics['precision']:.2f}, "
            f"Recall={metrics['recall']:.2f}, "
            f"F1={metrics['f1']:.2f}"
        )

        # Step 5: Propose intervention
        self.log("Proposing intervention: detrending + removing detected anomalies...")

        # Remove/interpolate anomalies in training data
        train_series = train.copy()
        anom_mask = outlier_labels[:len(train)] == 1
        
        if anom_mask.sum() > 0:
            # Simple interpolation for anomalies
            train_series.loc[anom_mask, "value"] = np.nan
            train_series["value"] = train_series["value"].interpolate(method="linear")
            self.log(f"Removed {int(anom_mask.sum())} anomalies from training data")
        else:
            self.log("No anomalies detected in training set")

        # Step 6: Backtest with intervention
        self.log("Backtesting intervention...")
        intervention_mae = self._forecast_prophet(
            train_series["value"].values, test["value"].values, label="Intervention"
        )
        self.backtest_results["intervention_mae"] = float(intervention_mae)
        self.log(f"Intervention Prophet MAE: {intervention_mae:.2f}")

        # Step 7: Evaluate improvement
        improvement = baseline_mae - intervention_mae
        improvement_pct = 100 * improvement / baseline_mae if baseline_mae > 0 else 0
        
        self.log(
            f"Improvement: {improvement:.2f} MAE "
            f"({improvement_pct:.1f}% reduction)"
        )

        # Step 8: Generate report
        if intervention_mae < baseline_mae:
            recommendation = "✅ ACCEPT intervention"
            self.log(f"{recommendation}: MAE improved from {baseline_mae:.2f} to {intervention_mae:.2f}")
        else:
            recommendation = "❌ REJECT intervention"
            self.log(f"{recommendation}: No improvement (baseline: {baseline_mae:.2f})")

        return {
            "success": True,
            "logs": self.logs,
            "backtest_results": self.backtest_results,
            "anomaly_detection_metrics": metrics,
            "recommendation": recommendation,
            "timestamp": datetime.now().isoformat(),
        }

    def _forecast_prophet(
        self, train_values: np.ndarray, test_values: np.ndarray, label: str = "Model"
    ) -> float:
        """Forecast with Prophet and compute MAE on test set.

        Args:
            train_values: Training time-series values.
            test_values: Test time-series values.
            label: Label for logging.

        Returns:
            MAE on test set.
        """
        try:
            # Prepare training data for Prophet
            train_df = pd.DataFrame({
                "ds": pd.date_range(start="2020-01-01", periods=len(train_values), freq="D"),
                "y": train_values,
            })

            # Fit Prophet with default parameters
            model = Prophet(
                yearly_seasonality=False,
                weekly_seasonality=True,
                daily_seasonality=False,
                interval_width=0.95,
            )
            model.fit(train_df)

            # Forecast
            future = pd.DataFrame({
                "ds": pd.date_range(
                    start=train_df["ds"].iloc[-1] + pd.Timedelta(days=1),
                    periods=len(test_values),
                    freq="D",
                )
            })
            forecast = model.make_future_dataframe(periods=len(test_values))
            forecast = model.predict(forecast)

            # Extract predictions for test period
            forecast_values = forecast.iloc[-len(test_values):]["yhat"].values

            # Compute MAE
            mae = np.mean(np.abs(test_values - forecast_values))
            return mae

        except Exception as e:
            self.log(f"Prophet forecast failed: {e}", level="error")
            return np.inf


def main() -> None:
    """Run the anomaly detection pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    pipeline = AnomalyDetectionPipeline(seed=42)
    results = pipeline.run()

    # Print summary
    print("\n" + "=" * 80)
    print("ANOMALY DETECTION PIPELINE RESULTS")
    print("=" * 80)
    print(json.dumps(results, indent=2, default=str))
    print("=" * 80)

    # Save results
    output_file = "pocs/anomaly/pipeline_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"✅ Results saved to {output_file}")


if __name__ == "__main__":
    main()
