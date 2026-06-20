"""PELT-based seasonality changepoint detection for the changepoint POC.

Wraps ruptures.Pelt(model="rbf") into a single clean function.
The key tunable is `pen` — see the POC TUNING RESULTS block below once
the POC has been run.

Requires: ruptures  (not in pyproject.toml by default — add via uv add ruptures)

C1 decision (plan.md): try raw series values first. If test_working_pen_exists
fails for all pen values in PENS, switch to the rolling-std fallback:
    signal = (
        pd.Series(series.values().ravel())
        .rolling(window=min_size, center=False)
        .std()
        .dropna()
        .to_numpy()
    )
Note: rolling-std lags the true break by up to `min_size` points, so
detected breaks land in [k, k+min_size] rather than symmetrically around k.
The ±period tolerance in the tests covers this, but a "late" detection is
still a correct detection — do not misread it as a miss.

POC TUNING RESULTS (fill in after running test_seasonal.py)
-----------------------------------------------------------
# Signal used:    raw values / rolling-std feature
# Penalty sweep:  {pen: (planted_found, control_clean), ...}
# Working range:  [lo, hi]
# Default pen:    <midpoint of working range>
# min_size=30     (one full seasonal period) — prevents within-cycle
#                 false positives on period-30 data (plan.md C2)
"""

from __future__ import annotations

from darts import TimeSeries


def detect_seasonality_change(
    series: TimeSeries,
    pen: float = 3.0,
    min_size: int = 30,     # ≈ one seasonal period (plan.md C2)
) -> list[int]:
    """Detect abrupt seasonality amplitude changes using PELT (rbf cost).

    Parameters
    ----------
    series:
        Univariate :class:`darts.TimeSeries` to analyse.
    pen:
        PELT penalty value. The **key tunable** for precision vs recall:
        - Too low  → false positives (breaks found in noise/within-season variance)
        - Too high → misses real breaks
        Use the penalty sweep in ``test_seasonal.py`` to find the working range.
        Default ``3.0`` is a starting hypothesis; update after running the POC.
    min_size:
        Minimum segment length enforced by PELT. Default = 30 (one seasonal
        period for daily data) so the algorithm cannot carve within-cycle
        segments and manufacture spurious breaks.

    Returns
    -------
    list[int]
        0-based indices of detected changepoints, excluding the mandatory
        final-index that ruptures always appends. Empty list = no breaks found.
    """
    try:
        import ruptures as rpt
    except ImportError as exc:
        raise ImportError(
            "ruptures is required for detect_seasonality_change(). "
            "Install it via: uv add ruptures  (use Walmart Artifactory index if on VPN)."
        ) from exc

    signal = series.values().ravel()

    algo = rpt.Pelt(model="rbf", min_size=min_size, jump=1)
    algo.fit(signal)
    raw = algo.predict(pen=pen)

    # ruptures always appends len(signal) as the final "break" — drop it.
    return raw[:-1]
