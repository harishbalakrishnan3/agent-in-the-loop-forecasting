"""T079/T080 — SC-007 split provenance stability across a config round-trip.

A recorded EffectiveConfig re-ingested as the next run's override must reproduce the same resolved
split AND keep provenance stable: a golden-source run stays 'golden'; an override-source run stays
'override' (re-resolved from recorded units; no re-rounding flips it).
"""

from __future__ import annotations

from ailf.core.backtest.split import ResolvedSplit, resolve_split
from ailf.core.config.schema import SplitSpec


def _golden() -> ResolvedSplit:
    return ResolvedSplit.from_lengths(train_rows=760, val_rows=120, test_rows=120, source="golden", n_rows=1000)


def test_golden_source_stays_golden_on_reingest():
    # Original golden run records split = SplitSpec(units="golden").
    recorded = SplitSpec.from_dict({"units": "golden"})
    out = resolve_split(recorded, n_rows=1000, golden=_golden())
    assert out.provenance.source == "golden"
    assert (out.train_rows, out.val_rows, out.test_rows) == (760, 120, 120)


def test_override_source_stays_override_and_reproduces_rows():
    # Original override run: ratios → resolved to absolute rows in provenance.
    first = resolve_split(
        SplitSpec(units="ratios", train_ratio=0.7, val_ratio=0.15, test_ratio=0.15),
        n_rows=1000, golden=_golden(),
    )
    assert first.provenance.source == "override"
    rows = first.provenance.resolved
    # Re-ingest using the RECORDED absolute rows (no re-rounding) → identical resolution + provenance.
    reingest = resolve_split(
        SplitSpec(units="absolute", train_rows=rows["train_rows"], val_rows=rows["val_rows"], test_rows=rows["test_rows"]),
        n_rows=1000, golden=_golden(),
    )
    assert reingest.provenance.source == "override"
    assert (reingest.train_rows, reingest.val_rows, reingest.test_rows) == (
        first.train_rows, first.val_rows, first.test_rows
    )


def test_ratio_and_recorded_absolute_resolve_identically():
    ratio = resolve_split(
        SplitSpec(units="ratios", train_ratio=0.76, val_ratio=0.12, test_ratio=0.12), n_rows=1000, golden=_golden()
    )
    rows = ratio.provenance.resolved
    absolute = resolve_split(
        SplitSpec(units="absolute", train_rows=rows["train_rows"], val_rows=rows["val_rows"], test_rows=rows["test_rows"]),
        n_rows=1000, golden=_golden(),
    )
    assert (ratio.train_rows, ratio.val_rows, ratio.test_rows) == (absolute.train_rows, absolute.val_rows, absolute.test_rows)
