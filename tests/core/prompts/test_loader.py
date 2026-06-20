"""T015 — generic prompt loader (test-first)."""

from __future__ import annotations

import pytest

from ailf.core.prompts.loader import load_prompt


def test_load_prompt_reads_versioned_file(tmp_path):
    (tmp_path / "greet_v1.md").write_text("Hello {{name}}, welcome.")
    text = load_prompt(tmp_path, "greet", 1, fill={"name": "Ada"})
    assert text == "Hello Ada, welcome."


def test_load_prompt_without_fill_returns_raw(tmp_path):
    (tmp_path / "x_v2.md").write_text("no placeholders here")
    assert load_prompt(tmp_path, "x", 2) == "no placeholders here"


def test_load_prompt_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prompt(tmp_path, "nope", 1)


def test_unfilled_placeholder_raises(tmp_path):
    (tmp_path / "p_v1.md").write_text("needs {{tool_menu}}")
    with pytest.raises(KeyError):
        load_prompt(tmp_path, "p", 1, fill={})
