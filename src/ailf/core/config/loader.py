"""Read a ``config.yaml`` defaults file into a raw dict (pyyaml).

Pure I/O — no validation or merge logic (that lives in ``resolve.py``). Kept separate so the
defaults source is swappable and the resolver is testable on plain dicts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config_yaml(path: str | Path) -> dict[str, Any]:
    """Load a ``config.yaml`` defaults file into a plain dict."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config.yaml not found: {p}")
    data = yaml.safe_load(p.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"config.yaml at {p} must be a mapping; got {type(data).__name__}")
    return data
