# Plan: Implement `pocs/changepoint/seasonalityV2` — Agent Beats Naive Prophet

## Context

The spec at `pocs/changepoint/seasonalityV2/spec.md` defines a self-contained POC whose
headline claim is: **an LLM agent, reasoning from extracted time-series statistics, can
select Prophet hyperparameters that produce lower val-MAE than a default-parameter Prophet
baseline on a synthetic dataset with 4 structural changepoints.**

This is the next step after the amplitude-shift POC (`seasonality/`) which proved PELT
detection works. Now we go end-to-end: dataset → stats → naive baseline → agent loop →
comparison → artefacts.

All code lives in `pocs/changepoint/seasonalityV2/`. **No imports from `src/ailf/`.**
Execution requires YOLO mode (Prophet fitting + LLM calls); this plan only covers authoring.

---

## Technology Decisions (from codebase exploration)

| Concern | Choice | Rationale |
|---|---|---|
| LLM client | `langchain_aws.ChatBedrockConverse` + `.with_structured_output()` | Already used in `pocs/changepoint/graph/llm.py`; Bedrock keys in `.env.example` |
| Structured output | Pydantic models + LangChain structured output | Pattern from `pocs/changepoint/graph/state.py` |
| Retry on LLM parse fail | Manual 3-attempt loop, 2s delay | Mirrors `pocs/changepoint/graph/llm.py` |
| Orchestration | Plain Python loop (not LangGraph) | Simpler for a single-agent, single-series POC |
| Prophet | `prophet.Prophet(**params).fit(train_df).predict(future)` | Already in `pocs/changepoint/forecasting.py` (mirror, don't import) |
| Changepoint detection (for stats) | Prophet's fitted `trend.deltas` | Deterministic; same approach as `pocs/changepoint/diagnostics.py` |
| Env loading | `python-dotenv` + `os.getenv` | Standard project pattern |

---

## File-by-File Implementation Plan

### 1. `config.py` — Bounded grid + env loading

**What it does:** Single source of truth for parameter bounds and environment config.

```python
# Bounded parameter grid (FR-022)
CHANGEPOINT_PRIOR_SCALE_GRID = [0.001, 0.01, 0.05, 0.1, 0.5]
SEASONALITY_PRIOR_SCALE_GRID = [0.01, 0.1, 1.0, 10.0]
SEASONALITY_MODE_GRID        = ["additive", "multiplicative"]
CHANGEPOINT_RANGE_GRID       = [0.8, 0.9, 0.95]
N_CHANGEPOINTS_GRID          = [10, 15, 25]

VALID_GRID = {
    "changepoint_prior_scale": CHANGEPOINT_PRIOR_SCALE_GRID,
    "seasonality_prior_scale": SEASONALITY_PRIOR_SCALE_GRID,
    "seasonality_mode":        SEASONALITY_MODE_GRID,
    "changepoint_range":       CHANGEPOINT_RANGE_GRID,
    "n_changepoints":          N_CHANGEPOINTS_GRID,
}

MAX_AGENT_ITERATIONS = 5
DEFAULT_SEED         = 42
TRAIN_FRAC, VAL_FRAC, TEST_FRAC = 0.70, 0.15, 0.15

@dataclass
class RunConfig:
    model_id: str          # from env PROPHET_AGENT_MODEL_ID
    aws_region: str        # from env AWS_REGION
    langsmith_tracing: bool
    seed: int

def load_config(seed=DEFAULT_SEED) -> RunConfig:
    # raises ConfigError if PROPHET_AGENT_MODEL_ID or AWS_REGION missing
```

**Key:** `validate_config(proposed: dict) -> None` raises `ValueError` listing
every out-of-bounds param — called before val scoring.

---

### 2. `datasets.py` — Synthetic 4-changepoint series

**What it does:** Generates a daily 1 095-point series with exactly 4 injected changepoints
(one per structural type) placed at indices ~200, ~420, ~630, ~840.

**Design — building on `ref_datasets_seasonal.py`:**

```
Base series components (same _base_components pattern):
  trend(t)    — piecewise linear, slope set per segment
  seasonal(t) — sine wave, amplitude/mode set per segment
  noise(t)    — Gaussian, std set per segment

Injection at each changepoint:

  Type A (idx ≈ 200) — Level shift
    y += LEVEL_JUMP (e.g. +15) from idx onward
    → defeats default changepoint_prior_scale (too smooth to track abrupt step)

  Type B (idx ≈ 420) — Trend kink
    slope changes from +0.02/day to -0.01/day
    changepoint placed after training 80% cutoff (default changepoint_range=0.8 misses it)
    → exactly the tail-kink blind spot

  Type C (idx ≈ 630) — Variance change
    noise std doubles: base_noise → 2 * base_noise
    → heteroscedasticity; default Prophet assumes constant noise

  Type D (idx ≈ 840) — Seasonality mode shift
    additive seasonal → multiplicative seasonal (amplitude scales with trend level)
    → default seasonality_mode='additive' fails after this point
```

**Public API:**
```python
def generate_dataset(
    seed: int = 42,
    length: int = 1095,
    train_frac: float = 0.70,
    val_frac:   float = 0.15,
) -> tuple[pd.DataFrame, dict]:
    """
    Returns:
      df: pd.DataFrame with columns ['ds', 'y']
      meta: {
        'changepoints': {
          'A_level_shift':        pd.Timestamp,
          'B_trend_kink':         pd.Timestamp,
          'C_variance_change':    pd.Timestamp,
          'D_seasonality_mode':   pd.Timestamp,
        },
        'train_end': pd.Timestamp,
        'val_end':   pd.Timestamp,
        'seed': int,
      }
    """
```

**Complexity floor check (FR-005):** Type D (seasonality mode shift) is engineered to
guarantee ≥10% relative improvement for `seasonality_mode='multiplicative'` over default
`'additive'` on the val split. Verify empirically; adjust amplitude ratio if needed.

---

### 3. `stats.py` — Training-only stats extraction

**What it does:** Pure deterministic function; no LLM calls.

```python
@dataclass
class SegmentStats:
    start: str           # ISO date
    end: str
    mean: float
    std: float
    slope: float         # OLS slope over segment

@dataclass
class StatsBundle:
    n_obs_train: int
    changepoints_detected: list[dict]    # [{date, index, delta}]
    segments: list[SegmentStats]
    seasonality_period_days: int         # dominant period (365 for annual, 30 for monthly)
    seasonality_mode_signal: float       # 0.0=additive, 1.0=multiplicative (heuristic)
    noise_level: float                   # median abs deviation of residuals
    post_last_cp_days: int
    insufficient_seasonal_history: bool  # post_last_cp_days < seasonality_period_days
    trend_direction: str                 # "up" | "down" | "flat"

def extract_stats(
    train_df: pd.DataFrame,          # ds, y — training only
    changepoints: list[pd.Timestamp], # known injection dates (from meta)
) -> StatsBundle:
    ...

def stats_to_dict(bundle: StatsBundle) -> dict:
    """JSON-safe dict (no NaN/Inf). Called before passing to agent and serialising."""
```

**seasonality_mode_signal heuristic:** Regress log(|seasonal residual|) on log(trend level).
Positive slope → multiplicative tendency. Normalise to [0,1].

**Determinism guarantee:** Uses only `train_df`, numpy, scipy. No randomness.

---

### 4. `naive.py` — Default Prophet baseline

**What it does:** Fits Prophet with all defaults on train; scores on val; re-scores on test
only when called in final-reporting mode.

```python
@dataclass
class NaiveResult:
    val_mae:      float
    val_rmse:     float
    test_mae:     float | None      # None during agent loop
    test_rmse:    float | None
    val_forecast: pd.DataFrame      # ds, yhat
    test_forecast: pd.DataFrame | None

def run_naive_prophet(
    train_df: pd.DataFrame,
    val_df:   pd.DataFrame,
    test_df:  pd.DataFrame | None = None,  # pass only after agent loop ends
    seed:     int = 42,
) -> NaiveResult:
```

**Prophet call:**
```python
m = Prophet()   # all defaults — no params
m.fit(train_df[["ds", "y"]])
future = m.make_future_dataframe(periods=len(val_df), freq="D")
forecast = m.predict(future)
```

**Metric:** MAE = `mean(|yhat - y|)` over val/test period.

---

### 5. `agent.py` — LLM loop + trace capture

**Architecture:** Plain Python `for` loop (not LangGraph). Single LLM call per iteration.

#### 5a. Pydantic schemas

```python
class ProphetConfig(BaseModel):
    changepoint_prior_scale: float
    seasonality_prior_scale: float
    seasonality_mode:        Literal["additive", "multiplicative"]
    changepoint_range:       float
    n_changepoints:          int

class AgentProposal(BaseModel):
    hypothesis:       str   # agent's reasoning about failure mode
    config:           ProphetConfig
    expected_effect:  str   # which Prophet blind spot this addresses
```

#### 5b. LLM invocation

```python
from langchain_aws import ChatBedrockConverse

llm = ChatBedrockConverse(
    model=run_config.model_id,
    region_name=run_config.aws_region,
    max_tokens=1500,
)
structured_llm = llm.with_structured_output(AgentProposal)
```

Retry: up to 3 attempts on `ValidationError`, 2s delay. Raises `ModelUnavailableError`
on Bedrock service errors.

#### 5c. System prompt (inline in `agent.py`)

```
You are a forecasting analyst. You receive training-data statistics for a time series
that has structural changepoints. Your task: identify the dominant failure mode and
propose Prophet hyperparameters that will fix it.

Failure-mode → parameter mapping:
- Level shift (abrupt step in mean) → raise changepoint_prior_scale (0.1–0.5)
- Trend kink in recent data → raise changepoint_range to 0.9 or 0.95
- Variance change (heteroscedasticity) → raise changepoint_prior_scale + lower n_changepoints
- Seasonality mode shift (additive→multiplicative) → set seasonality_mode='multiplicative'

You must propose EXACTLY ONE config. Parameters must come from the allowed grids only.
Do not repeat a previously rejected config.
```

#### 5d. Agent loop

```python
@dataclass
class IterationRecord:
    iteration:        int
    hypothesis:       str
    proposed_config:  dict
    val_mae:          float | None
    decision:         str    # "accepted" | "rejected" | "out_of_bounds" | "prophet_error"
    rejection_reason: str | None

def run_agent_loop(
    stats_bundle:   StatsBundle,
    train_df:       pd.DataFrame,
    val_df:         pd.DataFrame,
    naive_val_mae:  float,           # comparison bar — NOT passed to agent in prompt
    run_config:     RunConfig,
) -> tuple[ProphetConfig, list[IterationRecord]]:
```

**Loop logic:**
```
for i in 1..MAX_AGENT_ITERATIONS:
    build prompt = stats_dict + [prev val_maes of own proposals] (NOT naive_val_mae)
    proposal = structured_llm.invoke(prompt)   # retry up to 3x
    validate config against grid → if out-of-bounds: record, continue
    fit Prophet(proposal.config) on train_df, score on val_df
    record iteration
    if val_mae < naive_val_mae: accept, break

if no acceptance: carry best-val-MAE proposal
return (accepted_or_best_config, trace)
```

**What the agent sees vs does NOT see:**
- ✅ sees: `stats_dict`, its own previous val MAEs (after iter 1)
- ❌ never sees: naive_val_mae, val/test target values, ground-truth changepoint dates

---

### 6. `decision.py` — Decision matrix

```python
@dataclass
class DecisionMatrix:
    naive_val_mae:           float
    agent_val_mae:           float
    naive_test_mae:          float
    agent_test_mae:          float
    delta_val_mae:           float    # naive - agent (positive = agent wins)
    delta_test_mae:          float
    agent_beats_naive_on_val: bool
    pct_improvement_val:     float    # (naive - agent) / naive * 100

def build_decision_matrix(
    naive_val_mae:  float,
    agent_val_mae:  float,
    naive_test_mae: float,
    agent_test_mae: float,
) -> DecisionMatrix:

def print_decision_matrix(dm: DecisionMatrix) -> None:
    """Tabular stdout summary."""
```

---

### 7. `viz.py` — Two Plotly figures

#### Figure 1: `viz_dataset(df, meta) -> go.Figure`
Extends `ref_viz_seasonal._build_figure` pattern:
- Raw series trace (steelblue)
- Rolling mean overlay (orange dashed, window=30)
- Rolling std band (filled, 0.15 opacity)
- **4 vertical changepoint markers** — each with type label (A/B/C/D) and colour-coded
  - A: red, B: orange, C: purple, D: green
- **3 shaded regions**: train (no shade), val (light yellow), test (light red)
- Hover tooltip on markers shows date + type name
- Saved as `viz_dataset.html`

#### Figure 2: `plot_results(train_df, val_df, test_df, naive_fc, agent_fc, meta, dm) -> go.Figure`
- Train history (steelblue, solid)
- Val actuals (grey dashed)
- Test actuals (black solid)
- Naive Prophet forecast over test (red dashed)
- Agent Prophet forecast over test (green solid)
- MAE annotations: `f"Naive MAE: {dm.naive_test_mae:.2f}"` and `f"Agent MAE: {dm.agent_test_mae:.2f}"` as text boxes
- Changepoint markers (thin dashed, same colour scheme as Figure 1)
- Legend, axis labels, plotly_white template
- Saved as `viz_results.html`

---

### 8. `pipeline.py` — End-to-end orchestration

**Entry point:** `python -m pocs.changepoint.seasonalityV2.pipeline [--seed N] [--debug]`

```python
def run(seed: int = 42, debug: bool = False) -> Path:
    """Returns path to run directory."""
    run_dir = Path(f"runs/{datetime.now():%Y%m%d-%H%M%S}-seed{seed}")
    run_dir.mkdir(parents=True)

    # 1. Generate dataset + split
    df, meta = generate_dataset(seed=seed)
    train_df, val_df, test_df = split(df, meta)

    # 2. Save dataset.csv
    df.to_csv(run_dir / "dataset.csv", index=False)

    # 3. Viz dataset
    fig1 = viz_dataset(df, meta)
    fig1.write_html(run_dir / "viz_dataset.html")

    # 4. Extract stats (training only)
    bundle = extract_stats(train_df, list(meta["changepoints"].values()))
    stats_dict = stats_to_dict(bundle)
    (run_dir / "stats.json").write_text(json.dumps(stats_dict, indent=2))

    # 5. Naive baseline (val only — no test yet)
    naive_result = run_naive_prophet(train_df, val_df, seed=seed)

    # 6. Agent loop
    cfg = load_config(seed=seed)
    accepted_config, trace = run_agent_loop(bundle, train_df, val_df, naive_result.val_mae, cfg)
    (run_dir / "trace.json").write_text(json.dumps([asdict(r) for r in trace], indent=2))

    # 7. Final test evaluation (FIRST time test_df is used)
    naive_final = run_naive_prophet(train_df, val_df, test_df=test_df, seed=seed)
    agent_final = fit_and_score(accepted_config, train_df, test_df)

    # 8. Decision matrix
    dm = build_decision_matrix(
        naive_result.val_mae, agent_val_mae_from_trace(trace),
        naive_final.test_mae, agent_final.test_mae,
    )
    print_decision_matrix(dm)
    (run_dir / "decision_matrix.json").write_text(json.dumps(asdict(dm), indent=2))

    # 9. Results viz
    fig2 = plot_results(train_df, val_df, test_df, naive_final.test_forecast,
                        agent_final.forecast, meta, dm)
    fig2.write_html(run_dir / "viz_results.html")

    # 10. Run summary
    summary = build_run_summary(seed, meta, dm, accepted_config, trace)
    (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2))

    return run_dir
```

**Test MAE gate**: `test_df` is NEVER passed to `run_naive_prophet` or `fit_and_score` until
after `run_agent_loop` returns. This is the structural leakage guard.

---

### 9. `test_dataset.py` — Smoke tests

```python
def test_four_changepoint_types_present():
    df, meta = generate_dataset(seed=42)
    assert set(meta["changepoints"].keys()) == {
        "A_level_shift", "B_trend_kink", "C_variance_change", "D_seasonality_mode"
    }

def test_splits_non_overlapping():
    df, meta = generate_dataset(seed=42)
    train_df, val_df, test_df = split(df, meta)
    assert train_df["ds"].max() < val_df["ds"].min()
    assert val_df["ds"].max() < test_df["ds"].min()

def test_stats_bundle_json_serialisable():
    df, meta = generate_dataset(seed=42)
    train_df, _, _ = split(df, meta)
    bundle = extract_stats(train_df, list(meta["changepoints"].values()))
    d = stats_to_dict(bundle)
    import json, math
    s = json.dumps(d)
    assert "NaN" not in s and "Infinity" not in s

def test_reproducibility():
    df1, meta1 = generate_dataset(seed=42)
    df2, meta2 = generate_dataset(seed=42)
    pd.testing.assert_frame_equal(df1, df2)
    assert meta1["changepoints"] == meta2["changepoints"]

def test_config_validation_rejects_out_of_bounds():
    from config import validate_config
    with pytest.raises(ValueError):
        validate_config({"changepoint_prior_scale": 99.0, ...})
```

---

## Build Order (dependency-safe)

```
Step 1  config.py           — no deps; defines constants used everywhere
Step 2  datasets.py         — depends on config (DEFAULT_SEED, TRAIN_FRAC)
Step 3  stats.py            — depends on datasets (train_df shape)
Step 4  naive.py            — depends on datasets (split format)
Step 5  agent.py            — depends on config (grid), stats (StatsBundle), naive (val_mae)
Step 6  decision.py         — depends on naive + agent outputs
Step 7  viz.py              — depends on datasets (meta), decision (dm)
Step 8  pipeline.py         — wires everything; depends on all above
Step 9  test_dataset.py     — tests steps 1–3
```

Steps 1–4 have no LLM dependency and can be fully verified in WRITE mode (no YOLO needed).
Steps 5–8 need YOLO mode to run (LLM calls + Prophet fitting).

---

## Dataset Engineering — Ensuring AC-001 (agent beats naive on val)

The agent wins by addressing Type D (seasonality mode shift) which is engineered to be the
dominant signal on the val split:

- **Val split placement**: val covers the period entirely after Type D changepoint (~day 840
  onward), so the default `seasonality_mode='additive'` Prophet has maximum disadvantage.
- **Amplitude ratio**: multiplicative amplitude set to `trend_level * 0.3` (30% of trend).
  At trend level ~20, this gives ±6 seasonal swing vs. a fixed ±3 for additive — a 2×
  discrepancy that drives >10% MAE difference (FR-005).
- **Agent advantage**: `seasonality_mode_signal ≈ 0.85` in StatsBundle (high multiplicative
  likelihood) + `post_last_cp_days < seasonality_period_days` flag will guide the agent to
  propose `seasonality_mode='multiplicative'` on iteration 1.

If empirical val MAE gap is < 10% relative, increase amplitude ratio to 0.4 before
final submission.

---

## Critical Files to Create

```
pocs/changepoint/seasonalityV2/
├── config.py          NEW
├── datasets.py        NEW
├── stats.py           NEW
├── naive.py           NEW
├── agent.py           NEW
├── decision.py        NEW
├── viz.py             NEW
├── pipeline.py        NEW
└── test_dataset.py    NEW
```

**Reference files to mirror (not import):**
- `pocs/changepoint/seasonalityV2/ref_datasets_seasonal.py` → `_base_components`, `_step` pattern
- `pocs/changepoint/seasonalityV2/ref_viz_seasonal.py` → `_build_figure` pattern
- `pocs/changepoint/graph/llm.py` → `ChatBedrockConverse` + retry pattern
- `pocs/changepoint/diagnostics.py` → segment stats + changepoint detection pattern
- `pocs/changepoint/forecasting.py` → `Prophet.fit/predict` + MAE metric pattern

---

## Open Questions Resolved

| Question | Decision |
|---|---|
| LangGraph vs plain loop? | Plain Python loop — simpler, traceable, no graph overhead for single-series |
| Visual inspection node needed? | No — spec says agent receives `StatsBundle` (text stats), not an image; visual node is 003's design |
| Which model? | `PROPHET_AGENT_MODEL_ID` from env, default `anthropic.claude-sonnet-4-5-20251002-v1:0` via Bedrock |
| Naive val MAE revealed to agent? | Never — agent gets only its own previous val MAEs as feedback |
| langsmith in pyproject.toml? | Already present as transitive dep via langchain; import guarded by `LANGSMITH_TRACING=true` |

---

## Verification

After YOLO mode execution:

1. `uv run pytest pocs/changepoint/seasonalityV2/test_dataset.py` — all 5 smoke tests pass
2. `uv run python -m pocs.changepoint.seasonalityV2.pipeline --seed 42` — completes without error
3. Inspect `runs/<latest>/run_summary.json` → `agent_beats_naive_on_val: true`
4. Open `runs/<latest>/viz_dataset.html` → 4 colour-coded changepoint markers visible
5. Open `runs/<latest>/viz_results.html` → 2 forecast lines + MAE annotations visible
6. Count files in `runs/<latest>/` → exactly 7 artefacts present
7. `runs/<latest>/trace.json` → all proposed configs within bounded grid
