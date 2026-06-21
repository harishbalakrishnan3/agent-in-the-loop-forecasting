# Contract: `config.yaml` schema, merge, validation, lockstep

Owner: `core/config/{schema,loader,resolve}.py` (generic logic) + the pipeline's
`config.yaml` (changepoint-specific key lists). Covers FR-007..012, SC-003, SC-007, SC-008.

## File location & ownership

`config.yaml` is **pipeline-owned** at `src/ailf/pipelines/changepoint/config.yaml`. It is the only
defaults file for this feature and is unrelated to `src/config/config.yml` (drift). Secrets
(`ANTHROPIC_API_KEY`, AWS creds) stay in `.env` and **never** appear in `config.yaml`.

## `config.yaml` layout (defaults)

```yaml
models:
  visual_model_id: "<Claude Opus 4.8 Bedrock id>"      # POC default, overridable
  decision_model_id: "<Claude Sonnet 4.6 Bedrock id>"  # POC default (was REACT_MODEL_ID)
aws_region: "us-west-2"

visual_analysis_enabled: true

diagnostics:            # EXACTLY the 13 DiagnosticsBundle fields, each defaulting true
  detected_changepoints: true
  latest_changepoint: true
  primary_changepoint: true
  post_changepoint_history_len: true
  post_changepoint_shorter_than_season: true
  seasonal_period: true
  segment_stats: true
  candidate_event_blocks: true
  recurring_event_summary: true
  local_boundary_jumps: true
  candidate_drift_intervals: true
  transient_event_score: true
  permanent_shift_magnitude: true

agent_tools:            # the 5 structural tools + the always-on fallback, each true
  recent_window: true
  full_history_step_regressor: true
  full_history_ramp_regressor: true
  full_history_clean_event: true
  full_history_prophet_tuned_holidays: true
  full_history_default: true            # always-on fallback; MAY NOT be set false

split:
  source: golden        # use the scenario's golden metadata split verbatim
  # override (optional) — supply EITHER ratios OR absolute, never both:
  # units: ratios
  # train_ratio: 0.76
  # val_ratio: 0.12
  # test_ratio: 0.12
  # --- or ---
  # units: absolute
  # train_rows: 760
  # val_rows: 120
  # test_rows: 120

seed: 1729
```

## Per-run override

A run supplies a `ConfigOverride` of the **same shape** (possibly partial). Merge rules
(`resolve.py`):
- **scalars** (`models.*`, `aws_region`, `visual_analysis_enabled`, `seed`): replace if present.
- **`diagnostics` / `agent_tools`**: merge **key-wise** — an override may flip a subset; it MUST NOT
  introduce a key absent from the defaults (→ `ConfigError`).
- **`split`**: **replace as a unit** — if the override contains any split key, the whole `split` block
  is taken from the override (prevents golden+override hybrids and keeps the ambiguity check clean).

Order is **merge → validate → record**. The fully-resolved `EffectiveConfig.to_dict()` is written to
`reports/changepoint/<run_id>/effective_config.json` (SC-007/SC-012).

## Validation (all raise `ConfigError(RuntimeError)` naming the offending field — FR-010/SC-008)

1. **Lockstep** (`assert_config_in_lockstep`): the `diagnostics` key-set MUST equal the live
   `DiagnosticsBundle` field-set exactly; the `agent_tools` key-set MUST equal the **structural**
   tool names exactly **plus** `full_history_default`. Any symmetric difference (unknown OR missing)
   fails. The pipeline injects both reference sets (via `dataclasses.fields` and the registry) so core
   holds no changepoint symbols.
2. **Values**: every `diagnostics`/`agent_tools` value is a `bool`; model ids are non-empty strings;
   `seed` is an int.
3. **Fallback guard**: an override setting `agent_tools.full_history_default: false` → `ConfigError`.
4. **Split**: delegated to `resolve_split` (see `split_resolver.md`); a `SplitError` is surfaced as-is.

## Lockstep test (SC-003)

`tests/pipelines/changepoint/test_config_lockstep.py` loads the committed `config.yaml`, reflects
`dataclasses.fields(DiagnosticsBundle)` and the live registry's structural tool names, and asserts the
config key-sets equal them exactly. Reflecting **live symbols** (not literal lists) prevents the test
from rotting when a field/tool is added.

## SC-007 round-trip

`EffectiveConfig.to_dict`/`from_dict` round-trips losslessly. `SplitProvenance` records resolved
absolute rows + `source`. Re-ingesting a recorded `effective_config.json` as the next run's override
reproduces identical deterministic metrics; provenance is **stable** (golden→golden, override→override —
see `split_resolver.md`).
