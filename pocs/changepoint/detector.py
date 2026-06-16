"""Deterministic changepoint detector shared by the naive baseline and diagnostics (T008).

Fits a default Prophet on training history, reads its fitted piecewise-linear trend deltas at
the candidate changepoints, ranks by |delta|, and returns the top ``n_changepoints_to_detect``
(research.md Decision 2). Same detected set seeds both the naive candidate windows and the
agent's diagnostics, so they reason about identical changepoints.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from prophet import Prophet

from pocs.changepoint.forecasting import fit_predict_prophet  # noqa: F401  (ensures logging config)


@dataclass(frozen=True)
class Changepoint:
    index: int  # row index into the training frame
    ds: pd.Timestamp
    trend_delta: float


@dataclass(frozen=True)
class ChangepointSet:
    changepoints: list[Changepoint]  # top-N, date-sorted

    @property
    def latest(self) -> Changepoint | None:
        return max(self.changepoints, key=lambda c: c.index) if self.changepoints else None

    @property
    def primary(self) -> Changepoint | None:
        return max(self.changepoints, key=lambda c: abs(c.trend_delta)) if self.changepoints else None

    @property
    def indices(self) -> list[int]:
        return [c.index for c in self.changepoints]


def detect_changepoints(train_df: pd.DataFrame, *, n_changepoints_to_detect: int) -> ChangepointSet:
    """Return the top-N Prophet changepoints by absolute trend delta, date-sorted."""
    model = Prophet()
    model.fit(train_df[["ds", "y"]])

    # Prophet stores candidate changepoint timestamps and the fitted per-changepoint trend
    # deltas (params['delta']). Both are deterministic for a fixed training frame.
    cp_times = pd.to_datetime(pd.Series(model.changepoints)).reset_index(drop=True)
    deltas = np.asarray(model.params["delta"], dtype=float).ravel()[: len(cp_times)]

    ds_to_index = {pd.Timestamp(ts): i for i, ts in enumerate(train_df["ds"])}
    candidates: list[Changepoint] = []
    for ts, delta in zip(cp_times, deltas, strict=False):
        ts = pd.Timestamp(ts)
        idx = ds_to_index.get(ts)
        if idx is None:
            # Prophet changepoints fall on training timestamps; skip any that don't map.
            continue
        candidates.append(Changepoint(index=idx, ds=ts, trend_delta=float(delta)))

    top = sorted(candidates, key=lambda c: abs(c.trend_delta), reverse=True)[:n_changepoints_to_detect]
    top_sorted = sorted(top, key=lambda c: c.index)
    return ChangepointSet(changepoints=top_sorted)
