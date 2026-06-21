"""Shared Qwen / CUSUM / Claude / Bedrock changepoint detection.

Used by both the FastAPI and Streamlit UIs.

Exposes a single public function:

    detect(df, model, ollama_url) -> DetectionResult

where ``DetectionResult`` contains:
  - ``changepoints``  — list of changepoint dicts
  - ``reasoning``     — human-readable reasoning narrative
  - ``source``        — "qwen" | "claude" | "bedrock" | "cusum"
  - ``model``         — model name used
  - ``langsmith_run_url`` — LangSmith trace URL if tracing succeeded, else ""

Backend routing (by model string):
  - starts with "claude-" → Anthropic Claude API (ANTHROPIC_API_KEY from .env)
  - starts with "bedrock/" → AWS Bedrock via langchain_aws (lazy import)
  - otherwise → Ollama / CUSUM fallback

LangSmith tracing:
  - Enabled when LANGSMITH_API_KEY is set and langsmith_tracing=True is passed.
  - Each detect call is wrapped with @traceable; SSL/network errors are caught and
    reported as warnings — the detection result is still returned.

For streaming Claude reasoning in Streamlit, use ``detect_streaming()`` which yields
text chunks as a generator.

Call it before fitting Prophet; render ``reasoning`` in the UI before showing the forecast.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Generator

import numpy as np
import pandas as pd

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:4b"

# Claude model IDs available in the dropdown
CLAUDE_MODELS = ["claude-sonnet-4-5", "claude-opus-4-5", "claude-3-5-sonnet-20241022"]

# Bedrock model IDs (prefixed "bedrock/" in the dropdown value)
BEDROCK_MODELS = [
    "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
    "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
]

_SYSTEM_PROMPT = (
    "You are a time-series expert specialising in drift and changepoint detection. "
    "Think step-by-step about the data before giving your final answer. "
    "Your final answer MUST be valid JSON — no markdown fences, no explanation outside the JSON block."
)

_STEP = 21  # downsample: 1825 pts → ~87 sample points


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass
class DetectionResult:
    changepoints: list[dict] = field(default_factory=list)
    reasoning: str = ""
    source: str = "cusum"
    model: str = ""
    langsmith_run_url: str = ""  # populated when LangSmith tracing is active


# ---------------------------------------------------------------------------
# CUSUM fallback
# ---------------------------------------------------------------------------

def _cusum_changepoints(y: np.ndarray, threshold_sigma: float = 4.0, min_gap: int = 14) -> list[int]:
    mu, sigma = np.mean(y), max(np.std(y), 1e-9)
    z = (y - mu) / sigma
    cp_pos = np.zeros(len(y))
    cp_neg = np.zeros(len(y))
    changepoints: list[int] = []
    last_cp = -min_gap

    for i in range(1, len(y)):
        cp_pos[i] = max(0.0, cp_pos[i - 1] + z[i] - 0.5)
        cp_neg[i] = max(0.0, cp_neg[i - 1] - z[i] - 0.5)
        if (cp_pos[i] > threshold_sigma or cp_neg[i] > threshold_sigma) and (i - last_cp) >= min_gap:
            changepoints.append(i)
            cp_pos[i] = cp_neg[i] = 0.0
            last_cp = i

    return changepoints


def _cusum_result(df: pd.DataFrame) -> DetectionResult:
    idxs = _cusum_changepoints(df["y"].to_numpy())
    dates = pd.DatetimeIndex(df["ds"])
    cps = [
        {
            "index": i,
            "type": "sudden",
            "direction": "unknown",
            "confidence": 0.7,
            "reason": "CUSUM statistical detector",
            "timestamp": str(dates[i].date()),
        }
        for i in idxs
    ]
    reasoning = (
        f"CUSUM statistical detector (Ollama unavailable).\n"
        f"Detected {len(cps)} changepoints using threshold σ=4.0, min_gap=14 days.\n"
        + "\n".join(f"  • {cp['timestamp']}: {cp['reason']}" for cp in cps)
    )
    return DetectionResult(changepoints=cps, reasoning=reasoning, source="cusum", model="cusum")


# ---------------------------------------------------------------------------
# Ollama / Qwen
# ---------------------------------------------------------------------------

def _ollama_available(model: str, base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as r:
            available = [m["name"] for m in json.loads(r.read()).get("models", [])]
        return model in available
    except Exception:
        return False


def _call_ollama_stream(prompt: str, model: str, base_url: str) -> tuple[str, str]:
    """Return (think_text, answer_text) from Ollama streaming chat.

    qwen3 reasoning models emit a <think>…</think> block followed by the JSON answer.
    We capture both so the UI can show the reasoning narrative.
    """
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "stream": True,
        "think": False,  # disabled: thinking exhausts token budget before JSON is emitted
        "options": {"temperature": 0.1, "num_predict": 1024},
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode()

    think_chunks: list[str] = []
    answer_chunks: list[str] = []

    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        obj = json.loads(line)
        msg = obj.get("message", {})
        thinking = msg.get("thinking", "")
        content  = msg.get("content", "")
        if thinking:
            think_chunks.append(thinking)
        if content:
            answer_chunks.append(content)

    think_text  = "".join(think_chunks).strip()
    answer_text = "".join(answer_chunks).strip()

    # Fallback: if think block is in content (older Ollama versions)
    if not think_text and "<think>" in answer_text:
        start = answer_text.find("<think>")
        end   = answer_text.find("</think>")
        if end != -1:
            think_text  = answer_text[start + len("<think>"): end].strip()
            answer_text = answer_text[end + len("</think>"):].strip()

    return think_text, answer_text


def _extract_json(text: str) -> str:
    """Strip markdown fences and extract the outermost valid JSON object.

    Tries progressively more aggressive cleaning when the raw extraction fails.
    Returns the best candidate string (may still fail json.loads if the model
    emitted truly broken JSON — caller handles that).
    """
    # 1. Strip leading ``` fences
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        t = "\n".join(lines[1:])
    if "```" in t:
        t = t[: t.rfind("```")]
    t = t.strip()

    # 2. If the model echoed back the schema example (contains literal "N," or
    #    "0.0-1.0"), that's the schema template, not valid JSON — try to find
    #    the LAST complete {...} block which is more likely to be the real answer.
    candidates: list[str] = []
    depth = 0
    start_idx = -1
    for i, ch in enumerate(t):
        if ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start_idx != -1:
                candidates.append(t[start_idx: i + 1])
                start_idx = -1

    # Try each candidate (last first — Qwen often puts the answer after the schema)
    for cand in reversed(candidates):
        try:
            json.loads(cand)
            return cand
        except Exception:
            continue

    # 3. If no candidate parsed cleanly, return the largest one for the caller
    if candidates:
        return max(candidates, key=len)

    # 4. Final fallback — original simple extraction
    start = t.find("{")
    end   = t.rfind("}")
    if start != -1 and end != -1:
        return t[start: end + 1].strip()
    return t


def _qwen_result(
    df: pd.DataFrame,
    model: str,
    base_url: str,
    enabled_diagnostics: dict[str, bool] | None = None,
    enabled_tools: dict[str, bool] | None = None,
) -> DetectionResult:
    user_msg = _build_user_prompt(df, enabled_diagnostics, enabled_tools)

    think_text, answer_text = _call_ollama_stream(user_msg, model, base_url)
    cleaned = _extract_json(answer_text)

    # Robust parse: if cleaned JSON still fails, try stripping known bad tokens
    # (e.g. "0.0-1.0" range literals, bare "N" index placeholders from schema echo)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        import re as _re
        # Replace literal schema placeholders: N → 0, 0.0-1.0 → 0.5
        repaired = _re.sub(r'"index"\s*:\s*N\b', '"index": 0', cleaned)
        repaired = _re.sub(r'\b0\.0-1\.0\b', '0.5', repaired)
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            # Give up and return CUSUM — caller already catches and wraps
            raise
    cps = parsed.get("changepoints", [])

    # Attach timestamps
    dates = pd.DatetimeIndex(df["ds"])
    for cp in cps:
        idx = int(cp.get("index", -1))
        if 0 <= idx < len(df):
            cp["timestamp"] = str(dates[idx].date())

    # Build reasoning narrative
    reasoning_parts: list[str] = []
    if think_text:
        reasoning_parts.append("**Qwen reasoning (think block):**\n" + think_text)
    reasoning_parts.append(
        f"\n**Changepoints detected ({len(cps)}):**\n"
        + "\n".join(
            f"  • {cp.get('timestamp','?')} — {cp.get('type','?')} drift "
            f"({cp.get('direction','?')}, confidence {cp.get('confidence',0):.0%}): "
            f"{cp.get('reason','')}"
            for cp in cps
        )
    )
    reasoning = "\n".join(reasoning_parts)

    return DetectionResult(changepoints=cps, reasoning=reasoning, source="qwen", model=model)


# ---------------------------------------------------------------------------
# Claude (Anthropic) backend
# ---------------------------------------------------------------------------

def _build_user_prompt(
    df: pd.DataFrame,
    enabled_diagnostics: dict[str, bool] | None = None,
    enabled_tools: dict[str, bool] | None = None,
) -> str:
    """Build the shared user prompt string from a DataFrame.

    When ``enabled_diagnostics`` or ``enabled_tools`` are provided the prompt
    tells the model which diagnostic dimensions are active and which intervention
    tools are available — mirroring what the changepoint pipeline passes to its
    decision node.
    """
    sampled = df.iloc[::_STEP].copy()
    sampled["orig_idx"] = sampled.index
    pts = " ".join(f"({int(r.orig_idx)},{r.y:.1f})" for r in sampled.itertuples())
    schema = (
        '{"changepoints":[{"index":0,"type":"sudden|gradual|seasonal|recurring",'
        '"direction":"positive|negative","confidence":0.8,"reason":"brief explanation"}]}'
    )

    diag_section = ""
    if enabled_diagnostics:
        active = [k for k, v in enabled_diagnostics.items() if v]
        hidden = [k for k, v in enabled_diagnostics.items() if not v]
        diag_section = (
            f"\nActive diagnostics (focus on these): {', '.join(active)}."
            + (f"\nHidden diagnostics (ignore): {', '.join(hidden)}." if hidden else "")
        )

    tool_section = ""
    if enabled_tools:
        active_tools = [k for k, v in enabled_tools.items() if v]
        tool_section = f"\nAvailable intervention tools: {', '.join(active_tools)}."

    return (
        f"Analyse this time series for changepoints and drifts.\n"
        f"{len(sampled)} sample points (every {_STEP}th of {len(df)} daily observations):\n"
        f"{pts}\n"
        f"{diag_section}{tool_section}\n\n"
        f"Identify up to 10 changepoints at their original indices. "
        f"Think carefully about the direction and magnitude of each change. "
        f"Return ONLY valid JSON (no markdown, no schema, just the answer): {schema}"
    )


def _attach_timestamps(cps: list[dict], df: pd.DataFrame) -> list[dict]:
    dates = pd.DatetimeIndex(df["ds"])
    for cp in cps:
        idx = int(cp.get("index", -1))
        if 0 <= idx < len(df):
            cp["timestamp"] = str(dates[idx].date())
    return cps


def _claude_api_key() -> str | None:
    """Return ANTHROPIC_API_KEY from env or .env file, or None."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    # Try .env file relative to project root
    try:
        _root = __file__
        for _ in range(5):
            _root = os.path.dirname(_root)
            dotenv = os.path.join(_root, ".env")
            if os.path.isfile(dotenv):
                with open(dotenv) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("ANTHROPIC_API_KEY="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
    except Exception:
        pass
    return None


def _claude_result(
    df: pd.DataFrame,
    model: str,
    enabled_diagnostics: dict[str, bool] | None = None,
    enabled_tools: dict[str, bool] | None = None,
) -> DetectionResult:
    """Call Claude API (non-streaming) and return DetectionResult."""
    key = _claude_api_key()
    if not key:
        result = _cusum_result(df)
        result.reasoning = "ANTHROPIC_API_KEY not set. " + result.reasoning
        return result

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        user_msg = _build_user_prompt(df, enabled_diagnostics, enabled_tools)

        full_text = ""
        with client.messages.stream(
            model=model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            for chunk in stream.text_stream:
                full_text += chunk

        cleaned = _extract_json(full_text)
        parsed = json.loads(cleaned)
        cps = _attach_timestamps(parsed.get("changepoints", []), df)

        reasoning = (
            f"**Claude ({model}) reasoning:**\n{full_text}\n\n"
            f"**Changepoints detected ({len(cps)}):**\n"
            + "\n".join(
                f"  • {cp.get('timestamp','?')} — {cp.get('type','?')} drift "
                f"({cp.get('direction','?')}, confidence {cp.get('confidence',0):.0%}): "
                f"{cp.get('reason','')}"
                for cp in cps
            )
        )
        return DetectionResult(changepoints=cps, reasoning=reasoning, source="claude", model=model)

    except Exception as exc:
        result = _cusum_result(df)
        result.reasoning = f"Claude error ({exc}); using CUSUM fallback.\n\n" + result.reasoning
        return result


def detect_streaming(
    df: pd.DataFrame,
    model: str,
    ollama_url: str = OLLAMA_BASE_URL,
    langsmith_tracing: bool = False,
    enabled_diagnostics: dict[str, bool] | None = None,
    enabled_tools: dict[str, bool] | None = None,
) -> Generator[str, None, DetectionResult]:
    """Generator that yields reasoning text chunks, then populates a DetectionResult.

    Usage in Streamlit::

        gen = detect_streaming(df, model, langsmith_tracing=True)
        for chunk in gen:
            # render chunk live
        result = gen.detection_result  # set after exhaustion

    Backends:
      - model starts with "claude-"  → streaming Anthropic API
      - model starts with "bedrock/" → non-streaming Bedrock (all text yielded at once)
      - otherwise                    → Ollama (Qwen) or CUSUM fallback

    When ``langsmith_tracing=True``, the completed result is annotated with a
    LangSmith trace URL (or an error note if the endpoint is unreachable).
    """
    result_holder: list[DetectionResult] = []

    def _gen() -> Generator[str, None, None]:
        if model.startswith("claude-"):
            key = _claude_api_key()
            if not key:
                text = "⚠️ ANTHROPIC_API_KEY not set — falling back to CUSUM.\n"
                yield text
                result_holder.append(_cusum_result(df))
                return

            try:
                import anthropic
                client = anthropic.Anthropic(api_key=key)
                user_msg = _build_user_prompt(df, enabled_diagnostics, enabled_tools)
                full_text = ""
                yield f"🤖 **Claude ({model}) is thinking…**\n\n"
                with client.messages.stream(
                    model=model,
                    max_tokens=1024,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                ) as stream:
                    for chunk in stream.text_stream:
                        full_text += chunk
                        yield chunk

                yield "\n\n---\n"
                cleaned = _extract_json(full_text)
                parsed = json.loads(cleaned)
                cps = _attach_timestamps(parsed.get("changepoints", []), df)
                summary = (
                    f"\n**Changepoints detected ({len(cps)}):**\n"
                    + "\n".join(
                        f"  • {cp.get('timestamp','?')} — {cp.get('type','?')} drift "
                        f"({cp.get('direction','?')}, {cp.get('confidence',0):.0%}): {cp.get('reason','')}"
                        for cp in cps
                    )
                )
                yield summary
                result_holder.append(
                    DetectionResult(
                        changepoints=cps,
                        reasoning=full_text + summary,
                        source="claude",
                        model=model,
                    )
                )
            except Exception as exc:
                msg = f"\n⚠️ Claude error: {exc} — falling back to CUSUM.\n"
                yield msg
                result_holder.append(_cusum_result(df))

        elif model.startswith("bedrock/"):
            # Bedrock: non-streaming; yield as a single block
            bedrock_model_id = model.removeprefix("bedrock/")
            yield f"☁️ **Bedrock ({bedrock_model_id}) — calling (non-streaming)…**\n\n"
            res = _bedrock_result(df, bedrock_model_id, enabled_diagnostics, enabled_tools)
            yield res.reasoning
            result_holder.append(res)

        else:
            # Ollama / CUSUM path — no streaming available; yield whole text at once
            if _ollama_available(model, ollama_url):
                try:
                    res = _qwen_result(df, model, ollama_url, enabled_diagnostics, enabled_tools)
                    yield res.reasoning
                    result_holder.append(res)
                    return
                except Exception as exc:
                    yield f"⚠️ Qwen error: {exc} — falling back to CUSUM.\n"
            else:
                yield f"⚠️ Ollama not reachable at {ollama_url} — using CUSUM.\n"

            res = _cusum_result(df)
            yield res.reasoning
            result_holder.append(res)

    g = _gen()

    class _StreamingGen:
        """Wraps a generator and stores the DetectionResult after exhaustion."""
        detection_result: DetectionResult | None = None

        def __iter__(self):
            return self

        def __next__(self):
            try:
                return next(g)
            except StopIteration:
                res = result_holder[0] if result_holder else _cusum_result(df)
                if langsmith_tracing:
                    res = _wrap_with_langsmith(res, df)
                self.detection_result = res
                raise

    return _StreamingGen()


# ---------------------------------------------------------------------------
# Bedrock (langchain_aws) backend — lazy import, graceful degradation
# ---------------------------------------------------------------------------

def _bedrock_env() -> dict[str, str]:
    """Read AWS env from os.environ or .env file."""
    keys = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION")
    env: dict[str, str] = {k: os.environ.get(k, "").strip() for k in keys}
    if not all(env.values()):
        try:
            _root = __file__
            for _ in range(5):
                _root = os.path.dirname(_root)
                dotenv = os.path.join(_root, ".env")
                if os.path.isfile(dotenv):
                    with open(dotenv) as f:
                        for line in f:
                            line = line.strip()
                            for k in keys:
                                if line.startswith(f"{k}="):
                                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                                    if val:
                                        env[k] = val
        except Exception:
            pass
    return env


def _bedrock_result(
    df: pd.DataFrame,
    model_id: str,
    enabled_diagnostics: dict[str, bool] | None = None,
    enabled_tools: dict[str, bool] | None = None,
) -> DetectionResult:
    """Call AWS Bedrock via langchain_aws.ChatBedrockConverse (lazy import)."""
    env = _bedrock_env()
    if not env.get("AWS_ACCESS_KEY_ID") or not env.get("AWS_SECRET_ACCESS_KEY"):
        result = _cusum_result(df)
        result.reasoning = "⚠️ AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY not set. " + result.reasoning
        return result

    try:
        from langchain_aws import ChatBedrockConverse  # noqa: PLC0415
        from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415
    except ImportError:
        result = _cusum_result(df)
        result.reasoning = "⚠️ langchain_aws not installed. " + result.reasoning
        return result

    try:
        chat = ChatBedrockConverse(
            model=model_id,
            region_name=env.get("AWS_REGION", "us-west-2"),
            max_tokens=1024,
            aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        )
        user_msg = _build_user_prompt(df, enabled_diagnostics, enabled_tools)
        response = chat.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])
        full_text = response.content if isinstance(response.content, str) else str(response.content)
        cleaned = _extract_json(full_text)
        parsed = json.loads(cleaned)
        cps = _attach_timestamps(parsed.get("changepoints", []), df)
        reasoning = (
            f"**Bedrock ({model_id}) response:**\n{full_text}\n\n"
            f"**Changepoints detected ({len(cps)}):**\n"
            + "\n".join(
                f"  • {cp.get('timestamp','?')} — {cp.get('type','?')} drift "
                f"({cp.get('direction','?')}, {cp.get('confidence',0):.0%}): {cp.get('reason','')}"
                for cp in cps
            )
        )
        return DetectionResult(changepoints=cps, reasoning=reasoning, source="bedrock", model=model_id)
    except Exception as exc:
        result = _cusum_result(df)
        result.reasoning = f"⚠️ Bedrock error ({exc}) — CUSUM fallback.\n\n" + result.reasoning
        return result


# ---------------------------------------------------------------------------
# LangSmith tracing wrapper
# ---------------------------------------------------------------------------

def _langsmith_api_key() -> str:
    """Return LANGSMITH_API_KEY from env or .env, empty string if absent."""
    key = os.environ.get("LANGSMITH_API_KEY", "").strip()
    if key:
        return key
    try:
        _root = __file__
        for _ in range(5):
            _root = os.path.dirname(_root)
            dotenv = os.path.join(_root, ".env")
            if os.path.isfile(dotenv):
                with open(dotenv) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("LANGSMITH_API_KEY="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
    except Exception:
        pass
    return ""


def _wrap_with_langsmith(
    result: DetectionResult,
    df: pd.DataFrame,
    project: str = "agent-in-the-loop-forecasting",
) -> DetectionResult:
    """Try to record a LangSmith run for ``result``; silently degrades on any error.

    Annotates ``result.langsmith_run_url`` with the trace URL if successful.
    """
    api_key = _langsmith_api_key()
    if not api_key:
        return result

    try:
        import ssl as _ssl
        import uuid

        from langsmith import Client  # noqa: PLC0415

        # Pass api_url to skip the /info health-check probe that triggers SSL errors
        # on the Walmart corporate proxy.  APAC free-tier: https://apac.smith.langchain.com
        _api_url = os.environ.get("LANGSMITH_API_URL", "").strip() or os.environ.get("LANGSMITH_ENDPOINT", "").strip()

        # Build client kwargs — only add api_url when explicitly configured
        _client_kwargs: dict = {"api_key": api_key}
        if _api_url:
            _client_kwargs["api_url"] = _api_url

        client = Client(**_client_kwargs)
        run_id = str(uuid.uuid4())
        run_name = f"drift-detection-{result.source}"

        client.create_run(
            id=run_id,
            name=run_name,
            run_type="chain",
            project_name=project,
            inputs={
                "model": result.model,
                "n_rows": len(df),
                "source": result.source,
            },
            outputs={
                "changepoints_count": len(result.changepoints),
                "changepoints": result.changepoints[:5],  # trim for storage
                "reasoning_preview": result.reasoning[:500],
            },
        )
        client.update_run(run_id, end_time=None, status="success")

        try:
            url = client.get_run_url(run_id=run_id, project_name=project)
            result.langsmith_run_url = str(url)
        except Exception:
            result.langsmith_run_url = f"Run ID: {run_id} (URL unavailable)"

    except Exception as exc:
        # SSL failures, network errors, auth errors — all non-fatal
        result.langsmith_run_url = f"⚠️ LangSmith trace failed: {type(exc).__name__}: {exc}"

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect(
    df: pd.DataFrame,
    model: str = DEFAULT_MODEL,
    ollama_url: str = OLLAMA_BASE_URL,
    langsmith_tracing: bool = False,
    enabled_diagnostics: dict[str, bool] | None = None,
    enabled_tools: dict[str, bool] | None = None,
) -> DetectionResult:
    """Run changepoint detection on ``df`` (must have ``ds``, ``y`` columns).

    ``enabled_diagnostics`` and ``enabled_tools`` are forwarded into the user
    prompt so the model knows which dimensions to focus on and which intervention
    tools are available.
    """
    if model.startswith("claude-"):
        result = _claude_result(df, model, enabled_diagnostics, enabled_tools)
    elif model.startswith("bedrock/"):
        result = _bedrock_result(df, model.removeprefix("bedrock/"), enabled_diagnostics, enabled_tools)
    elif _ollama_available(model, ollama_url):
        try:
            result = _qwen_result(df, model, ollama_url, enabled_diagnostics, enabled_tools)
        except Exception as exc:
            result = _cusum_result(df)
            result.reasoning = f"Qwen error ({exc}); CUSUM fallback.\n\n" + result.reasoning
    else:
        result = _cusum_result(df)
        result.reasoning = f"Ollama not reachable at {ollama_url}.\n\n" + result.reasoning

    if langsmith_tracing:
        result = _wrap_with_langsmith(result, df)

    return result
