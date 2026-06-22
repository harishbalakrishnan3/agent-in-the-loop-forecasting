"""T003 — provider detection (Anthropic-first, fail-fast) — contracts/model_selection.md, FR-027/029.

The detection order is flipped to prefer the Anthropic API; when neither provider is configured,
detection raises a clear ConfigError at resolve time (not deferred to first model call).
"""

from __future__ import annotations

import pytest

from ailf.core.config.resolve import ConfigError, _detect_llm_provider

_ANTHROPIC = "ANTHROPIC_API_KEY"
_AWS = "AWS_ACCESS_KEY_ID"


def _clear(monkeypatch):
    monkeypatch.delenv(_ANTHROPIC, raising=False)
    monkeypatch.delenv(_AWS, raising=False)


def test_anthropic_only_returns_anthropic(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(_ANTHROPIC, "sk-test")
    assert _detect_llm_provider() == "anthropic"


def test_bedrock_only_returns_bedrock(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(_AWS, "AKIA-test")
    assert _detect_llm_provider() == "bedrock"


def test_both_set_prefers_anthropic(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(_ANTHROPIC, "sk-test")
    monkeypatch.setenv(_AWS, "AKIA-test")
    assert _detect_llm_provider() == "anthropic"


def test_neither_set_raises_config_error(monkeypatch):
    _clear(monkeypatch)
    with pytest.raises(ConfigError) as exc:
        _detect_llm_provider()
    msg = str(exc.value)
    assert "ANTHROPIC_API_KEY" in msg and "AWS_ACCESS_KEY_ID" in msg


def test_blank_values_are_ignored(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(_ANTHROPIC, "   ")  # whitespace-only → treated as unset
    monkeypatch.setenv(_AWS, "AKIA-test")
    assert _detect_llm_provider() == "bedrock"
