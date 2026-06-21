"""T021/T054 — split resolver (test-first, contracts/split_resolver.md).

Golden-path tests (T021, US1) + override tests (T054, US2) live together since they exercise one
module. The override block is marked with comments.
"""

from __future__ import annotations

import pytest

from ailf.core.backtest.split import ResolvedSplit, SplitError, resolve_split
from ailf.core.config.schema import SplitSpec


def _golden() -> ResolvedSplit:
    # POC golden for a 1000-row scenario: train_end=880, val_h=120, test_h=120.
    return ResolvedSplit.from_lengths(train_rows=760, val_rows=120, test_rows=120, source="golden")


# ---- ResolvedSplit derivation (nested-view) -------------------------------------------------

def test_resolved_split_nested_view_derivation():
    rs = _golden()
    assert rs.fit_end == 760
    assert rs.train_end == 880
    assert rs.test_start == 880
    assert rs.test_end == 1000
    assert rs.forecast_origin_index == 879
    assert rs.n_rows == 1000


def test_resolved_split_rejects_nonpositive_segments():
    with pytest.raises(SplitError):
        ResolvedSplit.from_lengths(train_rows=0, val_rows=120, test_rows=120, source="golden")


# ---- Golden path (US1) ----------------------------------------------------------------------

def test_resolve_split_none_returns_golden_verbatim():
    golden = _golden()
    out = resolve_split(None, n_rows=1000, golden=golden)
    assert out == golden
    assert out.provenance.source == "golden"


def test_resolve_split_golden_units_returns_golden():
    golden = _golden()
    out = resolve_split(SplitSpec(units="golden"), n_rows=1000, golden=golden)
    assert out == golden


# ---- Override: absolute (US2 / T054) --------------------------------------------------------

def test_absolute_override():
    out = resolve_split(
        SplitSpec(units="absolute", train_rows=700, val_rows=150, test_rows=150),
        n_rows=1000,
        golden=_golden(),
    )
    assert (out.train_rows, out.val_rows, out.test_rows) == (700, 150, 150)
    assert out.provenance.source == "override"
    assert out.provenance.units == "absolute"


# ---- Override: ratios + rounding rule (US2 / T054, SC-009) -----------------------------------

def test_ratio_override_rounding_sums_to_n():
    out = resolve_split(
        SplitSpec(units="ratios", train_ratio=0.7, val_ratio=0.15, test_ratio=0.15),
        n_rows=1000,
        golden=_golden(),
    )
    assert out.train_rows + out.val_rows + out.test_rows == 1000
    # floor(0.15*1000)=150 each for test & val; train absorbs remainder.
    assert (out.val_rows, out.test_rows) == (150, 150)
    assert out.train_rows == 700
    assert out.provenance.rounding_rule == "floor_test_val_train_absorbs"


def test_ratio_and_equivalent_absolute_resolve_identically_n1000():
    ratio = resolve_split(
        SplitSpec(units="ratios", train_ratio=0.76, val_ratio=0.12, test_ratio=0.12),
        n_rows=1000,
        golden=_golden(),
    )
    absolute = resolve_split(
        SplitSpec(units="absolute", train_rows=760, val_rows=120, test_rows=120),
        n_rows=1000,
        golden=_golden(),
    )
    assert (ratio.train_rows, ratio.val_rows, ratio.test_rows) == (
        absolute.train_rows,
        absolute.val_rows,
        absolute.test_rows,
    )


def test_ratio_and_equivalent_absolute_resolve_identically_n1730():
    n = 1730
    # 0.8/0.1/0.1 → test=val=173, train=1384
    ratio = resolve_split(
        SplitSpec(units="ratios", train_ratio=0.8, val_ratio=0.1, test_ratio=0.1),
        n_rows=n,
        golden=_golden(),
    )
    absolute = resolve_split(
        SplitSpec(units="absolute", train_rows=1384, val_rows=173, test_rows=173),
        n_rows=n,
        golden=_golden(),
    )
    assert (ratio.train_rows, ratio.val_rows, ratio.test_rows) == (1384, 173, 173)
    assert (ratio.train_rows, ratio.val_rows, ratio.test_rows) == (
        absolute.train_rows,
        absolute.val_rows,
        absolute.test_rows,
    )


# ---- Validation errors (US2 / T054, FR-018/FR-020) ------------------------------------------

def test_ambiguous_split_both_ratio_and_absolute_raises():
    with pytest.raises(SplitError, match="ambiguous"):
        resolve_split(
            SplitSpec(units="ratios", train_ratio=0.8, val_ratio=0.1, test_ratio=0.1, train_rows=700),
            n_rows=1000,
            golden=_golden(),
        )


def test_ratios_not_summing_to_one_raises():
    with pytest.raises(SplitError):
        resolve_split(
            SplitSpec(units="ratios", train_ratio=0.8, val_ratio=0.1, test_ratio=0.05),
            n_rows=1000,
            golden=_golden(),
        )


def test_segment_floored_to_zero_raises():
    with pytest.raises(SplitError):
        # val_ratio too small for n → floors to 0
        resolve_split(
            SplitSpec(units="ratios", train_ratio=0.9994, val_ratio=0.0001, test_ratio=0.0005),
            n_rows=1000,
            golden=_golden(),
        )


def test_absolute_exceeding_rows_raises():
    with pytest.raises(SplitError):
        resolve_split(
            SplitSpec(units="absolute", train_rows=900, val_rows=120, test_rows=120),
            n_rows=1000,
            golden=_golden(),
        )
