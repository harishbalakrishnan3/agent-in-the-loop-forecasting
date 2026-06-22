# Contract: Model Selection & Provider Initialization

How the UI's two model selectors map to concrete model clients, and how the backend picks a provider once per run.

## UI side — friendly choices → Bedrock-form ids

`ui/models.py` exposes a fixed catalog. The UI shows the **label**; the override carries the **Bedrock-form id**:

| Role selector | Allowed labels | Emitted `model_id` |
|---|---|---|
| Visual model | Claude Opus 4.8, Claude Sonnet 4.6 | `us.anthropic.claude-opus-4-8` / `us.anthropic.claude-sonnet-4-6` |
| Reasoning (decision) model | Claude Opus 4.8, Claude Sonnet 4.6 | same ids |

- Defaults: visual = Opus 4.8, reasoning = Sonnet 4.6 (match `config.yaml`).
- When `visual_analysis_enabled=false`, the visual selection is ignored by the run (no visual node) — the UI may grey it out (FR-015).
- The UI always emits **Bedrock-form** ids; it never needs to know the active provider.

## Backend side — provider detection (this feature flips it)

`core/config/resolve.py::_detect_llm_provider()` becomes Anthropic-first with fail-fast:

```python
def _detect_llm_provider() -> str:
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    if os.environ.get("AWS_ACCESS_KEY_ID", "").strip():
        return "bedrock"
    raise ConfigError(
        "Neither ANTHROPIC_API_KEY nor AWS_ACCESS_KEY_ID is set. "
        "Set one in .env (Anthropic API is preferred when both are present)."
    )
```

Guarantees:
- **Detected once per run** inside `resolve_config` (FR-027/028).
- **Fail-fast**: neither-configured raises `ConfigError` at resolve time, before any compute (FR-029). The UI catches this and shows a clear pre-run message.
- **Precedence**: Anthropic API preferred when both are configured.

## Model-id translation (unchanged, relied upon)

When provider is `anthropic`, `resolve_config` translates Bedrock-form ids to native via `_BEDROCK_TO_ANTHROPIC_MODEL_ID` (`resolve.py:27-46`):

| Bedrock-form (from UI) | Native (Anthropic API) |
|---|---|
| `us.anthropic.claude-opus-4-8` | `claude-opus-4-8` |
| `us.anthropic.claude-sonnet-4-6` | `claude-sonnet-4-6` |

When provider is `bedrock`, ids are used as-is. So the UI's two choices work on either provider with no UI awareness of which one is active.

## Client construction (per run)

`pipeline.py:234-241` builds one `ModelWrapper` per role via `build_visual_model` / `build_decision_model`, dispatching on the detected provider (`llm.py:106-130`). Two role clients per run is the intended "one-time clean initialization."

**Optional, non-blocking hardening** (may be done now or deferred): the Anthropic proxy currently constructs an `anthropic.Anthropic` client on every invoke (`llm.py:76-79`); moving it into `AnthropicStructuredClient.__init__` makes it once-per-role. The `httpx.Client(verify=False)` SSL behavior is a known wart, out of scope here.

## Out of scope

- Adding non-Claude providers, model auto-discovery, or per-call model overrides.
- Changing `aws_region` handling (defaults from config; overridable but not surfaced in the UI).
