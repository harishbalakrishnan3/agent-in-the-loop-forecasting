"""Drift eval-corpus build config + materializer (FR-010, FR-011).

The committed knob sweep below is the single source of truth for corpus composition:
exactly 25 cases per flavor (100 single-flavor) + 10 combined = 110 total. Per-case seeds
and knobs are derived deterministically from ``base_seed`` + case index, so a rebuild from
the same config is byte-identical (SC-003). Bulk output lands under ``data/synthetic/drift/``
(gitignored); reproducibility rests on this committed source, not the output.

CLI: ``uv run python -m ailf.pipelines.drift.corpus``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ailf.core.datasets import Case, load_corpus, write_case, write_manifest
from ailf.pipelines.drift.datasets import (
    DriftFlavor,
    GeneratorConfig,
    generate_case,
    generate_combined_case,
)

__all__ = ["build_corpus", "load_corpus", "DEFAULT_ROOT", "BASE_SEED"]

DEFAULT_ROOT = Path("data/synthetic/drift")
BASE_SEED = 42
BUILD_VERSION = "ailf.pipelines.drift.corpus@1"

_SINGLE_PER_FLAVOR = 25
_COMBINED = 10
_LENGTH = 400

# Combined-flavor pairings cycled across the 10 stretch cases.
_COMBINED_PAIRS = [
    [DriftFlavor.mean_level, DriftFlavor.variance_inflation],
    [DriftFlavor.trend_slope, DriftFlavor.seasonal_amplitude],
    [DriftFlavor.mean_level, DriftFlavor.seasonal_amplitude],
    [DriftFlavor.trend_slope, DriftFlavor.variance_inflation],
]


def _sweep_config(flavor: DriftFlavor, i: int, seed: int) -> GeneratorConfig:
    """Deterministically vary onset / magnitude / Δt across the 25 cases of a flavor."""
    onset = 120 + (i % 5) * 30          # 120..240
    width = 10 + (i % 5) * 25           # 10..110 (spans narrow → gradual → ambiguous)
    mag_base = {
        DriftFlavor.trend_slope: 0.03,
        DriftFlavor.mean_level: 8.0,
        DriftFlavor.variance_inflation: 1.5,
        DriftFlavor.seasonal_amplitude: 1.5,
    }[flavor]
    magnitude = mag_base * (1.0 + (i % 5) * 0.5)
    return GeneratorConfig(
        length=_LENGTH,
        onset=onset,
        transition_width=width,
        magnitude=magnitude,
        base_noise=1.0,
        seasonality_period=30,
        seasonality_amplitude=5.0,
        seed=seed,
    )


def build_corpus(
    root: str | Path = DEFAULT_ROOT,
    *,
    base_seed: int = BASE_SEED,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Materialize the canonical ≈110-case corpus to disk; return the manifest dict."""
    root = Path(root)
    if overwrite and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    cases: list[Case] = []
    case_index = 0

    for flavor in DriftFlavor:
        for i in range(_SINGLE_PER_FLAVOR):
            seed = base_seed + case_index
            cfg = _sweep_config(flavor, i, seed)
            case_id = f"drift-{flavor.value}-{i:04d}"
            cases.append(generate_case(flavor, seed=seed, config=cfg, case_id=case_id))
            case_index += 1

    for j in range(_COMBINED):
        seed = base_seed + case_index
        flavors = _COMBINED_PAIRS[j % len(_COMBINED_PAIRS)]
        cfg = GeneratorConfig(
            length=_LENGTH,
            onset=150 + (j % 4) * 20,
            transition_width=30 + (j % 4) * 20,
            magnitude=10.0,
            base_noise=1.0,
            seasonality_period=30,
            seasonality_amplitude=5.0,
            seed=seed,
        )
        case_id = f"drift-combined-{j:04d}"
        cases.append(generate_combined_case(flavors, seed=seed, config=cfg, case_id=case_id))
        case_index += 1

    for case in cases:
        write_case(root, case)
    write_manifest(root, cases, base_seed=base_seed, generated_with=BUILD_VERSION)
    return {
        "base_seed": base_seed,
        "generated_with": BUILD_VERSION,
        "cases": [
            {"case_id": c.case_id, "flavors": [lbl["flavor"] for lbl in c.labels], "labeled": c.labeled}
            for c in cases
        ],
    }


def main() -> None:
    manifest = build_corpus()
    print(f"Built {len(manifest['cases'])} cases under {DEFAULT_ROOT} (base_seed={BASE_SEED}).")


if __name__ == "__main__":
    main()
