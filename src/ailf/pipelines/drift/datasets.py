"""Drift dataset generation.

Seeded, knob-driven synthetic series with known drift, plus loaders for standard
drift datasets. Build generic Darts plumbing in `ailf.core.datasets`; keep only
drift-specific generation here.

Design notes
------------
* SiD2ReGenerator (referenced in SPEC-dataset.md) was not found on PyPI; the
  constitution (§ Technology & Architecture Constraints) mandates Darts for
  dataset generation. All series are built with numpy / pandas and are
  Prophet-compatible (columns ``ds`` and ``y``).
* Every public method:
  - Accepts an explicit ``seed`` parameter and uses a *local* RNG
    (``np.random.default_rng(seed)``) — never a global state.
  - Returns a ``(DataFrame, dict)`` pair where the dict captures the injected
    ground-truth metadata needed for precision / recall evaluation.
  - Reads defaults from ``config.yml`` but accepts keyword overrides so that
    tests can exercise arbitrary parameter combinations.
* The ``trend`` runtime variable is exposed by ``DriftGenerator.trend``; the
  FastAPI layer (``api.py``) mutates it via a shared state object so that
  subsequent ``generate_*`` calls pick up the new value without reloading the
  file.
"""

from __future__ import annotations

import pathlib
from typing import Any

import numpy as np
import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VALID_TRENDS = {"flat", "linear", "exponential"}


def _base_series(
    n_points: int,
    trend: str,
    noise_std: float,
    start_date: str,
    freq: str,
    rng: np.random.Generator,
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Return (timestamps, values) for the base series before drift injection."""
    dates = pd.date_range(start=start_date, periods=n_points, freq=freq)
    t = np.arange(n_points, dtype=float)

    if trend == "flat":
        base = np.zeros(n_points)
    elif trend == "linear":
        base = 0.05 * t
    elif trend == "exponential":
        base = np.exp(0.005 * t) - 1.0
    else:  # pragma: no cover — caught at init
        raise ValueError(f"Unknown trend '{trend}'")

    noise = rng.normal(0.0, noise_std, size=n_points)
    return dates, base + noise


def _make_df(dates: pd.DatetimeIndex, y: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"ds": dates, "y": y.astype(float)})


# ---------------------------------------------------------------------------
# DriftGenerator
# ---------------------------------------------------------------------------


class DriftGenerator:
    """Generates synthetic time-series datasets with controlled drift injections.

    Parameters
    ----------
    config_path:
        Path to ``config.yml``.  Resolved to an absolute path; raises
        ``FileNotFoundError`` if the file does not exist.
    trend:
        Override the ``drift.trend`` key from config.  Must be one of
        ``{"flat", "linear", "exponential"}``.

    Runtime mutation
    ----------------
    The ``trend`` attribute is intentionally mutable so that the FastAPI layer
    can update it at runtime without touching the file on disk.
    """

    def __init__(
        self,
        config_path: pathlib.Path | str,
        trend: str | None = None,
    ) -> None:
        config_path = pathlib.Path(config_path).resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")

        with config_path.open() as fh:
            raw: dict[str, Any] = yaml.safe_load(fh)

        self._cfg: dict[str, Any] = raw.get("drift", {})
        self._config_path = config_path

        resolved_trend = trend if trend is not None else self._cfg.get("trend", "linear")
        if resolved_trend not in _VALID_TRENDS:
            raise ValueError(
                f"Invalid trend '{resolved_trend}'. Must be one of {sorted(_VALID_TRENDS)}."
            )
        self.trend: str = resolved_trend

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _defaults(self) -> dict[str, Any]:
        """Return flat config defaults."""
        return {
            "n_points": self._cfg.get("n_points", 365),
            "noise_std": self._cfg.get("noise_std", 1.0),
            "start_date": self._cfg.get("start_date", "2023-01-01"),
            "freq": self._cfg.get("freq", "D"),
        }

    def _base(
        self, n_points: int, noise_std: float, start_date: str, freq: str, rng: np.random.Generator
    ) -> tuple[pd.DatetimeIndex, np.ndarray]:
        return _base_series(n_points, self.trend, noise_std, start_date, freq, rng)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sudden_drift(
        self,
        seed: int = 42,
        n_points: int | None = None,
        drift_point: int | None = None,
        magnitude: float | None = None,
        noise_std: float | None = None,
        start_date: str | None = None,
        freq: str | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Abrupt mean shift at a single changepoint.

        Returns
        -------
        df:
            Prophet-compatible DataFrame with columns ``ds`` and ``y``.
        meta:
            Ground-truth metadata: ``drift_type``, ``drift_point``, ``magnitude``.
        """
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        drift_point = drift_point if drift_point is not None else self._cfg.get("sudden", {}).get("drift_point", n_points // 2)
        magnitude = magnitude if magnitude is not None else self._cfg.get("sudden", {}).get("magnitude", 10.0)

        rng = np.random.default_rng(seed)
        dates, y = self._base(n_points, noise_std, start_date, freq, rng)
        y[drift_point:] += magnitude

        return _make_df(dates, y), {
            "drift_type": "sudden",
            "drift_point": drift_point,
            "magnitude": magnitude,
            "seed": seed,
        }

    def gradual_drift(
        self,
        seed: int = 42,
        n_points: int | None = None,
        drift_start: int | None = None,
        drift_end: int | None = None,
        magnitude: float | None = None,
        noise_std: float | None = None,
        start_date: str | None = None,
        freq: str | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Slow linear ramp from ``drift_start`` to ``drift_end``.

        The mean shifts smoothly from 0 to ``magnitude`` over the window
        ``[drift_start, drift_end)``, then stays at ``magnitude`` afterwards.
        """
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        cfg_g = self._cfg.get("gradual", {})
        drift_start = drift_start if drift_start is not None else cfg_g.get("drift_start", n_points // 4)
        drift_end = drift_end if drift_end is not None else cfg_g.get("drift_end", 3 * n_points // 4)
        magnitude = magnitude if magnitude is not None else cfg_g.get("magnitude", 8.0)

        rng = np.random.default_rng(seed)
        dates, y = self._base(n_points, noise_std, start_date, freq, rng)

        ramp_len = max(drift_end - drift_start, 1)
        for i in range(drift_start, min(drift_end, n_points)):
            y[i] += magnitude * (i - drift_start) / ramp_len
        y[drift_end:] += magnitude

        return _make_df(dates, y), {
            "drift_type": "gradual",
            "drift_start": drift_start,
            "drift_end": drift_end,
            "magnitude": magnitude,
            "seed": seed,
        }

    def incremental_drift(
        self,
        seed: int = 42,
        n_points: int | None = None,
        drift_start: int | None = None,
        slope: float | None = None,
        noise_std: float | None = None,
        start_date: str | None = None,
        freq: str | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Additional linear trend (slope) injected after ``drift_start``."""
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        cfg_i = self._cfg.get("incremental", {})
        drift_start = drift_start if drift_start is not None else cfg_i.get("drift_start", n_points // 4)
        slope = slope if slope is not None else cfg_i.get("slope", 0.05)

        rng = np.random.default_rng(seed)
        dates, y = self._base(n_points, noise_std, start_date, freq, rng)

        for i in range(drift_start, n_points):
            y[i] += slope * (i - drift_start)

        return _make_df(dates, y), {
            "drift_type": "incremental",
            "drift_start": drift_start,
            "slope": slope,
            "seed": seed,
        }

    def seasonal_drift(
        self,
        seed: int = 42,
        n_points: int | None = None,
        season_length: int | None = None,
        amplitude_before: float | None = None,
        amplitude_after: float | None = None,
        change_point: int | None = None,
        noise_std: float | None = None,
        start_date: str | None = None,
        freq: str | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Seasonal amplitude changes at ``change_point``.

        Pre-changepoint: sinusoidal component with ``amplitude_before``.
        Post-changepoint: sinusoidal component with ``amplitude_after``.
        """
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        cfg_s = self._cfg.get("seasonal", {})
        season_length = season_length if season_length is not None else cfg_s.get("season_length", 7)
        amplitude_before = amplitude_before if amplitude_before is not None else cfg_s.get("amplitude_before", 3.0)
        amplitude_after = amplitude_after if amplitude_after is not None else cfg_s.get("amplitude_after", 8.0)
        change_point = change_point if change_point is not None else cfg_s.get("change_point", n_points // 2)

        rng = np.random.default_rng(seed)
        dates, y = self._base(n_points, noise_std, start_date, freq, rng)

        t = np.arange(n_points, dtype=float)
        wave = np.sin(2 * np.pi * t / season_length)
        amplitude = np.where(t < change_point, amplitude_before, amplitude_after)
        y += amplitude * wave

        return _make_df(dates, y), {
            "drift_type": "seasonal",
            "season_length": season_length,
            "amplitude_before": amplitude_before,
            "amplitude_after": amplitude_after,
            "change_point": change_point,
            "seed": seed,
        }

    def recurring_drift(
        self,
        seed: int = 42,
        n_points: int | None = None,
        period: int | None = None,
        duration: int | None = None,
        magnitude: float | None = None,
        noise_std: float | None = None,
        start_date: str | None = None,
        freq: str | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Periodic drift windows: the mean shifts by ``magnitude`` for ``duration``
        steps every ``period`` steps.
        """
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        cfg_r = self._cfg.get("recurring", {})
        period = period if period is not None else cfg_r.get("period", 90)
        duration = duration if duration is not None else cfg_r.get("duration", 20)
        magnitude = magnitude if magnitude is not None else cfg_r.get("magnitude", 6.0)

        rng = np.random.default_rng(seed)
        dates, y = self._base(n_points, noise_std, start_date, freq, rng)

        drift_windows: list[tuple[int, int]] = []
        i = 0
        while i < n_points:
            end = min(i + duration, n_points)
            y[i:end] += magnitude
            drift_windows.append((i, end))
            i += period

        return _make_df(dates, y), {
            "drift_type": "recurring",
            "period": period,
            "duration": duration,
            "magnitude": magnitude,
            "drift_windows": drift_windows,
            "seed": seed,
        }

    def covariate_drift(
        self,
        seed: int = 42,
        n_points: int | None = None,
        n_covariates: int = 1,
        drift_point: int | None = None,
        covariate_magnitude: float | None = None,
        noise_std: float | None = None,
        start_date: str | None = None,
        freq: str | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Distribution shift in exogenous covariates at ``drift_point``.

        The target ``y`` is a linear function of the covariates; when the
        covariate distribution shifts, the target distribution shifts too.
        Columns ``x0``, ``x1``, … are added alongside ``ds`` and ``y``.
        """
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        cfg_c = self._cfg.get("covariate", {})
        drift_point = drift_point if drift_point is not None else cfg_c.get("drift_point", n_points // 2)
        covariate_magnitude = (
            covariate_magnitude if covariate_magnitude is not None
            else cfg_c.get("covariate_magnitude", 5.0)
        )

        rng = np.random.default_rng(seed)
        dates, y_base = self._base(n_points, noise_std, start_date, freq, rng)

        cov_cols: dict[str, np.ndarray] = {}
        for k in range(n_covariates):
            x = rng.standard_normal(n_points)
            x[drift_point:] += covariate_magnitude
            cov_cols[f"x{k}"] = x
            coef = rng.uniform(0.5, 1.5)
            y_base += coef * x

        df = _make_df(dates, y_base)
        for col, arr in cov_cols.items():
            df[col] = arr

        return df, {
            "drift_type": "covariate",
            "drift_point": drift_point,
            "n_covariates": n_covariates,
            "covariate_magnitude": covariate_magnitude,
            "seed": seed,
        }

    def concept_drift(
        self,
        seed: int = 42,
        n_points: int | None = None,
        change_point: int | None = None,
        coef_before: float | None = None,
        coef_after: float | None = None,
        noise_std: float | None = None,
        start_date: str | None = None,
        freq: str | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Change in the functional relationship between covariate ``x0`` and ``y``.

        Pre-changepoint:  y = coef_before * x0 + base + noise
        Post-changepoint: y = coef_after  * x0 + base + noise

        Column ``x0`` is retained in the returned DataFrame to enable the
        diagnostic tool to detect the relationship reversal.
        """
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        cfg_cd = self._cfg.get("concept", {})
        change_point = change_point if change_point is not None else cfg_cd.get("change_point", n_points // 2)
        coef_before = coef_before if coef_before is not None else cfg_cd.get("coef_before", 1.5)
        coef_after = coef_after if coef_after is not None else cfg_cd.get("coef_after", -1.5)

        rng = np.random.default_rng(seed)
        dates, y_base = self._base(n_points, noise_std, start_date, freq, rng)

        x0 = rng.standard_normal(n_points)
        coef = np.where(np.arange(n_points) < change_point, coef_before, coef_after)
        y = y_base + coef * x0

        df = _make_df(dates, y)
        df["x0"] = x0

        return df, {
            "drift_type": "concept",
            "change_point": change_point,
            "coef_before": coef_before,
            "coef_after": coef_after,
            "seed": seed,
        }
