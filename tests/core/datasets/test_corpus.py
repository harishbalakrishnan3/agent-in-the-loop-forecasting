"""US2: generic corpus persistence write/read/enumerate identity (T016)."""

import numpy as np
import pandas as pd
from darts import TimeSeries

from ailf.core.datasets import Case
from ailf.core.datasets.corpus import load_corpus, read_manifest, write_case, write_manifest


def _case(case_id: str, length: int = 12, labeled: bool = True) -> Case:
    idx = pd.date_range("2015-01-01", periods=length, freq="D")
    values = np.arange(length, dtype=float) + 0.25
    return Case(
        case_id=case_id,
        series=TimeSeries.from_times_and_values(idx, values),
        labels=[{"flavor": "mean_level", "onset_index": 6}] if labeled else [],
        is_synthetic=labeled,
        labeled=labeled,
        config={"length": length} if labeled else None,
        metadata={},
    )


def test_write_then_load_round_trips_series_and_labels(tmp_path) -> None:
    case = _case("drift-mean_level-0000")
    write_case(tmp_path, case)

    assert (tmp_path / "drift-mean_level-0000" / "series.csv").exists()
    assert (tmp_path / "drift-mean_level-0000" / "labels.json").exists()

    loaded = {c.case_id: c for c in load_corpus(tmp_path)}
    assert "drift-mean_level-0000" in loaded
    got = loaded["drift-mean_level-0000"]
    np.testing.assert_array_almost_equal(got.series.values(), case.series.values())
    assert got.labels == case.labels
    assert got.labeled is True


def test_manifest_enumerates_every_case(tmp_path) -> None:
    cases = [_case(f"drift-mean_level-{i:04d}") for i in range(3)]
    for c in cases:
        write_case(tmp_path, c)
    write_manifest(tmp_path, cases, base_seed=42)

    manifest = read_manifest(tmp_path)
    assert manifest["base_seed"] == 42
    ids = {row["case_id"] for row in manifest["cases"]}
    assert ids == {c.case_id for c in cases}
    assert all("flavors" in row and "labeled" in row for row in manifest["cases"])


def test_unlabeled_case_persists_with_empty_labels(tmp_path) -> None:
    write_case(tmp_path, _case("real-air_passengers", labeled=False))
    loaded = {c.case_id: c for c in load_corpus(tmp_path)}
    got = loaded["real-air_passengers"]
    assert got.labeled is False
    assert got.labels == []
