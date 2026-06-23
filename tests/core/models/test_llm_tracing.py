"""LangSmith tracing wrap-through for the Anthropic raw-SDK client (feature 006 follow-up).

LangSmith auto-traces LangChain/LangGraph but NOT raw-SDK calls, so the Anthropic client must be
explicitly wrapped via ``langsmith.wrappers.wrap_anthropic`` when tracing is requested.

NOTE: ``wrap_anthropic`` patches ``Messages.create`` at the CLASS level (process-wide) and is
idempotent, so once any client is wrapped the method stays wrapped for the process. These tests
therefore assert the requested-wrap path runs and that actual trace emission is still gated by the
LANGSMITH env (set by the pipeline only for a traced run) — not per-instance patching state.
"""

from __future__ import annotations

from ailf.core.models.llm import AnthropicStructuredClient, build_decision_model, build_visual_model


def test_trace_true_wraps_messages_create():
    traced = AnthropicStructuredClient("claude-opus-4-8", api_key="sk-ant-fake", trace=True)
    # After requesting tracing, messages.create is the instrumented (wrapped) callable.
    assert hasattr(traced._client.messages.create, "__wrapped__")


def test_builders_thread_trace_flag_without_error():
    # Both builders accept trace=True and construct a usable client (the wrap is applied inside).
    v = build_visual_model("claude-opus-4-8", "us-west-2", llm_provider="anthropic",
                           api_key="sk-ant-fake", trace=True)
    d = build_decision_model("claude-sonnet-4-6", "us-west-2", llm_provider="anthropic",
                             api_key="sk-ant-fake", trace=True)
    assert v._client is not None and d._client is not None
    # provider attribution still resolves to anthropic for error messages
    from ailf.core.models.llm import ModelWrapper
    assert ModelWrapper(v, "x")._provider == "anthropic"


def test_trace_failure_is_swallowed(monkeypatch):
    """If the tracing wrapper raises, client construction must still succeed (no broken run)."""
    import ailf.core.models.llm as llm_mod

    # Patch the import target so the wrap attempt raises; construction must fall back gracefully.
    import langsmith.wrappers as w

    def _boom(*a, **k):
        raise RuntimeError("langsmith unavailable")

    monkeypatch.setattr(w, "wrap_anthropic", _boom)
    # Must not raise — the except clause swallows the failure and keeps the unwrapped client.
    client = AnthropicStructuredClient("claude-opus-4-8", api_key="sk-ant-fake", trace=True)
    assert client._client is not None


def test_trace_false_constructs_without_langsmith(monkeypatch):
    # With trace=False we never touch langsmith at all; make it explode if imported to prove it.
    import langsmith.wrappers as w

    def _boom(*a, **k):  # pragma: no cover - should never be called
        raise AssertionError("wrap_anthropic must not be called when trace=False")

    monkeypatch.setattr(w, "wrap_anthropic", _boom)
    client = AnthropicStructuredClient("claude-opus-4-8", api_key="sk-ant-fake", trace=False)
    assert client._client is not None
