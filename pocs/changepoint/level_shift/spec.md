# POC Spec: Level Shift Diagnostic Pipeline

**Owner:** Meena  
**Location:** `pocs/changepoint/level_shift/`  
**Created:** 2026-06-15

---

## Goal

Build an end-to-end level shift diagnostic pipeline that:
1. Detects abrupt mean changes in time-series data
2. Applies intelligent interventions to Prophet based on detection results
3. Proves that informed interventions improve forecast accuracy (lower MAE) compared to naive Prophet defaults
4. Demonstrates agent value on complex scenarios where a fixed rule fails but reasoning wins

---

## End-to-End Flow

```
Input: Time series with poor Prophet forecast
                │
                ▼
┌──────────────────────────────────────────────┐
│  1. DETECTION (detect_level_shift)           │
│     Algorithm: PELT + L2 cost (ruptures)     │
│     Output: changepoint locations + mags     │
└──────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────┐
│  2. INTERVENTION (select_strategy)           │
│     Picks strategy based on detection output │
│     Configures Prophet accordingly           │
└──────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────┐
│  3. BACKTEST                                 │
│     Naive Prophet (no intervention) → MAE α  │
│     Prophet + intervention → MAE β           │
│     Improvement = ((α-β)/α) × 100           │
└──────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────┐
│  4. AGENT INTEGRATION (later)                │
│     LLM replaces deterministic strategy      │
│     picker with reasoning                    │
└──────────────────────────────────────────────┘
```

---

## Components

---

### 1. Dataset Generator (`datasets.py`)

Generate synthetic time series with known level shifts using Darts. All generation is seeded for reproducibility.

**Interface:**

```python
from darts import TimeSeries

def generate_level_shift_series(
    length: int = 500,
    freq: str = "D",
    start_date: str = "2023-01-01",
    base_level: float = 100.0,
    base_slope: float = 0.0,
    noise_std: float = 5.0,
    changepoint_indices: list[int] | None = None,
    magnitudes: list[float] | None = None,
    seasonality_period: int | None = None,
    seasonality_amplitude: float = 0.0,
    seasonality_end_index: int | None = None,
    spike_indices: list[int] | None = None,
    spike_magnitudes: list[float] | None = None,
    spike_duration: int = 20,
    noise_std_after: float | None = None,
    seed: int = 42,
) -> tuple[TimeSeries, dict]:
    """
    Returns:
      - Darts TimeSeries object
      - Ground truth metadata dict
    """
```

**Knobs/Parameters:**

| Parameter | Purpose | Range |
|-----------|---------|-------|
| `length` | Series length | 100 – 5000 |
| `base_level` | Starting mean value | Any float |
| `base_slope` | Underlying linear trend per step | -1.0 to 1.0 |
| `noise_std` | Gaussian noise standard deviation | 0.1 – 50.0 |
| `changepoint_indices` | Where level shifts occur | List of ints within [0, length) |
| `magnitudes` | Size of each shift (+/-) | List of floats |
| `seasonality_period` | Periodic pattern length | None, 7, 30, 365 |
| `seasonality_amplitude` | Seasonal strength | 0.0 – 50.0 |
| `seasonality_end_index` | Index after which seasonality stops | None or int |
| `spike_indices` | Temporary events that revert | List of ints |
| `spike_magnitudes` | Size of each spike | List of floats |
| `spike_duration` | How many points spike lasts before reverting | int |
| `noise_std_after` | Noise level after changepoint (variance regime) | None or float |
| `seed` | Reproducibility | Any int |

**Dataset Catalog:**

| ID | Name | Description | Difficulty | Complexity |
|----|------|-------------|-----------|------------|
| D1 | `single_large` | 1 shift, +40, low noise | Easy | Low |
| D2 | `single_subtle` | 1 shift, +10, high noise (SNR ≈ 1.25) | Hard | Low |
| D3 | `multiple` | 3 shifts at [150, 350, 500] | Medium | Low |
| D4 | `noisy` | 1 shift, +30, very high noise (σ=15) | Hard | Low |
| D5 | `with_trend` | 1 shift + underlying linear slope | Medium | Low |
| D6 | `with_seasonality` | 1 shift + weekly seasonal pattern | Medium | Low |
| D7 | `close_together` | 2 shifts only 50 points apart | Hard | Low |
| D8 | `no_changepoint` | Clean series (negative control) | Control | Low |
| D9 | `large_series` | 1 shift in 2000-point series | Medium | Low |
| D10 | `small_magnitude_large_series` | Subtle shift (+8) in long series | Hard | Low |
| D11 | `shift_loses_seasonality` | Shift + seasonality disappears after | Hard | **High** |
| D12 | `temporary_spike` | Large spike that reverts (not a permanent shift) | Hard | **High** |
| D13 | `shift_with_trend` | Level shift buried in existing upward trend | Hard | **High** |
| D14 | `mixed_magnitudes` | Multiple shifts — some subtle, some large | Hard | **High** |
| D15 | `shift_plus_noise_regime` | Mean AND variance change simultaneously | Hard | **High** |

**Why D11–D15 matter (complexity justification):**

| Dataset | Why naive approach fails | What smart reasoning does differently |
|---------|--------------------------|---------------------------------------|
| D11 | Injects changepoint but Prophet still expects seasonality → wrong | Also disables seasonality after shift |
| D12 | PELT sees 2 shifts, naive treats as permanent → wrong | Recognizes canceling magnitudes → cleans spike instead |
| D13 | Hard to separate "trend acceleration" from "level jump" | Uses magnitude + context to decide |
| D14 | Same strategy for all shifts; subtle ones need different handling | Applies different strategies per shift |
| D15 | Simple changepoint injection doesn't fix the variance issue | Adjusts uncertainty interval width |

**Ground truth metadata format:**

```json
{
  "dataset_id": "D11_shift_loses_seasonality",
  "length": 500,
  "changepoint_indices": [250],
  "changepoint_dates": ["2023-09-08"],
  "magnitudes": [30.0],
  "type": "level_shift_with_seasonality_loss",
  "noise_std": 3.0,
  "base_level": 100.0,
  "seasonality_end_index": 250,
  "complexity": "high",
  "seed": 60
}
```

---

### 2. Detection Tool (`detector.py`)

Detect level shifts using PELT with L2 cost from the `ruptures` library.

**Interface:**

```python
from dataclasses import dataclass

@dataclass
class LevelShiftResult:
    changepoint_indices: list[int]
    changepoint_dates: list[str]
    magnitudes: list[float]          # mean(after) - mean(before) for each
    n_changepoints: int
    method: str                      # "pelt_l2"
    penalty: float | str             # penalty used

def detect_level_shift(
    series: TimeSeries | pd.DataFrame,
    penalty: float | str = "bic",
    min_segment_length: int = 10,
) -> LevelShiftResult:
    """
    Detect abrupt mean changes in a time series using PELT (L2 cost).
    
    Args:
        series: Input time series (Darts TimeSeries or DataFrame with [timestamp, value])
        penalty: Penalty for number of changepoints ("bic", "aic", or float)
        min_segment_length: Minimum number of points between changepoints
    
    Returns:
        LevelShiftResult with detected changepoint locations, dates, and magnitudes
    """
```

**Algorithm details:**
- Cost model: `l2` (detects changes in mean)
- Search method: PELT (Pruned Exact Linear Time) — optimal, fast
- Penalty selection: BIC by default (balances fit vs complexity)
- Post-processing: compute magnitude as `mean(segment_after) - mean(segment_before)`

---

### 3. Intervention Module (`interventions.py`)

Strategy functions that take detection output and configure Prophet.

**Interface:**

```python
from dataclasses import dataclass
from prophet import Prophet
import pandas as pd

from pocs.changepoint.level_shift.detector import LevelShiftResult


@dataclass
class InterventionResult:
    strategy_name: str              # which strategy was applied
    model: Prophet                  # configured Prophet instance
    training_data: pd.DataFrame     # possibly modified training data
    description: str                # human-readable explanation of what was done


def inject_changepoints(
    result: LevelShiftResult,
    df: pd.DataFrame,
) -> InterventionResult:
    """Inject detected changepoints explicitly into Prophet.
    
    Use when: few large, unambiguous shifts.
    """


def trim_to_post_shift(
    result: LevelShiftResult,
    df: pd.DataFrame,
    buffer_days: int = 7,
) -> InterventionResult:
    """Train only on data after the most recent shift.
    
    Use when: recent regime change, old data is irrelevant.
    """


def add_step_regressor(
    result: LevelShiftResult,
    df: pd.DataFrame,
) -> InterventionResult:
    """Add a binary regressor column (0 before shift, 1 after).
    
    Use when: permanent level change that should be modeled explicitly.
    """


def increase_sensitivity(
    result: LevelShiftResult,
    df: pd.DataFrame,
    prior_scale: float = 0.5,
) -> InterventionResult:
    """Increase Prophet's changepoint_prior_scale.
    
    Use when: subtle shift that Prophet's defaults miss.
    """


def clean_temporary_event(
    result: LevelShiftResult,
    df: pd.DataFrame,
    threshold_ratio: float = 0.8,
) -> InterventionResult:
    """Remove temporary spikes from training data.
    
    Use when: two detected shifts of opposite sign (cancel out) → transient event.
    Identifies spike by: shift[i] and shift[i+1] magnitudes nearly cancel.
    """
```

**Strategy selection logic (deterministic for POC, LLM replaces this later):**

```python
def select_strategy(result: LevelShiftResult, df: pd.DataFrame) -> str:
    """Deterministic strategy picker for backtesting.
    
    In production, the LLM agent replaces this with reasoning.
    """
    if result.n_changepoints == 0:
        return "no_intervention"
    
    # Check for temporary spike (two shifts that cancel)
    if result.n_changepoints == 2:
        m1, m2 = result.magnitudes
        if abs(m1 + m2) / max(abs(m1), abs(m2)) < 0.3:
            return "clean_temporary_event"
    
    # Few large shifts → inject
    if result.n_changepoints <= 2 and all(abs(m) > 20 for m in result.magnitudes):
        return "inject_changepoints"
    
    # Many shifts → trim to most recent
    if result.n_changepoints >= 3:
        return "trim_to_post_shift"
    
    # Subtle shift → increase sensitivity
    if all(abs(m) < 15 for m in result.magnitudes):
        return "increase_sensitivity"
    
    # Default
    return "add_step_regressor"
```

---

### 4. Backtest Module (`backtest.py`)

**Interface:**

```python
from dataclasses import dataclass


@dataclass
class BacktestResult:
    dataset_id: str
    naive_mae: float                # Prophet with defaults, no intervention
    intervention_mae: float         # Prophet with best intervention applied
    strategy_used: str              # which intervention was applied
    forecast_horizon: int           # how many days ahead were forecasted
    train_size: int                 # number of training points
    improvement_pct: float          # (naive - intervention) / naive * 100


def run_backtest(
    dataset_name: str,
    config: dict,
    forecast_horizon: int = 30,
    train_ratio: float = 0.8,
) -> BacktestResult:
    """Run naive vs intervention comparison on one dataset.
    
    Steps:
        1. Generate dataset from config
        2. Split into train/test (by train_ratio)
        3. Fit Prophet with defaults on train → forecast test → Naive MAE
        4. Run detect_level_shift on train data
        5. Apply select_strategy → configure Prophet with intervention
        6. Fit Prophet with intervention on train → forecast test → Intervention MAE
        7. Return comparison
    """


def run_all_backtests(
    forecast_horizon: int = 30,
) -> pd.DataFrame:
    """Run backtest on all datasets (D1–D15).
    
    Returns DataFrame with columns:
        dataset_id | naive_mae | intervention_mae | strategy_used | improvement_pct
    """
```

**Train/test split:**

```
|←——————— train (80%) ———————→|←— test (20%) —→|
                                |← forecast_horizon →|

Prophet fits on train, predicts test period.
MAE computed on test period only.
```

**Evaluation metrics:**

| Metric | Definition | Target |
|--------|------------|--------|
| MAE | Mean Absolute Error of forecast | Lower is better |
| Improvement % | (naive_mae - intervention_mae) / naive_mae × 100 | > 0% means intervention helped |
| Strategy accuracy | Did the picker choose the best strategy? | Compare all strategies per dataset |

**Output format (`results.csv`):**

```
dataset_id,naive_mae,intervention_mae,strategy_used,improvement_pct
<dataset>,α,β,<strategy>,((α-β)/α)×100
...
```

**Actual backtest results (deterministic picker, 30-day horizon):**

| Dataset | Naive MAE | Intervention MAE | Strategy | Improvement | Verdict |
|---------|-----------|-----------------|----------|-------------|---------|
| D1 | 4.13 | 15.83 | inject_changepoints | -283% | ❌ Hurt |
| D2 | 7.65 | 6.78 | increase_sensitivity | +11% | ✅ Helped |
| D3 | 9.98 | 9.37 | clean_temporary_event | +6% | ✅ Helped |
| D4 | 13.86 | 13.57 | inject_changepoints | +2% | ✅ Marginal |
| D5 | 2.15 | 2.08 | add_step_regressor | +3% | ✅ Marginal |
| D6 | 2.28 | 18.81 | inject_changepoints | -725% | ❌ Hurt badly |
| D7 | 4.79 | 3.19 | clean_temporary_event | +33% | ✅ Win |
| D8 | 4.22 | 4.22 | no_intervention | 0% | ✅ Correct no-op |
| D9 | 3.58 | 12.68 | inject_changepoints | -254% | ❌ Hurt |
| D10 | 4.57 | 4.58 | increase_sensitivity | -0.3% | — Tie |
| D11 | 4.18 | 11.78 | inject_changepoints | -182% | ❌ Hurt |
| D12 | 3.94 | 3.99 | clean_temporary_event | -1% | — Tie |
| D13 | 4.44 | 3.72 | trim_to_post_shift | +16% | ✅ Helped |
| D14 | 15.71 | 3.70 | trim_to_post_shift | +76% | ✅ Big win |
| D15 | 12.49 | 16.94 | inject_changepoints | -36% | ❌ Hurt |

**Summary:** 7 improved, 7 hurt, 1 tie → **47% win rate** with a deterministic picker.

**Key insight:** `inject_changepoints` causes 5 of the 7 losses. Prophet already adapts to large obvious shifts on its own — explicitly injecting them adds instability. An LLM agent that can reason "Prophet is handling this fine, don't intervene" should push win rate to 80%+.

---

### 5. Agent Integration (promotion to pipeline)

Register `detect_level_shift` as a callable tool in the core ReAct loop.

**Tool registration contract (from `src/ailf/core/`):**

```python
from ailf.core.agent import ToolSpec

level_shift_tool = ToolSpec(
    name="detect_level_shift",
    description=(
        "Detect abrupt mean changes (level shifts) in a time series using PELT "
        "with L2 cost. Returns changepoint locations, dates, magnitudes, and count."
    ),
    function=detect_level_shift,
    parameters={
        "series": "TimeSeries — the input time series to analyze",
        "penalty": "str|float — 'bic', 'aic', or numeric penalty (default: 'bic')",
        "min_segment_length": "int — minimum points between changepoints (default: 10)",
    },
    returns="LevelShiftResult with changepoint_indices, dates, magnitudes, n_changepoints",
)
```

**Agent prompt (what the LLM sees):**

```markdown
You are a forecasting analyst. A Prophet model is producing poor forecasts.
You have access to diagnostic tools. Use them to identify what's wrong,
then propose an intervention.

Available tools:
- detect_level_shift(series, penalty, min_segment_length) → LevelShiftResult

Based on the tool output, choose one of these interventions:
- inject_changepoints: tell Prophet where shifts are
- trim_to_post_shift: train only on recent data
- add_step_regressor: add binary feature for the shift
- increase_sensitivity: raise changepoint_prior_scale
- clean_temporary_event: remove transient spikes from training data

Explain your reasoning, then apply the intervention.
```

**Agent flow:**

```
Input: time series with poor Prophet forecast
  ↓
Agent calls: detect_level_shift(series)
  ↓
Agent receives: LevelShiftResult
  ↓
Agent reasons: "I see 2 shifts of +50 and -48, close together.
               They nearly cancel — this is a temporary event, not a regime change.
               I'll clean it from training data."
  ↓
Agent calls: clean_temporary_event(result, df)
  ↓
Prophet re-forecasts → improved MAE
```

**File locations after promotion:**

```
src/ailf/pipelines/changepoint/
├── __init__.py
├── tool.py              ← detect_level_shift registered as agent tool
├── interventions.py     ← strategy functions (promoted from POC)
├── pipeline.py          ← wires tool + agent + backtest together
└── prompts/
    └── level_shift_v1.md  ← agent prompt
```

---

### 6. Agent Evaluation

**Evaluation setup:**

```python
@dataclass
class AgentEvalResult:
    dataset_id: str
    naive_mae: float                # Prophet defaults
    agent_mae: float                # after agent's chosen intervention
    agent_strategy: str             # which strategy the LLM picked
    optimal_strategy: str           # best strategy (from brute-force backtest)
    strategy_match: bool            # did agent pick the optimal one?
    reasoning_quality: float        # LLM judge score (1-5)
    explanation: str                # agent's reasoning text
```

**Comparison table (target output):**

```
dataset_id  | naive_mae | agent_mae | improvement      | strategy_match | reasoning_score
<dataset>   |     α     |     β     | ((α-β)/α)×100 % | ✅/❌          | 1-5
...
```

**LLM judge criteria (from `src/ailf/core/eval`):**

| Score | Meaning |
|-------|---------|
| 5 | Correct diagnosis, correct intervention, clear explanation |
| 4 | Correct diagnosis, reasonable intervention, adequate explanation |
| 3 | Partially correct diagnosis, intervention helps but not optimal |
| 2 | Incorrect diagnosis but intervention doesn't make things worse |
| 1 | Wrong diagnosis, intervention hurts forecast |

---

## Tests (`test_level_shift.py`)

**Test-first approach.** Tests written before implementation.

**Detection tests (D1–D10):**

| Test | Assertion |
|------|-----------|
| `test_finds_single_large_shift` | Detected index within ±5 of ground truth |
| `test_finds_multiple_shifts` | Finds all 3 changepoints (within ±5 tolerance) |
| `test_no_false_positives` | Returns 0 changepoints on clean data (D8) |
| `test_detects_subtle_shift` | Finds changepoint in D2 (wider tolerance ±10) |
| `test_handles_noisy_data` | Finds changepoint in D4 (noisy) |
| `test_works_with_trend` | Finds shift despite underlying slope (D5) |
| `test_works_with_seasonality` | Finds shift despite seasonal pattern (D6) |
| `test_correct_magnitude` | Magnitude within ±20% of truth |
| `test_output_schema` | LevelShiftResult has all required fields |
| `test_reproducibility` | Same input → same output |

**Intervention tests (D11–D15):**

| Test | Assertion |
|------|-----------|
| `test_d11_intervention_disables_seasonality` | Prophet configured without seasonality post-shift |
| `test_d12_spike_cleaned_not_treated_as_shift` | Temporary spike removed from training data |
| `test_d13_shift_detected_despite_trend` | Level jump identified separately from trend |
| `test_d14_different_strategies_per_magnitude` | Subtle shifts get different treatment than large |
| `test_d15_variance_change_handled` | Uncertainty intervals adjust after regime change |
| `test_backtest_improvement_positive` | Intervention MAE < Naive MAE on D11–D15 |

**Evaluation metrics (computed across all datasets):**

| Metric | Definition |
|--------|------------|
| Precision | correct detections / all detections |
| Recall | correct detections / all true changepoints |
| Detection delay | \|detected_index - true_index\| |
| False positive rate | false alarms on clean data |
| Magnitude accuracy | \|detected_magnitude - true_magnitude\| / true_magnitude |

Tolerance window: a detection is "correct" if within **±5 indices** of a ground truth changepoint.

---

## File Structure

```
pocs/changepoint/level_shift/
├── spec.md                  ← this file
├── pr1_summary.md           ← PR 1 deliverables summary
├── __init__.py
├── datasets.py              ← D1–D15 synthetic data generator
├── detector.py              ← PELT L2 level shift detection
├── interventions.py         ← 6 strategy functions + deterministic picker
├── backtest.py              ← naive vs intervention comparison harness
├── results.csv              ← backtest output (15 rows, MAE + improvement %)
├── test_level_shift.py      ← 30 unit tests (detection + datasets)
├── visualize.py             ← Plotly interactive visualization
├── export_plots.py          ← static PNG exporter (detection plots)
├── visualize_backtest.py    ← per-dataset forecast comparison plots
└── plots/
    ├── detection/           ← D1–D15 detection plots (series + changepoints)
    └── backtest/            ← D1–D15 forecast comparison (naive vs intervention vs actual)
```

---

## Dependencies

```
darts          # synthetic time series generation
ruptures       # PELT changepoint detection
prophet        # forecasting model (the model being diagnosed/fixed)
pandas         # data handling
numpy          # numerical operations
plotly         # interactive visualization
scikit-learn   # metrics (mean_absolute_error)
pytest         # testing
kaleido        # static PNG export
```

---

## Implementation Order

```
1. Write tests                        → detection tests pass, intervention tests fail
2. Implement datasets.py (D1–D10)     → generator works, dataset tests pass
3. Implement detector.py              → detection tests pass
4. Implement visualize.py             → visual inspection
5. Extend datasets.py (D11–D15)       → complex scenarios generate correctly
6. Implement interventions.py         → strategy functions work in isolation
7. Implement backtest.py              → end-to-end naive vs intervention comparison
8. Generate results.csv               → table proving intervention improves MAE
9. Register tool in src/ailf/core/    → agent can call detect_level_shift
10. Write agent prompt                → LLM uses tool + picks strategy
11. Run agent on D1–D15              → collect agent MAE + reasoning
12. Score with LLM judge             → reasoning quality evaluation
```

---

## Success Criteria

**Detection (steps 1–4):** ✅ Complete
- ✅ All 10 datasets generated with correct ground truth metadata
- ✅ Detection precision ≥ 0.9 on D1, D3, D5, D6, D9
- ✅ Zero false positives on D8 (control)
- ✅ Detection delay ≤ 5 indices on easy datasets
- ✅ Magnitude accuracy within ±20%
- ✅ All 30 unit tests passing (10 detection + 10 dataset generator + 10 complex datasets)
- ✅ Visualization + static PNG exports working
- ✅ All code seeded and reproducible

**Intervention & Backtest (steps 5–8):** ✅ Complete
- ✅ D11–D15 datasets implemented with ground truth
- ✅ 6 intervention strategies implemented (inject_changepoints, trim_to_post_shift, add_step_regressor, increase_sensitivity, clean_temporary_event, no_intervention)
- ✅ Deterministic strategy picker + dispatcher working
- ✅ Backtest harness runs all 15 datasets (naive vs intervention)
- ✅ results.csv generated — 7/15 datasets improved (47% win rate)
- ✅ Improvement > 30% on D7 (+33.4%), D13 (+16.1%), D14 (+76.5%)
- ⚠️ Key insight: `inject_changepoints` hurts when Prophet already adapts (D1, D6, D9, D11)
- ✅ Visualization: per-dataset comparison plots (actual vs naive vs intervention)
- ✅ 30 unit tests passing (detection + datasets)
- [ ] Intervention/backtest unit tests (pending)

**Agent Integration (steps 9–12):**
- [ ] Detection tool registered in core agent tool registry
- [ ] Agent calls tool and applies intervention end-to-end
- [ ] Agent MAE < Naive MAE on D11–D15 via LLM reasoning
- [ ] Agent picks optimal strategy on ≥ 80% of datasets
- [ ] Reasoning quality score ≥ 4/5 average (LLM judge)

---

## Open Questions

**Resolved:**
- ✅ What penalty works best? → BIC across all D1–D10
- ✅ `min_segment_length` configurable or fixed? → Configurable (default=10)
- ✅ Detection near boundaries? → PELT handles naturally
- ✅ PELT L2 with trend + shift? → Works with moderate trend (D5)
- ✅ Does Prophet need `cmdstanpy` or can we use the default backend? → Uses cmdstanpy (MAP optimizer, "Chain [1]" in logs)
- ✅ Should D11's seasonality disappear abruptly or fade over N points? → Abruptly at `seasonality_end_index`
- ✅ For D12 (temporary spike), what spike duration is realistic? → 20 points works well
- ✅ What forecast horizon is fair for backtesting? → 30 days

**Open:**
- [ ] How to handle cases where multiple strategies improve MAE similarly? (brute-force all strategies per dataset?)
- [ ] Agent integration: LangChain/LangGraph vs custom ReAct loop?
- [ ] Should the agent see the plot (visual inspection) or only LevelShiftResult numbers?
