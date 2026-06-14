"""Bedrock chat-model factory + structured-output helpers (T010).

Builds ``ChatBedrockConverse`` clients for the visual and ReAct nodes from config. On a Bedrock
error naming the configured model (unavailable / access denied / not found), the error is
surfaced explicitly — never a silent fallback to another model (FR-024, SC-010).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TypeVar

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from pocs.changepoint.config import PocConfig

T = TypeVar("T", bound=BaseModel)


class ModelUnavailableError(RuntimeError):
    """Raised when a configured Bedrock model id cannot be used — no fallback is attempted."""


def build_visual_model(config: PocConfig) -> ChatBedrockConverse:
    # No temperature: newer Bedrock models (e.g. Opus 4.8) reject the deprecated parameter.
    return ChatBedrockConverse(
        model=config.visual_model_id, region_name=config.aws_region, max_tokens=2000
    )


def build_react_model(config: PocConfig) -> ChatBedrockConverse:
    return ChatBedrockConverse(
        model=config.react_model_id, region_name=config.aws_region, max_tokens=2400
    )


def _wrap_bedrock_error(model_id: str, exc: Exception) -> ModelUnavailableError:
    return ModelUnavailableError(
        f"Bedrock model '{model_id}' could not be invoked ({type(exc).__name__}: {exc}). "
        "Verify VISUAL_MODEL_ID / REACT_MODEL_ID and Bedrock access in the configured region. "
        "The POC does not silently substitute a different model."
    )


def invoke_structured_text(
    model: ChatBedrockConverse, *, model_id: str, prompt: str, schema: type[T]
) -> T:
    """Invoke a text-only prompt and parse the reply into ``schema`` (structured output)."""
    try:
        structured = model.with_structured_output(schema)
        return structured.invoke([HumanMessage(content=prompt)])
    except Exception as exc:  # noqa: BLE001 — re-raised explicitly, never swallowed
        raise _wrap_bedrock_error(model_id, exc) from exc


def invoke_structured_with_image(
    model: ChatBedrockConverse, *, model_id: str, prompt: str, image_path: Path, schema: type[T]
) -> T:
    """Invoke a multimodal (text + PNG image) prompt and parse the reply into ``schema``."""
    image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image", "source_type": "base64", "mime_type": "image/png", "data": image_b64},
    ]
    try:
        structured = model.with_structured_output(schema)
        return structured.invoke([HumanMessage(content=content)])
    except Exception as exc:  # noqa: BLE001 — re-raised explicitly, never swallowed
        raise _wrap_bedrock_error(model_id, exc) from exc
