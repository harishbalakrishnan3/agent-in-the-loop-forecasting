"""US1: knob-validation rejections — fail clearly, never mislabel (T010, FR-009)."""

import pytest

from ailf.pipelines.drift.datasets import DriftFlavor, GeneratorConfig, generate_case


def test_onset_too_near_start_rejected() -> None:
    cfg = GeneratorConfig(length=400, onset=2, transition_width=20, seed=42)
    with pytest.raises(ValueError):
        generate_case(DriftFlavor.mean_level, seed=42, config=cfg)


def test_onset_too_near_end_rejected() -> None:
    cfg = GeneratorConfig(length=400, onset=398, transition_width=20, seed=42)
    with pytest.raises(ValueError):
        generate_case(DriftFlavor.mean_level, seed=42, config=cfg)


def test_transition_width_below_one_rejected() -> None:
    cfg = GeneratorConfig(length=400, onset=200, transition_width=0, seed=42)
    with pytest.raises(ValueError):
        generate_case(DriftFlavor.mean_level, seed=42, config=cfg)


def test_onset_plus_width_past_end_rejected_not_clamped() -> None:
    # Reject (I1 decision): never silently clamp-and-relabel.
    cfg = GeneratorConfig(length=400, onset=380, transition_width=50, seed=42)
    with pytest.raises(ValueError):
        generate_case(DriftFlavor.mean_level, seed=42, config=cfg)


def test_zero_magnitude_rejected() -> None:
    cfg = GeneratorConfig(length=400, onset=200, transition_width=20, magnitude=0.0, seed=42)
    with pytest.raises(ValueError):
        generate_case(DriftFlavor.mean_level, seed=42, config=cfg)


def test_variance_inflation_requires_positive_base_noise() -> None:
    cfg = GeneratorConfig(
        length=400, onset=200, transition_width=20, magnitude=2.0, base_noise=0.0, seed=42
    )
    with pytest.raises(ValueError):
        generate_case(DriftFlavor.variance_inflation, seed=42, config=cfg)


def test_seasonal_amplitude_requires_seasonality() -> None:
    cfg = GeneratorConfig(
        length=400, onset=200, transition_width=20, magnitude=2.0,
        seasonality_period=None, seed=42,
    )
    with pytest.raises(ValueError):
        generate_case(DriftFlavor.seasonal_amplitude, seed=42, config=cfg)
