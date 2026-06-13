"""Generic, domain-agnostic on-disk corpus: write / read / enumerate cases.

Each case is persisted as ``<root>/<case_id>/series.csv`` (timestamp,value) plus
``labels.json``; a top-level ``corpus.json`` manifest enumerates every case so consumers
never hand-parse files (FR-012). Plain, diffable, language-agnostic (Principle I). CSV
values use a fixed float format so a rebuild from the same inputs is byte-identical (FR-011).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
from darts import TimeSeries

from ailf.core.datasets.case import Case

_FLOAT_FMT = "{:.10g}"
_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%S"


def write_case(root: str | Path, case: Case) -> Path:
    """Persist one case under ``root/<case_id>/`` as series.csv + labels.json."""
    case_dir = Path(root) / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    times = case.series.time_index
    values = case.series.values().ravel()
    lines = ["timestamp,value"]
    lines += [
        f"{ts.strftime(_TIMESTAMP_FMT)},{_FLOAT_FMT.format(float(v))}"
        for ts, v in zip(times, values, strict=True)
    ]
    (case_dir / "series.csv").write_text("\n".join(lines) + "\n")

    labels_payload = {
        "case_id": case.case_id,
        "is_synthetic": case.is_synthetic,
        "labeled": case.labeled,
        "labels": case.labels,
        "config": case.config,
        "metadata": case.metadata,
        "freq": case.series.freq_str,
    }
    (case_dir / "labels.json").write_text(
        json.dumps(labels_payload, indent=2, sort_keys=True) + "\n"
    )
    return case_dir


def _read_case(case_dir: Path) -> Case:
    meta = json.loads((case_dir / "labels.json").read_text())
    df = pd.read_csv(case_dir / "series.csv")
    times = pd.DatetimeIndex(pd.to_datetime(df["timestamp"]), freq=meta.get("freq"))
    series = TimeSeries.from_times_and_values(times, df["value"].to_numpy(dtype=float))
    return Case(
        case_id=meta["case_id"],
        series=series,
        labels=meta.get("labels", []),
        is_synthetic=meta.get("is_synthetic", True),
        labeled=meta.get("labeled", True),
        config=meta.get("config"),
        metadata=meta.get("metadata", {}),
    )


def load_corpus(root: str | Path) -> Iterable[Case]:
    """Yield every case under ``root`` (series rehydrated, labels attached), manifest order if present."""
    root = Path(root)
    manifest_path = root / "corpus.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        case_ids = [row["case_id"] for row in manifest["cases"]]
    else:
        case_ids = sorted(p.name for p in root.iterdir() if (p / "labels.json").exists())
    for case_id in case_ids:
        yield _read_case(root / case_id)


def write_manifest(root: str | Path, cases: list[Case], *, base_seed: int, generated_with: str = "") -> Path:
    """Write the ``corpus.json`` manifest enumerating every case (FR-012)."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "base_seed": base_seed,
        "generated_with": generated_with,
        "cases": [
            {
                "case_id": c.case_id,
                "flavors": [lbl["flavor"] for lbl in c.labels],
                "labeled": c.labeled,
            }
            for c in cases
        ],
    }
    (root / "corpus.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return root / "corpus.json"


def read_manifest(root: str | Path) -> dict[str, Any]:
    return json.loads((Path(root) / "corpus.json").read_text())
