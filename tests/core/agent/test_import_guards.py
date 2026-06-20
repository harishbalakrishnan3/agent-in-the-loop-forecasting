"""T065 — import-cleanliness guards (SC-002, cross-cutting notes 2/3, research Decision 15).

- langgraph is imported ONLY by ailf.core.agent.engine.
- langchain_aws is imported ONLY by ailf.core.models.llm.
- Importing core.backtest / core.agent.registry / core.events does NOT transitively pull
  ailf.core.datasets (Darts-coupled) or darts.
- The changepoint pipeline imports only ailf.core.* + stdlib/third-party, not another pipeline.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_CORE = Path("src/ailf/core")
_PIPE = Path("src/ailf/pipelines/changepoint")


def _modules_importing(token: str, root: Path) -> set[str]:
    """Return module file paths whose AST actually IMPORTS a module named (or under) ``token``.

    Matches real import statements only — not the word appearing in a docstring or comment.
    """
    hits = set()
    for py in root.rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any(n == token or n.startswith(token + ".") for n in names):
                hits.add(str(py.relative_to("src")))
    return hits


def test_langgraph_confined_to_engine():
    hits = _modules_importing("langgraph", _CORE)
    assert hits == {"ailf/core/agent/engine.py"}, hits


def test_langchain_aws_confined_to_llm():
    hits = _modules_importing("langchain_aws", _CORE) | _modules_importing("langchain_aws", _PIPE)
    assert hits == {"ailf/core/models/llm.py"}, hits


def test_backtest_does_not_pull_datasets_or_darts():
    # Fresh subprocess so we measure a clean import graph.
    code = (
        "import sys; "
        "import ailf.core.backtest.gate, ailf.core.backtest.split, "
        "ailf.core.agent.registry, ailf.core.events.leakage; "
        "bad=[m for m in ('ailf.core.datasets','darts','langgraph') if m in sys.modules]; "
        "print('LEAK' if bad else 'CLEAN', bad)"
    )
    env = {**__import__("os").environ, "PYTHONPATH": "src:" + __import__("os").environ.get("PYTHONPATH", "")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=".", env=env)
    assert "CLEAN" in out.stdout, out.stdout + out.stderr


def test_changepoint_pipeline_imports_no_other_pipeline():
    for py in _PIPE.rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            mod = None
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
            elif isinstance(node, ast.Import):
                mod = ",".join(a.name for a in node.names)
            if mod and "ailf.pipelines." in mod:
                assert "ailf.pipelines.changepoint" in mod, f"{py} imports another pipeline: {mod}"
            if mod and "ailf.core.datasets" in mod:
                raise AssertionError(f"{py} imports ailf.core.datasets (Darts/drift-coupled): {mod}")
