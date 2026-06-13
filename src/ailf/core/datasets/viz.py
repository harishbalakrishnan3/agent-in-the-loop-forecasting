"""Visual-confirmation overlay for a Case (reproduces proposal Figure 3).

Plots observations + rolling mean + rolling-std band, with a vertical onset marker when the
case is labeled (omitted for unlabeled real series). Returns the plotly figure (no forced
display) so it is testable headlessly; ``save_drift_overlay`` writes paired ``.png`` + ``.html``
under ``reports/`` for manual inspection. Domain-agnostic — lives in core.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from ailf.core.datasets.case import Case

DEFAULT_OUT_DIR = "reports"


def _rolling_window(n: int, window: int | None) -> int:
    if window is not None:
        return max(2, window)
    return max(2, n // 10)


def plot_drift_overlay(case: Case, *, window: int | None = None) -> go.Figure:
    """Return a plotly overlay: observations + rolling mean + rolling-std band (FR-017, FR-018)."""
    # Native python datetimes: pandas Timestamps are not serializable by kaleido's PNG export.
    times = [ts.to_pydatetime() for ts in case.series.time_index]
    values = case.series.values().ravel()
    s = pd.Series(values)
    win = _rolling_window(len(values), window)
    roll_mean = s.rolling(win, min_periods=1).mean()
    roll_std = s.rolling(win, min_periods=2).std().fillna(0.0)

    upper = (roll_mean + roll_std).to_numpy()
    lower = (roll_mean - roll_std).to_numpy()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=times, y=values, mode="lines", name="Observations",
                             line={"color": "#1f77b4", "width": 1}))
    # Rolling-std band (drawn as upper + lower with fill between).
    fig.add_trace(go.Scatter(x=times, y=upper, mode="lines", name="Rolling std (upper)",
                             line={"width": 0}, showlegend=False))
    fig.add_trace(go.Scatter(x=times, y=lower, mode="lines", name="Rolling std band",
                             line={"width": 0}, fill="tonexty",
                             fillcolor="rgba(255,127,14,0.2)"))
    fig.add_trace(go.Scatter(x=times, y=roll_mean.to_numpy(), mode="lines", name="Rolling mean",
                             line={"color": "#ff7f0e", "width": 2}))

    if case.labeled and case.labels:
        for label in case.labels:
            onset_idx = label.get("onset_index")
            if onset_idx is None or onset_idx >= len(times):
                continue
            fig.add_vline(
                x=times[onset_idx].timestamp() * 1000,  # plotly datetime axis uses epoch ms
                line={"color": "red", "width": 2, "dash": "dash"},
                annotation_text=f"onset: {label.get('flavor', '')}",
            )

    fig.update_layout(
        title=f"Drift overlay — {case.case_id}",
        xaxis_title="time",
        yaxis_title="value",
        template="plotly_white",
    )
    return fig


def save_drift_overlay(
    case: Case, out_dir: str | Path = DEFAULT_OUT_DIR, *, window: int | None = None
) -> tuple[Path, Path]:
    """Write the overlay as paired static PNG + interactive HTML; return (png_path, html_path)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig = plot_drift_overlay(case, window=window)

    png_path = out_dir / f"{case.case_id}.png"
    html_path = out_dir / f"{case.case_id}.html"
    fig.write_image(str(png_path))
    fig.write_html(str(html_path))
    return png_path, html_path
