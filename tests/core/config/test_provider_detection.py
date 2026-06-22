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


def _byo_defaults():
    return {
        "models": {
            "visual_model_id": "us.anthropic.claude-opus-4-8",
            "decision_model_id": "us.anthropic.claude-sonnet-4-6",
        },
        "aws_region": "us-west-2",
        "visual_analysis_enabled": True,
        "diagnostics": {"d1": True},
        "agent_tools": {"t1": True, "full_history_default": True},
        "split": {"units": "golden"},
        "seed": 1729,
    }


def _resolve_byo(creds):
    from ailf.core.config.resolve import resolve_config

    return resolve_config(
        _byo_defaults(), None,
        diagnostics_field_names={"d1"}, structural_tool_names={"t1"},
        credentials=creds,
    )


def test_byo_anthropic_key_forces_anthropic_and_translates_model_ids(monkeypatch):
    """An explicit BYO Anthropic key forces the Anthropic provider even with NO server env
    credentials, and Bedrock-form model ids are translated to native Anthropic ids."""
    from ailf.core.config.schema import RunCredentials

    _clear(monkeypatch)  # neither ANTHROPIC_API_KEY nor AWS_ACCESS_KEY_ID in env
    cfg = _resolve_byo(RunCredentials(anthropic_api_key="sk-ant-byo-test"))
    assert cfg.models.llm_provider == "anthropic"
    assert cfg.models.visual_model_id == "claude-opus-4-8"      # translated from Bedrock-form
    assert cfg.models.decision_model_id == "claude-sonnet-4-6"


def test_byo_aws_creds_force_bedrock_and_override_region(monkeypatch):
    """Explicit BYO AWS creds force the Bedrock provider (no env creds) and the supplied region wins;
    Bedrock-form model ids are kept as-is (no translation)."""
    from ailf.core.config.schema import RunCredentials

    _clear(monkeypatch)
    cfg = _resolve_byo(RunCredentials(
        aws_access_key_id="AKIA-byo", aws_secret_access_key="secret-byo", aws_region="eu-west-1",
    ))
    assert cfg.models.llm_provider == "bedrock"
    assert cfg.models.visual_model_id == "us.anthropic.claude-opus-4-8"  # unchanged for Bedrock
    assert cfg.models.aws_region == "eu-west-1"


def test_byo_anthropic_wins_when_both_kinds_present(monkeypatch):
    from ailf.core.config.schema import RunCredentials

    _clear(monkeypatch)
    cfg = _resolve_byo(RunCredentials(
        anthropic_api_key="sk-ant-byo", aws_access_key_id="AKIA", aws_secret_access_key="sec",
    ))
    assert cfg.models.llm_provider == "anthropic"
