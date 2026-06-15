"""Generate all drift series (SPEC §9–12), save CSVs, run Prophet, save forecast plots.

SPEC §13: Save generated graphs as CSV (full + train split at year-4 boundary).
SPEC §14: Save predicted-vs-actual plots for all series in pocs/prophet/.

Run from ANY directory:
    python3 pocs/generate_and_forecast.py

Outputs
-------
    pocs/data/<name>_full.csv      — complete 5-year series (ds, y)
    pocs/data/<name>_train.csv     — years 1–4 (for Prophet input / UI upload)
    pocs/prophet/<name>_forecast.png — Prophet yr-5 forecast vs actual
"""

from __future__ import annotations

import pathlib
import sys
import warnings

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore")

# ── Path bootstrap ────────────────────────────────────────────────────────
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from ailf.pipelines.drift.datasets import DriftGenerator  # noqa: E402

CONFIG    = _PROJECT_ROOT / "src" / "config" / "config.yml"
DATA_DIR  = pathlib.Path(__file__).parent / "data"
PROP_DIR  = pathlib.Path(__file__).parent / "prophet"
DATA_DIR.mkdir(exist_ok=True)
PROP_DIR.mkdir(exist_ok=True)

N_YEARS    = 5
N_POINTS   = N_YEARS * 365          # 1 825 daily steps
TRAIN_END  = 4 * 365                # year-5 starts at index 1460
START_DATE = "2020-01-01"
SEED       = 7
start_ts   = pd.Timestamp(START_DATE)
QUARTER_DAYS = 91

# ── Shared helpers ────────────────────────────────────────────────────────

def _qspecs(seed_offset: int) -> list[dict]:
    """Quarter-end 10-day recurrent burst specs."""
    rng_q = np.random.default_rng(SEED + seed_offset)
    specs: list[dict] = []
    for q in range(N_YEARS * 4):
        q_end   = min((q + 1) * QUARTER_DAYS, N_POINTS) - 1
        burst_s = max(q_end - 9, q * QUARTER_DAYS)
        if burst_s >= N_POINTS:
            break
        sign = -1.0 if rng_q.random() < 0.30 else 1.0
        mag  = sign * rng_q.uniform(5.0, 10.0)
        specs.append({"_burst_start": burst_s, "_sign": sign, "magnitude": abs(mag)})
    return specs


def _apply_bursts(y: np.ndarray, specs: list[dict]) -> None:
    for s in specs:
        bs = s["_burst_start"]
        y[bs:min(bs + 10, N_POINTS)] += s["magnitude"] * s["_sign"]


_HOLIDAY_DEFS = [
    (1,  1,  +1), (1, 15, -1), (2, 14, +1), (2, 20, -1),
    (5, 27,  +1), (6, 19, +1), (7,  4, +1), (9,  2, -1),
    (10, 14, -1), (11, 11, +1), (11, 28, +1), (12, 25, +1), (12, 26, -1),
]
_HOLIDAY_MAG = {+1: 12.0, -1: -10.0}
SEASONAL_PERIOD = 365.0


def _apply_holidays(y: np.ndarray, dates: pd.DatetimeIndex) -> None:
    for yr_off in range(N_YEARS):
        year = start_ts.year + yr_off
        for month, day, direction in _HOLIDAY_DEFS:
            try:
                ts = pd.Timestamp(year=year, month=month, day=day)
            except ValueError:
                continue
            idx = (ts - start_ts).days
            if idx < 0 or idx >= N_POINTS:
                continue
            end = min(idx + (2 if direction == +1 else 1), N_POINTS)
            y[idx:end] += _HOLIDAY_MAG[direction]


def _apply_seasonal_amplitude(y: np.ndarray, dates: pd.DatetimeIndex) -> None:
    """Boost amplitude summer/year-end; severe drop in winter alternate (even) years."""
    n = len(y)
    amp_env = np.zeros(n, dtype=float)
    for i, ts in enumerate(dates):
        m, yr = ts.month, ts.year
        if m in (6, 7, 8):
            amp_env[i] = 4.0
        elif m in (11, 12):
            amp_env[i] = 5.0
        elif m in (1, 2) and (yr % 2 == 0):
            amp_env[i] = -7.0
    t = np.arange(n, dtype=float)
    y += amp_env * np.sin(2 * np.pi * t / SEASONAL_PERIOD)


def _base_series(gen: DriftGenerator, extra_specs: list[dict], seed_offset: int) -> tuple[pd.DataFrame, list[dict]]:
    """Build base sine series with quarter-end bursts + extra drift specs."""
    qspecs = _qspecs(seed_offset)
    drift_input = extra_specs if extra_specs else [{"type": "sudden", "drift_point": 0, "magnitude": 0.0}]
    df, _ = gen.combined_drift(
        drift_specs=drift_input, seed=SEED, n_points=N_POINTS,
        noise_std=0.5, start_date=START_DATE, freq="D",
    )
    y = df["y"].to_numpy().copy()
    _apply_bursts(y, qspecs)
    return pd.DataFrame({"ds": df["ds"], "y": y}), qspecs


# ── Series generators ─────────────────────────────────────────────────────

def build_all_series() -> dict[str, pd.DataFrame]:
    """Generate all SPEC §9–12 series. Returns {name: DataFrame(ds, y)}."""
    gen = DriftGenerator(config_path=CONFIG, trend="sine")
    series: dict[str, pd.DataFrame] = {}

    # ── §9-i  Negative trend year-2 Q3 ──────────────────────────────────
    df, _ = _base_series(gen, [], seed_offset=1)
    y = df["y"].to_numpy().copy()
    dates = pd.DatetimeIndex(df["ds"])
    _apply_holidays(y, dates)
    _apply_seasonal_amplitude(y, dates)
    yr2_q3_s = (pd.Timestamp("2021-07-01") - start_ts).days
    yr2_q3_e = (pd.Timestamp("2021-09-30") - start_ts).days
    for k in range(yr2_q3_s, min(yr2_q3_e, N_POINTS)):
        y[k] += -0.18 * (k - yr2_q3_s)
    df["y"] = y
    series["sec9_i_neg_yr2q3"] = df

    # ── §9-ii  Escalating Q4-end up / Q1 down / gradual rise Q2-Q3 ─────────
    # SPEC §9-ii: last 5 days Q4 yr1, 10 days yr2, 15 yr3, 20 yr4, 25 yr5;
    # goes down in Q1 of next year, gradually rises Q2-Q3.
    q4q1: list[dict] = []
    for yr_off in range(N_YEARS):
        year = start_ts.year + yr_off
        # Q4 end burst: last (5 + yr_off*5) days of December
        q4_burst_days = 5 + yr_off * 5
        q4_end = (pd.Timestamp(f"{year}-12-31") - start_ts).days
        q4_burst_start = q4_end - q4_burst_days + 1
        if 0 <= q4_burst_start < N_POINTS:
            q4q1.append({
                "type": "sudden",
                "drift_point": max(q4_burst_start, 0),
                "magnitude": 15.0,
            })
        # Q1 down: Jan 1 of next year
        next_year = year + 1
        q1_next = (pd.Timestamp(f"{next_year}-01-01") - start_ts).days
        if 0 <= q1_next < N_POINTS:
            q4q1.append({"type": "sudden", "drift_point": q1_next, "magnitude": -12.0})
        # Q2-Q3 gradual rise
        q2 = (pd.Timestamp(f"{year}-04-01") - start_ts).days
        q3e = (pd.Timestamp(f"{year}-09-30") - start_ts).days
        if 0 <= q2 < N_POINTS:
            q4q1.append({"type": "gradual", "drift_start": q2,
                          "drift_end": min(q3e, N_POINTS), "magnitude": 8.0})
    df, _ = _base_series(gen, q4q1, seed_offset=2)
    y = df["y"].to_numpy().copy()
    dates = pd.DatetimeIndex(df["ds"])
    _apply_holidays(y, dates)
    _apply_seasonal_amplitude(y, dates)
    df["y"] = y
    series["sec9_ii_q4up_q1down"] = df

    # ── §9-iii  Persistent negative, Q2 upward only ──────────────────────
    q2specs: list[dict] = []
    for yr_off in range(N_YEARS):
        year = start_ts.year + yr_off
        q2 = (pd.Timestamp(f"{year}-04-01") - start_ts).days
        if 0 <= q2 < N_POINTS:
            q2specs.append({"type": "sudden", "drift_point": q2, "magnitude": 20.0})
    df, _ = _base_series(gen, q2specs, seed_offset=3)
    y = df["y"].to_numpy().copy()
    dates = pd.DatetimeIndex(df["ds"])
    y += -0.05 * np.arange(N_POINTS, dtype=float)
    for yr_off in range(N_YEARS):
        year = start_ts.year + yr_off
        for month, day, _ in _HOLIDAY_DEFS:
            try:
                ts = pd.Timestamp(year=year, month=month, day=day)
            except ValueError:
                continue
            idx = (ts - start_ts).days
            if 0 <= idx < N_POINTS:
                y[idx:min(idx + 2, N_POINTS)] += 10.0
    _apply_seasonal_amplitude(y, dates)
    df["y"] = y
    series["sec9_iii_neg_q2up"] = df

    # ── §10  Sine wave: seasonal amp drift year-3 Q2+Q3 only ─────────────
    gen10 = DriftGenerator(config_path=CONFIG, trend="sine")
    df, _ = _base_series(gen10, [], seed_offset=10)
    y = df["y"].to_numpy().copy()
    dates = pd.DatetimeIndex(df["ds"])
    yr3_q2_s = (pd.Timestamp("2022-04-01") - start_ts).days
    yr3_q2_e = (pd.Timestamp("2022-06-30") - start_ts).days
    yr3_q3_s = (pd.Timestamp("2022-07-01") - start_ts).days
    yr3_q3_e = (pd.Timestamp("2022-09-30") - start_ts).days
    amp_env10 = np.zeros(N_POINTS, dtype=float)
    for i in range(N_POINTS):
        if yr3_q2_s <= i <= yr3_q2_e:
            amp_env10[i] = 9.0
        elif yr3_q3_s <= i <= yr3_q3_e:
            amp_env10[i] = -7.0
    t10 = np.arange(N_POINTS, dtype=float)
    y += amp_env10 * np.sin(2 * np.pi * t10 / SEASONAL_PERIOD)
    df["y"] = y
    series["sec10_sine_yr3_seasonal"] = df

    # ── §11  Hard-to-predict configs (A, B, C) ───────────────────────────
    with CONFIG.open() as fh:
        full_cfg = yaml.safe_load(fh)

    # Config A: exponential + concept drift
    _cfgA = full_cfg["hard_config_a"]
    genA = DriftGenerator(config_path=CONFIG, trend=_cfgA["trend"])
    dfA, _ = genA.concept_drift(
        seed=_cfgA["seed"], n_points=_cfgA["n_points"],
        change_point=_cfgA["concept"]["change_point"],
        coef_before=_cfgA["concept"]["coef_before"],
        coef_after=_cfgA["concept"]["coef_after"],
        noise_std=_cfgA["noise_std"], start_date=_cfgA["start_date"], freq=_cfgA["freq"],
    )
    series["sec11_A_exponential_concept"] = dfA[["ds", "y"]].copy()

    # Config B: binary + covariate drift
    _cfgB = full_cfg["hard_config_b"]
    genB = DriftGenerator(config_path=CONFIG, trend=_cfgB["trend"])
    dfB, _ = genB.covariate_drift(
        seed=_cfgB["seed"], n_points=_cfgB["n_points"],
        drift_point=_cfgB["covariate"]["drift_point"],
        n_covariates=_cfgB["covariate"]["n_covariates"],
        covariate_magnitude=_cfgB["covariate"]["covariate_magnitude"],
        noise_std=_cfgB["noise_std"], start_date=_cfgB["start_date"], freq=_cfgB["freq"],
    )
    series["sec11_B_binary_covariate"] = dfB[["ds", "y"]].copy()

    # Config C: flat + sudden+gradual+recurring
    _cfgC = full_cfg["hard_config_c"]
    genC = DriftGenerator(config_path=CONFIG, trend=_cfgC["trend"])
    _specsC = [
        {"type": "sudden",    "drift_point":  _cfgC["sudden"]["drift_point"],
                               "magnitude":   _cfgC["sudden"]["magnitude"]},
        {"type": "gradual",   "drift_start":  _cfgC["gradual"]["drift_start"],
                               "drift_end":   _cfgC["gradual"]["drift_end"],
                               "magnitude":   _cfgC["gradual"]["magnitude"]},
        {"type": "recurring", "period":       _cfgC["recurring"]["period"],
                               "duration":    _cfgC["recurring"]["duration"],
                               "magnitude":   _cfgC["recurring"]["magnitude"]},
    ]
    dfC, _ = genC.combined_drift(
        drift_specs=_specsC, seed=_cfgC["seed"], n_points=_cfgC["n_points"],
        noise_std=_cfgC["noise_std"], start_date=_cfgC["start_date"], freq=_cfgC["freq"],
    )
    series["sec11_C_flat_combined"] = dfC[["ds", "y"]].copy()

    # ── §12  Sinusoidal: covariate + December seasonal + month-end + sudden ─
    import calendar as _cal
    gen12 = DriftGenerator(config_path=CONFIG, trend="sine")
    sudden12: list[dict] = []
    _sudden_sched = {
        0: [pd.Timestamp("2020-07-04")],
        1: [pd.Timestamp("2021-03-15"), pd.Timestamp("2021-09-01")],
        2: [pd.Timestamp("2022-06-01")],
        3: [pd.Timestamp("2023-02-14"), pd.Timestamp("2023-08-20")],
        4: [pd.Timestamp("2024-01-10"), pd.Timestamp("2024-05-01"), pd.Timestamp("2024-10-15")],
    }
    for yr_off, ts_list in _sudden_sched.items():
        for ts_s in ts_list:
            idx_s = (ts_s - start_ts).days
            if 0 <= idx_s < N_POINTS:
                sudden12.append({
                    "type": "sudden", "drift_point": idx_s,
                    "magnitude": 14.0 * (1 if yr_off % 2 == 0 else -1),
                })
    df12, _ = gen12.combined_drift(
        drift_specs=sudden12 if sudden12 else [{"type": "sudden", "drift_point": 0, "magnitude": 0.0}],
        seed=SEED, n_points=N_POINTS, noise_std=0.5, start_date=START_DATE, freq="D",
    )
    dates12 = pd.DatetimeIndex(df12["ds"])
    y12 = df12["y"].to_numpy().copy()

    # Covariate drift with taper
    rng12 = np.random.default_rng(SEED + 12)
    x_cov = rng12.standard_normal(N_POINTS)
    cov_s = (pd.Timestamp("2021-04-01") - start_ts).days
    cov_e = (pd.Timestamp("2021-09-30") - start_ts).days
    cov_r = (pd.Timestamp("2022-12-31") - start_ts).days
    x_cov[cov_s:cov_e + 1] += 8.0
    taper_len = max(cov_r - cov_e, 1)
    for i in range(cov_e + 1, min(cov_r + 1, N_POINTS)):
        x_cov[i] += 8.0 * (1.0 - (i - cov_e) / taper_len)
    y12 += 1.5 * x_cov

    # December seasonal drift
    t12 = np.arange(N_POINTS, dtype=float)
    amp_dec = np.array([6.0 if dates12[i].month == 12 else 0.0 for i in range(N_POINTS)])
    y12 += amp_dec * np.sin(2 * np.pi * t12 / SEASONAL_PERIOD)

    # Month-end recurrent bursts (last 5 days)
    for i, ts_d in enumerate(dates12):
        last_day = _cal.monthrange(ts_d.year, ts_d.month)[1]
        if ts_d.day >= last_day - 4:
            y12[i] += 5.0

    df12["y"] = y12
    series["sec12_covariate_seasonal"] = df12[["ds", "y"]].copy()

    return series


# ── CSV export ────────────────────────────────────────────────────────────

def save_csvs(series: dict[str, pd.DataFrame]) -> None:
    """Save full and train (years 1-4) CSVs to pocs/data/."""
    for name, df in series.items():
        full_path  = DATA_DIR / f"{name}_full.csv"
        train_path = DATA_DIR / f"{name}_train.csv"
        df["ds"] = pd.to_datetime(df["ds"])
        df.to_csv(full_path, index=False, date_format="%Y-%m-%d")

        # Train = first TRAIN_END rows (years 1-4)
        train_df = df.iloc[:TRAIN_END].copy()
        train_df.to_csv(train_path, index=False, date_format="%Y-%m-%d")

        print(f"  CSV saved: {full_path.name}  ({len(df)} rows)  "
              f"|  train: {train_path.name}  ({len(train_df)} rows)")


# ── Prophet forecast + plot ───────────────────────────────────────────────

def _prophet_forecast(train_df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    from prophet import Prophet
    m = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=True,
        changepoint_prior_scale=0.05,
    )
    m.fit(train_df[["ds", "y"]])
    future = m.make_future_dataframe(periods=horizon, freq="D")
    return m.predict(future)


def _plot_forecast(name: str, full_df: pd.DataFrame, forecast: pd.DataFrame) -> None:
    dates = pd.DatetimeIndex(full_df["ds"])
    y     = full_df["y"].to_numpy()

    actual_train = dates[:TRAIN_END]
    actual_yr5   = dates[TRAIN_END:]

    cutoff = dates[TRAIN_END - 1]
    fc_fut = forecast[pd.to_datetime(forecast["ds"]) > cutoff]

    fig, ax = plt.subplots(figsize=(20, 6))

    # Historical solid blue
    ax.plot(actual_train, y[:TRAIN_END], lw=0.8, color="steelblue", alpha=0.9,
            label="Historical actual (years 1–4)")

    # Actual year-5 solid green
    ax.plot(actual_yr5, y[TRAIN_END:], lw=1.0, color="seagreen", alpha=0.9,
            label="Actual year 5")

    # CI shaded (fill between — equivalent to Plotly tonexty)
    ax.fill_between(
        pd.to_datetime(fc_fut["ds"]),
        fc_fut["yhat_lower"],
        fc_fut["yhat_upper"],
        alpha=0.18, color="darkorange",
        label="Prophet 95% CI",
    )

    # Forecast dashed orange
    ax.plot(pd.to_datetime(fc_fut["ds"]), fc_fut["yhat"],
            lw=1.5, color="darkorange", ls="--", alpha=0.9,
            label="Prophet forecast (year 5)")

    # Boundary
    ax.axvline(pd.Timestamp("2024-01-01"), color="black", lw=1.2,
               label="Year-5 boundary")

    # Metrics
    n5 = min(len(y) - TRAIN_END, len(fc_fut))
    y5_act = y[TRAIN_END: TRAIN_END + n5]
    y5_prd = fc_fut["yhat"].to_numpy()[:n5]
    mae  = np.mean(np.abs(y5_act - y5_prd))
    rmse = np.sqrt(np.mean((y5_act - y5_prd) ** 2))

    ax.set_title(
        f"{name}  —  Prophet Year-5 Forecast vs Actual\n"
        f"MAE={mae:.2f}  RMSE={rmse:.2f}",
        fontsize=11,
    )
    ax.set_ylabel("y")
    ax.tick_params(axis="x", rotation=30, labelsize=8)
    ax.legend(loc="upper left", fontsize=7, ncol=3)
    fig.tight_layout()

    out = PROP_DIR / f"{name}_forecast.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {out.resolve()}")


def run_forecasts(series: dict[str, pd.DataFrame]) -> None:
    horizon = N_POINTS - TRAIN_END   # 365 days = year 5
    for name, df in series.items():
        print(f"\n[{name}] fitting Prophet on years 1–4…")
        df = df.copy()
        df["ds"] = pd.to_datetime(df["ds"])
        train_df = df.iloc[:TRAIN_END].copy()
        try:
            forecast = _prophet_forecast(train_df, horizon)
            _plot_forecast(name, df, forecast)
        except Exception as exc:
            print(f"  ✗ Error: {exc}")


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Generating all drift series (SPEC §9–12)…")
    series = build_all_series()
    print(f"\nGenerated {len(series)} series.")

    print("\n" + "=" * 60)
    print(f"Saving CSVs → {DATA_DIR}/")
    save_csvs(series)

    print("\n" + "=" * 60)
    print(f"Running Prophet forecasts → {PROP_DIR}/")
    run_forecasts(series)

    print("\n✓ Done.")
    print(f"  CSVs:     {DATA_DIR}/")
    print(f"  Forecasts:{PROP_DIR}/")


if __name__ == "__main__":
    main()
