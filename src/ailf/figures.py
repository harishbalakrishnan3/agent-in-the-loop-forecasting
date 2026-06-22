"""Paper-grade figure export (publication, not the live UI).

Builds clean, light-theme, **vector** figures (PDF/SVG) sized for a two-column paper directly from a
run's committed artifacts — ``forecast_comparison.csv`` (ds, y_actual, region∈{train,val,test}, the
three method yhats) and ``metrics.json`` (per-method metrics + winner). No agent re-run is needed,
so a figure is reproducible from a committed scenario + seed.

This is deliberately separate from ``ui/chart.py`` (interactive Plotly, dark) and
``pipelines/changepoint/viz.py`` (the run's quick PNG). Lines are styled to remain distinguishable
in grayscale (distinct dashes + markers), and fonts/sizes target IEEE-style two-column figures.

CLI:
    uv run python -m ailf.figures reports/changepoint/<run_id> --out figures/<name>.pdf
    uv run python -m ailf.figures reports/changepoint/<run_id> --width single   # 1-column
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

# IEEE two-column widths in inches: a single column is ~3.5", a full (double) span ~7.16".
COLUMN_WIDTH_IN = 3.5
DOUBLE_WIDTH_IN = 7.16

# Method → (column, legend label, line color, dash, marker). Colors are also grayscale-separable
# thanks to distinct dashes/markers, so the figure survives B&W printing.
_METHOD_STYLE = [
    ("y_actual", "Actuals", "#000000", "-", None),
    ("yhat_agent", "Agent", "#6a3d9a", (0, (1, 1)), "o"),
    ("yhat_full_history", "Full-history Prophet", "#1f4e79", (0, (4, 2)), "s"),
    ("yhat_naive", "Naive baseline", "#b15928", (0, (2, 2)), "^"),
]
_REGION_FILL = {
    "train": ("#000000", 0.04, "Train"),
    "val": ("#1f4e79", 0.10, "Validation"),
    "test": ("#2ca02c", 0.08, "Test"),
}


def _paper_rc(base_font: float) -> dict:
    """Matplotlib rcParams tuned for crisp, embeddable, two-column paper figures."""
    return {
        "font.size": base_font,
        "font.family": "serif",            # matches most LaTeX body fonts; use 'sans-serif' if preferred
        "axes.titlesize": base_font + 1,
        "axes.labelsize": base_font,
        "legend.fontsize": base_font - 1,
        "xtick.labelsize": base_font - 1,
        "ytick.labelsize": base_font - 1,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linewidth": 0.4,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        "pdf.fonttype": 42,                # embed TrueType (editable text, no Type-3 — venue-safe)
        "ps.fonttype": 42,
        "svg.fonttype": "none",
    }


def load_run_artifacts(run_dir: str | Path) -> tuple[pd.DataFrame, dict]:
    """Load ``forecast_comparison.csv`` + ``metrics.json`` from a run directory."""
    run_dir = Path(run_dir)
    csv_path = run_dir / "forecast_comparison.csv"
    metrics_path = run_dir / "metrics.json"
    if not csv_path.exists():
        raise FileNotFoundError(f"missing {csv_path} — run the scenario first")
    if not metrics_path.exists():
        raise FileNotFoundError(f"missing {metrics_path} — run the scenario first")
    frame = pd.read_csv(csv_path)
    frame["ds"] = pd.to_datetime(frame["ds"])
    metrics = json.loads(metrics_path.read_text())
    return frame, metrics


def _context_window(frame: pd.DataFrame, context_points: int) -> pd.DataFrame:
    """Recent training context + the full forecast region (keeps the comparison legible)."""
    forecast_mask = frame["region"].isin(["val", "test"])
    if not forecast_mask.any():
        return frame
    first_forecast = frame.index[forecast_mask][0]
    start = max(0, frame.index.get_loc(first_forecast) - context_points)
    return frame.iloc[start:]


def render_forecast_comparison_paper(
    run_dir: str | Path,
    out_path: str | Path,
    *,
    width: str = "double",
    context_points: int = 180,
    title: str | None = None,
    changepoints: list[dict] | None = None,
) -> Path:
    """Render the publication forecast-comparison figure to a vector file (PDF/SVG by extension).

    ``width``: "single" (~3.5in, 1 column) or "double" (~7.16in, full span). ``context_points`` is
    how many trailing training points to show before the forecast region. Region bands are labelled
    Train / Validation / Test; methods carry their hidden-test MAE in the legend.
    """
    frame, metrics = load_run_artifacts(run_dir)
    methods = metrics.get("methods", {})
    winner = metrics.get("winner", "")

    base_font = 8.0 if width == "single" else 9.0
    fig_w = COLUMN_WIDTH_IN if width == "single" else DOUBLE_WIDTH_IN
    fig_h = fig_w * (0.72 if width == "single" else 0.45)

    view = _context_window(frame, context_points)

    def _mae(method: str) -> str:
        m = methods.get(method, {}).get("mae")
        return f" (MAE {m:.2f})" if isinstance(m, (int, float)) else ""

    label_suffix = {
        "Agent": _mae("agent"),
        "Full-history Prophet": _mae("full_history_prophet"),
        "Naive baseline": _mae("naive_workflow"),
        "Actuals": "",
    }

    with plt.rc_context(_paper_rc(base_font)):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))

        # Region shading + a faint boundary line at each region start.
        for region, (color, alpha, _) in _REGION_FILL.items():
            seg = view[view["region"] == region]
            if seg.empty:
                continue
            ax.axvspan(seg["ds"].iloc[0], seg["ds"].iloc[-1], color=color, alpha=alpha, lw=0, zorder=0)

        # Method traces. Markers are sparse so the line stays readable; only forecast cols are
        # non-NaN in the forecast region, so empty traces are skipped automatically.
        n = len(view)
        markevery = max(1, n // 12)
        for col, label, color, dash, marker in _METHOD_STYLE:
            if col not in view.columns or view[col].notna().sum() == 0:
                continue
            ax.plot(
                view["ds"], view[col],
                color=color, linestyle=dash, linewidth=1.3,
                marker=marker, markersize=3, markevery=markevery, markerfacecolor="none",
                label=f"{label}{label_suffix.get(label, '')}",
                zorder=3,
            )

        # Changepoint markers (optional).
        for cp in (changepoints or []):
            cp_ds = pd.Timestamp(cp["ds"])
            if view["ds"].iloc[0] <= cp_ds <= view["ds"].iloc[-1]:
                ax.axvline(cp_ds, color="#d62728", linestyle=(0, (1, 2)), linewidth=0.8, zorder=2)

        # Region labels centered over the visible part of each band, near the top.
        ymax = ax.get_ylim()[1]
        for region, (color, _, label) in _REGION_FILL.items():
            seg = view[view["region"] == region]
            if seg.empty:
                continue
            mid = seg["ds"].iloc[0] + (seg["ds"].iloc[-1] - seg["ds"].iloc[0]) / 2
            ax.text(mid, ymax, label, ha="center", va="top", fontsize=base_font - 1,
                    color=color, alpha=0.9)

        if title is None:
            sid = metrics.get("scenario_id", "")
            title = f"{sid} — winner: {winner}" if sid else None
        if title:
            ax.set_title(title)
        ax.set_xlabel("date")
        ax.set_ylabel("value")
        ax.legend(loc="best", frameon=False, ncol=1 if width == "single" else 2)
        fig.autofmt_xdate(rotation=0, ha="center")
        fig.tight_layout()

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path)   # extension (.pdf/.svg/.png) selects the vector/raster backend
        plt.close(fig)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a paper-grade forecast-comparison figure.")
    parser.add_argument("run_dir", help="A reports/changepoint/<run_id> directory")
    parser.add_argument("--out", default=None, help="Output file (.pdf/.svg/.png). Default: <run_dir>/figure.pdf")
    parser.add_argument("--width", choices=["single", "double"], default="double")
    parser.add_argument("--context-points", type=int, default=180)
    parser.add_argument("--title", default=None)
    args = parser.parse_args()

    out = args.out or str(Path(args.run_dir) / "figure.pdf")
    path = render_forecast_comparison_paper(
        args.run_dir, out, width=args.width, context_points=args.context_points, title=args.title
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
