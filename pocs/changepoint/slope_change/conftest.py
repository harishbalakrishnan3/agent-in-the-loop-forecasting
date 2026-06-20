"""Pytest bootstrap for the slope-change POC.

The workspace ``pyproject.toml`` only puts ``src`` on the path, so the
namespace package ``pocs`` is not importable by default. Insert the repo root
on ``sys.path`` so ``uv run pytest pocs/changepoint/slope_change/`` resolves
``pocs.changepoint.slope_change.*`` imports. POC-local and self-contained.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
