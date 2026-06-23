"""Push the golden dataset to LangSmith and run an experiment — matched to the INSTALLED
langsmith==0.8.15 API (signatures introspected, and a full evaluate() round-trip verified live).

KEY 0.8.15 quirk: ``create_examples`` takes ``examples=[{...}]`` (a list of example dicts), NOT
the teaching repo's parallel ``inputs=[...], outputs=[...]`` lists — mixing the two raises
ValueError. ``evaluate``'s target is positional-only (the ``/`` in its signature).
"""

from __future__ import annotations

import os
from typing import Any, Callable

from llm_eval.evaluators import ALL_EVALUATORS


def get_client():
    """Build a LangSmith Client, failing loud if no API key (hosted calls would silently fail)."""
    if not (os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")):
        raise RuntimeError("LANGSMITH_API_KEY (or LANGCHAIN_API_KEY) not set — cannot reach LangSmith.")
    from langsmith import Client  # noqa: PLC0415
    return Client()


def _example_inputs(rec: dict[str, Any]) -> dict[str, Any]:
    """AGENT-VISIBLE fields only — keep ground truth OUT of the example inputs."""
    g = rec["ground_truth"]
    return {"scenario_id": rec["scenario_id"], "seed": rec["seed"],
            "n_changepoints_to_detect": g["n_changepoints_to_detect"],
            "seasonal_period": g["seasonal_period"]}


def ensure_dataset(client, name: str, records: list[dict[str, Any]]):
    """Create the dataset + examples idempotently (modern 0.8.15 list-of-dicts form).

    has_dataset guards the duplicate-name error; it does NOT refresh examples, so to re-push
    changed records bump the name (e.g. ``-v2``) rather than relying on this.
    """
    if client.has_dataset(dataset_name=name):
        print(f"[langsmith] dataset {name!r} already exists — reusing (examples not refreshed).")
        return client.read_dataset(dataset_name=name)
    ds = client.create_dataset(name, description="6 committed changepoint scenarios; audit_only ground truth (MVP)")
    client.create_examples(
        dataset_id=ds.id,
        examples=[{"inputs": _example_inputs(rec),
                   "outputs": rec,  # FULL golden record so REPLAY evaluators read everything
                   "metadata": {"family_channel": rec["ground_truth"]["family_channel"],
                                "expected_intervention_family": rec["ground_truth"]["expected_intervention_family"]}}
                  for rec in records],
        max_concurrency=3,  # 0.8.15 requires 1..3
    )
    print(f"[langsmith] created dataset {name!r} with {len(records)} examples.")
    return ds


def make_replay_target(records: list[dict[str, Any]]) -> Callable[[dict], dict]:
    """REPLAY target: look up the prebuilt golden record by scenario_id and echo it. Fast,
    deterministic, no Bedrock cost — still a real, comparable experiment in the UI."""
    by_id = {r["scenario_id"]: r for r in records}

    def target(inputs: dict) -> dict:
        return by_id[inputs["scenario_id"]]

    return target


def run_experiment(client, dataset_name: str, records: list[dict[str, Any]],
                   *, experiment_prefix: str, max_concurrency: int = 4, with_judge: bool = False):
    """Run evaluate() over the dataset (REPLAY target). with_judge=True adds the LLM-as-judge
    (rationale adherence) — Bedrock calls per case, so keep concurrency modest."""
    from langsmith.evaluation import evaluate  # noqa: PLC0415
    from llm_eval.evaluators import all_evaluators  # noqa: PLC0415
    target = make_replay_target(records)
    return evaluate(
        target,  # positional-only
        data=dataset_name,
        evaluators=all_evaluators(with_judge=with_judge),
        experiment_prefix=experiment_prefix,
        max_concurrency=(2 if with_judge else max_concurrency),  # judge hits Bedrock — throttle
        client=client,
    )


def experiment_url(results) -> str | None:
    """Best-effort experiment URL (ExperimentResults exposes .url in 0.8.15)."""
    return getattr(results, "url", None)
