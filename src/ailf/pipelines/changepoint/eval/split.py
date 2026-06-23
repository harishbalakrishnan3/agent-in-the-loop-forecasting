"""Golden-absolute split builder for the changepoint eval (reimplemented to break the POC
``generator.verify.build_split`` dependency — no module under ``pocs/`` is imported).

Depends only on promoted code: ``ailf.core.backtest.split.ResolvedSplit`` + the pipeline's
``SeriesSplit``. Unlike the ratio path (which floor-rounds), this honors the absolute boundaries so
the realized ``train_end`` equals the metadata ``train_end`` exactly — required for boundary scoring.
"""

from __future__ import annotations

import pandas as pd

from ailf.core.backtest.split import ResolvedSplit
from ailf.pipelines.changepoint.scenarios import SeriesSplit


def build_split(df: pd.DataFrame, train_end: int, val_h: int, test_h: int) -> SeriesSplit:
    """Golden absolute split: train_rows = train_end - val_h, then val_h, then test_h."""
    train_rows = train_end - val_h
    resolved = ResolvedSplit.from_lengths(
        train_rows=train_rows, val_rows=val_h, test_rows=test_h,
        source="golden", units="golden", n_rows=len(df),
    )
    return SeriesSplit(ds=df["ds"].reset_index(drop=True),
                       y=df["y"].astype(float).reset_index(drop=True), resolved=resolved)
