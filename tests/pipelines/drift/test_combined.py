"""US2: combined-flavor cases — every injected flavor labeled (T018, FR-007)."""

import pytest

from ailf.pipelines.drift.datasets import (
    DriftFlavor,
    GeneratorConfig,
    generate_combined_case,
)


def test_combined_case_has_one_label_per_flavor() -> None:
    flavors = [DriftFlavor.mean_level, DriftFlavor.variance_inflation]
    case = generate_combined_case(flavors, seed=42)
    assert len(case.labels) == 2
    labeled_flavors = {lbl["flavor"] for lbl in case.labels}
    assert labeled_flavors == {"mean_level", "variance_inflation"}
    assert case.is_synthetic and case.labeled


def test_combined_case_is_reproducible() -> None:
    flavors = [DriftFlavor.trend_slope, DriftFlavor.seasonal_amplitude]
    a = generate_combined_case(flavors, seed=7)
    b = generate_combined_case(flavors, seed=7)
    assert a.series == b.series
    assert a.labels == b.labels


def test_combined_requires_at_least_two_flavors() -> None:
    with pytest.raises(ValueError):
        generate_combined_case([DriftFlavor.mean_level], seed=42)


def test_combined_effects_both_present() -> None:
    # mean-level + variance: both a level rise and a spread increase should appear.
    flavors = [DriftFlavor.mean_level, DriftFlavor.variance_inflation]
    cfg = GeneratorConfig(length=400, onset=200, transition_width=20, magnitude=20.0, base_noise=1.0)
    case = generate_combined_case(flavors, seed=42, config=cfg)
    v = case.series.values().ravel()
    assert v[300:390].mean() - v[100:190].mean() > 10.0
