"""Test-first (Principle II) — the reimplemented build_split that BREAKS the pocs/generator dep.

Golden-ABSOLUTE split: realized train_end must equal the input train_end EXACTLY (the ratio path
would floor-round it). Depends only on promoted core (ResolvedSplit) + the pipeline's SeriesSplit.
"""

from __future__ import annotations

import pandas as pd

from ailf.pipelines.changepoint.eval.split import build_split


def _df(n):
    return pd.DataFrame({"ds": pd.date_range("2019-01-01", periods=n, freq="D"),
                         "y": [float(i) for i in range(n)]})


def test_build_split_golden_absolute_exact():
    s = build_split(_df(1000), train_end=880, val_h=120, test_h=120)
    assert s.train_end == 880          # exact, not floor-rounded
    assert s.fit_end == 760            # train_rows = train_end - val_h
    assert s.test_horizon == 120


def test_build_split_long_layout_exact():
    s = build_split(_df(1730), train_end=1610, val_h=120, test_h=120)
    assert s.train_end == 1610 and s.fit_end == 1490 and s.test_horizon == 120


def test_build_split_partitions_cover_series():
    s = build_split(_df(1000), train_end=880, val_h=120, test_h=120)
    # train_df is [0, train_end); test region is [train_end, train_end+test_h)
    assert len(s.train_df) == 880
    assert s.resolved.provenance.source == "golden"
