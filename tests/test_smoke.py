"""Smoke test: the package and its subpackages import cleanly.

Keeps CI green until real tests land, and catches gross packaging breakage.
"""

import importlib

import pytest

MODULES = [
    "ailf",
    "ailf.core",
    "ailf.core.agent",
    "ailf.core.backtest",
    "ailf.core.datasets",
    "ailf.core.eval",
    "ailf.core.metrics",
    "ailf.core.models",
    "ailf.core.prompts",
    "ailf.core.reporting",
    "ailf.pipelines",
    "ailf.pipelines.drift",
    "ailf.pipelines.changepoint",
    "ailf.pipelines.anomaly",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module: str) -> None:
    importlib.import_module(module)
