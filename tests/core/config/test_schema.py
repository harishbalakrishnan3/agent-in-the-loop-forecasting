"""T017 — config schema round-trip (test-first, data-model.md → Configuration domain)."""

from __future__ import annotations

from ailf.core.config.schema import (
    ConfigOverride,
    EffectiveConfig,
    ModelConfig,
    SplitSpec,
)


def _golden_effective() -> EffectiveConfig:
    return EffectiveConfig(
        models=ModelConfig(
            visual_model_id="vis-id", decision_model_id="dec-id", aws_region="us-west-2"
        ),
        visual_analysis_enabled=True,
        diagnostics={"a": True, "b": False},
        agent_tools={"recent_window": True, "full_history_default": True},
        split=SplitSpec(units="golden"),
        seed=1729,
    )


def test_effective_config_to_from_dict_roundtrip():
    cfg = _golden_effective()
    payload = cfg.to_dict()
    assert EffectiveConfig.from_dict(payload) == cfg


def test_effective_config_to_dict_is_json_native():
    from ailf.core.events.leakage import to_json

    # Must serialize through the strict serializer without raising.
    to_json(_golden_effective().to_dict())


def test_model_config_roundtrip():
    mc = ModelConfig(visual_model_id="v", decision_model_id="d", aws_region="r")
    assert ModelConfig.from_dict(mc.to_dict()) == mc


def test_split_spec_ratios_roundtrip():
    s = SplitSpec(units="ratios", train_ratio=0.76, val_ratio=0.12, test_ratio=0.12)
    assert SplitSpec.from_dict(s.to_dict()) == s


def test_split_spec_absolute_roundtrip():
    s = SplitSpec(units="absolute", train_rows=760, val_rows=120, test_rows=120)
    assert SplitSpec.from_dict(s.to_dict()) == s


def test_config_override_partial_roundtrip():
    ov = ConfigOverride(visual_analysis_enabled=False, diagnostics={"a": False})
    payload = ov.to_dict()
    assert ConfigOverride.from_dict(payload) == ov
    # Unset fields are None / absent (partial override).
    assert ov.models is None and ov.split is None and ov.agent_tools is None
