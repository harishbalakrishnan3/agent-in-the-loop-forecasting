"""US3: ambiguous (mid-Δt) cases + narrow-vs-wide change concentration (T023)."""

import numpy as np

from ailf.pipelines.drift.datasets import (
    TRANSITION_BANDS,
    DriftFlavor,
    GeneratorConfig,
    generate_case,
)


def _values(case) -> np.ndarray:
    return case.series.values().ravel()


def test_named_bands_exist_narrow_gradual_ambiguous() -> None:
    assert {"narrow", "ambiguous", "gradual"} <= set(TRANSITION_BANDS)
    # narrow is changepoint-like (small), gradual is wide.
    assert TRANSITION_BANDS["narrow"] < TRANSITION_BANDS["ambiguous"] < TRANSITION_BANDS["gradual"]


def test_label_records_given_transition_width() -> None:
    for width in (3, 60, 120):
        case = generate_case(
            DriftFlavor.mean_level, seed=42,
            config=GeneratorConfig(length=400, onset=150, transition_width=width),
        )
        assert case.labels[0]["transition_width"] == width


def test_narrow_change_more_concentrated_than_wide() -> None:
    onset = 150
    narrow = generate_case(
        DriftFlavor.mean_level, seed=42,
        config=GeneratorConfig(length=400, onset=onset, transition_width=4, magnitude=30.0, base_noise=0.1),
    )
    wide = generate_case(
        DriftFlavor.mean_level, seed=42,
        config=GeneratorConfig(length=400, onset=onset, transition_width=150, magnitude=30.0, base_noise=0.1),
    )
    # Max single-step jump near the onset: narrow concentrates the change, wide spreads it.
    nv, wv = _values(narrow), _values(wide)
    narrow_max_step = np.abs(np.diff(nv[onset - 2 : onset + 8])).max()
    wide_max_step = np.abs(np.diff(wv[onset - 2 : onset + 8])).max()
    assert narrow_max_step > wide_max_step * 3
