"""Generic, domain-agnostic case container shared by all pipelines.

A ``Case`` holds one univariate :class:`darts.TimeSeries` plus an opaque-to-core
label record and provenance. Its serialized form is plain JSON-compatible data
(Principle I): ``to_dict``/``from_dict`` round-trip series values and labels exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from darts import TimeSeries

_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%S"


@dataclass
class Case:
    """One univariate series plus its (possibly empty) ground-truth labels."""

    case_id: str
    series: TimeSeries
    labels: list[dict[str, Any]] = field(default_factory=list)
    is_synthetic: bool = True
    labeled: bool = True
    config: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.series.is_univariate:
            raise ValueError(
                f"Case series must be univariate; got "
                f"{self.series.n_components} components for case_id={self.case_id!r}."
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain JSON-compatible data (series as timestamp/value records)."""
        times = self.series.time_index
        values = self.series.values().ravel().tolist()
        series_records = [
            {"timestamp": ts.strftime(_TIMESTAMP_FMT), "value": float(v)}
            for ts, v in zip(times, values, strict=True)
        ]
        return {
            "case_id": self.case_id,
            "is_synthetic": self.is_synthetic,
            "labeled": self.labeled,
            "labels": self.labels,
            "config": self.config,
            "metadata": self.metadata,
            "freq": self.series.freq_str,
            "series": series_records,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Case:
        """Rehydrate a Case from :meth:`to_dict` output."""
        records = payload["series"]
        times = pd.DatetimeIndex(
            [pd.Timestamp(r["timestamp"]) for r in records],
            freq=payload.get("freq"),
        )
        values = [float(r["value"]) for r in records]
        series = TimeSeries.from_times_and_values(times, values)
        return cls(
            case_id=payload["case_id"],
            series=series,
            labels=payload.get("labels", []),
            is_synthetic=payload.get("is_synthetic", True),
            labeled=payload.get("labeled", True),
            config=payload.get("config"),
            metadata=payload.get("metadata", {}),
        )
