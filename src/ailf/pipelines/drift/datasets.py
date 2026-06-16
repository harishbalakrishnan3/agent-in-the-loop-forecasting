"""Drift dataset generation.

Seeded, knob-driven synthetic series with known, injected gradual drift, plus loaders
for standard real drift datasets. Each base series is composed from Darts primitives
(``y = g(t) + s(t) + ε``) and the chosen flavor is injected by modulating the relevant
component over a transition window. Generic Darts plumbing (the ``Case`` container,
corpus IO) lives in ``ailf.core.datasets``; only drift-specific logic lives here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from darts import TimeSeries
from darts.utils.timeseries_generation import linear_timeseries, sine_timeseries

from ailf.core.datasets import Case

# Minimum points required on each side of the onset so the reference regime is stable
# and the drift has room to develop (FR-009 / spec Edge Cases).
_MIN_REFERENCE = 10
_MIN_DRIFT = 10

# Base trend the synthetic series rides on (gentle upward slope) before any injection.
_BASE_TREND_RISE = 10.0


class DriftFlavor(str, Enum):
    """The four supported injected drift types, each bound to a Prophet component."""

    trend_slope = "trend_slope"
    mean_level = "mean_level"
    variance_inflation = "variance_inflation"
    seasonal_amplitude = "seasonal_amplitude"

    @property
    def affected_component(self) -> str:
        return {
            DriftFlavor.trend_slope: "trend",
            DriftFlavor.mean_level: "trend",
            DriftFlavor.variance_inflation: "noise",
            DriftFlavor.seasonal_amplitude: "seasonality",
        }[self]


# Named transition-width bands spanning changepoint-like → clearly-gradual (FR-008). These are
# advisory defaults for generating the ambiguous middle ground; the exact numeric Δt threshold
# demarcating drift vs changepoint is a deferred cross-team agreement (spec Dependencies), NOT
# committed here.
TRANSITION_BANDS: dict[str, int] = {
    "narrow": 5,
    "ambiguous": 40,
    "gradual": 120,
}


# Flavor-specific default drift magnitude (data-model.md: "magnitude default flavor-specific").
_DEFAULT_MAGNITUDE = {
    DriftFlavor.trend_slope: 0.05,
    DriftFlavor.mean_level: 10.0,
    DriftFlavor.variance_inflation: 2.0,
    DriftFlavor.seasonal_amplitude: 2.0,
}


@dataclass
class GeneratorConfig:
    """Reproducible knob set determining one synthetic case (FR-003). All have defaults."""

    length: int = 365
    start: pd.Timestamp = field(default_factory=lambda: pd.Timestamp("2015-01-01"))
    freq: str = "D"
    onset: int | None = None  # defaults to length // 2 when resolved
    magnitude: float | None = None  # defaults to flavor-specific when resolved
    transition_width: int | None = None  # defaults to length // 5 when resolved
    duration: int | None = None  # None => drifted regime persists to end of series
    base_noise: float = 1.0
    seasonality_period: int | None = 30
    seasonality_amplitude: float = 5.0
    seed: int = 42

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start"] = pd.Timestamp(self.start).isoformat()
        return d


@dataclass
class DriftLabel:
    """One injected drift's ground truth (FR-005). A case holds a list of these."""

    flavor: DriftFlavor
    affected_component: str
    onset_index: int
    onset_time: pd.Timestamp
    transition_width: int
    magnitude: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "flavor": self.flavor.value,
            "affected_component": self.affected_component,
            "onset_index": int(self.onset_index),
            "onset_time": pd.Timestamp(self.onset_time).isoformat(),
            "transition_width": int(self.transition_width),
            "magnitude": float(self.magnitude),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DriftLabel:
        return cls(
            flavor=DriftFlavor(d["flavor"]),
            affected_component=d["affected_component"],
            onset_index=int(d["onset_index"]),
            onset_time=pd.Timestamp(d["onset_time"]),
            transition_width=int(d["transition_width"]),
            magnitude=float(d["magnitude"]),
        )


def _resolve(flavor: DriftFlavor, seed: int, config: GeneratorConfig | None) -> GeneratorConfig:
    """Apply defaults (seed param wins) and validate; raise ValueError on contradictions."""
    cfg = config or GeneratorConfig()
    length = cfg.length
    onset = cfg.onset if cfg.onset is not None else length // 2
    width = cfg.transition_width if cfg.transition_width is not None else length // 5
    magnitude = cfg.magnitude if cfg.magnitude is not None else _DEFAULT_MAGNITUDE[flavor]

    if length <= 0:
        raise ValueError(f"length must be positive, got {length}.")
    if width < 1:
        raise ValueError(f"transition_width must be >= 1, got {width}.")
    if not (0 < onset < length):
        raise ValueError(f"onset must satisfy 0 < onset < length; got onset={onset}, length={length}.")
    if onset < _MIN_REFERENCE:
        raise ValueError(
            f"onset={onset} leaves too few reference points (< {_MIN_REFERENCE}) before the drift."
        )
    if length - onset < _MIN_DRIFT:
        raise ValueError(
            f"onset={onset} leaves too little room (< {_MIN_DRIFT} points) for the drift to develop."
        )
    if onset + width > length:
        # I1 decision: reject, never silently clamp (would desync label width from config).
        raise ValueError(
            f"onset+transition_width ({onset}+{width}={onset + width}) exceeds length ({length}); "
            "rejected rather than clamped."
        )
    if magnitude == 0:
        raise ValueError("magnitude must be non-zero (a zero-magnitude case would contradict its label).")
    if flavor is DriftFlavor.variance_inflation and cfg.base_noise <= 0:
        raise ValueError("variance_inflation requires base_noise > 0.")
    if flavor is DriftFlavor.seasonal_amplitude and (
        cfg.seasonality_period is None or cfg.seasonality_amplitude <= 0
    ):
        raise ValueError("seasonal_amplitude requires a seasonality_period and positive amplitude.")
    if cfg.duration is not None and cfg.duration < 1:
        raise ValueError(f"duration must be >= 1 when set, got {cfg.duration}.")

    return GeneratorConfig(
        length=length,
        start=pd.Timestamp(cfg.start),
        freq=cfg.freq,
        onset=onset,
        magnitude=magnitude,
        transition_width=width,
        duration=cfg.duration,
        base_noise=cfg.base_noise,
        seasonality_period=cfg.seasonality_period,
        seasonality_amplitude=cfg.seasonality_amplitude,
        seed=seed,
    )


def _ramp(length: int, onset: int, width: int) -> np.ndarray:
    """Clamped linear ramp: 0 before onset, rising to 1 across [onset, onset+width], held after."""
    t = np.arange(length)
    return np.clip((t - onset) / width, 0.0, 1.0)


def _base_components(cfg: GeneratorConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (trend, seasonal, raw_noise) arrays composed from Darts primitives."""
    trend = linear_timeseries(
        start_value=0.0, end_value=_BASE_TREND_RISE,
        length=cfg.length, start=cfg.start, freq=cfg.freq,
    ).values().ravel()

    if cfg.seasonality_period:
        seasonal = sine_timeseries(
            value_frequency=1.0 / cfg.seasonality_period,
            value_amplitude=cfg.seasonality_amplitude,
            length=cfg.length, start=cfg.start, freq=cfg.freq,
        ).values().ravel()
    else:
        seasonal = np.zeros(cfg.length)

    rng = np.random.default_rng(cfg.seed)
    raw_noise = cfg.base_noise * rng.standard_normal(cfg.length)
    return trend, seasonal, raw_noise


def _inject(flavor: DriftFlavor, cfg: GeneratorConfig) -> np.ndarray:
    """Compose the base series and inject one flavor's drift over the transition window."""
    trend, seasonal, noise = _base_components(cfg)
    ramp = _ramp(cfg.length, cfg.onset, cfg.transition_width)
    mag = cfg.magnitude

    if flavor is DriftFlavor.trend_slope:
        # Extra per-step slope ramps in; cumulative sum bends the trajectory.
        trend = trend + np.cumsum(mag * ramp)
    elif flavor is DriftFlavor.mean_level:
        # Level offset ramps from 0 to magnitude and holds.
        trend = trend + mag * ramp
    elif flavor is DriftFlavor.variance_inflation:
        noise = noise * (1.0 + mag * ramp)
    elif flavor is DriftFlavor.seasonal_amplitude:
        seasonal = seasonal * (1.0 + mag * ramp)

    return trend + seasonal + noise


def _make_case(flavor: DriftFlavor, cfg: GeneratorConfig, case_id: str | None) -> Case:
    values = _inject(flavor, cfg)
    index = pd.date_range(start=cfg.start, periods=cfg.length, freq=cfg.freq)
    series = TimeSeries.from_times_and_values(index, values)
    label = DriftLabel(
        flavor=flavor,
        affected_component=flavor.affected_component,
        onset_index=cfg.onset,
        onset_time=index[cfg.onset],
        transition_width=cfg.transition_width,
        magnitude=cfg.magnitude,
    )
    return Case(
        case_id=case_id or f"drift-{flavor.value}",
        series=series,
        labels=[label.to_dict()],
        is_synthetic=True,
        labeled=True,
        config=cfg.to_dict(),
        metadata={},
    )


def generate_case(
    flavor: DriftFlavor,
    *,
    seed: int = 42,
    config: GeneratorConfig | None = None,
    case_id: str | None = None,
) -> Case:
    """Generate one single-flavor labeled drift case (FR-001, FR-004, FR-006)."""
    cfg = _resolve(flavor, seed, config)
    return _make_case(flavor, cfg, case_id)


def _apply_flavor(
    flavor: DriftFlavor,
    cfg: GeneratorConfig,
    trend: np.ndarray,
    seasonal: np.ndarray,
    noise: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Inject one flavor's drift into the (trend, seasonal, noise) components in place-style."""
    ramp = _ramp(cfg.length, cfg.onset, cfg.transition_width)
    mag = cfg.magnitude
    if flavor is DriftFlavor.trend_slope:
        trend = trend + np.cumsum(mag * ramp)
    elif flavor is DriftFlavor.mean_level:
        trend = trend + mag * ramp
    elif flavor is DriftFlavor.variance_inflation:
        noise = noise * (1.0 + mag * ramp)
    elif flavor is DriftFlavor.seasonal_amplitude:
        seasonal = seasonal * (1.0 + mag * ramp)
    return trend, seasonal, noise


def generate_combined_case(
    flavors: list[DriftFlavor],
    *,
    seed: int = 42,
    config: GeneratorConfig | None = None,
    case_id: str | None = None,
) -> Case:
    """Generate one case with multiple injected flavors, each individually labeled (FR-007)."""
    if len(flavors) < 2:
        raise ValueError("generate_combined_case requires at least two flavors.")

    # Validate each flavor against a shared config; the first resolution fixes the base series.
    resolved = [_resolve(f, seed, config) for f in flavors]
    base_cfg = resolved[0]

    trend, seasonal, noise = _base_components(base_cfg)
    labels: list[dict[str, Any]] = []
    for flavor, cfg in zip(flavors, resolved, strict=True):
        trend, seasonal, noise = _apply_flavor(flavor, cfg, trend, seasonal, noise)
        labels.append(
            DriftLabel(
                flavor=flavor,
                affected_component=flavor.affected_component,
                onset_index=cfg.onset,
                onset_time=pd.date_range(start=cfg.start, periods=cfg.length, freq=cfg.freq)[cfg.onset],
                transition_width=cfg.transition_width,
                magnitude=cfg.magnitude,
            ).to_dict()
        )

    index = pd.date_range(start=base_cfg.start, periods=base_cfg.length, freq=base_cfg.freq)
    series = TimeSeries.from_times_and_values(index, trend + seasonal + noise)
    return Case(
        case_id=case_id or f"drift-combined-{'+'.join(f.value for f in flavors)}",
        series=series,
        labels=labels,
        is_synthetic=True,
        labeled=True,
        config=base_cfg.to_dict(),
        metadata={"combined_flavors": [f.value for f in flavors]},
    )


# --- Real demo series (FR-014–FR-016) -------------------------------------------------------
# Curated real univariate series surfaced through the same Case interface as synthetic, but
# flagged unlabeled (no ground-truth onset) so they are excluded from precision/recall.

_REAL_SERIES = ("air_passengers", "mauna_loa_co2")


def list_real_series() -> list[str]:
    """Enumerate the available real demo series (US4 scenario 3)."""
    return list(_REAL_SERIES)


def load_air_passengers() -> Case:
    """Load the Air Passengers series (growing seasonal amplitude), unlabeled (FR-014–FR-016)."""
    from darts.datasets import AirPassengersDataset

    series = AirPassengersDataset().load()
    return Case(
        case_id="real-air_passengers",
        series=series,
        labels=[],
        is_synthetic=False,
        labeled=False,
        config=None,
        metadata={
            "source": "darts.datasets.AirPassengersDataset",
            "qualitative_drift": "growing seasonal amplitude (additive→multiplicative seasonality)",
        },
    )


def load_mauna_loa_co2() -> Case:
    """Load Mauna Loa CO₂ (rising level + seasonality), resampled to regular monthly (FR-014–FR-016)."""
    from statsmodels.datasets import co2

    df = co2.load_pandas().data  # weekly, with gaps
    monthly = df["co2"].resample("MS").mean().interpolate("linear")
    index = pd.DatetimeIndex(monthly.index, freq="MS")
    series = TimeSeries.from_times_and_values(index, monthly.to_numpy(dtype=float))
    return Case(
        case_id="real-mauna_loa_co2",
        series=series,
        labels=[],
        is_synthetic=False,
        labeled=False,
        config=None,
        metadata={
            "source": "statsmodels.datasets.co2",
            "qualitative_drift": "slow rising level with seasonality",
            "preprocessing": "resampled weekly→monthly (MS) mean, linearly interpolated to fill gaps",
        },
    )
