"""Environment-driven configuration for the changepoint POC (T005).

No provider model IDs are hardcoded: ``VISUAL_MODEL_ID`` and ``REACT_MODEL_ID`` MUST be set
or the run fails clearly (FR-022/024, SC-010). LangSmith tracing activates from env when present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Repo root = three levels up from this file: pocs/changepoint/config.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "pocs" / "changepoint" / "data"
RUNS_DIR = REPO_ROOT / "pocs" / "changepoint" / "runs"

# Fixed, recorded seed for reproducibility (FR-040, SC-007).
SEED = 1729


class ConfigError(RuntimeError):
    """Raised when required configuration is missing — surfaced clearly, never swallowed."""


@dataclass(frozen=True)
class PocConfig:
    visual_model_id: str
    react_model_id: str
    aws_region: str
    langsmith_tracing: bool
    seed: int = SEED


def load_config() -> PocConfig:
    """Load ``.env`` and read required model/region settings, failing fast if absent.

    ``override=True`` so ``.env`` is authoritative for this POC: otherwise a stale shell export
    (e.g. ``AWS_REGION``) would silently shadow the committed ``.env`` value.
    """
    load_dotenv(REPO_ROOT / ".env", override=True)

    visual = os.getenv("VISUAL_MODEL_ID", "").strip()
    react = os.getenv("REACT_MODEL_ID", "").strip()
    region = os.getenv("AWS_REGION", "").strip()

    missing = [
        name
        for name, value in (
            ("VISUAL_MODEL_ID", visual),
            ("REACT_MODEL_ID", react),
            ("AWS_REGION", region),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "Missing required environment configuration: "
            + ", ".join(missing)
            + ". Set these in .env (see .env.example). No provider model id is assumed by "
            "default — the run will not silently fall back to another model."
        )

    return PocConfig(
        visual_model_id=visual,
        react_model_id=react,
        aws_region=region,
        langsmith_tracing=os.getenv("LANGSMITH_TRACING", "").strip().lower() == "true",
    )
