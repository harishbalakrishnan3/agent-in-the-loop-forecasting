"""Changepoint fixture loading + golden-split adapter (NOT synthetic generation).

Reads the committed ``data/scenario_metadata.json`` + per-scenario ``ds,y`` CSVs (resolved by
basename under this pipeline's ``data/csv/``). Translates the golden metadata's nested split
encoding into a core ``ResolvedSplit`` (contracts/split_resolver.md):
``val_rows = validation_horizon``, ``train_rows = train_end - validation_horizon``,
``test_rows = test_horizon``. Rejects metadata that would derive a non-positive ``train_rows``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ailf.core.backtest.split import ResolvedSplit, SplitError

_DATA_DIR = Path(__file__).resolve().parent / "data"
_CSV_DIR = _DATA_DIR / "csv"
_METADATA_PATH = _DATA_DIR / "scenario_metadata.json"


class ScenarioError(RuntimeError):
    """Raised on missing fixtures or invalid scenario metadata."""


def load_metadata() -> dict[str, Any]:
    if not _METADATA_PATH.exists():
        raise ScenarioError(f"Scenario metadata not found at {_METADATA_PATH}")
    return json.loads(_METADATA_PATH.read_text())


def load_series(scenario_id: str, csv_path: str) -> pd.DataFrame:
    """Load a scenario's ``ds,y`` frame, resolving the CSV by basename under this pipeline."""
    path = _CSV_DIR / Path(csv_path).name
    if not path.exists():
        raise ScenarioError(f"CSV fixture not found for {scenario_id}: {path}")
    frame = pd.read_csv(path, parse_dates=["ds"])
    if list(frame.columns[:2]) != ["ds", "y"]:
        raise ScenarioError(f"{path} must have columns ds,y; got {list(frame.columns)}")
    return frame


def golden_split_from_metadata(meta: dict[str, Any], n_rows: int) -> ResolvedSplit:
    """Translate golden metadata (nested encoding) into a strict-partition ``ResolvedSplit``."""
    train_end = int(meta["train_end"])
    val_h = int(meta["validation_horizon"])
    test_h = int(meta["test_horizon"])
    train_rows = train_end - val_h
    if train_rows < 1:
        raise SplitError(
            f"golden metadata for {meta.get('scenario_id')!r} derives non-positive train_rows="
            f"{train_rows} (train_end={train_end}, validation_horizon={val_h})."
        )
    return ResolvedSplit.from_lengths(
        train_rows=train_rows,
        val_rows=val_h,
        test_rows=test_h,
        source="golden",
        units="golden",
        rounding_rule="none",
        n_rows=n_rows,
    )
