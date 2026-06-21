# Local Swap Guide: Bedrock → Anthropic Direct API

Run the pipeline locally with your personal Anthropic API key instead of AWS Bedrock.

> **DO NOT COMMIT** any of these changes. They are for local testing only.

---

## Prerequisites

1. An Anthropic API key (starts with `sk-ant-api...`)
2. `langchain-anthropic` installed (already added to `pyproject.toml`)
3. VPN **disconnected** (needed for both Anthropic API and LangSmith tracing)

---

## Step 1: `.env` — Add your Anthropic key

```dotenv
# Add this line (your key):
ANTHROPIC_API_KEY=sk-ant-api03-...your-key-here...

# Optional: enable LangSmith tracing
LANGSMITH_TRACING=true
```

---

## Step 2: `pyproject.toml` — Add dependency (already done)

Line 26 was added:

```toml
    "langchain-anthropic>=1.4.6",
```

Then run `uv sync` to update `uv.lock` and install it.

> **Are pyproject.toml / uv.lock changes necessary?**
> YES — `langchain-anthropic` is the SDK that talks to Anthropic's direct API.
> Without it, the import in `llm.py` fails. However, since `langchain-aws` is
> still listed too, both coexist — no harm if you leave it in, just don't commit.

---

## Step 3: `src/ailf/core/models/llm.py` — The swap

There are **4 swap points** (search for `# SWAP:`):

### Swap Point 1: Import (lines ~21-23)

```python
# COMMENT OUT (Bedrock):
# from langchain_aws import ChatBedrockConverse

# UNCOMMENT (Anthropic):
from langchain_anthropic import ChatAnthropic
```

### Swap Point 2: Model name mapping (lines ~33-40)

**ADD this block** (not present in original):

```python
_ANTHROPIC_MODEL_MAP = {
    "us.anthropic.claude-opus-4-8": "claude-opus-4-8",
    "us.anthropic.claude-sonnet-4-6": "claude-sonnet-4-6",
}

def _resolve_model_id(model_id: str) -> str:
    """Map Bedrock model IDs to Anthropic direct API IDs."""
    return _ANTHROPIC_MODEL_MAP.get(model_id, model_id)
```

> Note: Visual model maps to `claude-opus-4-8` (strongest reasoning),
> decision model maps to `claude-sonnet-4-6` (fast + capable).

### Swap Point 3: Builder functions (lines ~50-70)

```python
# COMMENT OUT (Bedrock):
# def build_visual_model(model_id: str, region_name: str, *, max_tokens: int = 2000) -> ChatBedrockConverse:
#     return ChatBedrockConverse(model=model_id, region_name=region_name, max_tokens=max_tokens)
#
# def build_decision_model(model_id: str, region_name: str, *, max_tokens: int = 2400) -> ChatBedrockConverse:
#     return ChatBedrockConverse(model=model_id, region_name=region_name, max_tokens=max_tokens)

# UNCOMMENT (Anthropic):
def build_visual_model(model_id: str, region_name: str, *, max_tokens: int = 2000) -> ChatAnthropic:
    return ChatAnthropic(
        model=_resolve_model_id(model_id),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        max_tokens=max_tokens,
    )

def build_decision_model(model_id: str, region_name: str, *, max_tokens: int = 2400) -> ChatAnthropic:
    return ChatAnthropic(
        model=_resolve_model_id(model_id),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        max_tokens=max_tokens,
    )
```

### Swap Point 4: ModelWrapper type hint (line ~107)

```python
# COMMENT OUT (Bedrock):
# def __init__(self, client: ChatBedrockConverse, model_id: str) -> None:

# UNCOMMENT (Anthropic):
def __init__(self, client: ChatAnthropic, model_id: str) -> None:
```

---

## Running

```bash
# Source .env and run (must be disconnected from VPN):
set -a && source .env && set +a
.venv/bin/python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality
```

---

## Reverting

1. In `llm.py`: uncomment all `ChatBedrockConverse` lines, comment out all `ChatAnthropic` lines, remove the `_ANTHROPIC_MODEL_MAP` block.
2. Optionally remove `"langchain-anthropic>=1.4.6"` from `pyproject.toml` and re-run `uv sync`.
3. Or just `git checkout src/ailf/core/models/llm.py pyproject.toml uv.lock`.

---

## Summary of changed files (DO NOT COMMIT)

| File | Change |
|------|--------|
| `.env` | Added `ANTHROPIC_API_KEY`, set `LANGSMITH_TRACING=true` |
| `pyproject.toml` | Added `langchain-anthropic>=1.4.6` to dependencies |
| `uv.lock` | Auto-updated by `uv sync` (adds anthropic + langchain-anthropic packages) |
| `src/ailf/core/models/llm.py` | Swapped Bedrock → Anthropic at 4 points |
