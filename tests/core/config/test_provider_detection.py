"""T003 — provider detection (Anthropic-first; sentinel when unconfigured) — model_selection.md, FR-027/029.

The detection order is flipped to prefer the Anthropic API. When neither provider is configured,
detection returns the ``LLM_PROVIDER_UNCONFIGURED`` sentinel (it never raises) so config resolution
stays credential-free for the deterministic test suite; the clear fail-fast for a REAL run lives in
the pipeline (covered by test_pipeline_smoke).
"""

from __future__ import annotations

from ailf.core.config.resolve import LLM_PROVIDER_UNCONFIGURED, _detect_llm_provider

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


def test_neither_set_returns_unconfigured_sentinel(monkeypatch):
    _clear(monkeypatch)
    assert _detect_llm_provider() == LLM_PROVIDER_UNCONFIGURED


def test_blank_values_are_ignored(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(_ANTHROPIC, "   ")  # whitespace-only → treated as unset
    monkeypatch.setenv(_AWS, "AKIA-test")
    assert _detect_llm_provider() == "bedrock"
