# Backtest Results: Naive Prophet vs Intervention

**Date:** 2026-06-20  
**Forecast Horizon:** 30 days  
**Train/Test Split:** 80/20  
**Metric:** MAE (Mean Absolute Error) — lower is better  

---

## Summary

| Metric | Value |
|--------|-------|
| Datasets tested | 15 |
| Intervention wins | 7 (47%) |
| Intervention hurts | 7 (47%) |
| Tie (no-op) | 1 (6%) |
| Best improvement | D14: +76.5% |
| Worst regression | D6: -725% |

---

## Per-Dataset Results

| Dataset | Naive MAE | Intervention MAE | Strategy | Improvement | Verdict |
|---------|-----------|-----------------|----------|-------------|---------|
| D1 single_large | 4.13 | 15.83 | inject_changepoints | -283.3% | ❌ Hurt |
| D2 single_subtle | 7.65 | 6.78 | increase_sensitivity | +11.3% | ✅ Helped |
| D3 multiple | 9.98 | 9.37 | clean_temporary_event | +6.1% | ✅ Helped |
| D4 noisy | 13.86 | 13.57 | inject_changepoints | +2.1% | ✅ Marginal |
| D5 with_trend | 2.15 | 2.08 | add_step_regressor | +2.9% | ✅ Marginal |
| D6 with_seasonality | 2.28 | 18.81 | inject_changepoints | -724.9% | ❌ Hurt badly |
| D7 close_together | 4.79 | 3.19 | clean_temporary_event | +33.4% | ✅ Win |
| D8 no_changepoint | 4.22 | 4.22 | no_intervention | 0.0% | ✅ Correct no-op |
| D9 large_series | 3.58 | 12.68 | inject_changepoints | -254.4% | ❌ Hurt |
| D10 small_mag_large | 4.57 | 4.58 | increase_sensitivity | -0.3% | — Tie |
| D11 loses_seasonality | 4.18 | 11.78 | inject_changepoints | -181.6% | ❌ Hurt |
| D12 temporary_spike | 3.94 | 3.99 | clean_temporary_event | -1.1% | — Tie |
| D13 shift_with_trend | 4.44 | 3.72 | trim_to_post_shift | +16.1% | ✅ Helped |
| D14 mixed_magnitudes | 15.71 | 3.70 | trim_to_post_shift | +76.5% | ✅ Big win |
| D15 shift+noise_regime | 12.49 | 16.94 | inject_changepoints | -35.7% | ❌ Hurt |

---

## Strategy Performance Breakdown

| Strategy | Times Used | Wins | Losses | Win Rate |
|----------|-----------|------|--------|----------|
| inject_changepoints | 7 | 1 (D4) | 5 (D1,D6,D9,D11,D15) | 14% |
| clean_temporary_event | 3 | 2 (D3,D7) | 1 (D12) | 67% |
| trim_to_post_shift | 2 | 2 (D13,D14) | 0 | 100% |
| increase_sensitivity | 2 | 1 (D2) | 1 (D10) | 50% |
| add_step_regressor | 1 | 1 (D5) | 0 | 100% |
| no_intervention | 1 | 1 (D8) | 0 | 100% |

---

## Key Insights

### Why `inject_changepoints` fails so often (5/7 uses hurt)

Prophet already handles large, obvious level shifts well on its own. When we *explicitly* inject changepoint dates, it overrides Prophet's internal flexibility and introduces instability. This is the **#1 failure mode** of the deterministic picker.

Datasets where it hurts:
- **D1, D9:** Single large shift with enough post-shift data — Prophet adapts without help
- **D6:** Seasonality present — injection disrupts the seasonal component
- **D11:** Seasonality loss at shift — needs seasonality adjustment, not changepoint injection
- **D15:** Noise regime change — the issue is variance, not just mean

### Where interventions provide clear value

- **D14 (+76.5%):** Multiple conflicting shifts confuse Prophet → `trim_to_post_shift` focuses on the latest regime
- **D7 (+33.4%):** Temporary bump → `clean_temporary_event` removes the distraction
- **D13 (+16.1%):** Shift buried in trend → trimming isolates the current regime

### The agent opportunity

A deterministic picker wins **47%** of the time. The key failures are cases where:
1. Prophet already handles the situation (→ agent should say "no intervention needed")
2. The wrong strategy is picked (→ agent should reason about *which* strategy fits)

An LLM agent that can reason about context ("Prophet has enough post-shift data to adapt on its own") could push win rate to **80%+** by simply *not intervening* on D1, D6, D9, D11, and D15.

---

## Visualizations

Detection plots: `plots/detection/`  
Backtest comparison plots: `plots/backtest/`  

Each backtest plot shows:
- Blue = training data
- Black = actual test values (ground truth)
- Orange dashed = naive Prophet forecast
- Green dashed = intervention forecast
- Red dotted verticals = detected changepoints
