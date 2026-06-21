"""LLM provider abstraction — Bedrock (primary) and Anthropic direct API (fallback).

This is the ONLY module that imports provider SDKs (``langchain_aws``, ``anthropic``), so the
model is swappable and mockable (Constitution architecture, FR-001). On a provider error naming the
configured model, the error is surfaced explicitly — never a silent fallback (FR-036, SC-010).

Model ids and llm_provider come from ``EffectiveConfig`` (no env reads here beyond what the SDKs
read automatically: ``AWS_*`` for boto, ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_BASE_URL`` for the
anthropic SDK). ``build_react_model`` from the POC is renamed ``build_decision_model`` (spec
vocabulary); ``build_visual_model`` is unchanged.

Provider selection
------------------
``llm_provider`` on ``ModelConfig`` drives which backend is used:
  - ``"bedrock"``   — ``ChatBedrockConverse`` via ``langchain_aws`` (original path, unchanged).
  - ``"anthropic"`` — Native Anthropic SDK via ``AnthropicStructuredClient``, which duck-types
    the ``ChatBedrockConverse.with_structured_output`` contract ``ModelWrapper`` depends on.
    Uses ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_BASE_URL`` from env (same as boto reads ``AWS_*``).
    TLS: validated with the system CA bundle (Walmart proxy); never ``verify=False``.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, TypeVar

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_MAX_PARSE_RETRIES = 3
_RETRY_DELAY_S = 2.0

# System CA bundle used for Anthropic calls (trusts the Walmart gateway proxy certificate).
_SYSTEM_CA_BUNDLE = "/opt/homebrew/etc/openssl@3/cert.pem"


class ModelUnavailableError(RuntimeError):
    """Raised when a configured model id cannot be used — no fallback is attempted."""


# ---------------------------------------------------------------------------
# Anthropic direct-API structured-output client
# ---------------------------------------------------------------------------

class _AnthropicStructuredOutputProxy:
    """Returned by ``AnthropicStructuredClient.with_structured_output(schema)``.

    Exposes a single ``.invoke(messages)`` method that calls the Anthropic API with
    tool_use forced to ``schema``, translates the LangChain message/content format that
    ``ModelWrapper`` passes, and returns a validated pydantic instance.
    """

    def __init__(self, client: "anthropic.Anthropic", model_id: str, schema: type[T], max_tokens: int) -> None:
        self._client = client
        self._model_id = model_id
        self._schema = schema
        self._max_tokens = max_tokens

    @staticmethod
    def _translate_content(content: str | list) -> list[dict]:
        """Translate LangChain content (str or list of dicts) to Anthropic content blocks."""
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        blocks: list[dict] = []
        for item in content:
            if item.get("type") == "text":
                blocks.append({"type": "text", "text": item["text"]})
            elif item.get("type") == "image":
                # LangChain Bedrock shape: {"type":"image","source_type":"base64","mime_type":...,"data":...}
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": item.get("mime_type", "image/png"),
                        "data": item["data"],
                    },
                })
        return blocks

    def invoke(self, messages: list) -> T:
        """Invoke the model with tool_use structured output; return validated pydantic instance."""
        import anthropic

        tool_name = f"structured_{self._schema.__name__.lower()}"
        tool_schema = {
            "name": tool_name,
            "description": f"Return a structured {self._schema.__name__} response.",
            "input_schema": self._schema.model_json_schema(),
        }

        anthropic_messages = []
        for msg in messages:
            # LangChain HumanMessage has a .content attribute
            content = msg.content if hasattr(msg, "content") else msg
            anthropic_messages.append({
                "role": "user",
                "content": self._translate_content(content),
            })

        response = self._client.messages.create(
            model=self._model_id,
            max_tokens=self._max_tokens,
            messages=anthropic_messages,
            tools=[tool_schema],
            tool_choice={"type": "tool", "name": tool_name},
        )

        tool_block = next(
            (b for b in response.content if b.type == "tool_use"),
            None,
        )
        if tool_block is None:
            raise ModelUnavailableError(
                f"Anthropic model '{self._model_id}' returned no tool_use block."
            )

        raw: dict = tool_block.input
        try:
            return self._schema.model_validate(raw)
        except ValidationError as exc:
            raise ValidationError(exc.errors()) from exc  # let retry logic catch it


class AnthropicStructuredClient:
    """Duck-type replacement for ``ChatBedrockConverse`` for the ``ModelWrapper`` seam.

    Only exposes ``.with_structured_output(schema)`` — the single method ``ModelWrapper`` calls.
    Credentials and base_url are read automatically from ``ANTHROPIC_API_KEY`` /
    ``ANTHROPIC_BASE_URL`` environment variables (mirrors how boto reads ``AWS_*``).
    """

    def __init__(self, model_id: str, *, max_tokens: int) -> None:
        import anthropic
        import httpx

        self._model_id = model_id
        self._max_tokens = max_tokens
        self._client = anthropic.Anthropic(
            http_client=httpx.Client(verify=_SYSTEM_CA_BUNDLE),
        )

    def with_structured_output(self, schema: type[T]) -> _AnthropicStructuredOutputProxy:
        return _AnthropicStructuredOutputProxy(
            self._client, self._model_id, schema, self._max_tokens
        )


# ---------------------------------------------------------------------------
# Provider-aware model factories
# ---------------------------------------------------------------------------

def build_visual_model(
    model_id: str,
    region_name: str,
    *,
    max_tokens: int = 2000,
    llm_provider: str = "bedrock",
) -> ChatBedrockConverse | AnthropicStructuredClient:
    """Build a visual-node LLM client for the given provider.

    Returns ``ChatBedrockConverse`` for ``"bedrock"`` (original path, unchanged) or
    ``AnthropicStructuredClient`` for ``"anthropic"``.
    """
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
) -> ChatBedrockConverse | AnthropicStructuredClient:
    """Build a decision-node LLM client for the given provider."""
    if llm_provider == "anthropic":
        return AnthropicStructuredClient(model_id, max_tokens=max_tokens)
    return ChatBedrockConverse(model=model_id, region_name=region_name, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# Retry + error helpers
# ---------------------------------------------------------------------------

def _wrap_model_error(model_id: str, exc: Exception) -> ModelUnavailableError:
    return ModelUnavailableError(
        f"Model '{model_id}' could not be invoked ({type(exc).__name__}: {exc}). "
        "Verify the configured visual/decision model id and provider access. "
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
        except ModelUnavailableError:
            raise  # already wrapped — propagate immediately
        except Exception as exc:  # noqa: BLE001
            raise _wrap_model_error(model_id, exc) from exc
    raise _wrap_model_error(model_id, last_exc) from last_exc


# ---------------------------------------------------------------------------
# ModelWrapper — interface unchanged; tests inject FakeModelWrapper here
# ---------------------------------------------------------------------------

class ModelWrapper:
    """Thin wrapper over an LLM client for one node (visual or decision).

    The single seam the agent talks to. Tests inject a ``FakeModelWrapper`` implementing the same
    two methods, so no production code reaches the provider SDK during deterministic graph tests.
    Accepts either ``ChatBedrockConverse`` or ``AnthropicStructuredClient`` as ``client``.
    """

    def __init__(self, client: Any, model_id: str) -> None:
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
