"""Batch-run the CURRENT changepoint agent over the 6 committed scenarios on AWS Bedrock (D2),
LangSmith tracing ON. Reuses ``run_scenario`` exactly as shipped — NO core/pipeline edits.

Tracing is enabled purely by passing ``credentials=RunCredentials(langsmith_tracing=True, ...)``;
``pipeline.py`` sets/restores the ``LANGSMITH_*`` env vars around the run. Provider is forced to
Bedrock by supplying AWS creds and NOT supplying an Anthropic key.
"""

from __future__ import annotations

import os
from pathlib import Path

from ailf.core.config.schema import ConfigOverride, RunCredentials
from ailf.pipelines.changepoint.pipeline import run_scenario

from llm_eval.scenarios import scenario_ids

# Default reports root (relative to repo root — run the CLI from there). Matches run_scenario's
# own default location so the existing committed run dir is found too.
DEFAULT_REPORTS_ROOT = Path("reports/changepoint")


def build_credentials() -> RunCredentials:
    """Construct RunCredentials for a Bedrock + LangSmith-traced run.

    Resolves AWS creds the way boto3 does (explicit env keys OR a named ``AWS_PROFILE`` / SSO /
    instance role) and threads the *resolved* access/secret into RunCredentials so the pipeline
    selects provider="bedrock" (resolve.py keys off ``has_aws``). Model ids come from the
    pipeline's config.yaml — no MODEL_ID env vars needed. An Anthropic key in the env would flip
    the provider to Anthropic, so we fail loud. LangSmith tracing is best-effort.
    """
    if os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is set — it would override the Bedrock provider (D2). Unset it for "
            "the MVP batch run (we want Bedrock so LangSmith auto-traces the LangGraph node tree)."
        )

    access, secret, token, region = _resolve_aws()
    if token:
        # The pipeline's typed BYO path (_bedrock_kwargs) can't carry a session token, so for
        # temporary creds we export all three to the env and let ChatBedrockConverse resolve them
        # from the ambient boto3 chain (and resolve.py's env-based provider detection pick Bedrock).
        os.environ["AWS_ACCESS_KEY_ID"] = access or ""
        os.environ["AWS_SECRET_ACCESS_KEY"] = secret or ""
        os.environ["AWS_SESSION_TOKEN"] = token
        aws_kwargs: dict = {}  # leave RunCredentials AWS fields empty -> ambient chain
        print("[batch] using temporary AWS creds (session token) via the ambient boto3 chain.")
    else:
        aws_kwargs = {"aws_access_key_id": access, "aws_secret_access_key": secret, "aws_region": region}

    creds = RunCredentials(
        **aws_kwargs,
        langsmith_tracing=bool(os.getenv("LANGSMITH_API_KEY")),
        langsmith_api_key=os.getenv("LANGSMITH_API_KEY"),
        langsmith_project=os.getenv("LANGSMITH_PROJECT", "agent-in-the-loop-forecasting"),
    )
    if not (creds.has_aws or token):
        raise RuntimeError(
            "No AWS credentials resolved for Bedrock (D2). Set AWS_PROFILE (or AWS_ACCESS_KEY_ID + "
            "AWS_SECRET_ACCESS_KEY) in .env so boto3 can authenticate to Bedrock."
        )
    if not creds.has_langsmith:
        print("[batch] WARNING: LANGSMITH_API_KEY not set — runs will NOT be traced to LangSmith.")
    print(f"[batch] provider=bedrock region={region} "
          f"(creds via {'env keys' if os.getenv('AWS_ACCESS_KEY_ID') and not token else 'profile/chain'})")
    return creds


def _resolve_aws() -> tuple[str | None, str | None, str | None, str]:
    """Return (access_key, secret_key, session_token, region) from the boto3 chain (env keys,
    AWS_PROFILE, SSO, instance role). Region prefers AWS_REGION, then the session's region."""
    import boto3  # noqa: PLC0415

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2"
    try:
        session = boto3.Session(profile_name=os.getenv("AWS_PROFILE") or None)
        region = os.getenv("AWS_REGION") or session.region_name or region
        c = session.get_credentials()
        if c is None:
            return None, None, None, region
        fc = c.get_frozen_credentials()
        return fc.access_key, fc.secret_key, fc.token, region
    except Exception as exc:  # noqa: BLE001
        print(f"[batch] WARNING: boto3 credential resolution failed ({type(exc).__name__}: {exc}).")
        return None, None, None, region


def run_all(scenario_ids_: list[str] | None = None, *, seed_runs: int = 1,
            reports_root: Path | None = None) -> list[str]:
    """Run each scenario (× seed_runs) through run_scenario; return the run-dir paths.

    seed_runs>1 varies the config seed via ConfigOverride(seed=...) so each repeat gets a distinct
    run_id "<scenario_id>-<seed>" (without this the same dir would be overwritten). seed_runs=1
    uses the config default seed.
    """
    sids = scenario_ids_ or scenario_ids()
    creds = build_credentials()
    reports_root = reports_root or DEFAULT_REPORTS_ROOT
    run_dirs: list[str] = []
    for sid in sids:
        for rep in range(seed_runs):
            override = ConfigOverride(seed=1729 + rep) if seed_runs > 1 else None
            print(f"[batch] running {sid} (rep {rep + 1}/{seed_runs})...")
            report = run_scenario(sid, credentials=creds, override=override, reports_root=reports_root)
            run_dirs.append(report["run_dir"])
            print(f"[batch]   -> winner={report.get('winner')} run_dir={report['run_dir']}")
    return run_dirs
