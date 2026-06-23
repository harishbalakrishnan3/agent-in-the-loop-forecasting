"""Test-first (Principle II / III:73-75) — the DETERMINISTIC plumbing around the LLM judge.

The judge's VERDICT is non-deterministic and is NEVER unit-asserted (Principle III). But the
plumbing around it IS: the score=1/0/None contract, the n/a + judge_error handling, and that
build_judge_model takes plain model_id/region args (no use-case env read). A FAKE model is injected
so this test makes NO Bedrock call.
"""

from __future__ import annotations

import inspect

import pytest

from ailf.core.eval.judge import Verdict, build_judge_model, make_rationale_judge


class _FakeModel:
    """Duck-types ModelWrapper.invoke_structured_text; returns a canned verdict or raises."""
    def __init__(self, verdict=None, raises=None):
        self._verdict, self._raises = verdict, raises

    def invoke_structured_text(self, *, prompt, schema):
        if self._raises:
            raise self._raises
        return self._verdict


@pytest.fixture
def prompt_dir(tmp_path):
    """A real versioned prompt with the three placeholders the judge fills."""
    (tmp_path / "x_v1.md").write_text(
        "Judge this.\n{{diagnostics}}\n{{chosen_tool}}\n{{rationale}}\n")
    return tmp_path


def _judge(model, prompt_dir, *, text="some rationale",
           tool="full_history_prophet_tuned_holidays", diag=None):
    # extract_fn is the pipeline-injected seam; here it returns fixed values.
    def extract_fn(rec):
        return text, tool, (diag or {"k": "v"})
    return make_rationale_judge(prompt_dir=prompt_dir, prompt_name="x", version=1,
                                extract_fn=extract_fn, model=model)


def test_verdict_adheres_scores_1(prompt_dir):
    ev = _judge(_FakeModel(Verdict(verdict="adheres", reason="ok")), prompt_dir)
    out = ev({"outputs": {}}, None)
    assert out["key"] == "rationale_adheres" and out["score"] == 1


def test_verdict_rationalizes_scores_0(prompt_dir):
    ev = _judge(_FakeModel(Verdict(verdict="rationalizes", reason="bad")), prompt_dir)
    assert ev({"outputs": {}}, None)["score"] == 0


def test_malformed_verdict_scores_0_not_none(prompt_dir):
    # ANY non-'adheres' string -> 0 (never None). A judge that returns garbage must not look like n/a.
    ev = _judge(_FakeModel(Verdict(verdict="??garbage??", reason="")), prompt_dir)
    assert ev({"outputs": {}}, None)["score"] == 0


def test_empty_rationale_scores_none_na(prompt_dir):
    ev = _judge(_FakeModel(Verdict(verdict="adheres", reason="x")), prompt_dir, text="")  # no text to judge
    out = ev({"outputs": {}}, None)
    assert out["score"] is None and out["value"] == "n/a_no_rationale"


def test_model_error_scores_none_judge_error(prompt_dir):
    ev = _judge(_FakeModel(raises=RuntimeError("boom")), prompt_dir)
    out = ev({"outputs": {}}, None)
    assert out["score"] is None and out["value"].startswith("judge_error:")


def test_build_judge_model_takes_plain_args_no_env_read():
    import ailf.core.eval.judge as judge_mod
    sig = inspect.signature(build_judge_model)
    assert "model_id" in sig.parameters and "region" in sig.parameters
    # core judge must not bake in use-case env names (Principle I: core stays use-case-free)
    src = open(judge_mod.__file__).read()
    assert "REACT_MODEL_ID" not in src and "AWS_REGION" not in src
    assert "os.getenv" not in src and "os.environ" not in src
