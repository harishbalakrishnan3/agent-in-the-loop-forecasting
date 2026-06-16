"""Drift dataset generation.

Uses Darts (``darts.utils.timeseries_generation``) as the internal series-building
layer.  Every public method returns a Prophet-compatible ``(DataFrame, dict)`` pair:

* ``DataFrame`` columns: ``ds`` (datetime64) and ``y`` (float64), plus optional
  covariate columns ``x0``, ``x1``, … for covariate / concept drift.
* ``dict`` — ground-truth metadata: drift type(s), injected parameters, and the
  **exact timestamps** of each injection point (``ts_<key>`` entries) so that
  precision / recall evaluation tools can work without index arithmetic.

Design notes
------------
* Darts ``TimeSeries`` objects are created with deterministic seeds by seeding
  ``numpy`` before every generation call that uses random draws.  After the series
  is assembled the values are extracted as a plain numpy array via
  ``ts.values().flatten()`` before any drift injection — keeping drift logic simple
  and dependency-free.
* The ``trend`` runtime variable is intentionally mutable so that the FastAPI layer
  (``pipeline.py``) can update it at runtime without reloading config.
* Series shapes supported by the spec (item 6): ``linear``, ``sine``, ``binary``,
  ``exponential``, ``flat`` — controlled by the ``trend`` attribute.
* Multiple drifts can be stacked on the **same** base series via
  ``combined_drift()``, which applies each listed drift type sequentially to a
  shared (trend + seasonal + noise) series (spec items 6–8).
"""

from __future__ import annotations

import pathlib
from typing import Any, Literal

import numpy as np
import pandas as pd
import yaml
from darts import TimeSeries
from darts.utils.timeseries_generation import (
    constant_timeseries,
    gaussian_timeseries,
    linear_timeseries,
    sine_timeseries,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_TRENDS = {"flat", "linear", "exponential", "sine", "binary"}

# Drift types supported by combined_drift
_DRIFT_TYPES = frozenset(
    {"sudden", "gradual", "incremental", "seasonal", "recurring", "covariate", "concept"}
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_base_ts(
    n_points: int,
    trend: str,
    noise_std: float,
    start_date: str,
    freq: str,
    rng: np.random.Generator,
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Build a base series using Darts, return (timestamps, values array).

    Darts TimeSeries objects are used for the trend and seasonal components;
    gaussian noise is added via ``darts.utils.timeseries_generation.gaussian_timeseries``
    seeded through numpy before the call.
    """
    start = pd.Timestamp(start_date)

    if trend == "flat":
        trend_ts = constant_timeseries(value=0.0, length=n_points, start=start, freq=freq)
    elif trend == "linear":
        trend_ts = linear_timeseries(
            start_value=0.0,
            end_value=0.05 * (n_points - 1),
            length=n_points,
            start=start,
            freq=freq,
        )
    elif trend == "exponential":
        t = np.arange(n_points, dtype=float)
        exp_vals = np.exp(0.005 * t) - 1.0
        idx = pd.date_range(start=start_date, periods=n_points, freq=freq)
        trend_ts = TimeSeries.from_times_and_values(idx, exp_vals.reshape(-1, 1))
    elif trend == "sine":
        # Full-series sinusoid at weekly frequency
        trend_ts = sine_timeseries(
            value_frequency=1 / 7,
            value_amplitude=5.0,
            length=n_points,
            start=start,
            freq=freq,
        )
    elif trend == "binary":
        # Square wave: alternates between 0 and 1 every 14 steps
        t = np.arange(n_points, dtype=float)
        binary_vals = ((t // 14) % 2).astype(float) * 10.0
        idx = pd.date_range(start=start_date, periods=n_points, freq=freq)
        trend_ts = TimeSeries.from_times_and_values(idx, binary_vals.reshape(-1, 1))
    else:  # pragma: no cover — caught at init
        raise ValueError(f"Unknown trend '{trend}'")

    # Noise — seed numpy so the Darts gaussian call is deterministic
    seed_state = rng.integers(0, 2**31)
    np.random.seed(int(seed_state))
    noise_ts = gaussian_timeseries(
        mean=0.0,
        std=noise_std,
        length=n_points,
        start=start,
        freq=freq,
    )

    combined_ts = trend_ts + noise_ts
    timestamps: pd.DatetimeIndex = combined_ts.time_index
    values: np.ndarray = combined_ts.values().flatten().copy()
    return timestamps, values


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
        ``{"flat", "linear", "exponential", "sine", "binary"}``.

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
        self,
        n_points: int,
        noise_std: float,
        start_date: str,
        freq: str,
        rng: np.random.Generator,
    ) -> tuple[pd.DatetimeIndex, np.ndarray]:
        return _build_base_ts(n_points, self.trend, noise_std, start_date, freq, rng)

    @staticmethod
    def _ts(dates: pd.DatetimeIndex, idx: int) -> str:
        """Return ISO timestamp string for index ``idx`` within ``dates``."""
        return str(dates[idx].date())

    # ------------------------------------------------------------------
    # Public API — individual drift methods
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
            Ground-truth metadata including ``ts_drift_point`` (ISO date string).
        """
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        drift_point = (
            drift_point
            if drift_point is not None
            else min(self._cfg.get("sudden", {}).get("drift_point", n_points // 2), n_points - 1)
        )
        magnitude = (
            magnitude
            if magnitude is not None
            else self._cfg.get("sudden", {}).get("magnitude", 10.0)
        )

        rng = np.random.default_rng(seed)
        dates, y = self._base(n_points, noise_std, start_date, freq, rng)
        y[drift_point:] += magnitude

        return _make_df(dates, y), {
            "drift_type": "sudden",
            "drift_point": drift_point,
            "magnitude": magnitude,
            "seed": seed,
            "ts_drift_point": self._ts(dates, drift_point),
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
        """Slow linear ramp from ``drift_start`` to ``drift_end``."""
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        cfg_g = self._cfg.get("gradual", {})
        drift_start = (
            drift_start
            if drift_start is not None
            else min(cfg_g.get("drift_start", n_points // 4), n_points - 1)
        )
        drift_end = (
            drift_end
            if drift_end is not None
            else min(cfg_g.get("drift_end", 3 * n_points // 4), n_points)
        )
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
            "ts_drift_start": self._ts(dates, drift_start),
            "ts_drift_end": self._ts(dates, min(drift_end, n_points - 1)),
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
        drift_start = (
            drift_start
            if drift_start is not None
            else min(cfg_i.get("drift_start", n_points // 4), n_points - 1)
        )
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
            "ts_drift_start": self._ts(dates, drift_start),
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
        """Seasonal amplitude changes at ``change_point``."""
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        cfg_s = self._cfg.get("seasonal", {})
        season_length = (
            season_length if season_length is not None else cfg_s.get("season_length", 7)
        )
        amplitude_before = (
            amplitude_before
            if amplitude_before is not None
            else cfg_s.get("amplitude_before", 3.0)
        )
        amplitude_after = (
            amplitude_after
            if amplitude_after is not None
            else cfg_s.get("amplitude_after", 8.0)
        )
        change_point = (
            change_point
            if change_point is not None
            else min(cfg_s.get("change_point", n_points // 2), n_points - 1)
        )

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
            "ts_change_point": self._ts(dates, change_point),
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
        """Periodic drift windows: mean shifts by ``magnitude`` for ``duration`` steps
        every ``period`` steps.
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
        ts_windows: list[tuple[str, str]] = []
        i = 0
        while i < n_points:
            end = min(i + duration, n_points)
            y[i:end] += magnitude
            drift_windows.append((i, end))
            ts_windows.append((self._ts(dates, i), self._ts(dates, end - 1)))
            i += period

        return _make_df(dates, y), {
            "drift_type": "recurring",
            "period": period,
            "duration": duration,
            "magnitude": magnitude,
            "drift_windows": drift_windows,
            "ts_drift_windows": ts_windows,
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
        """Distribution shift in exogenous covariates at ``drift_point``."""
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        cfg_c = self._cfg.get("covariate", {})
        drift_point = (
            drift_point
            if drift_point is not None
            else min(cfg_c.get("drift_point", n_points // 2), n_points - 1)
        )
        covariate_magnitude = (
            covariate_magnitude
            if covariate_magnitude is not None
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
            "ts_drift_point": self._ts(dates, drift_point),
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
        """Change in the functional relationship between covariate ``x0`` and ``y``."""
        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]
        cfg_cd = self._cfg.get("concept", {})
        change_point = (
            change_point
            if change_point is not None
            else min(cfg_cd.get("change_point", n_points // 2), n_points - 1)
        )
        coef_before = (
            coef_before if coef_before is not None else cfg_cd.get("coef_before", 1.5)
        )
        coef_after = (
            coef_after if coef_after is not None else cfg_cd.get("coef_after", -1.5)
        )

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
            "ts_change_point": self._ts(dates, change_point),
        }

    # ------------------------------------------------------------------
    # combined_drift — spec items 6–8
    # ------------------------------------------------------------------

    def combined_drift(
        self,
        drift_specs: list[dict[str, Any]],
        seed: int = 42,
        n_points: int | None = None,
        noise_std: float | None = None,
        start_date: str | None = None,
        freq: str | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Stack two or more drift types on a **single shared base series**.

        Drift is injected by modifying the shared series in-place so effects
        accumulate (spec item 7).  Each drift spec dict must contain a ``type``
        key and optional per-drift keyword overrides (all except ``seed``,
        ``n_points``, ``noise_std``, ``start_date``, ``freq`` which are shared).

        Parameters
        ----------
        drift_specs:
            List of dicts, e.g.::

                [
                    {"type": "sudden", "drift_point": 100, "magnitude": 8.0},
                    {"type": "gradual", "drift_start": 200, "drift_end": 300},
                ]

        seed, n_points, noise_std, start_date, freq:
            Shared generation parameters (same meaning as individual methods).

        Returns
        -------
        df:
            Prophet-compatible DataFrame.  Covariate columns from covariate /
            concept drifts are included with a suffix to avoid collisions
            (``x0_covariate``, ``x0_concept``, …).
        meta:
            ``drift_type`` = ``"combined"``, ``components`` = list of per-drift
            metadata dicts (each includes ``ts_*`` timestamps), plus the full
            ``drift_specs`` list.
        """
        if not drift_specs:
            raise ValueError("drift_specs must contain at least one drift entry.")
        for spec in drift_specs:
            if "type" not in spec:
                raise ValueError(f"Each drift spec must have a 'type' key, got: {spec}")
            if spec["type"] not in _DRIFT_TYPES:
                raise ValueError(
                    f"Unknown drift type '{spec['type']}'. Must be one of {sorted(_DRIFT_TYPES)}."
                )

        d = self._defaults()
        n_points = n_points or d["n_points"]
        noise_std = noise_std if noise_std is not None else d["noise_std"]
        start_date = start_date or d["start_date"]
        freq = freq or d["freq"]

        # Build the single shared base
        rng = np.random.default_rng(seed)
        dates, y = self._base(n_points, noise_std, start_date, freq, rng)

        extra_cols: dict[str, np.ndarray] = {}
        components: list[dict[str, Any]] = []

        for spec in drift_specs:
            drift_type = spec["type"]
            # Pull per-spec overrides (exclude shared params)
            _shared = {"type", "seed", "n_points", "noise_std", "start_date", "freq"}
            overrides = {k: v for k, v in spec.items() if k not in _shared}

            if drift_type == "sudden":
                dp = min(overrides.get("drift_point", self._cfg.get("sudden", {}).get("drift_point", n_points // 2)), n_points - 1)
                mag = overrides.get("magnitude", self._cfg.get("sudden", {}).get("magnitude", 10.0))
                y[dp:] += mag
                components.append({
                    "drift_type": "sudden",
                    "drift_point": dp,
                    "magnitude": mag,
                    "ts_drift_point": self._ts(dates, dp),
                })

            elif drift_type == "gradual":
                cfg_g = self._cfg.get("gradual", {})
                ds = min(overrides.get("drift_start", cfg_g.get("drift_start", n_points // 4)), n_points - 1)
                de = min(overrides.get("drift_end", cfg_g.get("drift_end", 3 * n_points // 4)), n_points)
                mag = overrides.get("magnitude", cfg_g.get("magnitude", 8.0))
                ramp_len = max(de - ds, 1)
                for i in range(ds, min(de, n_points)):
                    y[i] += mag * (i - ds) / ramp_len
                y[de:] += mag
                components.append({
                    "drift_type": "gradual",
                    "drift_start": ds,
                    "drift_end": de,
                    "magnitude": mag,
                    "ts_drift_start": self._ts(dates, ds),
                    "ts_drift_end": self._ts(dates, min(de, n_points - 1)),
                })

            elif drift_type == "incremental":
                cfg_i = self._cfg.get("incremental", {})
                ds = min(overrides.get("drift_start", cfg_i.get("drift_start", n_points // 4)), n_points - 1)
                slope = overrides.get("slope", cfg_i.get("slope", 0.05))
                for i in range(ds, n_points):
                    y[i] += slope * (i - ds)
                components.append({
                    "drift_type": "incremental",
                    "drift_start": ds,
                    "slope": slope,
                    "ts_drift_start": self._ts(dates, ds),
                })

            elif drift_type == "seasonal":
                cfg_s = self._cfg.get("seasonal", {})
                sl = overrides.get("season_length", cfg_s.get("season_length", 7))
                ab = overrides.get("amplitude_before", cfg_s.get("amplitude_before", 3.0))
                aa = overrides.get("amplitude_after", cfg_s.get("amplitude_after", 8.0))
                cp = min(overrides.get("change_point", cfg_s.get("change_point", n_points // 2)), n_points - 1)
                t_arr = np.arange(n_points, dtype=float)
                wave = np.sin(2 * np.pi * t_arr / sl)
                amp = np.where(t_arr < cp, ab, aa)
                y += amp * wave
                components.append({
                    "drift_type": "seasonal",
                    "season_length": sl,
                    "amplitude_before": ab,
                    "amplitude_after": aa,
                    "change_point": cp,
                    "ts_change_point": self._ts(dates, cp),
                })

            elif drift_type == "recurring":
                cfg_r = self._cfg.get("recurring", {})
                period = overrides.get("period", cfg_r.get("period", 90))
                duration = overrides.get("duration", cfg_r.get("duration", 20))
                mag = overrides.get("magnitude", cfg_r.get("magnitude", 6.0))
                windows: list[tuple[int, int]] = []
                ts_windows: list[tuple[str, str]] = []
                i = 0
                while i < n_points:
                    end = min(i + duration, n_points)
                    y[i:end] += mag
                    windows.append((i, end))
                    ts_windows.append((self._ts(dates, i), self._ts(dates, end - 1)))
                    i += period
                components.append({
                    "drift_type": "recurring",
                    "period": period,
                    "duration": duration,
                    "magnitude": mag,
                    "drift_windows": windows,
                    "ts_drift_windows": ts_windows,
                })

            elif drift_type == "covariate":
                cfg_c = self._cfg.get("covariate", {})
                dp = min(overrides.get("drift_point", cfg_c.get("drift_point", n_points // 2)), n_points - 1)
                cov_mag = overrides.get("covariate_magnitude", cfg_c.get("covariate_magnitude", 5.0))
                n_cov = overrides.get("n_covariates", 1)
                for k in range(n_cov):
                    x = rng.standard_normal(n_points)
                    x[dp:] += cov_mag
                    coef = rng.uniform(0.5, 1.5)
                    y += coef * x
                    col_name = f"x{k}_covariate"
                    extra_cols[col_name] = x
                components.append({
                    "drift_type": "covariate",
                    "drift_point": dp,
                    "n_covariates": n_cov,
                    "covariate_magnitude": cov_mag,
                    "ts_drift_point": self._ts(dates, dp),
                })

            elif drift_type == "concept":
                cfg_cd = self._cfg.get("concept", {})
                cp = min(overrides.get("change_point", cfg_cd.get("change_point", n_points // 2)), n_points - 1)
                cb = overrides.get("coef_before", cfg_cd.get("coef_before", 1.5))
                ca = overrides.get("coef_after", cfg_cd.get("coef_after", -1.5))
                x0 = rng.standard_normal(n_points)
                coef = np.where(np.arange(n_points) < cp, cb, ca)
                y += coef * x0
                extra_cols["x0_concept"] = x0
                components.append({
                    "drift_type": "concept",
                    "change_point": cp,
                    "coef_before": cb,
                    "coef_after": ca,
                    "ts_change_point": self._ts(dates, cp),
                })

        df = _make_df(dates, y)
        for col, arr in extra_cols.items():
            df[col] = arr

        return df, {
            "drift_type": "combined",
            "components": components,
            "drift_specs": drift_specs,
            "seed": seed,
            "n_components": len(drift_specs),
        }
