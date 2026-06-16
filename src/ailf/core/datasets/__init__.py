"""Shared dataset utilities.

Generic Darts-based time-series generation (seeded, knob-driven) and standard-dataset
loaders reused by every pipeline. Use-case-specific generation lives in each
`ailf.pipelines.<usecase>.datasets`.
"""

from ailf.core.datasets.case import Case
from ailf.core.datasets.corpus import (
    load_corpus,
    read_manifest,
    write_case,
    write_manifest,
)
from ailf.core.datasets.viz import plot_drift_overlay, save_drift_overlay

__all__ = [
    "Case",
    "load_corpus",
    "read_manifest",
    "write_case",
    "write_manifest",
    "plot_drift_overlay",
    "save_drift_overlay",
]
