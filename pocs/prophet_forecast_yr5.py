"""Prophet year-5 forecast vs actual.

Trains Prophet on years 1–4 of each generated drift series, forecasts
year 5, and overlays the prediction against the actual year-5 data.

Run from ANY directory:
    python3 pocs/prophet_forecast_yr5.py

Produces (per series):
    pocs/<series_name>_prophet_yr5.png
        - Historical (years 1-4): solid blue line
        - Prophet forecast (year 5): dashed orange line
        - 95% CI: shaded band (fill='tonexty' equivalent)
        - Actual year 5: solid green line
        - Drift changepoint markers for reference
"""

from __future__ import annotations

import pathlib
import sys
import warnings

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Project path bootstrap ────────────────────────────────────────────────
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from ailf.pipelines.drift.datasets import DriftGenerator  # noqa: E402

CONFIG = _PROJECT_ROOT / "src" / "config" / "config.yml"
OUT_DIR = pathlib.Path(__file__).parent

N_YEARS = 5
N_POINTS = N_YEARS * 365          # 1 825 daily steps
START_DATE = "2020-01-01"
SEED = 7

# Year-5 starts at index 4*365 = 1460
TRAIN_END_IDX = 4 * 365            # exclusive — days 0…1459
# Year-5 actual: indices 1460…1824

start_ts = pd.Timestamp(START_DATE)


# ── Re-generate the same 5-year series as visualize_drift.py ─────────────

def _build_series() -> dict[str, tuple[pd.DataFrame, list[int]]]:
    """Returns {name: (full_df, ground_truth_changepoint_indices)}."""
    gen = DriftGenerator(config_path=CONFIG, trend="sine")
    QUARTER_DAYS = 91

    def _qspecs(seed_offset: int) -> list[dict]:
        rng_q = np.random.default_rng(SEED + seed_offset)
        specs = []
        for q in range(N_YEARS * 4):
            q_end = min((q + 1) * QUARTER_DAYS, N_POINTS) - 1
            burst_s = max(q_end - 9, q * QUARTER_DAYS)
            if burst_s >= N_POINTS:
                break
            sign = -1.0 if rng_q.random() < 0.30 else 1.0
            mag = sign * rng_q.uniform(5.0, 10.0)
            specs.append({
                "type": "recurring", "period": N_POINTS + 1,
                "duration": 10, "magnitude": abs(mag),
                "_sign": sign, "_burst_start": burst_s,
            })
        return specs

    def _burst(y: np.ndarray, specs: list[dict]) -> list[int]:
        idxs = []
        for s in specs:
            bs, sign, mag = s["_burst_start"], s["_sign"], s["magnitude"]
            y[bs:min(bs + 10, N_POINTS)] += mag * sign
            idxs.append(bs)
        return idxs

    def _base(seed_offset: int, extra_specs: list[dict] | None = None) -> tuple[pd.DataFrame, list[dict], list[int]]:
        qspecs = _qspecs(seed_offset)
        drift_specs = extra_specs or [{"type": "sudden", "drift_point": 0, "magnitude": 0.0}]
        df, _ = gen.combined_drift(
            drift_specs=drift_specs, seed=SEED,
            n_points=N_POINTS, noise_std=0.5,
            start_date=START_DATE, freq="D",
        )
        y = df["y"].to_numpy().copy()
        cp_idxs = _burst(y, qspecs)
        return pd.DataFrame({"ds": df["ds"], "y": y}), qspecs, cp_idxs

    # ── Graph i — negative trend in year-2 Q3 ──────────────────────────────
    df_i, qspecs_i, cps_i = _base(1)
    yr2_q3_s = (pd.Timestamp("2021-07-01") - start_ts).days
    yr2_q3_e = (pd.Timestamp("2021-09-30") - start_ts).days
    y_i = df_i["y"].to_numpy().copy()
    for k in range(yr2_q3_s, min(yr2_q3_e, N_POINTS)):
        y_i[k] += -0.18 * (k - yr2_q3_s)
    df_i["y"] = y_i
    cps_i.append(yr2_q3_s)

    # ── Graph ii — Q4 up / Q1 down / gradual rise Q2-Q3 ────────────────────
    q4q1: list[dict] = []
    q4q1_cps: list[int] = []
    for yr_off in range(N_YEARS):
        year = start_ts.year + yr_off
        q4_idx = (pd.Timestamp(f"{year}-10-01") - start_ts).days
        q1_idx = (pd.Timestamp(f"{year}-01-01") - start_ts).days
        q2_idx = (pd.Timestamp(f"{year}-04-01") - start_ts).days
        q3_end = (pd.Timestamp(f"{year}-09-30") - start_ts).days
        if 0 <= q4_idx < N_POINTS:
            q4q1.append({"type": "sudden", "drift_point": q4_idx, "magnitude": 15.0})
            q4q1_cps.append(q4_idx)
        if 0 <= q1_idx < N_POINTS:
            q4q1.append({"type": "sudden", "drift_point": q1_idx, "magnitude": -12.0})
            q4q1_cps.append(q1_idx)
        if 0 <= q2_idx < N_POINTS:
            q4q1.append({"type": "gradual", "drift_start": q2_idx,
                          "drift_end": min(q3_end, N_POINTS), "magnitude": 8.0})
    df_ii, _, cps_ii = _base(2, extra_specs=q4q1)
    cps_ii += q4q1_cps

    # ── Graph iii — persistent negative, Q2 upward only ────────────────────
    q2specs: list[dict] = []
    q2_cps: list[int] = []
    for yr_off in range(N_YEARS):
        year = start_ts.year + yr_off
        q2_idx = (pd.Timestamp(f"{year}-04-01") - start_ts).days
        if 0 <= q2_idx < N_POINTS:
            q2specs.append({"type": "sudden", "drift_point": q2_idx, "magnitude": 20.0})
            q2_cps.append(q2_idx)
    df_iii, _, cps_iii = _base(3, extra_specs=q2specs)
    y_iii = df_iii["y"].to_numpy().copy()
    y_iii += -0.05 * np.arange(N_POINTS, dtype=float)
    df_iii["y"] = y_iii
    cps_iii += q2_cps

    return {
        "graph_i_neg_yr2q3":    (df_i, sorted(set(cps_i))),
        "graph_ii_q4up_q1down": (df_ii, sorted(set(cps_ii))),
        "graph_iii_neg_q2up":   (df_iii, sorted(set(cps_iii))),
    }


# ── Prophet fit + forecast ────────────────────────────────────────────────

def _prophet_forecast(train_df: pd.DataFrame, horizon: int, freq: str = "D") -> pd.DataFrame:
    """Fit Prophet on ``train_df`` and return a forecast DataFrame."""
    from prophet import Prophet  # lazy import

    model = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=True,
        changepoint_prior_scale=0.05,   # conservative — avoids overfitting
    )
    model.fit(train_df[["ds", "y"]])
    future = model.make_future_dataframe(periods=horizon, freq=freq)
    return model.predict(future)


# ── Plot ─────────────────────────────────────────────────────────────────

def _plot(
    name: str,
    full_df: pd.DataFrame,
    forecast: pd.DataFrame,
    changepoints: list[int],
) -> None:
    dates = pd.DatetimeIndex(full_df["ds"])
    y = full_df["y"].to_numpy()
    cutoff = dates[TRAIN_END_IDX - 1]

    # Split forecast into history-fit and future
    fc_hist = forecast[forecast["ds"] <= cutoff]
    fc_fut  = forecast[forecast["ds"] >  cutoff]

    fig, ax = plt.subplots(figsize=(20, 6))

    # Historical actual (years 1-4) — solid blue
    ax.plot(dates[:TRAIN_END_IDX], y[:TRAIN_END_IDX],
            lw=0.8, color="steelblue", alpha=0.9, label="Historical actual (years 1–4)")

    # Actual year-5 — solid green
    ax.plot(dates[TRAIN_END_IDX:], y[TRAIN_END_IDX:],
            lw=1.0, color="seagreen", alpha=0.9, label="Actual year 5")

    # CI band for future — fill between upper/lower
    ax.fill_between(
        fc_fut["ds"],
        fc_fut["yhat_lower"],
        fc_fut["yhat_upper"],
        alpha=0.18, color="darkorange",
        label="Prophet 95% CI (year-5 forecast)",
    )

    # Prophet forecast year-5 — dashed orange
    ax.plot(fc_fut["ds"], fc_fut["yhat"],
            lw=1.5, color="darkorange", ls="--", alpha=0.9,
            label="Prophet forecast (year 5)")

    # Prophet in-sample fit — thin dotted for reference
    ax.plot(fc_hist["ds"], fc_hist["yhat"],
            lw=0.6, color="gray", ls=":", alpha=0.5,
            label="Prophet in-sample fit")

    # Year-5 boundary
    ax.axvline(pd.Timestamp("2024-01-01"), color="black", lw=1.2, ls="-",
               label="Year 5 start (forecast boundary)")

    # Drift changepoints — red dotted verticals
    for cp_idx in changepoints:
        if cp_idx < len(dates):
            ax.axvline(dates[cp_idx], color="red", lw=0.5, ls=":", alpha=0.4)

    # Metrics in title
    y5_actual = y[TRAIN_END_IDX:]
    y5_pred   = fc_fut["yhat"].to_numpy()
    min_len   = min(len(y5_actual), len(y5_pred))
    mae = np.mean(np.abs(y5_actual[:min_len] - y5_pred[:min_len]))
    rmse = np.sqrt(np.mean((y5_actual[:min_len] - y5_pred[:min_len]) ** 2))

    ax.set_title(
        f"{name}  —  Prophet Year-5 Forecast vs Actual\n"
        f"MAE={mae:.2f}  RMSE={rmse:.2f}  "
        f"(red dots = ground-truth drift changepoints)",
        fontsize=11,
    )
    ax.set_ylabel("y")
    ax.tick_params(axis="x", rotation=30, labelsize=8)

    legend_handles = [
        plt.Line2D([0], [0], color="steelblue",  lw=1.5, label="Historical actual (years 1–4)"),
        plt.Line2D([0], [0], color="seagreen",   lw=1.5, label="Actual year 5"),
        plt.Line2D([0], [0], color="darkorange", lw=1.5, ls="--", label="Prophet forecast (year 5)"),
        mpatches.Patch(color="darkorange", alpha=0.3, label="95% CI"),
        plt.Line2D([0], [0], color="gray",  lw=0.8, ls=":", label="Prophet in-sample fit"),
        plt.Line2D([0], [0], color="black", lw=1.2, label="Year-5 boundary"),
        plt.Line2D([0], [0], color="red",   lw=0.8, ls=":", alpha=0.6, label="Drift changepoints"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", fontsize=7, ncol=4)
    fig.tight_layout()

    out = OUT_DIR / f"{name}_prophet_yr5.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {out.resolve()}")


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    print("Generating 5-year series…")
    series_map = _build_series()

    for name, (full_df, changepoints) in series_map.items():
        print(f"\n[{name}] fitting Prophet on years 1–4 ({TRAIN_END_IDX} pts)…")
        train_df = full_df.iloc[:TRAIN_END_IDX].copy()
        horizon  = N_POINTS - TRAIN_END_IDX   # year-5 days = 365

        try:
            forecast = _prophet_forecast(train_df, horizon=horizon)
            _plot(name, full_df, forecast, changepoints)
        except Exception as exc:
            print(f"  ✗ Error: {exc}")

    print("\nDone.")


if __name__ == "__main__":
    main()
