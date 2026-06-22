# Paper & presentation diagrams

Vector-first figures for the research paper — kept as editable source, not screenshots.

## Conceptual diagrams (Mermaid)

- `architecture.mmd` — the 5-layer system architecture (core + thin pipelines, agent proposes / guardrail disposes).
- `agent_loop.mmd` — the bounded agent loop (prelude → diagnostics ∥ visual → decision ↔ backtest gate → final eval).

Render to vector for the paper (TrueType/vector, scales cleanly in a two-column layout):

```bash
# one-off, no install:
npx -y @mermaid-js/mermaid-cli -i docs/diagrams/architecture.mmd -o architecture.pdf
npx -y @mermaid-js/mermaid-cli -i docs/diagrams/agent_loop.mmd   -o agent_loop.pdf
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

## Why not screenshot the Streamlit UI?

The interactive UI (`src/ailf/ui/app.py`) is for live demos. For the paper, prefer these vector
figures: they embed cleanly, scale without pixelation, print well in grayscale, and are reproducible.
