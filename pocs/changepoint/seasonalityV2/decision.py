"""Decision matrix: naive vs agent MAE comparison.

Usage
-----
    from decision import build_decision_matrix, print_decision_matrix

    dm = build_decision_matrix(
        naive_val_mae=4.2,
        agent_val_mae=3.1,
        naive_test_mae=4.5,
        agent_test_mae=3.3,
    )
    print_decision_matrix(dm)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class DecisionMatrix:
    naive_val_mae:            float
    agent_val_mae:            float
    naive_test_mae:           float
    agent_test_mae:           float
    delta_val_mae:            float   # naive - agent  (positive = agent wins)
    delta_test_mae:           float
    agent_beats_naive_on_val: bool
    pct_improvement_val:      float   # (naive - agent) / naive * 100
    pct_improvement_test:     float   # (naive - agent) / naive * 100


def build_decision_matrix(
    naive_val_mae:  float,
    agent_val_mae:  float,
    naive_test_mae: float,
    agent_test_mae: float,
) -> DecisionMatrix:
    """Compute all comparison metrics."""
    delta_val  = naive_val_mae  - agent_val_mae
    delta_test = naive_test_mae - agent_test_mae

    pct_val  = (delta_val  / naive_val_mae  * 100) if naive_val_mae  > 0 else 0.0
    pct_test = (delta_test / naive_test_mae * 100) if naive_test_mae > 0 else 0.0

    return DecisionMatrix(
        naive_val_mae=round(naive_val_mae, 4),
        agent_val_mae=round(agent_val_mae, 4),
        naive_test_mae=round(naive_test_mae, 4),
        agent_test_mae=round(agent_test_mae, 4),
        delta_val_mae=round(delta_val, 4),
        delta_test_mae=round(delta_test, 4),
        agent_beats_naive_on_val=agent_val_mae < naive_val_mae,
        pct_improvement_val=round(pct_val, 2),
        pct_improvement_test=round(pct_test, 2),
    )


def print_decision_matrix(dm: DecisionMatrix) -> None:
    """Print a human-readable tabular summary to stdout."""
    winner_val  = "AGENT" if dm.agent_beats_naive_on_val else "NAIVE"
    winner_test = "AGENT" if dm.delta_test_mae > 0 else "NAIVE"

    print()
    print("=" * 60)
    print("  DECISION MATRIX — Naive Prophet vs Agent Prophet")
    print("=" * 60)
    print(f"  {'Metric':<30} {'Naive':>10} {'Agent':>10}")
    print("-" * 60)
    print(f"  {'Val MAE':<30} {dm.naive_val_mae:>10.4f} {dm.agent_val_mae:>10.4f}")
    print(f"  {'Test MAE':<30} {dm.naive_test_mae:>10.4f} {dm.agent_test_mae:>10.4f}")
    print("-" * 60)
    print(f"  {'Val MAE improvement':<30} {'':>10} {dm.pct_improvement_val:>+9.1f}%")
    print(f"  {'Test MAE improvement':<30} {'':>10} {dm.pct_improvement_test:>+9.1f}%")
    print("-" * 60)
    print(f"  Val winner:   {winner_val}")
    print(f"  Test winner:  {winner_test}")
    print(f"  agent_beats_naive_on_val: {dm.agent_beats_naive_on_val}")
    print("=" * 60)
    print()


def decision_matrix_to_dict(dm: DecisionMatrix) -> dict:
    """Return JSON-serialisable dict."""
    return asdict(dm)
