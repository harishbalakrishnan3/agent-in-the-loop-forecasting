# Changepoint Agent POC — Cross-Scenario Summary

Can a visual-first bounded agent beat a naive changepoint-window workflow on hard scenarios?
Validation = single holdout (last validation_horizon of training); hidden test scored only
after the agent loop. Lower MAE is better.

| Scenario | Winner | Agent tool | Agent MAE | Naive MAE | Full-hist MAE | Agent beat naive? |
|---|---|---|---|---|---|---|
| level_shift_loses_seasonality | full_history_prophet | full_history_ramp_regressor | 7.76 | 5.99 | 5.99 | no |
| gradual_drift_loses_seasonality | agent | full_history_ramp_regressor | 4.56 | 7.32 | 7.32 | yes |
| temporary_event_not_regime_change | agent | full_history_clean_event | 1.53 | 10.41 | 10.41 | yes |
| many_temporary_events_long_history | agent | full_history_clean_event | 1.82 | 13.95 | 13.95 | yes |
| prophet_prior_tuning_recurring_event | agent | full_history_prophet_tuned_holidays | 1.50 | 1.79 | 1.79 | yes |

## Intervention-family coverage (SC-008)

Required families (must be demonstrated as accepted/best-validation):
- **ramp**: level_shift_loses_seasonality (best-val), gradual_drift_loses_seasonality (best-val)
- **clean_event**: temporary_event_not_regime_change (best-val), many_temporary_events_long_history (best-val)
- **holidays_tuned**: prophet_prior_tuning_recurring_event (best-val)

Available but not required to win on this data placement (see spec Assumptions):
- **step**: not exercised
- **recent_window**: not exercised
