"""Bedrock chat-model wrapper + structured-output helpers (promoted from the POC ``llm.py``).

This is the ONLY module that imports the provider SDK (``langchain_aws``), so the model is
swappable and mockable (Constitution architecture, FR-001). On a Bedrock error naming the
configured model, the error is surfaced explicitly — never a silent fallback (FR-036, SC-010).

Model ids come from ``EffectiveConfig`` (no env reads here). ``build_react_model`` from the POC is
renamed ``build_decision_model`` (spec vocabulary); ``build_visual_model`` is unchanged.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import TypeVar

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_MAX_PARSE_RETRIES = 3
_RETRY_DELAY_S = 2.0


class ModelUnavailableError(RuntimeError):
    """Raised when a configured model id cannot be used — no fallback is attempted."""


# ---------------------------------------------------------------------------
# Anthropic SDK client (used when llm_provider="anthropic")
# ---------------------------------------------------------------------------

class _AnthropicProxy:
    """Returned by AnthropicStructuredClient.with_structured_output(); has .invoke(messages)."""

    def __init__(self, model_id: str, schema: type, max_tokens: int) -> None:
        self._model_id = model_id
        self._schema = schema
        self._max_tokens = max_tokens

    def invoke(self, messages):
        import anthropic  # noqa: PLC0415

        content_parts = []
        image_parts = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                c = msg.content
                if isinstance(c, str):
                    content_parts.append({"type": "text", "text": c})
                elif isinstance(c, list):
                    for part in c:
                        if part.get("type") == "text":
                            content_parts.append({"type": "text", "text": part["text"]})
                        elif part.get("type") == "image":
                            image_parts.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": part.get("mime_type", "image/png"),
                                    "data": part.get("data", ""),
                                },
                            })

        msg_content = image_parts + content_parts
        schema_json = json.dumps(self._schema.model_json_schema(), indent=2)
        if content_parts:
            content_parts[-1]["text"] += (
                f"\n\nRespond with ONLY valid JSON matching this schema:\n{schema_json}"
            )

        import httpx  # noqa: PLC0415
        # Corporate proxy uses self-signed cert — disable verification for internal network.
        http_client = httpx.Client(verify=False)
        client = anthropic.Anthropic(http_client=http_client)
        response = client.messages.create(
            model=self._model_id,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": msg_content or content_parts}],
        )
        text = response.content[0].text if response.content else ""
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start : end + 1]) if start != -1 and end != -1 else {}
        return self._schema(**data)


class AnthropicStructuredClient:
    """Anthropic SDK client duck-typing ChatBedrockConverse for ModelWrapper."""

    def __init__(self, model_id: str, *, max_tokens: int = 2000) -> None:
        self._model_id = model_id
        self._max_tokens = max_tokens

    def with_structured_output(self, schema: type) -> _AnthropicProxy:
        return _AnthropicProxy(self._model_id, schema, self._max_tokens)


# ---------------------------------------------------------------------------
# Factory functions — dispatch on llm_provider
# ---------------------------------------------------------------------------

def build_visual_model(
    model_id: str,
    region_name: str,
    *,
    max_tokens: int = 2000,
    llm_provider: str = "bedrock",
):
    """Build the visual-node model client. Dispatches on ``llm_provider``."""
    if llm_provider == "anthropic":
        return AnthropicStructuredClient(model_id, max_tokens=max_tokens)
    # No temperature: newer Bedrock models (e.g. Opus 4.8) reject the deprecated parameter.
    return ChatBedrockConverse(model=model_id, region_name=region_name, max_tokens=max_tokens)


def build_decision_model(
    model_id: str,
    region_name: str,
    *,
    max_tokens: int = 2400,
    llm_provider: str = "bedrock",
):
    """Build the decision-node model client. Dispatches on ``llm_provider``."""
    if llm_provider == "anthropic":
        return AnthropicStructuredClient(model_id, max_tokens=max_tokens)
    return ChatBedrockConverse(model=model_id, region_name=region_name, max_tokens=max_tokens)


def _wrap_bedrock_error(model_id: str, exc: Exception) -> ModelUnavailableError:
    return ModelUnavailableError(
        f"Bedrock model '{model_id}' could not be invoked ({type(exc).__name__}: {exc}). "
        "Verify the configured visual/decision model id and Bedrock access in the configured "
        "region. The system does not silently substitute a different model."
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
    """Thin wrapper over a ``ChatBedrockConverse`` client for one node (visual or decision).

    The single seam the agent talks to. Tests inject a ``FakeModelWrapper`` implementing the same
    two methods, so no production code reaches the provider SDK during deterministic graph tests.
    """

    def __init__(self, client: ChatBedrockConverse, model_id: str) -> None:
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
