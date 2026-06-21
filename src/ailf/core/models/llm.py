"""Chat-model wrapper + structured-output helpers.

This is the ONLY module that imports the provider SDK, so the model is
swappable and mockable (Constitution architecture, FR-001). On an error naming the
configured model, the error is surfaced explicitly — never a silent fallback (FR-036, SC-010).

## LOCAL SWAP (Anthropic direct API instead of Bedrock)
## To revert: uncomment the Bedrock lines, comment out the Anthropic lines.
## Search for "# SWAP:" to find all changed lines.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import TypeVar

# SWAP: Original Bedrock import (uncomment to revert)
# from langchain_aws import ChatBedrockConverse
# SWAP: Anthropic direct API (comment out to revert)
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_MAX_PARSE_RETRIES = 3
_RETRY_DELAY_S = 2.0

# SWAP: Anthropic model name mapping (Bedrock uses "us.anthropic.claude-*", direct API uses "claude-*")
_ANTHROPIC_MODEL_MAP = {
    "us.anthropic.claude-opus-4-8": "claude-opus-4-8",
    "us.anthropic.claude-sonnet-4-6": "claude-sonnet-4-6",
}


def _resolve_model_id(model_id: str) -> str:
    """Map Bedrock model IDs to Anthropic direct API IDs."""
    return _ANTHROPIC_MODEL_MAP.get(model_id, model_id)


class ModelUnavailableError(RuntimeError):
    """Raised when a configured model id cannot be used — no fallback is attempted."""


# SWAP: Original Bedrock builders (uncomment to revert)
# def build_visual_model(model_id: str, region_name: str, *, max_tokens: int = 2000) -> ChatBedrockConverse:
#     return ChatBedrockConverse(model=model_id, region_name=region_name, max_tokens=max_tokens)
#
# def build_decision_model(model_id: str, region_name: str, *, max_tokens: int = 2400) -> ChatBedrockConverse:
#     return ChatBedrockConverse(model=model_id, region_name=region_name, max_tokens=max_tokens)

# SWAP: Anthropic direct API builders (comment out to revert)
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


def _wrap_bedrock_error(model_id: str, exc: Exception) -> ModelUnavailableError:
    return ModelUnavailableError(
        f"Model '{model_id}' could not be invoked ({type(exc).__name__}: {exc}). "
        "Verify the configured visual/decision model id and API access. "
        "The system does not silently substitute a different model."
    )


def _invoke_with_retry(structured, messages, model_id: str):
    """Invoke a structured-output chain, retrying on parse failures (ValidationError)."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_PARSE_RETRIES):
        try:
            return structured.invoke(messages)
        except ValidationError as exc:
            last_exc = exc
            if attempt < _MAX_PARSE_RETRIES - 1:
                time.sleep(_RETRY_DELAY_S)
        except Exception as exc:  # noqa: BLE001
            raise _wrap_bedrock_error(model_id, exc) from exc
    raise _wrap_bedrock_error(model_id, last_exc) from last_exc


class ModelWrapper:
    """Thin wrapper over a chat model client for one node (visual or decision).

    The single seam the agent talks to. Tests inject a ``FakeModelWrapper`` implementing the same
    two methods, so no production code reaches the provider SDK during deterministic graph tests.
    """

    # SWAP: Original type hint (uncomment to revert)
    # def __init__(self, client: ChatBedrockConverse, model_id: str) -> None:
    # SWAP: Anthropic type hint (comment out to revert)
    def __init__(self, client: ChatAnthropic, model_id: str) -> None:
        self._client = client
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def invoke_structured_text(self, *, prompt: str, schema: type[T]) -> T:
        """Invoke a text-only prompt and parse the reply into ``schema`` (structured output)."""
        structured = self._client.with_structured_output(schema)
        return _invoke_with_retry(structured, [HumanMessage(content=prompt)], self._model_id)

    def invoke_structured_with_image(self, *, prompt: str, image_path: Path, schema: type[T]) -> T:
        """Invoke a multimodal (text + PNG) prompt and parse the reply into ``schema``."""
        image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": prompt},
            {"type": "image", "source_type": "base64", "mime_type": "image/png", "data": image_b64},
        ]
        structured = self._client.with_structured_output(schema)
        return _invoke_with_retry(structured, [HumanMessage(content=content)], self._model_id)
