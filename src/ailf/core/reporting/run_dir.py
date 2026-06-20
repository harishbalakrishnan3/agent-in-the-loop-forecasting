"""Per-run directory creation + effective-config stamping (FR-021, SC-007/SC-012)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ailf.core.events.leakage import to_json

_REPORTS_ROOT = Path("reports") / "changepoint"


def create_run_dir(run_id: str, *, root: Path | None = None) -> Path:
    """Create and return ``reports/changepoint/<run_id>/`` (+ ``event_payloads/`` subdir)."""
    base = (root or _REPORTS_ROOT) / run_id
    (base / "event_payloads").mkdir(parents=True, exist_ok=True)
    return base


def stamp_effective_config(
    run_dir: Path,
    *,
    effective_config: dict[str, Any],
    split_provenance: dict[str, Any],
    seed: int,
) -> Path:
    """Write ``effective_config.json`` = resolved config + split provenance + seed (SC-012)."""
    payload = {
        "effective_config": effective_config,
        "split_provenance": split_provenance,
        "seed": seed,
    }
    path = run_dir / "effective_config.json"
    path.write_text(to_json(payload, indent=2))  # strict serializer — raises on non-JSON
    return path
