"""POC visualization for anomaly detection agent reasoning + predictions.

Creates interactive Plotly dashboard showing:
1. Original series with detected anomalies
2. Agent diagnostic steps (level shifts, outliers)
3. Before/after forecast comparison
4. Agent reasoning log
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ailf.pipelines.anomaly.datasets import generate_nab_like_synthetic, split_dataset
from ailf.pipelines.anomaly.tools import detect_level_shift, detect_outliers
from ailf.pipelines.anomaly.pipeline import AnomalyDetectionPipeline


def create_agent_visualization(results_file: str = "pocs/anomaly/pipeline_results.json") -> None:
    """Create interactive visualization of agent reasoning.

    Args:
        results_file: Path to pipeline results JSON.
    """
    # Load results
    with open(results_file, "r") as f:
        results = json.load(f)

    # Reload dataset for visualization
    dataset = generate_nab_like_synthetic(
        n_points=500, seed=42, anomaly_type="level_shift"
    )
    train, val, test = split_dataset(dataset)

    # Detect anomalies
    outlier_labels = detect_outliers(dataset.series["value"].values)
    shift_indices = detect_level_shift(dataset.series["value"].values)

    # Create subplots
    fig = make_subplots(
        rows=3,
        cols=1,
        subplot_titles=(
            "Series with Detected Anomalies",
            "Agent Diagnostic: Level Shifts & Outliers",
            "Agent Reasoning Log",
        ),
        specs=[
            [{"secondary_y": False}],
            [{"secondary_y": True}],
            [{"type": "table"}],
        ],
        row_heights=[0.4, 0.4, 0.2],
        vertical_spacing=0.12,
    )

    # --- Row 1: Series with Anomalies ---
    timestamps = dataset.series.index
    
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=dataset.series["value"],
            name="Original Series",
            mode="lines",
            line=dict(color="blue", width=1.5),
        ),
        row=1,
        col=1,
    )

    # Ground truth anomalies
    anom_mask = dataset.series["anomaly_label"] == 1
    fig.add_trace(
        go.Scatter(
            x=timestamps[anom_mask],
            y=dataset.series["value"][anom_mask],
            name="Ground Truth Anomalies",
            mode="markers",
            marker=dict(color="red", size=6, symbol="x"),
        ),
        row=1,
        col=1,
    )

    # Detected anomalies
    detected_mask = outlier_labels == 1
    fig.add_trace(
        go.Scatter(
            x=timestamps[detected_mask],
            y=dataset.series["value"][detected_mask],
            name="Detected Anomalies",
            mode="markers",
            marker=dict(color="orange", size=5, symbol="circle"),
        ),
        row=1,
        col=1,
    )

    # Train/test split line
    split_idx = len(train)
    fig.add_vline(
        x=timestamps[split_idx],
        line_dash="dash",
        line_color="gray",
        annotation_text="Train|Test",
        row=1,
        col=1,
    )

    # --- Row 2: Diagnostic Steps ---
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=dataset.series["value"],
            name="Series (diagnostic)",
            mode="lines",
            line=dict(color="lightblue", width=1),
            opacity=0.6,
        ),
        row=2,
        col=1,
        secondary_y=False,
    )

    # Level shifts as vertical lines
    for shift_idx in shift_indices:
        if 0 <= shift_idx < len(timestamps):
            fig.add_vline(
                x=timestamps[shift_idx],
                line_dash="dot",
                line_color="green",
                opacity=0.5,
                row=2,
                col=1,
            )

    # MAE comparison on secondary axis
    mae_data = [
        results["backtest_results"]["baseline_mae"],
        results["backtest_results"]["intervention_mae"],
    ]
    methods = ["Baseline", "Intervention"]

    fig.add_trace(
        go.Bar(
            x=methods,
            y=mae_data,
            name="MAE",
            marker_color=["red", "green"],
            opacity=0.7,
            text=[f"{m:.2f}" for m in mae_data],
            textposition="outside",
        ),
        row=2,
        col=1,
        secondary_y=True,
    )

    # --- Row 3: Reasoning Log (as table) ---
    log_entries = results["logs"][-5:]  # Last 5 entries
    log_messages = [entry["message"] for entry in log_entries]

    fig.add_trace(
        go.Table(
            header=dict(
                values=["Timestamp", "Message"],
                fill_color="paleturquoise",
                align="left",
            ),
            cells=dict(
                values=[
                    [entry["timestamp"].split("T")[1][:8] for entry in log_entries],
                    log_messages,
                ],
                fill_color="lavender",
                align="left",
                height=25,
            ),
        ),
        row=3,
        col=1,
    )

    # Update layout
    fig.update_xaxes(title_text="Time", row=1, col=1)
    fig.update_yaxes(title_text="Value", row=1, col=1)

    fig.update_xaxes(title_text="Method", row=2, col=1)
    fig.update_yaxes(title_text="Series Value", row=2, col=1, secondary_y=False)
    fig.update_yaxes(
        title_text="MAE",
        row=2,
        col=1,
        secondary_y=True,
        title_font=dict(color="darkgreen"),
        tickfont=dict(color="darkgreen"),
    )

    fig.update_layout(
        title_text="Anomaly Detection Agent: Diagnosis & Intervention",
        showlegend=True,
        height=1000,
        hovermode="x unified",
    )

    # Save
    output_file = "pocs/anomaly/agent_visualization.html"
    fig.write_html(output_file)
    print(f"✅ Visualization saved to {output_file}")


def create_metrics_summary() -> None:
    """Print metrics summary from pipeline results."""
    results_file = "pocs/anomaly/pipeline_results.json"
    
    with open(results_file, "r") as f:
        results = json.load(f)

    print("\n" + "=" * 80)
    print("ANOMALY DETECTION METRICS SUMMARY")
    print("=" * 80)

    metrics = results["anomaly_detection_metrics"]
    print(f"Anomaly Detection Performance:")
    print(f"  Precision: {metrics['precision']:.3f} (low false positives)")
    print(f"  Recall:    {metrics['recall']:.3f} (detection coverage)")
    print(f"  F1-Score:  {metrics['f1']:.3f}")

    print(f"\nBacktest Results:")
    baseline = results["backtest_results"]["baseline_mae"]
    intervention = results["backtest_results"]["intervention_mae"]
    improvement = baseline - intervention
    improvement_pct = 100 * improvement / baseline if baseline > 0 else 0

    print(f"  Baseline MAE:      {baseline:.2f}")
    print(f"  Intervention MAE:  {intervention:.2f}")
    print(f"  Improvement:       {improvement:.2f} ({improvement_pct:.1f}%)")

    print(f"\nRecommendation: {results['recommendation']}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    # First run the pipeline to generate results
    print("Running anomaly detection pipeline...")
    pipeline = AnomalyDetectionPipeline(seed=42)
    pipeline.run()

    # Create visualization
    print("\nGenerating visualization...")
    create_agent_visualization()

    # Print summary
    create_metrics_summary()
