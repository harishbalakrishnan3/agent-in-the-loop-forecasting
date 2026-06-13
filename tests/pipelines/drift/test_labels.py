"""US1: label correctness for each flavor (T009)."""

import pandas as pd
import pytest

from ailf.pipelines.drift.datasets import DriftFlavor, GeneratorConfig, generate_case

EXPECTED_COMPONENT = {
    DriftFlavor.trend_slope: "trend",
    DriftFlavor.mean_level: "trend",
    DriftFlavor.variance_inflation: "noise",
    DriftFlavor.seasonal_amplitude: "seasonality",
}


def _config_for(flavor: DriftFlavor) -> GeneratorConfig:
    # seasonal flavor needs seasonality; variance flavor wants positive base noise.
    return GeneratorConfig(length=400, onset=200, transition_width=40, magnitude=2.0, seed=42)


@pytest.mark.parametrize("flavor", list(DriftFlavor))
def test_label_fields_present_and_consistent(flavor: DriftFlavor) -> None:
    cfg = _config_for(flavor)
    case = generate_case(flavor, seed=42, config=cfg)
    assert len(case.labels) == 1
    label = case.labels[0]

    assert label["flavor"] == flavor.value
    assert label["affected_component"] == EXPECTED_COMPONENT[flavor]
    assert label["onset_index"] == 200
    assert label["transition_width"] == 40
    assert label["magnitude"] == 2.0

    # onset_time matches the series index at onset_index.
    onset_time = pd.Timestamp(label["onset_time"])
    assert onset_time == case.series.time_index[200]


@pytest.mark.parametrize("flavor", list(DriftFlavor))
def test_labels_are_json_serializable(flavor: DriftFlavor) -> None:
    import json

    case = generate_case(flavor, seed=42, config=_config_for(flavor))
    json.dumps(case.labels)  # must not raise
