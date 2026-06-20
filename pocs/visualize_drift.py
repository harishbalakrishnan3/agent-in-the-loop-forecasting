"""Drift visualisation helper.

Run from ANY directory:
    python pocs/visualize_drift.py
    # or from project root:
    python3 -c "exec(open('pocs/visualize_drift.py').read())"

Produces:
  - An interactive matplotlib window with all 8 drift types (7 individual + 1 combined).
  - A second figure: 5-year sinusoidal series (SPEC item 9) — three sub-graphs:
      i.  Negative trend in year-2 Q3; otherwise default sinusoidal.
      ii. Rises every year Q4, drops Q1 next year, then gradually rises again.
      iii.Persistent negative trend with upward-only spikes in Q2 each year.
  - drift_overview.png   — 4×2 individual+combined grid
  - drift_5yr.png        — 5-year three-panel composite series
"""

from __future__ import annotations

import pathlib
import sys

# Ensure `src` is on the path when running as a plain script
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from ailf.pipelines.drift.datasets import DriftGenerator

# Config is resolved relative to this file — works regardless of cwd
CONFIG = _PROJECT_ROOT / "src" / "config" / "config.yml"
gen = DriftGenerator(config_path=CONFIG)

# ---------------------------------------------------------------------------
# (label, callable, kwargs) for every drift type
# ---------------------------------------------------------------------------

individual_calls: list[tuple[str, object, dict]] = [
    ("sudden",      gen.sudden_drift,      {}),
    ("gradual",     gen.gradual_drift,     {}),
    ("incremental", gen.incremental_drift, {}),
    ("seasonal",    gen.seasonal_drift,    {}),
    ("recurring",   gen.recurring_drift,   {}),
    ("covariate",   gen.covariate_drift,   {}),
    ("concept",     gen.concept_drift,     {}),
]

# combined: sudden + gradual stacked on the same base
combined_specs = [
    {"type": "sudden",  "drift_point": 120, "magnitude": 8.0},
    {"type": "gradual", "drift_start": 200, "drift_end": 300, "magnitude": 5.0},
]

# ---------------------------------------------------------------------------
# Figure 1 — 4×2 grid: 7 individual + 1 combined (8 total, fills grid exactly)
# ---------------------------------------------------------------------------

fig, axes = plt.subplots(4, 2, figsize=(14, 16))
axes = axes.flatten()

for ax, (name, fn, kwargs) in zip(axes, individual_calls):
    df, meta = fn(seed=42, n_points=365, **kwargs)
    ax.plot(df["ds"], df["y"], lw=0.7, color="steelblue")

    # Mark drift location where metadata carries it
    for key in ("drift_point", "drift_start", "change_point"):
        if key in meta:
            ax.axvline(
                df["ds"].iloc[meta[key]],
                color="red", ls="--", lw=1,
                label=f"{key}={meta[key]}",
            )
            break

    # Shade recurring windows
    if "drift_windows" in meta:
        for start, end in meta["drift_windows"]:
            ax.axvspan(
                df["ds"].iloc[start],
                df["ds"].iloc[min(end, len(df) - 1)],
                alpha=0.15, color="orange",
            )

    ax.set_title(name, fontsize=11)
    ax.tick_params(axis="x", rotation=30, labelsize=7)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(fontsize=7)

# 8th subplot — combined drift
ax_combined = axes[7]
df_c, meta_c = gen.combined_drift(drift_specs=combined_specs, seed=42, n_points=365)
ax_combined.plot(df_c["ds"], df_c["y"], lw=0.7, color="darkorchid")
# Mark each component's injection timestamp
colors = ["red", "orange", "green", "brown"]
for comp, color in zip(meta_c["components"], colors):
    for key in ("drift_point", "drift_start", "change_point"):
        if key in comp:
            ax_combined.axvline(
                df_c["ds"].iloc[comp[key]],
                color=color, ls="--", lw=1,
                label=f"{comp['drift_type']}:{key}={comp[key]}",
            )
            break
ax_combined.set_title("combined (sudden+gradual)", fontsize=11)
ax_combined.tick_params(axis="x", rotation=30, labelsize=7)
ax_combined.legend(fontsize=7)

fig.suptitle(
    f"Drift Types — DriftGenerator  (trend={gen.trend})",
    fontsize=13, y=1.01,
)
plt.tight_layout()

out1 = pathlib.Path(__file__).parent / "drift_overview.png"
fig.savefig(out1, dpi=120, bbox_inches="tight")
print(f"Saved → {out1.resolve()}")

# ---------------------------------------------------------------------------
# Figure 2 — SPEC item 9: 5-year sinusoidal series, three sub-graphs
#
# Shared base characteristics (all three graphs):
#   • Sinusoidal base trend (trend="sine"), 5 years daily (≈1825 pts)
#   • ≥10 sudden drifts/year: 1–2 day holiday spikes, ±direction
#   • Recurrent drifts at every quarter-end (10-day burst windows)
#   • Low noise (σ=0.5) — reduced for naked-eye changepoint visibility
#   • Seasonal amplitude drifts:
#       - INCREASE during year-end (Nov–Dec) and summer (Jun–Aug)
#       - DROPS (negative severely) during winter in alternate (even) years (Jan–Feb)
#
# Per-graph trend modifiers:
#   i.  Negative incremental drift injected in year-2 Q3 (Jul–Sep of year 2)
#   ii. Strong positive sudden drift every Q4; negative drift every Q1;
#       gradual upward ramp throughout each year after Q1
#   iii.Persistent negative linear slope on top; positive sudden spikes only in Q2
#
# Implementation notes:
#   • DriftGenerator(trend="sine") builds the sinusoidal base via combined_drift.
#   • Holiday drifts and seasonal amplitude modulation are applied post-hoc
#     because the built-in seasonal branch supports only one change-point.
#   • Quarter-end recurrent drifts replace the previous incremental-per-quarter
#     approach: each quarter's last 10 days carry a recurring magnitude burst.
#   • Per-graph trend modifiers are layered on top of the shared base copy.
# ---------------------------------------------------------------------------

N_YEARS = 5
N_POINTS = N_YEARS * 365          # 1 825 daily steps
START_DATE = "2020-01-01"
SEED = 7

gen_sine = DriftGenerator(config_path=CONFIG, trend="sine")

# ── Shared holiday definitions (13 per year → ≥10 per year ±) ──────────────
_HOLIDAY_DEFS = [
    # (month, day, direction)
    (1,  1,  +1),   # New Year's Day
    (1, 15,  -1),   # MLK Day
    (2, 14,  +1),   # Valentine's Day
    (2, 20,  -1),   # Presidents' Day
    (5, 27,  +1),   # Memorial Day
    (6, 19,  +1),   # Juneteenth
    (7,  4,  +1),   # Independence Day
    (9,  2,  -1),   # Labor Day
    (10, 14, -1),   # Columbus Day
    (11, 11, +1),   # Veterans Day
    (11, 28, +1),   # Thanksgiving
    (12, 25, +1),   # Christmas
    (12, 26, -1),   # Day-after Christmas lull
]
_HOLIDAY_MAG = {+1: 12.0, -1: -10.0}

QUARTER_DAYS = 91
N_QUARTERS = N_YEARS * 4
SEASONAL_PERIOD = 365.0

start_ts = pd.Timestamp(START_DATE)


def _build_quarterly_specs(n_points: int, seed_offset: int = 0) -> list[dict]:
    """Recurrent drift burst at the end of each quarter (last 10 days).

    ~30% of quarters get a negative magnitude burst; the rest are positive.
    Uses the ``recurring`` drift type so that effects are clearly visible as
    discrete amplitude pulses at quarter-end rather than a running slope.
    """
    rng_q = np.random.default_rng(SEED + seed_offset)
    specs: list[dict] = []
    BURST_DURATION = 10   # last N days of each quarter carry the drift pulse
    for q in range(N_QUARTERS):
        q_end = min((q + 1) * QUARTER_DAYS, n_points) - 1  # last day of quarter
        burst_start = max(q_end - BURST_DURATION + 1, q * QUARTER_DAYS)
        if burst_start >= n_points:
            break
        sign = -1.0 if rng_q.random() < 0.30 else 1.0
        mag = sign * rng_q.uniform(5.0, 10.0)
        # recurring with period > n_points fires exactly once (at burst_start)
        specs.append({
            "type": "recurring",
            "drift_start": burst_start,   # injected via period trick below
            "period": n_points + 1,       # sentinel: won't repeat
            "_magnitude": mag,            # kept for legend colouring
        })
        # DriftGenerator.combined_drift doesn't accept arbitrary keys —
        # pass only recognised recurring keys.
        specs[-1] = {
            "type": "recurring",
            "period": n_points + 1,
            "duration": BURST_DURATION,
            "magnitude": abs(mag),
            "_sign": sign,
            "_burst_start": burst_start,
        }
    return specs


def _apply_quarter_bursts(y: np.ndarray, specs: list[dict], n_points: int) -> None:
    """Apply quarter-end burst magnitudes directly (handles sign correctly)."""
    BURST_DURATION = 10
    for spec in specs:
        bs = spec["_burst_start"]
        sign = spec["_sign"]
        mag = spec["magnitude"] * sign
        end = min(bs + BURST_DURATION, n_points)
        y[bs:end] += mag


def _apply_holidays(y: np.ndarray, dates: pd.DatetimeIndex) -> None:
    """Inject holiday sudden drifts in-place."""
    for yr_off in range(N_YEARS):
        year = start_ts.year + yr_off
        for month, day, direction in _HOLIDAY_DEFS:
            try:
                ts = pd.Timestamp(year=year, month=month, day=day)
            except ValueError:
                continue
            idx = (ts - start_ts).days
            if idx < 0 or idx >= len(y):
                continue
            mag = _HOLIDAY_MAG[direction]
            end_idx = min(idx + (2 if direction == +1 else 1), len(y))
            y[idx:end_idx] += mag


def _apply_seasonal_amplitude(y: np.ndarray, dates: pd.DatetimeIndex) -> None:
    """Boost amplitude in summer/year-end; drop severely in winter (alternate even years)."""
    n = len(y)
    amp_env = np.zeros(n, dtype=float)
    for i, ts in enumerate(dates):
        m, yr = ts.month, ts.year
        if m in (6, 7, 8):
            amp_env[i] = 4.0
        elif m in (11, 12):
            amp_env[i] = 5.0
        elif m in (1, 2) and (yr % 2 == 0):   # alternate = even years
            amp_env[i] = -7.0                  # severe negative drop
    t_arr = np.arange(n, dtype=float)
    y += amp_env * np.sin(2 * np.pi * t_arr / SEASONAL_PERIOD)


def _shade_seasons(ax: plt.Axes, dates: pd.DatetimeIndex) -> None:
    """Shade summer/year-end/winter regions on ax."""
    flags = {"summer": False, "yearend": False, "winter": False}
    starts: dict[str, pd.Timestamp | None] = {"summer": None, "yearend": None, "winter": None}
    colors = {"summer": "gold", "yearend": "tomato", "winter": "cornflowerblue"}
    alphas = {"summer": 0.08, "yearend": 0.10, "winter": 0.12}

    def _close(key: str, end_ts: pd.Timestamp) -> None:
        ax.axvspan(starts[key], end_ts, alpha=alphas[key], color=colors[key])
        flags[key] = False

    for i, ts in enumerate(dates):
        m, yr = ts.month, ts.year
        now = {
            "summer":  m in (6, 7, 8),
            "yearend": m in (11, 12),
            "winter":  m in (1, 2) and (yr % 2 == 0),   # alternate = even years
        }
        for key in ("summer", "yearend", "winter"):
            if now[key] and not flags[key]:
                starts[key] = dates[i]
                flags[key] = True
            elif not now[key] and flags[key]:
                _close(key, dates[i - 1])

    for key in ("summer", "yearend", "winter"):
        if flags[key]:
            ax.axvspan(starts[key], dates[-1], alpha=alphas[key], color=colors[key])


def _mark_holidays(ax: plt.Axes, y: np.ndarray, dates: pd.DatetimeIndex) -> None:
    for yr_off in range(N_YEARS):
        year = start_ts.year + yr_off
        for month, day, direction in _HOLIDAY_DEFS:
            try:
                ts = pd.Timestamp(year=year, month=month, day=day)
            except ValueError:
                continue
            idx = (ts - start_ts).days
            if idx < 0 or idx >= len(y):
                continue
            c = "crimson" if direction == +1 else "navy"
            mk = "^" if direction == +1 else "v"
            ax.plot(dates[idx], y[idx], marker=mk, color=c,
                    markersize=3, alpha=0.7, zorder=5)


def _mark_quarters(ax: plt.Axes, specs: list[dict], dates: pd.DatetimeIndex) -> None:
    for spec in specs:
        idx = spec["_burst_start"]
        if idx < len(dates):
            lc = "darkgreen" if spec["_sign"] > 0 else "darkorange"
            ax.axvspan(
                dates[idx],
                dates[min(idx + 10, len(dates) - 1)],
                alpha=0.10, color=lc,
            )


_LEGEND_HANDLES = [
    mpatches.Patch(color="gold",           alpha=0.5, label="Summer amp boost (Jun–Aug)"),
    mpatches.Patch(color="tomato",         alpha=0.6, label="Year-end amp boost (Nov–Dec)"),
    mpatches.Patch(color="cornflowerblue", alpha=0.6, label="Severe winter amp drop (even years Jan–Feb)"),
    plt.Line2D([0], [0], marker="^", color="crimson", ls="", markersize=6, label="Holiday +spike"),
    plt.Line2D([0], [0], marker="v", color="navy",    ls="", markersize=6, label="Holiday −dip"),
    mpatches.Patch(color="darkgreen",  alpha=0.4, label="Q-end recurrent burst (+)"),
    mpatches.Patch(color="darkorange", alpha=0.4, label="Q-end recurrent burst (−)"),
]

# ── Figure 2: three-row layout ──────────────────────────────────────────────
fig2, axes2 = plt.subplots(3, 1, figsize=(20, 15), sharex=False)
fig2.suptitle(
    "SPEC §9 — 5-Year Sinusoidal Series: Three Trend Variants\n"
    "(Low noise σ=0.5 for clear changepoint visibility · Holiday sudden drifts · Quarter-end recurrent bursts · Seasonal amplitude modulation)",
    fontsize=12,
)


# ── Graph i — Negative trend in year-2 Q3 ──────────────────────────────────
# Base sinusoidal series with quarter-end recurrent bursts applied post-hoc.
# Extra: steep negative incremental drift in year-2 Q3 (Jul–Sep 2021).
q_specs_i = _build_quarterly_specs(N_POINTS, seed_offset=1)
# Build base with no drift specs (bursts applied manually to preserve sign)
df_i, _ = gen_sine.combined_drift(
    drift_specs=[{"type": "sudden", "drift_point": 0, "magnitude": 0.0}],  # no-op seed
    seed=SEED, n_points=N_POINTS, noise_std=0.5,
    start_date=START_DATE, freq="D",
)
dates_i = pd.DatetimeIndex(df_i["ds"])
y_i = df_i["y"].to_numpy().copy()

_apply_quarter_bursts(y_i, q_specs_i, N_POINTS)

# Year-2 Q3: Jul–Sep of year 2020+1 = 2021
yr2_q3_start = (pd.Timestamp("2021-07-01") - start_ts).days
yr2_q3_end   = (pd.Timestamp("2021-09-30") - start_ts).days
for k in range(yr2_q3_start, min(yr2_q3_end, N_POINTS)):
    y_i[k] += -0.18 * (k - yr2_q3_start)   # steep negative ramp

_apply_holidays(y_i, dates_i)
_apply_seasonal_amplitude(y_i, dates_i)

ax_i = axes2[0]
ax_i.plot(dates_i, y_i, lw=0.55, color="steelblue", alpha=0.85)
_shade_seasons(ax_i, dates_i)
_mark_holidays(ax_i, y_i, dates_i)
_mark_quarters(ax_i, q_specs_i, dates_i)
ax_i.axvspan(
    dates_i[yr2_q3_start],
    dates_i[min(yr2_q3_end, N_POINTS - 1)],
    alpha=0.18, color="red", label="Year-2 Q3 neg. trend",
)
ax_i.set_title("Graph i — Negative trend in Year-2 Q3 (Jul–Sep 2021)", fontsize=11)
ax_i.set_ylabel("y")
ax_i.tick_params(axis="x", rotation=30, labelsize=8)
ax_i.legend(
    handles=_LEGEND_HANDLES + [mpatches.Patch(color="red", alpha=0.3, label="Year-2 Q3 neg. trend")],
    loc="upper left", fontsize=7, ncol=3,
)


# ── Graph ii — Up every Q4, down Q1 next year, gradual rise after ──────────
# Mechanism:
#   • Q4 (Oct–Dec): large positive sudden drift at Q4 start each year
#   • Q1 (Jan–Mar): negative sudden drift at Q1 start each year
#   • Gradual ramp (gradual drift) from Q2 through Q3 each year
#   • Quarter-end recurrent bursts applied post-hoc
q_specs_ii = _build_quarterly_specs(N_POINTS, seed_offset=2)
q4_q1_specs: list[dict] = []
for yr_off in range(N_YEARS):
    year = start_ts.year + yr_off
    q4_idx = (pd.Timestamp(f"{year}-10-01") - start_ts).days
    if 0 <= q4_idx < N_POINTS:
        q4_q1_specs.append({"type": "sudden", "drift_point": q4_idx, "magnitude": 15.0})
    q1_idx = (pd.Timestamp(f"{year}-01-01") - start_ts).days
    if 0 <= q1_idx < N_POINTS:
        q4_q1_specs.append({"type": "sudden", "drift_point": q1_idx, "magnitude": -12.0})
    # Gradual rise Apr–Sep each year
    q2_idx = (pd.Timestamp(f"{year}-04-01") - start_ts).days
    q3_end  = (pd.Timestamp(f"{year}-09-30") - start_ts).days
    if 0 <= q2_idx < N_POINTS:
        q4_q1_specs.append({
            "type": "gradual",
            "drift_start": q2_idx,
            "drift_end": min(q3_end, N_POINTS),
            "magnitude": 8.0,
        })

df_ii, _ = gen_sine.combined_drift(
    drift_specs=q4_q1_specs,
    seed=SEED, n_points=N_POINTS, noise_std=0.5,
    start_date=START_DATE, freq="D",
)
dates_ii = pd.DatetimeIndex(df_ii["ds"])
y_ii = df_ii["y"].to_numpy().copy()

_apply_quarter_bursts(y_ii, q_specs_ii, N_POINTS)
_apply_holidays(y_ii, dates_ii)
_apply_seasonal_amplitude(y_ii, dates_ii)

ax_ii = axes2[1]
ax_ii.plot(dates_ii, y_ii, lw=0.55, color="darkorchid", alpha=0.85)
_shade_seasons(ax_ii, dates_ii)
_mark_holidays(ax_ii, y_ii, dates_ii)
_mark_quarters(ax_ii, q_specs_ii, dates_ii)

# Shade Q4 (rises) and Q1 (drops) each year
for yr_off in range(N_YEARS):
    year = start_ts.year + yr_off
    q4_s = (pd.Timestamp(f"{year}-10-01") - start_ts).days
    q4_e = (pd.Timestamp(f"{year}-12-31") - start_ts).days
    q1_s = (pd.Timestamp(f"{year}-01-01") - start_ts).days
    q1_e = (pd.Timestamp(f"{year}-03-31") - start_ts).days
    for s, e, col in [(q4_s, q4_e, "limegreen"), (q1_s, q1_e, "salmon")]:
        s = max(s, 0); e = min(e, N_POINTS - 1)
        if s < N_POINTS:
            ax_ii.axvspan(dates_ii[s], dates_ii[e], alpha=0.12, color=col)

ax_ii.set_title(
    "Graph ii — Up every Q4, Down Q1, Gradual Rise Q2–Q3", fontsize=11
)
ax_ii.set_ylabel("y")
ax_ii.tick_params(axis="x", rotation=30, labelsize=8)
_leg_ii = _LEGEND_HANDLES + [
    mpatches.Patch(color="limegreen", alpha=0.4, label="Q4 rise window"),
    mpatches.Patch(color="salmon",    alpha=0.4, label="Q1 drop window"),
]
ax_ii.legend(handles=_leg_ii, loc="upper left", fontsize=7, ncol=3)


# ── Graph iii — Persistent negative trend; upward only in Q2 ───────────────
# Mechanism:
#   • Persistent negative linear slope applied across entire series (−0.05/day)
#   • Q2 (Apr–Jun) each year: positive sudden spike (+20) to break the negative trend
#   • All holiday drifts: positive direction only (override negatives to +8)
#   • Quarter-end recurrent bursts applied post-hoc
#   • Seasonal amplitude modulation applied as shared
q_specs_iii = _build_quarterly_specs(N_POINTS, seed_offset=3)

# Q2 upward spikes only
q2_specs: list[dict] = []
for yr_off in range(N_YEARS):
    year = start_ts.year + yr_off
    q2_idx = (pd.Timestamp(f"{year}-04-01") - start_ts).days
    if 0 <= q2_idx < N_POINTS:
        q2_specs.append({"type": "sudden", "drift_point": q2_idx, "magnitude": 20.0})

df_iii, _ = gen_sine.combined_drift(
    drift_specs=q2_specs,
    seed=SEED, n_points=N_POINTS, noise_std=0.5,
    start_date=START_DATE, freq="D",
)
dates_iii = pd.DatetimeIndex(df_iii["ds"])
y_iii = df_iii["y"].to_numpy().copy()

_apply_quarter_bursts(y_iii, q_specs_iii, N_POINTS)

# Persistent negative slope
t_iii = np.arange(N_POINTS, dtype=float)
y_iii += -0.05 * t_iii

# Holidays: positive only (upward spikes regardless of original direction)
for yr_off in range(N_YEARS):
    year = start_ts.year + yr_off
    for month, day, _dir in _HOLIDAY_DEFS:
        try:
            ts = pd.Timestamp(year=year, month=month, day=day)
        except ValueError:
            continue
        idx = (ts - start_ts).days
        if idx < 0 or idx >= N_POINTS:
            continue
        y_iii[idx:min(idx + 2, N_POINTS)] += 10.0   # all positive

_apply_seasonal_amplitude(y_iii, dates_iii)

ax_iii = axes2[2]
ax_iii.plot(dates_iii, y_iii, lw=0.55, color="darkorange", alpha=0.85)
_shade_seasons(ax_iii, dates_iii)

# Mark Q2 upward windows
for yr_off in range(N_YEARS):
    year = start_ts.year + yr_off
    q2_s = max((pd.Timestamp(f"{year}-04-01") - start_ts).days, 0)
    q2_e = min((pd.Timestamp(f"{year}-06-30") - start_ts).days, N_POINTS - 1)
    if q2_s < N_POINTS:
        ax_iii.axvspan(dates_iii[q2_s], dates_iii[q2_e], alpha=0.15, color="limegreen")

# Mark holiday +spikes (all upward)
for yr_off in range(N_YEARS):
    year = start_ts.year + yr_off
    for month, day, _ in _HOLIDAY_DEFS:
        try:
            ts = pd.Timestamp(year=year, month=month, day=day)
        except ValueError:
            continue
        idx = (ts - start_ts).days
        if idx < 0 or idx >= N_POINTS:
            continue
        ax_iii.plot(dates_iii[idx], y_iii[idx], marker="^", color="crimson",
                    markersize=3, alpha=0.7, zorder=5)

_mark_quarters(ax_iii, q_specs_iii, dates_iii)

ax_iii.set_title(
    "Graph iii — Persistent Negative Trend; Upward Spikes in Q2 Only (Apr–Jun)", fontsize=11
)
ax_iii.set_ylabel("y")
ax_iii.tick_params(axis="x", rotation=30, labelsize=8)
_leg_iii = [
    mpatches.Patch(color="gold",           alpha=0.5, label="Summer amp boost (Jun–Aug)"),
    mpatches.Patch(color="tomato",         alpha=0.6, label="Year-end amp boost (Nov–Dec)"),
    mpatches.Patch(color="cornflowerblue", alpha=0.6, label="Severe winter amp drop (even years)"),
    mpatches.Patch(color="limegreen",      alpha=0.4, label="Q2 upward window"),
    plt.Line2D([0], [0], marker="^", color="crimson", ls="", markersize=6, label="Holiday +spike (all up)"),
    mpatches.Patch(color="darkgreen",  alpha=0.4, label="Q-end recurrent burst (+)"),
    mpatches.Patch(color="darkorange", alpha=0.4, label="Q-end recurrent burst (−)"),
]
ax_iii.legend(handles=_leg_iii, loc="upper right", fontsize=7, ncol=3)

fig2.tight_layout(rect=[0, 0, 1, 0.96])

out2 = pathlib.Path(__file__).parent / "drift_5yr.png"
fig2.savefig(out2, dpi=120, bbox_inches="tight")
print(f"Saved → {out2.resolve()}")

# ---------------------------------------------------------------------------
# Figure 3 — SPEC item 10
# Sine wave, 5 years, seasonal amplitude drift ONLY in year-3 Q2+Q3,
# recurring 10-day quarter-end bursts every year, low noise.
# ---------------------------------------------------------------------------

gen_sine10 = DriftGenerator(config_path=CONFIG, trend="sine")
N10 = N_POINTS   # reuse 5yr constants

# Quarter-end recurring bursts: every ~91 days, last 10 days, all positive
recurring_specs_10: list[dict] = []
for q in range(N_YEARS * 4):
    q_end = min((q + 1) * QUARTER_DAYS, N10) - 1
    burst_s = max(q_end - 9, q * QUARTER_DAYS)
    if burst_s >= N10:
        break
    recurring_specs_10.append({
        "type": "recurring",
        "period": N10 + 1,   # fire-once sentinel
        "duration": 10,
        "magnitude": 8.0,
        "_burst_start": burst_s,
        "_sign": 1.0,
    })

df10, _ = gen_sine10.combined_drift(
    drift_specs=[{"type": "sudden", "drift_point": 0, "magnitude": 0.0}],
    seed=SEED, n_points=N10, noise_std=0.5,
    start_date=START_DATE, freq="D",
)
dates10 = pd.DatetimeIndex(df10["ds"])
y10 = df10["y"].to_numpy().copy()

# Apply quarter-end bursts
_apply_quarter_bursts(y10, recurring_specs_10, N10)

# Seasonal amplitude drift ONLY in year-3 Q2 (Apr–Jun 2022) and Q3 (Jul–Sep 2022)
yr3_q2_s = (pd.Timestamp("2022-04-01") - start_ts).days
yr3_q2_e = (pd.Timestamp("2022-06-30") - start_ts).days
yr3_q3_s = (pd.Timestamp("2022-07-01") - start_ts).days
yr3_q3_e = (pd.Timestamp("2022-09-30") - start_ts).days

t10 = np.arange(N10, dtype=float)
amp_env10 = np.zeros(N10, dtype=float)
for i in range(N10):
    idx = i
    if yr3_q2_s <= idx <= yr3_q2_e:
        amp_env10[i] = 9.0    # strong amplitude boost Q2
    elif yr3_q3_s <= idx <= yr3_q3_e:
        amp_env10[i] = -7.0   # amplitude inversion Q3
seasonal_overlay10 = amp_env10 * np.sin(2 * np.pi * t10 / SEASONAL_PERIOD)
y10 += seasonal_overlay10

fig3, ax10s = plt.subplots(figsize=(20, 5))
ax10s.plot(dates10, y10, lw=0.7, color="mediumseagreen", alpha=0.9)

# Shade year-3 Q2 (boost) and Q3 (inversion)
ax10s.axvspan(dates10[yr3_q2_s], dates10[min(yr3_q2_e, N10-1)],
              alpha=0.18, color="gold", label="Year-3 Q2: seasonal amp boost")
ax10s.axvspan(dates10[yr3_q3_s], dates10[min(yr3_q3_e, N10-1)],
              alpha=0.18, color="cornflowerblue", label="Year-3 Q3: seasonal amp inversion")

# Shade quarter-end burst windows
for spec in recurring_specs_10:
    bs = spec["_burst_start"]
    be = min(bs + 10, N10 - 1)
    ax10s.axvspan(dates10[bs], dates10[be], alpha=0.12, color="tomato")

_legend10 = [
    mpatches.Patch(color="gold",           alpha=0.5, label="Year-3 Q2 seasonal amp boost"),
    mpatches.Patch(color="cornflowerblue", alpha=0.5, label="Year-3 Q3 seasonal amp inversion"),
    mpatches.Patch(color="tomato",         alpha=0.4, label="Quarter-end recurrent burst (10 days)"),
]
ax10s.legend(handles=_legend10, loc="upper left", fontsize=8, ncol=3)
ax10s.set_title(
    "SPEC §10 — 5-Year Sine Wave: Seasonal Amplitude Drift in Year-3 Q2/Q3 Only "
    "+ Quarter-End Recurrent Bursts (10 days, every quarter)",
    fontsize=11,
)
ax10s.set_ylabel("y")
ax10s.tick_params(axis="x", rotation=30, labelsize=8)
fig3.tight_layout()

out3 = pathlib.Path(__file__).parent / "drift_10_single.png"
fig3.savefig(out3, dpi=120, bbox_inches="tight")
print(f"Saved → {out3.resolve()}")

# ---------------------------------------------------------------------------
# Figure 4 — SPEC item 11
# Three hard-to-predict drift configs (mutually exclusive).
# Config params shown in each subplot title.
# ---------------------------------------------------------------------------

import yaml as _yaml

_cfg_path = CONFIG
with _cfg_path.open() as _fh:
    _full_cfg = _yaml.safe_load(_fh)

# ── Config A: exponential + concept drift ────────────────────────────────
_cfgA = _full_cfg["hard_config_a"]
genA = DriftGenerator(config_path=CONFIG, trend=_cfgA["trend"])
_cpA = _cfgA["concept"]["change_point"]
dfA, _ = genA.concept_drift(
    seed=_cfgA["seed"],
    n_points=_cfgA["n_points"],
    change_point=_cpA,
    coef_before=_cfgA["concept"]["coef_before"],
    coef_after=_cfgA["concept"]["coef_after"],
    noise_std=_cfgA["noise_std"],
    start_date=_cfgA["start_date"],
    freq=_cfgA["freq"],
)
datesA = pd.DatetimeIndex(dfA["ds"])
yA = dfA["y"].to_numpy().copy()

# ── Config B: binary + covariate drift ──────────────────────────────────
_cfgB = _full_cfg["hard_config_b"]
genB = DriftGenerator(config_path=CONFIG, trend=_cfgB["trend"])
_dpB = _cfgB["covariate"]["drift_point"]
dfB, _ = genB.covariate_drift(
    seed=_cfgB["seed"],
    n_points=_cfgB["n_points"],
    drift_point=_dpB,
    n_covariates=_cfgB["covariate"]["n_covariates"],
    covariate_magnitude=_cfgB["covariate"]["covariate_magnitude"],
    noise_std=_cfgB["noise_std"],
    start_date=_cfgB["start_date"],
    freq=_cfgB["freq"],
)
datesB = pd.DatetimeIndex(dfB["ds"])
yB = dfB["y"].to_numpy().copy()

# ── Config C: flat + sudden+gradual+recurring ────────────────────────────
_cfgC = _full_cfg["hard_config_c"]
genC = DriftGenerator(config_path=CONFIG, trend=_cfgC["trend"])
_specsC = [
    {"type": "sudden",    "drift_point": _cfgC["sudden"]["drift_point"],
                          "magnitude":   _cfgC["sudden"]["magnitude"]},
    {"type": "gradual",   "drift_start": _cfgC["gradual"]["drift_start"],
                          "drift_end":   _cfgC["gradual"]["drift_end"],
                          "magnitude":   _cfgC["gradual"]["magnitude"]},
    {"type": "recurring", "period":      _cfgC["recurring"]["period"],
                          "duration":    _cfgC["recurring"]["duration"],
                          "magnitude":   _cfgC["recurring"]["magnitude"]},
]
dfC, metaC = genC.combined_drift(
    drift_specs=_specsC,
    seed=_cfgC["seed"],
    n_points=_cfgC["n_points"],
    noise_std=_cfgC["noise_std"],
    start_date=_cfgC["start_date"],
    freq=_cfgC["freq"],
)
datesC = pd.DatetimeIndex(dfC["ds"])
yC = dfC["y"].to_numpy().copy()

fig4, axes4 = plt.subplots(3, 1, figsize=(20, 14), sharex=False)
fig4.suptitle(
    "SPEC §11 — Three Mutually Exclusive Hard-to-Predict Drift Configs\n"
    "(Chosen to defeat Prophet/naive models — config params shown in titles)",
    fontsize=12,
)

# Panel A
axes4[0].plot(datesA, yA, lw=0.7, color="firebrick", alpha=0.9)
axes4[0].axvline(datesA[_cpA], color="black", ls="--", lw=1.2,
                 label=f"Concept change_point={_cpA}")
axes4[0].set_title(
    f"Config A — trend={_cfgA['trend']!r}, drift=concept, "
    f"change_point={_cpA}, coef_before={_cfgA['concept']['coef_before']}, "
    f"coef_after={_cfgA['concept']['coef_after']}, noise_std={_cfgA['noise_std']}\n"
    "WHY HARD: exponential growth + mid-series covariate relationship reversal",
    fontsize=9,
)
axes4[0].legend(fontsize=8)
axes4[0].set_ylabel("y")
axes4[0].tick_params(axis="x", rotation=30, labelsize=8)

# Panel B
axes4[1].plot(datesB, yB, lw=0.7, color="royalblue", alpha=0.9)
axes4[1].axvline(datesB[_dpB], color="darkorange", ls="--", lw=1.2,
                 label=f"Covariate drift_point={_dpB}")
axes4[1].set_title(
    f"Config B — trend={_cfgB['trend']!r}, drift=covariate, "
    f"drift_point={_dpB}, n_covariates={_cfgB['covariate']['n_covariates']}, "
    f"cov_magnitude={_cfgB['covariate']['covariate_magnitude']}, noise_std={_cfgB['noise_std']}\n"
    "WHY HARD: binary square-wave trend (non-smooth) + hidden exogenous covariate shift",
    fontsize=9,
)
axes4[1].legend(fontsize=8)
axes4[1].set_ylabel("y")
axes4[1].tick_params(axis="x", rotation=30, labelsize=8)

# Panel C — mark each drift component
colors_c = ["crimson", "darkorchid", "darkorange"]
for comp, col in zip(metaC["components"], colors_c):
    for key in ("drift_point", "drift_start", "change_point"):
        if key in comp:
            axes4[2].axvline(
                datesC[comp[key]], color=col, ls="--", lw=1,
                label=f"{comp['drift_type']}: {key}={comp[key]}",
            )
            break
    if "drift_windows" in comp:
        for ws, we in comp["drift_windows"][:4]:   # first 4 windows only
            axes4[2].axvspan(datesC[ws], datesC[min(we, len(datesC)-1)],
                             alpha=0.10, color="darkorange")
axes4[2].plot(datesC, yC, lw=0.7, color="darkslategray", alpha=0.9)
axes4[2].set_title(
    f"Config C — trend={_cfgC['trend']!r}, drifts=sudden+gradual+recurring, "
    f"sudden_pt={_cfgC['sudden']['drift_point']}, gradual={_cfgC['gradual']['drift_start']}–{_cfgC['gradual']['drift_end']}, "
    f"recur_period={_cfgC['recurring']['period']}d, noise_std={_cfgC['noise_std']}\n"
    "WHY HARD: zero trend + three asynchronous overlapping drifts at different timescales",
    fontsize=9,
)
axes4[2].legend(fontsize=8)
axes4[2].set_ylabel("y")
axes4[2].tick_params(axis="x", rotation=30, labelsize=8)

fig4.tight_layout(rect=[0, 0, 1, 0.95])

out4 = pathlib.Path(__file__).parent / "drift_11_hard.png"
fig4.savefig(out4, dpi=120, bbox_inches="tight")
print(f"Saved → {out4.resolve()}")

# ---------------------------------------------------------------------------
# Figure 5 — SPEC item 12
#
# Sinusoidal base, 5 years daily.  Layers:
#   A. Covariate drift (high amplitude) during year-2 Q2+Q3 (Apr–Sep 2021);
#      covariate reverts to baseline at end of year-3 (Dec 2022).
#   B. Seasonal drift (amplitude boost) every December across all 5 years.
#   C. Recurrent amplitude drift: every month-end, 5-day window.
#   D. Sudden covariate drifts:
#        year-1: 1 sudden  (Jul 2020)
#        year-2: 2 suddent (Mar 2021, Sep 2021)
#        year-3: 1 sudden  (Jun 2022)
#        year-4: 2 sudden  (Feb 2023, Aug 2023)
#        year-5: 3 sudden  (Jan 2024, May 2024, Oct 2024)
# ---------------------------------------------------------------------------

gen12 = DriftGenerator(config_path=CONFIG, trend="sine")
N12 = N_POINTS   # 5yr
start12 = start_ts   # 2020-01-01

# ── D: Sudden covariate drift specs (used in combined_drift) ──────────────
_sudden_schedule = {
    0: [pd.Timestamp("2020-07-04")],
    1: [pd.Timestamp("2021-03-15"), pd.Timestamp("2021-09-01")],
    2: [pd.Timestamp("2022-06-01")],
    3: [pd.Timestamp("2023-02-14"), pd.Timestamp("2023-08-20")],
    4: [pd.Timestamp("2024-01-10"), pd.Timestamp("2024-05-01"), pd.Timestamp("2024-10-15")],
}
sudden_specs12: list[dict] = []
all_sudden_idxs: list[tuple[int, int]] = []   # (idx, year_offset) for annotation
for yr_off, dates_list in _sudden_schedule.items():
    for ts_s in dates_list:
        idx_s = (ts_s - start12).days
        if 0 <= idx_s < N12:
            sudden_specs12.append({
                "type": "sudden",
                "drift_point": idx_s,
                "magnitude": 14.0 * (1 if yr_off % 2 == 0 else -1),  # alternate sign
            })
            all_sudden_idxs.append((idx_s, yr_off))

df12, _ = gen12.combined_drift(
    drift_specs=sudden_specs12 if sudden_specs12 else
                [{"type": "sudden", "drift_point": 0, "magnitude": 0.0}],
    seed=SEED, n_points=N12, noise_std=0.5,
    start_date=START_DATE, freq="D",
)
dates12 = pd.DatetimeIndex(df12["ds"])
y12 = df12["y"].to_numpy().copy()

# ── A: Covariate drift — high amplitude in year-2 Q2+Q3 ─────────────────
# A covariate x is drawn; its mean shifts up in the window, reverts at year-3 end.
rng12 = np.random.default_rng(SEED + 12)
x_cov = rng12.standard_normal(N12)
cov_window_s = (pd.Timestamp("2021-04-01") - start12).days
cov_window_e = (pd.Timestamp("2021-09-30") - start12).days
cov_revert    = (pd.Timestamp("2022-12-31") - start12).days

HIGH_COV_MAG = 8.0
x_cov[cov_window_s:cov_window_e + 1] += HIGH_COV_MAG   # shift up in window
# After revert point: x returns to baseline (no additional shift)
# (The "shift back" is modelled by NOT keeping the added mean after cov_revert)
# For visual clarity we taper the shift back to 0 linearly from cov_window_e to cov_revert
taper_len = max(cov_revert - cov_window_e, 1)
for i in range(cov_window_e + 1, min(cov_revert + 1, N12)):
    frac = (i - cov_window_e) / taper_len
    x_cov[i] += HIGH_COV_MAG * (1.0 - frac)   # linear taper back to baseline

coef_cov = 1.5   # fixed coefficient
y12 += coef_cov * x_cov

# ── B: Seasonal drift every December ────────────────────────────────────
DEC_AMP = 6.0
t12 = np.arange(N12, dtype=float)
amp_dec = np.zeros(N12, dtype=float)
for i, ts_d in enumerate(dates12):
    if ts_d.month == 12:
        amp_dec[i] = DEC_AMP
y12 += amp_dec * np.sin(2 * np.pi * t12 / SEASONAL_PERIOD)

# ── C: Recurrent month-end amplitude bursts (last 5 days of each month) ──
MONTH_BURST_MAG = 5.0
month_end_windows: list[tuple[int, int]] = []
for i, ts_d in enumerate(dates12):
    # Check if this day is in the last 5 days of its month
    import calendar as _cal
    last_day = _cal.monthrange(ts_d.year, ts_d.month)[1]
    if ts_d.day >= last_day - 4:
        y12[i] += MONTH_BURST_MAG
        if not month_end_windows or i > month_end_windows[-1][1] + 1:
            month_end_windows.append((i, i))
        else:
            month_end_windows[-1] = (month_end_windows[-1][0], i)

# ── Plot ─────────────────────────────────────────────────────────────────
fig5, ax12 = plt.subplots(figsize=(22, 6))
ax12.plot(dates12, y12, lw=0.6, color="darkcyan", alpha=0.9, label="series")

# Shade covariate high-amplitude window (year-2 Q2+Q3)
ax12.axvspan(dates12[cov_window_s], dates12[min(cov_window_e, N12-1)],
             alpha=0.15, color="gold", label="Covariate high-amp window (Year-2 Q2+Q3)")
# Shade covariate taper-back zone
ax12.axvspan(dates12[min(cov_window_e+1, N12-1)],
             dates12[min(cov_revert, N12-1)],
             alpha=0.08, color="khaki", label="Covariate revert taper (→ end Year-3)")

# Shade December seasonal drift windows
_dec_in = False
_dec_start = None
for i, ts_d in enumerate(dates12):
    if ts_d.month == 12 and not _dec_in:
        _dec_start = dates12[i]; _dec_in = True
    elif ts_d.month != 12 and _dec_in:
        ax12.axvspan(_dec_start, dates12[i-1], alpha=0.12, color="tomato")
        _dec_in = False
if _dec_in:
    ax12.axvspan(_dec_start, dates12[-1], alpha=0.12, color="tomato")

# Shade month-end burst windows (sample first 3 per year for readability)
_shown = 0
for ws, we in month_end_windows:
    ax12.axvspan(dates12[ws], dates12[min(we, N12-1)], alpha=0.07, color="mediumpurple")
    _shown += 1

# Mark sudden covariate drifts by year (color-coded)
_yr_colors = ["crimson", "navy", "darkgreen", "saddlebrown", "darkorange"]
_yr_labels = {0: "Year-1 (1×)", 1: "Year-2 (2×)", 2: "Year-3 (1×)",
              3: "Year-4 (2×)", 4: "Year-5 (3×)"}
_yr_plotted: set[int] = set()
for idx_s, yr_off in all_sudden_idxs:
    col = _yr_colors[yr_off]
    mk = "^" if sudden_specs12[[s["drift_point"] for s in sudden_specs12].index(idx_s)]["magnitude"] > 0 else "v"
    lbl = _yr_labels[yr_off] if yr_off not in _yr_plotted else None
    ax12.plot(dates12[idx_s], y12[idx_s], marker=mk, color=col,
              markersize=7, zorder=6, label=lbl)
    ax12.axvline(dates12[idx_s], color=col, lw=0.6, ls="--", alpha=0.6)
    _yr_plotted.add(yr_off)

_leg12 = [
    mpatches.Patch(color="gold",         alpha=0.5, label="Covariate high-amp (Year-2 Q2+Q3)"),
    mpatches.Patch(color="khaki",        alpha=0.4, label="Covariate revert taper (→ Year-3 end)"),
    mpatches.Patch(color="tomato",       alpha=0.5, label="December seasonal drift"),
    mpatches.Patch(color="mediumpurple", alpha=0.4, label="Month-end recurrent burst (5 days)"),
    plt.Line2D([0],[0], marker="^", color="crimson",    ls="", markersize=7, label="Sudden cov. Year-1 (1×) ↑"),
    plt.Line2D([0],[0], marker="v", color="navy",       ls="", markersize=7, label="Sudden cov. Year-2 (2×) ↓"),
    plt.Line2D([0],[0], marker="^", color="darkgreen",  ls="", markersize=7, label="Sudden cov. Year-3 (1×) ↑"),
    plt.Line2D([0],[0], marker="v", color="saddlebrown",ls="", markersize=7, label="Sudden cov. Year-4 (2×) ↓"),
    plt.Line2D([0],[0], marker="^", color="darkorange", ls="", markersize=7, label="Sudden cov. Year-5 (3×) ↑"),
]
ax12.legend(handles=_leg12, loc="upper left", fontsize=7, ncol=3)
ax12.set_title(
    "SPEC §12 — Sinusoidal Series: Covariate Drift (Year-2 Q2/Q3 high-amp, reverts Year-3 end) "
    "+ December Seasonal Drifts + Month-End Recurrent Bursts (5 days) "
    "+ Sudden Covariate Drifts (1/2/1/2/3 per year)",
    fontsize=10,
)
ax12.set_ylabel("y")
ax12.tick_params(axis="x", rotation=30, labelsize=8)
fig5.tight_layout()

out5 = pathlib.Path(__file__).parent / "drift_12_covariate.png"
fig5.savefig(out5, dpi=120, bbox_inches="tight")
print(f"Saved → {out5.resolve()}")

plt.show()
