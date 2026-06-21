"""LLM agent loop for the seasonalityV2 POC.

The agent receives a StatsBundle (training-only) and iteratively proposes
Prophet hyperparameter configurations. Each proposal is validated against the
bounded grid, fitted on training data, and scored on val. The loop accepts the
first config that beats naive val MAE; otherwise carries the best proposal.

Architecture: plain Python for-loop (not LangGraph) with LangChain Bedrock.

Leakage guards
--------------
- naive_val_mae is NEVER included in the agent prompt.
- val/test target values never appear in the agent context.
- Ground-truth changepoint dates never appear in the agent context.

Usage
-----
    from agent import run_agent_loop
    from config import load_config

    cfg = load_config(seed=42)
    accepted_config, trace = run_agent_loop(bundle, train_df, val_df, naive_val_mae, cfg)
"""

from __future__ import annotations

import json
import logging
import time
import warnings
from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ValidationError

from config import (
    LLM_MAX_RETRIES,
    LLM_RETRY_DELAY_S,
    MAX_AGENT_ITERATIONS,
    VALID_GRID,
    validate_config,
)
from stats import StatsBundle, stats_to_dict

logging.getLogger("prophet").setLevel(logging.ERROR)
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# Pydantic schemas for structured LLM output
# ---------------------------------------------------------------------------

class ProphetConfig(BaseModel):
    changepoint_prior_scale: float
    seasonality_prior_scale: float
    seasonality_mode: Literal["additive", "multiplicative"]
    changepoint_range: float
    n_changepoints: int


class AgentProposal(BaseModel):
    hypothesis: str       # agent's reasoning about the dominant failure mode
    config: ProphetConfig
    expected_effect: str  # which Prophet blind spot this addresses


# ---------------------------------------------------------------------------
# Iteration record (trace entry)
# ---------------------------------------------------------------------------

@dataclass
class IterationRecord:
    iteration: int
    hypothesis: str
    proposed_config: dict
    val_mae: float | None
    decision: str          # "accepted" | "rejected" | "out_of_bounds" | "prophet_error" | "exhausted"
    rejection_reason: str | None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a forecasting analyst. You receive training-data statistics \
for a time series that has structural changepoints. Your task: identify the dominant \
failure mode and propose Prophet hyperparameters that will address it.

Failure-mode → parameter mapping:
- Level shift (abrupt step in mean, large level_shift_magnitude) \
→ raise changepoint_prior_scale to 0.1 or 0.5
- Trend kink in recent data (last changepoint near end of training, slope change) \
→ raise changepoint_range to 0.9 or 0.95
- Variance change (variance_ratio > 1.5, heteroscedasticity) \
→ raise changepoint_prior_scale AND lower n_changepoints to 10
- Seasonality mode shift (seasonality_mode_signal > 0.6) \
→ set seasonality_mode='multiplicative'

You must propose EXACTLY ONE config. All parameter values MUST come from \
the allowed grids:
- changepoint_prior_scale: one of [0.001, 0.01, 0.05, 0.1, 0.5]
- seasonality_prior_scale: one of [0.01, 0.1, 1.0, 10.0]
- seasonality_mode: one of ["additive", "multiplicative"]
- changepoint_range: one of [0.8, 0.9, 0.95]
- n_changepoints: one of [10, 15, 25]

Do not repeat a previously rejected configuration."""


def _build_user_prompt(
    stats_dict: dict,
    prev_val_maes: list[dict],
) -> str:
    """Build the user-turn prompt for one iteration.

    prev_val_maes : list of {"config": dict, "val_mae": float} — own results only.
    """
    lines = [
        "## Time Series Statistics (training data only)\n",
        "```json",
        json.dumps(stats_dict, indent=2),
        "```",
    ]

    if prev_val_maes:
        lines.append("\n## Your Previous Proposals and Their Val MAE\n")
        for entry in prev_val_maes:
            lines.append(
                f"- Config: {json.dumps(entry['config'])}  →  val_mae={entry['val_mae']:.4f}"
            )
        lines.append(
            "\nChoose a different config that you expect to improve on these results."
        )

    lines.append(
        "\n## Task\nAnalyse the statistics above. Identify the dominant failure mode "
        "and propose a Prophet config from the allowed grids that addresses it."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prophet fit + score helper (mirrors naive.py without importing it)
# ---------------------------------------------------------------------------

def _fit_and_score_prophet(
    config: ProphetConfig,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
) -> tuple[float, pd.DataFrame]:
    """Fit Prophet with given config; return (val_mae, forecast_df)."""
    from prophet import Prophet

    params = {
        "changepoint_prior_scale": config.changepoint_prior_scale,
        "seasonality_prior_scale": config.seasonality_prior_scale,
        "seasonality_mode":        config.seasonality_mode,
        "changepoint_range":       config.changepoint_range,
        "n_changepoints":          config.n_changepoints,
    }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = Prophet(**params)
        m.fit(train_df[["ds", "y"]])

    horizon = len(val_df) + len(train_df)  # make_future_dataframe counts from train start
    future  = m.make_future_dataframe(periods=len(val_df), freq="D")
    fc      = m.predict(future)
    fc_val  = fc[["ds", "yhat"]].tail(len(val_df)).reset_index(drop=True)

    actual  = val_df["y"].to_numpy()
    yhat    = fc_val["yhat"].to_numpy()
    mae     = float(np.mean(np.abs(actual - yhat)))

    return mae, fc_val


def fit_and_score_test(
    config: ProphetConfig,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
) -> tuple[float, pd.DataFrame]:
    """Final test evaluation. Call ONLY after agent loop completes."""
    from prophet import Prophet

    params = {
        "changepoint_prior_scale": config.changepoint_prior_scale,
        "seasonality_prior_scale": config.seasonality_prior_scale,
        "seasonality_mode":        config.seasonality_mode,
        "changepoint_range":       config.changepoint_range,
        "n_changepoints":          config.n_changepoints,
    }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = Prophet(**params)
        m.fit(train_df[["ds", "y"]])

    total_periods = len(val_df) + len(test_df)
    future = m.make_future_dataframe(periods=total_periods, freq="D")
    fc     = m.predict(future)
    fc_test = fc[["ds", "yhat"]].tail(len(test_df)).reset_index(drop=True)

    actual = test_df["y"].to_numpy()
    yhat   = fc_test["yhat"].to_numpy()
    mae    = float(np.mean(np.abs(actual - yhat)))

    return mae, fc_test


# ---------------------------------------------------------------------------
# LLM invocation with retry
# ---------------------------------------------------------------------------

class ModelUnavailableError(RuntimeError):
    """Raised when Bedrock cannot serve the configured model."""


def _invoke_llm(
    structured_llm,
    system_prompt: str,
    user_prompt: str,
) -> AgentProposal:
    """Invoke structured LLM with retry on parse failures."""
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    last_exc: Exception | None = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            result = structured_llm.invoke(messages)
            return result
        except ValidationError as exc:
            last_exc = exc
            if attempt < LLM_MAX_RETRIES:
                time.sleep(LLM_RETRY_DELAY_S)
        except Exception as exc:
            # Bedrock service errors — fail immediately
            raise ModelUnavailableError(
                f"LLM invocation failed (attempt {attempt}): {exc}"
            ) from exc

    raise ModelUnavailableError(
        f"Structured output parse failed after {LLM_MAX_RETRIES} attempts. "
        f"Last error: {last_exc}"
    )


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

def run_agent_loop(
    stats_bundle: StatsBundle,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    naive_val_mae: float,      # comparison bar — NEVER passed to agent in prompt
    run_config,                # RunConfig from config.py
) -> tuple[ProphetConfig, list[IterationRecord]]:
    """Run the LLM agent loop.

    The agent proposes Prophet configs; each is validated, fitted, and scored on val.
    Accepts the first config that strictly beats naive_val_mae.
    If the budget is exhausted, carries the best-val-MAE proposal.

    Parameters
    ----------
    stats_bundle : StatsBundle
        Training-only statistics. Never contains val/test values.
    train_df, val_df : pd.DataFrame
        Training and validation splits. test_df is NOT a parameter here.
    naive_val_mae : float
        Acceptance threshold. NOT shown to the agent.
    run_config : RunConfig
        LLM model ID, region, etc.

    Returns
    -------
    accepted_config : ProphetConfig
        The accepted config, or best-val-MAE proposal if none accepted.
    trace : list[IterationRecord]
        Full iteration log.
    """
    from langchain_aws import ChatBedrockConverse

    # Validate model is available before starting the loop
    try:
        llm = ChatBedrockConverse(
            model=run_config.model_id,
            region_name=run_config.aws_region,
            max_tokens=1500,
        )
        structured_llm = llm.with_structured_output(AgentProposal)
    except Exception as exc:
        raise ModelUnavailableError(
            f"Cannot initialise Bedrock client for model '{run_config.model_id}': {exc}"
        ) from exc

    stats_dict = stats_to_dict(stats_bundle)
    trace: list[IterationRecord] = []
    prev_val_maes: list[dict]   = []   # own results only — no naive_val_mae
    rejected_signatures: set[str] = set()

    best_config: ProphetConfig | None = None
    best_val_mae: float = float("inf")

    for i in range(1, MAX_AGENT_ITERATIONS + 1):
        user_prompt = _build_user_prompt(stats_dict, prev_val_maes)

        # --- LLM call ---
        try:
            proposal: AgentProposal = _invoke_llm(structured_llm, SYSTEM_PROMPT, user_prompt)
        except ModelUnavailableError as exc:
            trace.append(IterationRecord(
                iteration=i,
                hypothesis="[LLM unavailable]",
                proposed_config={},
                val_mae=None,
                decision="prophet_error",
                rejection_reason=str(exc),
            ))
            break

        # --- Signature dedup ---
        sig = json.dumps(proposal.config.model_dump(), sort_keys=True)
        if sig in rejected_signatures:
            trace.append(IterationRecord(
                iteration=i,
                hypothesis=proposal.hypothesis,
                proposed_config=proposal.config.model_dump(),
                val_mae=None,
                decision="rejected",
                rejection_reason="Duplicate of a previously rejected config.",
            ))
            continue

        # --- Bounded grid validation ---
        try:
            validate_config(proposal.config.model_dump())
        except ValueError as exc:
            rejected_signatures.add(sig)
            trace.append(IterationRecord(
                iteration=i,
                hypothesis=proposal.hypothesis,
                proposed_config=proposal.config.model_dump(),
                val_mae=None,
                decision="out_of_bounds",
                rejection_reason=str(exc),
            ))
            continue

        # --- Prophet fit + val score ---
        try:
            val_mae, _ = _fit_and_score_prophet(proposal.config, train_df, val_df)
        except Exception as exc:
            rejected_signatures.add(sig)
            trace.append(IterationRecord(
                iteration=i,
                hypothesis=proposal.hypothesis,
                proposed_config=proposal.config.model_dump(),
                val_mae=None,
                decision="prophet_error",
                rejection_reason=f"Prophet fitting failed: {exc}",
            ))
            continue

        prev_val_maes.append({"config": proposal.config.model_dump(), "val_mae": val_mae})

        # Track best proposal regardless of acceptance
        if val_mae < best_val_mae:
            best_val_mae = val_mae
            best_config  = proposal.config

        # --- Acceptance check (strictly < naive, no leakage of naive_val_mae to agent) ---
        if val_mae < naive_val_mae:
            trace.append(IterationRecord(
                iteration=i,
                hypothesis=proposal.hypothesis,
                proposed_config=proposal.config.model_dump(),
                val_mae=val_mae,
                decision="accepted",
                rejection_reason=None,
            ))
            return proposal.config, trace

        # --- Rejected: log and continue ---
        rejected_signatures.add(sig)
        trace.append(IterationRecord(
            iteration=i,
            hypothesis=proposal.hypothesis,
            proposed_config=proposal.config.model_dump(),
            val_mae=val_mae,
            decision="rejected",
            rejection_reason=f"val_mae={val_mae:.4f} did not beat naive baseline.",
        ))

    # Budget exhausted — carry best proposal
    if best_config is None:
        # Fallback: use grid defaults if all iterations failed before scoring
        best_config = ProphetConfig(
            changepoint_prior_scale=0.05,
            seasonality_prior_scale=10.0,
            seasonality_mode="multiplicative",
            changepoint_range=0.8,
            n_changepoints=25,
        )

    # Mark last record as exhausted if not already accepted
    if trace and trace[-1].decision not in ("accepted",):
        trace[-1] = IterationRecord(
            iteration=trace[-1].iteration,
            hypothesis=trace[-1].hypothesis,
            proposed_config=trace[-1].proposed_config,
            val_mae=trace[-1].val_mae,
            decision="exhausted",
            rejection_reason="Budget exhausted. Carrying best-val-MAE proposal.",
        )

    return best_config, trace
