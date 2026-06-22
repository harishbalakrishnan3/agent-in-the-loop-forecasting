# Paper & presentation diagrams

Vector-first figures for the research paper — kept as editable source, not screenshots.

## Conceptual diagrams (Mermaid)

- `architecture.mmd` — the 5-layer system architecture (core + thin pipelines, agent proposes / guardrail disposes).
- `agent_loop.mmd` — the bounded agent loop (prelude → diagnostics ∥ visual → decision ↔ backtest gate → final eval).

Render to vector for the paper (TrueType/vector, scales cleanly in a two-column layout). Use
`--pdfFit` so a tall flowchart lands on a single, tightly-cropped page:

```bash
# one-off, no install:
npx -y @mermaid-js/mermaid-cli -i docs/diagrams/architecture.mmd -o figures/architecture.pdf --pdfFit
npx -y @mermaid-js/mermaid-cli -i docs/diagrams/agent_loop.mmd   -o figures/agent_loop.pdf   --pdfFit
```

Or paste the `.mmd` into <https://mermaid.live> and export SVG/PDF, or preview in VS Code (Mermaid extension).

## Data figure (forecast comparison)

The publication forecast-comparison plot is generated from a run's committed artifacts by
`src/ailf/figures.py` (light theme, serif fonts, grayscale-safe line styles, vector output):

```bash
# double-column (full span):
uv run python -m ailf.figures reports/changepoint/<run_id> --out figures/comparison.pdf --width double
# single-column:
uv run python -m ailf.figures reports/changepoint/<run_id> --out figures/comparison.pdf --width single
```

It reads `forecast_comparison.csv` + `metrics.json`, so the figure is reproducible from a committed
scenario + seed — no agent re-run, no API calls. Output extension picks the format (`.pdf` / `.svg`
for vector, `.png` for raster).

## Dataset overview figure (appendix)

For an appendix "here is the dataset" plot, render the **full** series (train + validation + test)
with the splits shaded and the ground-truth injected boundaries marked — no forecasts:

```bash
uv run python -m ailf.figures reports/changepoint/<run_id> --kind dataset \
    --out figures/dataset_<scenario>.pdf --width double \
    --boundaries 610,700      # from scenario_metadata.json audit_only.true_injected_boundaries
```

The committed `figures/dataset_<scenario>.pdf` (one per scenario) were generated this way, pulling
each scenario's `true_injected_boundaries` from the metadata.

## Results table (LaTeX)

`src/ailf/metrics_table.py` aggregates every `<run>/metrics.json` under a reports directory into a
`booktabs` LaTeX table — per-scenario hidden-test error for agent / full-history Prophet / naive,
the agent's chosen tool, the winner in bold, and the agent's % improvement over naive:

```bash
uv run python -m ailf.metrics_table reports/changepoint --metric mae  --out figures/results_mae.tex
uv run python -m ailf.metrics_table reports/changepoint --metric rmse --out figures/results_rmse.tex
```

Requires `\usepackage{booktabs}`; drop it into the paper with `\input{figures/results_mae.tex}`.

## Pre-rendered outputs (`figures/`)

The repo's top-level `figures/` directory holds the generated, paper-ready artifacts produced by the
commands above: `architecture.{pdf,svg}`, `agent_loop.{pdf,svg}`, `forecast_<scenario>.pdf` (forecast
window, one per scenario), `dataset_<scenario>.pdf` (full-series appendix plots, one per scenario),
and `results_{mae,rmse}.tex`. Regenerate any of them with the commands in this file.

## Why not screenshot the Streamlit UI?

The interactive UI (`src/ailf/ui/app.py`) is for live demos. For the paper, prefer these vector
figures: they embed cleanly, scale without pixelation, print well in grayscale, and are reproducible.
