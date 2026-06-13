"""US1: case structure + reproducibility (T007)."""

import numpy as np
import pytest

from ailf.core.datasets import Case
from ailf.pipelines.drift.datasets import DriftFlavor, GeneratorConfig, generate_case

ALL_FLAVORS = list(DriftFlavor)


def test_generate_case_returns_labeled_synthetic_case() -> None:
    case = generate_case(DriftFlavor.mean_level, seed=42)
    assert isinstance(case, Case)
    assert case.is_synthetic is True
    assert case.labeled is True
    assert case.series.is_univariate
    assert len(case.labels) == 1
    assert case.config is not None


@pytest.mark.parametrize("flavor", ALL_FLAVORS)
def test_same_seed_and_config_is_reproducible(flavor: DriftFlavor) -> None:
    a = generate_case(flavor, seed=42)
    b = generate_case(flavor, seed=42)
    assert a.series == b.series
    np.testing.assert_array_equal(a.series.values(), b.series.values())
    assert a.labels == b.labels


def test_different_seeds_same_semantics_different_noise() -> None:
    a = generate_case(DriftFlavor.mean_level, seed=1)
    b = generate_case(DriftFlavor.mean_level, seed=2)
    # Same flavor/onset semantics...
    assert a.labels[0]["flavor"] == b.labels[0]["flavor"]
    assert a.labels[0]["onset_index"] == b.labels[0]["onset_index"]
    # ...but different noise realization.
    assert not np.array_equal(a.series.values(), b.series.values())


def test_config_is_respected_and_recorded() -> None:
    cfg = GeneratorConfig(length=400, onset=200, transition_width=50, seed=7)
    case = generate_case(DriftFlavor.trend_slope, seed=7, config=cfg)
    assert len(case.series) == 400
    assert case.labels[0]["onset_index"] == 200
    assert case.labels[0]["transition_width"] == 50
    assert case.config["length"] == 400


def test_generate_case_does_not_write_to_disk(tmp_path, monkeypatch) -> None:
    # FR-013: in-memory typed object, no disk persistence required.
    monkeypatch.chdir(tmp_path)
    generate_case(DriftFlavor.mean_level, seed=42)
    assert not any(tmp_path.iterdir())
