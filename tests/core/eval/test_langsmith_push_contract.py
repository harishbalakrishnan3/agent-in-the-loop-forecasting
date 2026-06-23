"""Test-first (Principle II) — the domain-agnostic LangSmith push contract in
ailf.core.eval.langsmith_push, exercised with a FAKE client (no network).

Asserts: inputs_projector + metadata_builder are called per record; the 0.8.15 examples=[{...}]
list form (not parallel inputs/outputs lists); the refresh_guard raises on a count mismatch and
reuses on a match; make_replay_target echoes by scenario_id; experiment_url reads .url.
"""

from __future__ import annotations

import pytest

from ailf.core.eval.langsmith_push import (
    ensure_dataset,
    experiment_url,
    make_replay_target,
)


class _FakeDataset:
    def __init__(self, id="d1"):
        self.id = id


class _FakeClient:
    """Minimal stand-in for langsmith.Client recording the create_examples call."""
    def __init__(self, existing=None, existing_count=0):
        self._existing = existing            # name -> bool exists
        self._existing_count = existing_count
        self.created_examples = None
        self.created_dataset = None

    def has_dataset(self, *, dataset_name):
        return bool(self._existing and dataset_name in self._existing)

    def read_dataset(self, *, dataset_name):
        return _FakeDataset()

    def create_dataset(self, name, description=None):
        self.created_dataset = name
        return _FakeDataset()

    def create_examples(self, *, dataset_id, examples, max_concurrency=1):
        self.created_examples = examples

    # for the refresh_guard count check
    def list_examples(self, *, dataset_id):
        return [object()] * self._existing_count


def _records():
    return [{"scenario_id": "a", "x": 1}, {"scenario_id": "b", "x": 2}]


def test_create_examples_uses_modern_list_form_and_calls_seams():
    c = _FakeClient()
    calls = {"inputs": 0, "meta": 0}

    def inputs_projector(rec):
        calls["inputs"] += 1
        return {"sid": rec["scenario_id"]}

    def metadata_builder(rec):
        calls["meta"] += 1
        return {"m": rec["x"]}

    ensure_dataset(c, "ds-new", _records(),
                   inputs_projector=inputs_projector, metadata_builder=metadata_builder)
    assert calls["inputs"] == 2 and calls["meta"] == 2
    ex = c.created_examples
    assert isinstance(ex, list) and len(ex) == 2
    # modern 0.8.15 form: each item is a dict with inputs/outputs/metadata (NOT parallel lists)
    assert set(ex[0]) >= {"inputs", "outputs", "metadata"}
    assert ex[0]["inputs"] == {"sid": "a"} and ex[0]["outputs"]["scenario_id"] == "a"
    assert ex[0]["metadata"] == {"m": 1}


def test_refresh_guard_raises_on_count_mismatch():
    # existing dataset has 5 examples but we push 2 -> stale-dataset trap -> raise
    c = _FakeClient(existing={"ds-x"}, existing_count=5)
    with pytest.raises(RuntimeError):
        ensure_dataset(c, "ds-x", _records(),
                       inputs_projector=lambda r: {}, metadata_builder=lambda r: {})


def test_refresh_guard_reuses_on_count_match():
    c = _FakeClient(existing={"ds-x"}, existing_count=2)  # matches len(_records())
    # should NOT raise, should NOT re-create examples (reuse)
    ensure_dataset(c, "ds-x", _records(),
                   inputs_projector=lambda r: {}, metadata_builder=lambda r: {})
    assert c.created_examples is None and c.created_dataset is None


def test_make_replay_target_echoes_by_scenario_id():
    recs = _records()
    target = make_replay_target(recs)
    assert target({"scenario_id": "b"})["x"] == 2


def test_experiment_url_reads_dot_url():
    class R:
        url = "https://smith/exp/1"
    assert experiment_url(R()) == "https://smith/exp/1"
