"""Split resolver — golden default + ratio/absolute override (contracts/split_resolver.md).

Strict-partition core model carrying segment LENGTHS, with a FIXED nested-view derivation back to
the POC indices so golden reproduction is bit-exact (FR-017..021, SC-009/SC-012).

Knows only ``(n_rows, SplitSpec | None, golden: ResolvedSplit)`` — no config-file/CSV/metadata
knowledge (the pipeline owns those).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ailf.core.config.schema import SplitSpec


class SplitError(RuntimeError):
    """Raised on an ambiguous, out-of-range, or otherwise invalid split specification."""


@dataclass(frozen=True)
class SplitProvenance:
    source: str  # "golden" | "override"
    units: str  # "golden" | "ratios" | "absolute"
    requested: dict[str, Any]
    resolved: dict[str, int]
    rounding_rule: str
    derived: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "units": self.units,
            "requested": dict(self.requested),
            "resolved": dict(self.resolved),
            "rounding_rule": self.rounding_rule,
            "derived": dict(self.derived),
        }


@dataclass(frozen=True)
class ResolvedSplit:
    """Segment LENGTHS (all >= 1) + provenance. Fixed nested-view derivation to POC indices."""

    train_rows: int
    val_rows: int
    test_rows: int
    provenance: SplitProvenance

    # --- nested-view derivation (mirrors POC SeriesSplit) ---
    @property
    def fit_end(self) -> int:
        return self.train_rows

    @property
    def train_end(self) -> int:
        return self.train_rows + self.val_rows

    @property
    def test_start(self) -> int:
        return self.train_end

    @property
    def test_end(self) -> int:
        return self.train_end + self.test_rows

    @property
    def forecast_origin_index(self) -> int:
        return self.train_end - 1

    @property
    def n_rows(self) -> int:
        return self.train_rows + self.val_rows + self.test_rows

    @classmethod
    def from_lengths(
        cls,
        *,
        train_rows: int,
        val_rows: int,
        test_rows: int,
        source: str,
        units: str = "golden",
        requested: dict[str, Any] | None = None,
        rounding_rule: str = "none",
        n_rows: int | None = None,
    ) -> "ResolvedSplit":
        for name, v in (("train_rows", train_rows), ("val_rows", val_rows), ("test_rows", test_rows)):
            if v < 1:
                raise SplitError(f"Split segment {name}={v} must be >= 1 (positive, non-empty).")
        total = train_rows + val_rows + test_rows
        n = n_rows if n_rows is not None else total
        if total > n:
            raise SplitError(
                f"Split lengths sum to {total} but only {n} rows are available "
                f"(train={train_rows}, val={val_rows}, test={test_rows})."
            )
        derived = {
            "train_end": train_rows + val_rows,
            "fit_end": train_rows,
            "forecast_origin_index": train_rows + val_rows - 1,
        }
        provenance = SplitProvenance(
            source=source,
            units=units,
            requested=requested or {},
            resolved={
                "train_rows": train_rows,
                "val_rows": val_rows,
                "test_rows": test_rows,
                "n_rows": n,
            },
            rounding_rule=rounding_rule,
            derived=derived,
        )
        return cls(train_rows=train_rows, val_rows=val_rows, test_rows=test_rows, provenance=provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "train_rows": self.train_rows,
            "val_rows": self.val_rows,
            "test_rows": self.test_rows,
            "provenance": self.provenance.to_dict(),
        }


def _has_ratio(spec: SplitSpec) -> bool:
    return any(v is not None for v in (spec.train_ratio, spec.val_ratio, spec.test_ratio))


def _has_absolute(spec: SplitSpec) -> bool:
    return any(v is not None for v in (spec.train_rows, spec.val_rows, spec.test_rows))


def resolve_split(
    spec: SplitSpec | None, *, n_rows: int, golden: ResolvedSplit
) -> ResolvedSplit:
    """Resolve a (possibly absent) split spec against ``n_rows`` and the scenario ``golden`` split.

    ``None`` or ``units="golden"`` → the golden split verbatim (FR-017). Otherwise an override:
    either ratios (sum to exactly 1.0; ``floor_test_val_train_absorbs`` rounding) or absolute rows;
    supplying both → ``SplitError`` (FR-018). All segments must be >= 1 and fit within ``n_rows``.
    """
    if spec is None or spec.units == "golden":
        return golden

    has_ratio, has_abs = _has_ratio(spec), _has_absolute(spec)
    if has_ratio and has_abs:
        raise SplitError(
            "ambiguous split specification: supply EITHER ratios OR absolute rows, not both."
        )

    if spec.units == "absolute":
        if not has_abs:
            raise SplitError("absolute split requires train_rows/val_rows/test_rows.")
        return ResolvedSplit.from_lengths(
            train_rows=int(spec.train_rows),
            val_rows=int(spec.val_rows),
            test_rows=int(spec.test_rows),
            source="override",
            units="absolute",
            requested=spec.to_dict(),
            rounding_rule="none",
            n_rows=n_rows,
        )

    if spec.units == "ratios":
        if not has_ratio:
            raise SplitError("ratios split requires train_ratio/val_ratio/test_ratio.")
        total = (spec.train_ratio or 0) + (spec.val_ratio or 0) + (spec.test_ratio or 0)
        if abs(total - 1.0) > 1e-9:
            raise SplitError(
                f"split ratios must sum to exactly 1.0; got {total} "
                f"(train={spec.train_ratio}, val={spec.val_ratio}, test={spec.test_ratio})."
            )
        test_rows = int(spec.test_ratio * n_rows)  # floor
        val_rows = int(spec.val_ratio * n_rows)  # floor
        train_rows = n_rows - test_rows - val_rows  # absorbs remainder
        return ResolvedSplit.from_lengths(
            train_rows=train_rows,
            val_rows=val_rows,
            test_rows=test_rows,
            source="override",
            units="ratios",
            requested=spec.to_dict(),
            rounding_rule="floor_test_val_train_absorbs",
            n_rows=n_rows,
        )

    raise SplitError(f"unknown split units {spec.units!r} (expected golden|ratios|absolute).")
