"""Plotting (T013/T017).

``render_agent_context`` → the EXACT training-only image shown to the visual node: a plain
line plot, no test data, no changepoint/boundary annotations (FR-034, SC-002).
``render_forecast_comparison`` → human-only post-evaluation artifact, never shown to an agent
node (FR-035).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from pocs.changepoint.scenarios import SeriesSplit  # noqa: E402


def render_agent_context(split: SeriesSplit, title: str, out_path: Path) -> Path:
    """Training-only line plot + forecast-origin marker. No test data, no annotations."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    train = split.train_df
    # Leakage invariant (SC-002): the agent image must contain only training rows.
    assert len(train) == split.train_end, "agent_context must plot exactly the training region"
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(train["ds"], train["y"], color="#1f77b4", linewidth=1.2)
    ax.axvline(split.forecast_origin, color="black", linewidth=1.3, label="forecast origin")
    ax.set_title(title)
    ax.set_xlabel("date")
    ax.set_ylabel("y")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def render_forecast_comparison(
    split: SeriesSplit,
    *,
    title: str,
    full_history_yhat: np.ndarray,
    naive_yhat: np.ndarray,
    agent_yhat: np.ndarray,
    agent_label: str,
    metrics_by_method: dict[str, dict[str, float]],
    out_path: Path,
) -> Path:
    """Train history + hidden-test actuals + the three method forecasts (human-only)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    train = split.train_df
    test = split.test_df
    history_start = max(0, split.train_end - 520)

    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.plot(
        train["ds"].iloc[history_start:],
        train["y"].iloc[history_start:],
        color="#7f7f7f",
        linewidth=1.0,
        label="train history",
    )
    ax.plot(test["ds"], test["y"], color="black", linewidth=2.0, label="hidden-test actuals")

    def mae(method: str) -> float:
        return metrics_by_method.get(method, {}).get("mae", float("nan"))

    ax.plot(test["ds"], full_history_yhat, color="#1f77b4", linewidth=1.6, label=f"full-history Prophet ({mae('full_history_prophet'):.1f})")
    ax.plot(test["ds"], naive_yhat, color="#d62728", linewidth=1.6, label=f"naive workflow ({mae('naive_workflow'):.1f})")
    ax.plot(test["ds"], agent_yhat, color="#2ca02c", linewidth=1.8, label=f"agent: {agent_label} ({mae('agent'):.1f})")

    ax.axvline(split.forecast_origin, color="black", linewidth=1.0, linestyle=":")
    ax.set_title(title)
    ax.set_xlabel("date")
    ax.set_ylabel("y")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
