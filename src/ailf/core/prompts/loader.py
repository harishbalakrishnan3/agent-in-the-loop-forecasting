"""Generic versioned-prompt loader (no use-case text).

Loads ``<name>_v<N>.md`` from a prompt directory and fills ``{{placeholder}}`` tokens. Use-case
prompts live in their pipeline (e.g. ``ailf/pipelines/changepoint/prompts/``); this is only the
mechanism (Constitution prompt-versioning rule + research Decision 7).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def load_prompt(
    prompt_dir: str | Path, name: str, version: int, *, fill: Mapping[str, str] | None = None
) -> str:
    """Read ``<prompt_dir>/<name>_v<version>.md`` and fill ``{{placeholder}}`` tokens.

    Raises ``FileNotFoundError`` if the versioned prompt is absent, and ``KeyError`` if the text
    contains a placeholder with no value in ``fill`` (so a missing menu fails loudly).
    """
    path = Path(prompt_dir) / f"{name}_v{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    text = path.read_text()
    values = dict(fill or {})

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(
                f"Prompt {path.name} has unfilled placeholder {{{{{key}}}}}; provide it in `fill`."
            )
        return str(values[key])

    return _PLACEHOLDER.sub(_replace, text)
