"""Drift visualisation helper.

Run from ANY directory:
    python sessions/ksowmya/visualize_drift.py
    # or from project root:
    python3 -c "exec(open('sessions/ksowmya/visualize_drift.py').read())"

Produces:
  - An interactive matplotlib window with all 8 drift types (7 individual + 1 combined).
  - drift_overview.png saved next to this script.
"""

from __future__ import annotations

import pathlib
import sys

# Ensure `src` is on the path when running as a plain script
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import matplotlib.pyplot as plt

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
# 4×2 grid: 7 individual + 1 combined (8 total, fills grid exactly)
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

out = pathlib.Path(__file__).parent / "drift_overview.png"
fig.savefig(out, dpi=120, bbox_inches="tight")
print(f"Saved → {out.resolve()}")
plt.show()
