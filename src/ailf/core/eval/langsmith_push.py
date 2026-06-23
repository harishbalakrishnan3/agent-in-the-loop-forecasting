"""Domain-agnostic LangSmith dataset + experiment infra (promoted from the POC), matched to the
installed ``langsmith==0.8.15`` API.

Use-case seams are INJECTED, never imported (Principle VII): ``ensure_dataset`` takes
``inputs_projector`` + ``metadata_builder``; ``run_experiment`` takes ``evaluators``. The 0.8.15
quirks are encapsulated here: ``create_examples`` uses the modern ``examples=[{...}]`` list form,
``evaluate``'s target is positional-only, and ``create_examples`` concurrency is clamped to 1..3.
A ``refresh_guard`` turns the silent "reuse existing dataset without refreshing examples" behavior
into a loud error when the example count disagrees with the records being pushed (stale-dataset trap).
"""

from __future__ import annotations

from typing import Any, Callable


def get_client():
    """Build a LangSmith Client, failing loud if no API key (hosted calls would silently fail)."""
    import os  # noqa: PLC0415
    if not (os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")):
        raise RuntimeError("LANGSMITH_API_KEY (or LANGCHAIN_API_KEY) not set — cannot reach LangSmith.")
    from langsmith import Client  # noqa: PLC0415
    return Client()


def ensure_dataset(client, name: str, records: list[dict[str, Any]], *,
                   inputs_projector: Callable[[dict], dict],
                   metadata_builder: Callable[[dict], dict],
                   description: str = "eval golden set", refresh_guard: bool = True):
    """Create the dataset + examples idempotently (modern 0.8.15 list-of-dicts form).

    If the dataset already exists: reuse it ONLY when its example count matches ``len(records)``;
    otherwise raise (the existing examples are stale relative to what you're scoring). To push a
    changed set, use a fresh dataset name.
    """
    if client.has_dataset(dataset_name=name):
        if refresh_guard:
            existing = list(client.list_examples(dataset_id=client.read_dataset(dataset_name=name).id))
            if len(existing) != len(records):
                raise RuntimeError(
                    f"dataset {name!r} exists with {len(existing)} examples but {len(records)} records "
                    "were given — examples are NOT refreshed on reuse. Use a fresh dataset name.")
        print(f"[langsmith] dataset {name!r} exists with matching count — reusing (examples not refreshed).")
        return client.read_dataset(dataset_name=name)

    ds = client.create_dataset(name, description=description)
    client.create_examples(
        dataset_id=ds.id,
        examples=[{"inputs": inputs_projector(rec),
                   "outputs": rec,                 # full record so REPLAY evaluators read everything
                   "metadata": metadata_builder(rec)}
                  for rec in records],
        max_concurrency=3,  # 0.8.15 requires 1..3
    )
    print(f"[langsmith] created dataset {name!r} with {len(records)} examples.")
    return ds


def make_replay_target(records: list[dict[str, Any]]) -> Callable[[dict], dict]:
    """REPLAY target: look up the prebuilt record by ``scenario_id`` and echo it. Fast, deterministic,
    no agent re-run — still a real, comparable experiment in the UI."""
    by_id = {r["scenario_id"]: r for r in records}

    def target(inputs: dict) -> dict:
        return by_id[inputs["scenario_id"]]

    return target


def run_experiment(client, dataset_name: str, records: list[dict[str, Any]], *,
                   evaluators: list, experiment_prefix: str, max_concurrency: int = 4):
    """Run ``evaluate()`` over the dataset with the (injected) evaluator list, REPLAY target."""
    from langsmith.evaluation import evaluate  # noqa: PLC0415
    target = make_replay_target(records)
    return evaluate(
        target,  # positional-only (the "/" in the 0.8.15 signature)
        data=dataset_name,
        evaluators=evaluators,
        experiment_prefix=experiment_prefix,
        max_concurrency=max_concurrency,
        client=client,
    )


def experiment_url(results) -> str | None:
    """Best-effort experiment URL (ExperimentResults exposes ``.url`` in 0.8.15)."""
    return getattr(results, "url", None)
