"""Configuration domain types — frozen dataclasses with to_dict/from_dict (data-model.md).

One serialization idiom across the boundary (research Decision 16): plain frozen dataclasses
mirroring ``ailf/core/datasets/case.py``. ``EffectiveConfig`` is the resolved, recorded per-run
config; ``ConfigOverride`` is a possibly-partial per-run override merged onto file defaults
(merge/validate live in ``resolve.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    visual_model_id: str
    decision_model_id: str
    aws_region: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "visual_model_id": self.visual_model_id,
            "decision_model_id": self.decision_model_id,
            "aws_region": self.aws_region,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ModelConfig":
        return cls(
            visual_model_id=d["visual_model_id"],
            decision_model_id=d["decision_model_id"],
            aws_region=d["aws_region"],
        )


@dataclass(frozen=True)
class SplitSpec:
    """The *requested* split. ``units`` discriminates; ratio/absolute fields set accordingly.

    ``units="golden"`` means "use the scenario's golden metadata split verbatim" (no override).
    """

    units: str = "golden"  # "golden" | "ratios" | "absolute"
    train_ratio: float | None = None
    val_ratio: float | None = None
    test_ratio: float | None = None
    train_rows: int | None = None
    val_rows: int | None = None
    test_rows: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"units": self.units}
        for k in ("train_ratio", "val_ratio", "test_ratio", "train_rows", "val_rows", "test_rows"):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SplitSpec":
        return cls(
            units=d.get("units", "golden"),
            train_ratio=d.get("train_ratio"),
            val_ratio=d.get("val_ratio"),
            test_ratio=d.get("test_ratio"),
            train_rows=d.get("train_rows"),
            val_rows=d.get("val_rows"),
            test_rows=d.get("test_rows"),
        )


@dataclass(frozen=True)
class EffectiveConfig:
    """The validated, fully-resolved per-run configuration (recorded to effective_config.json)."""

    models: ModelConfig
    visual_analysis_enabled: bool
    diagnostics: dict[str, bool]
    agent_tools: dict[str, bool]
    split: SplitSpec
    seed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "models": self.models.to_dict(),
            "visual_analysis_enabled": self.visual_analysis_enabled,
            "diagnostics": dict(self.diagnostics),
            "agent_tools": dict(self.agent_tools),
            "split": self.split.to_dict(),
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EffectiveConfig":
        return cls(
            models=ModelConfig.from_dict(d["models"]),
            visual_analysis_enabled=bool(d["visual_analysis_enabled"]),
            diagnostics=dict(d["diagnostics"]),
            agent_tools=dict(d["agent_tools"]),
            split=SplitSpec.from_dict(d["split"]),
            seed=int(d["seed"]),
        )

    @property
    def enabled_diagnostics(self) -> frozenset[str]:
        return frozenset(k for k, v in self.diagnostics.items() if v)

    @property
    def enabled_tools(self) -> frozenset[str]:
        return frozenset(k for k, v in self.agent_tools.items() if v)


@dataclass(frozen=True)
class ConfigOverride:
    """A possibly-partial per-run override (every field optional). Merged in ``resolve.py``."""

    models: dict[str, Any] | None = None
    visual_analysis_enabled: bool | None = None
    diagnostics: dict[str, bool] | None = None
    agent_tools: dict[str, bool] | None = None
    split: dict[str, Any] | None = None
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in ("models", "visual_analysis_enabled", "diagnostics", "agent_tools", "split", "seed"):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConfigOverride":
        return cls(
            models=d.get("models"),
            visual_analysis_enabled=d.get("visual_analysis_enabled"),
            diagnostics=d.get("diagnostics"),
            agent_tools=d.get("agent_tools"),
            split=d.get("split"),
            seed=d.get("seed"),
        )
