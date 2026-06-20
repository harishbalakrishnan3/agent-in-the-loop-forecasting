"""MCP-ready tool registry contract (contracts/tool_registry.md, FR-022..025, SC-011).

Plain-data types: the agent proposes a tool NAME + bounded params; the registry validates bounds
and resolves the tool; the gate (core/backtest/gate.py) is the only caller of ``invoke``. A tool's
``invoker`` is a pure ``(ToolContext, params) -> ToolResult`` mapping over plain JSON-native data —
no SeriesSplit / DiagnosticsBundle object / Prophet handle crosses the boundary — so an
out-of-process (MCP-served) implementation with the same contract is a drop-in replacement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from ailf.core.agent.errors import ToolBoundsError

# Crossing types (plain dicts, documented in contracts/tool_registry.md):
#   ToolContext = {"training": [{"ds": iso, "y": float}, ...], "future": [iso, ...], "diagnostics": {...}}
#   ToolResult  = {"yhat": [float, ...], "resolved_params": {...}}
ToolContext = dict[str, Any]
ToolResult = dict[str, Any]


@dataclass(frozen=True)
class ToolParamSchema:
    """The single source of a param's bounds. The POC grids become ``allowed`` data."""

    name: str
    kind: str  # "enum" | "float_grid" | "int" | "str_choice" | "block_list"
    allowed: list[Any] | None = None
    default: Any = None
    required: bool = False

    def validate(self, value: Any) -> Any:
        if self.kind in ("enum", "float_grid", "str_choice"):
            if self.allowed is not None and value not in self.allowed:
                raise ToolBoundsError(
                    f"param {self.name!r}={value!r} not in allowed {self.allowed}"
                )
        elif self.kind == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ToolBoundsError(f"param {self.name!r} must be an int, got {value!r}")
        elif self.kind == "block_list":
            if not (value == "all_closed" or isinstance(value, list)):
                raise ToolBoundsError(f"param {self.name!r} must be 'all_closed' or a list, got {value!r}")
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "allowed": self.allowed,
            "default": self.default,
            "required": self.required,
        }


@dataclass(frozen=True)
class ToolSpec:
    """One registered intervention. ``invoker``/``precondition`` are held registry-side, NOT
    serialized: ``to_dict`` emits only the agent-facing menu view."""

    name: str
    description: str
    params: list[ToolParamSchema]
    enabled: bool = True
    structural: bool = True
    invoker: Callable[[ToolContext, dict[str, Any]], ToolResult] | None = field(default=None, repr=False, compare=False)
    precondition: Callable[[ToolContext], str | None] | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "params": [p.to_dict() for p in self.params],
            "enabled": self.enabled,
            "structural": self.structural,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate provided params against this spec's schemas; fill defaults for omitted ones."""
        by_name = {p.name: p for p in self.params}
        unknown = set(params) - set(by_name)
        if unknown:
            raise ToolBoundsError(f"tool {self.name!r} got unknown params {sorted(unknown)}")
        resolved: dict[str, Any] = {}
        for p in self.params:
            if p.name in params:
                resolved[p.name] = p.validate(params[p.name])
            elif p.required:
                raise ToolBoundsError(f"tool {self.name!r} requires param {p.name!r}")
            elif p.default is not None:
                resolved[p.name] = p.default
        return resolved


@dataclass(frozen=True)
class Proposal:
    """The agent's single choice (POC-identical action_signature)."""

    tool: str
    params: dict[str, Any]
    rationale: str = ""

    @property
    def action_signature(self) -> str:
        return f"{self.tool}|{json.dumps(self.params, sort_keys=True)}"


class ToolRegistry:
    """Holds registered tools; projects a per-run view filtering both menu and allowed-set."""

    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec

    def for_run(self, enabled_names: set[str]) -> "ToolRegistry":
        """Project a registry whose menu()/allowed_names() reflect only enabled tools (FR-014).

        A tool is enabled if its name is in ``enabled_names``; non-structural tools (the fallback)
        are always retained regardless so a run always has a valid forecast (FR-016).
        """
        projected: list[ToolSpec] = []
        for spec in self._specs.values():
            keep = (spec.name in enabled_names) or (not spec.structural)
            projected.append(
                ToolSpec(
                    name=spec.name,
                    description=spec.description,
                    params=spec.params,
                    enabled=keep,
                    structural=spec.structural,
                    invoker=spec.invoker,
                    precondition=spec.precondition,
                )
            )
        reg = ToolRegistry()
        for spec in projected:
            reg.register(spec)
        return reg

    def menu(self) -> list[dict[str, Any]]:
        """Agent-facing menu of ENABLED tools (name + description + bounded schema)."""
        return [s.to_dict() for s in self._specs.values() if s.enabled]

    def allowed_names(self) -> set[str]:
        return {name for name, s in self._specs.items() if s.enabled}

    def get(self, name: str) -> ToolSpec:
        if name not in self._specs:
            raise ToolBoundsError(f"unknown tool {name!r}")
        spec = self._specs[name]
        if not spec.enabled:
            raise ToolBoundsError(f"tool {name!r} is disabled for this run")
        return spec

    def validate_params(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        return self.get(name).validate_params(params)

    def invoke(self, name: str, context: ToolContext, params: dict[str, Any]) -> ToolResult:
        """Validate → precondition → invoke. The gate is the only caller (sole scoring authority)."""
        spec = self.get(name)
        resolved = spec.validate_params(params)
        if spec.precondition is not None:
            reason = spec.precondition(context)
            if reason:
                raise ToolBoundsError(f"tool {name!r} precondition failed: {reason}")
        if spec.invoker is None:
            raise ToolBoundsError(f"tool {name!r} has no invoker registered")
        return spec.invoker(context, resolved)
