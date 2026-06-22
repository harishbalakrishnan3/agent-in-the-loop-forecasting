"""T023 — custom-CSV three-fraction split (research R5, FR-009).

The extended ``_series_split_from_df`` must honor three explicit fractions, reject sums != 1, and
guarantee each segment has >= 1 row.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ailf.pipelines.changepoint.pipeline import _series_split_from_df


def _df(n: int) -> pd.DataFrame:
    return pd.DataFrame({
        "ds": pd.date_range("2021-01-01", periods=n, freq="D"),
        "y": np.arange(n, dtype=float),
    })


def test_three_fractions_honored():
    split = _series_split_from_df(_df(1000), train_ratio=0.7, val_ratio=0.2, test_ratio=0.1)
    # floor(test)=100, floor(val)=200, train absorbs remainder=700.
    assert split.test_horizon == 100
    assert split.validation_horizon == 200
    assert split.train_end == 900  # fit_end(700) + val(200)
    assert split.fit_end == 700


def test_default_fractions():
    split = _series_split_from_df(_df(1000))  # 0.8 / 0.1 / 0.1
    assert split.test_horizon == 100
    assert split.validation_horizon == 100
    assert split.fit_end == 800


def test_rejects_fractions_not_summing_to_one():
    with pytest.raises(ValueError, match="sum to 1"):
        _series_split_from_df(_df(500), train_ratio=0.8, val_ratio=0.2, test_ratio=0.2)


def test_each_segment_at_least_one_row():
    # Tiny frame: 0.8/0.1/0.1 on 5 rows → test=floor(.5)→max1, val=max1, train=3 → all >= 1.
    split = _series_split_from_df(_df(5), train_ratio=0.8, val_ratio=0.1, test_ratio=0.1)
    assert split.fit_end >= 1 and split.validation_horizon >= 1 and split.test_horizon >= 1


def test_too_few_rows_raises():
    with pytest.raises(ValueError, match="at least 1 row"):
        # 2 rows can't yield train>=1 after val=1 + test=1.
        _series_split_from_df(_df(2), train_ratio=0.8, val_ratio=0.1, test_ratio=0.1)
