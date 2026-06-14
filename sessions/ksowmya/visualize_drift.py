"""Drift visualisation helper.

Run from the project root:
    uv run python visualize_drift.py

Produces:
  - An interactive matplotlib window with all 7 drift types.
  - drift_overview.png saved to the project root.
"""

from __future__ import annotations

import pathlib

import matplotlib.pyplot as plt

from src.ailf.pipelines.drift.datasets import DriftGenerator

CONFIG = pathlib.Path("../../src/config/config.yml")
gen = DriftGenerator(config_path=CONFIG)

# ---------------------------------------------------------------------------
# (df, meta) pairs for every drift type
# ---------------------------------------------------------------------------

calls: list[tuple[str, object, dict]] = [
    ("sudden",      gen.sudden_drift,      {}),
    ("gradual",     gen.gradual_drift,     {}),
    ("incremental", gen.incremental_drift, {}),
    ("seasonal",    gen.seasonal_drift,    {}),
    ("recurring",   gen.recurring_drift,   {}),
    ("covariate",   gen.covariate_drift,   {}),
    ("concept",     gen.concept_drift,     {}),
]

# ---------------------------------------------------------------------------
# 4×2 grid (7 plots, last cell blank)
# ---------------------------------------------------------------------------

fig, axes = plt.subplots(4, 2, figsize=(14, 16))
axes = axes.flatten()

for ax, (name, fn, kwargs) in zip(axes, calls):
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
    ax.legend(fontsize=7)

axes[-1].set_visible(False)  # 7 plots, 8 slots

fig.suptitle(
    f"Drift Types — DriftGenerator  (trend={gen.trend})",
    fontsize=13, y=1.01,
)
plt.tight_layout()

out = pathlib.Path("../../drift_overview.png")
fig.savefig(out, dpi=120, bbox_inches="tight")
print(f"Saved → {out.resolve()}")
plt.show()
