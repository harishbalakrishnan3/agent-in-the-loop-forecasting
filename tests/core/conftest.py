"""Shared core test fixtures — T014: a FakeModelWrapper test double.

Implements the same two methods as ``ailf.core.models.llm.ModelWrapper`` so deterministic graph
tests never reach Bedrock. Returns caller-supplied canned pydantic objects, records every
``(prompt, image_path)`` it saw (for leakage / visual-first assertions), and can raise
``ModelUnavailableError`` to exercise the fail-fast path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ailf.core.models.llm import ModelUnavailableError


class FakeModelWrapper:
    """Drop-in stand-in for ``ModelWrapper`` with no provider dependency."""

    def __init__(
        self,
        *,
        model_id: str = "fake-model",
        responses: list[Any] | None = None,
        raise_unavailable: bool = False,
    ) -> None:
        self._model_id = model_id
        self._responses = list(responses or [])
        self._raise_unavailable = raise_unavailable
        self.calls: list[dict[str, Any]] = []  # records {kind, prompt, image_path, schema}

    @property
    def model_id(self) -> str:
        return self._model_id

    def _next(self, schema: type) -> Any:
        if self._raise_unavailable:
            raise ModelUnavailableError(f"fake: model {self._model_id!r} unavailable")
        if not self._responses:
            raise AssertionError("FakeModelWrapper ran out of canned responses")
        return self._responses.pop(0)

    def invoke_structured_text(self, *, prompt: str, schema: type) -> Any:
        self.calls.append({"kind": "text", "prompt": prompt, "image_path": None, "schema": schema})
        return self._next(schema)

    def invoke_structured_with_image(self, *, prompt: str, image_path: Path, schema: type) -> Any:
        self.calls.append(
            {"kind": "image", "prompt": prompt, "image_path": image_path, "schema": schema}
        )
        return self._next(schema)


@pytest.fixture
def make_fake_model():
    """Factory so a test can build a fake with its own canned responses."""

    def _factory(**kwargs: Any) -> FakeModelWrapper:
        return FakeModelWrapper(**kwargs)

    return _factory
