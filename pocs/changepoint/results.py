"""Shared result dataclasses (data-model.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class CandidateResult:
    label: str
    val_metrics: dict[str, float]
    forecast: np.ndarray | None = None  # over the relevant horizon
    test_metrics: dict[str, float] | None = None  # filled ONLY at final evaluation
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def val_mae(self) -> float:
        return self.val_metrics["mae"]

    def summary_dict(self) -> dict[str, Any]:
        """JSON-serializable view without the raw forecast array."""
        return {
            "label": self.label,
            "val_metrics": self.val_metrics,
            "test_metrics": self.test_metrics,
            **({"extra": self.extra} if self.extra else {}),
        }
