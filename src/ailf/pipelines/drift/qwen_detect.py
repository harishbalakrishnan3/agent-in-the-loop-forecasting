"""Shared Qwen / CUSUM changepoint detection used by both the FastAPI and Streamlit UIs.

Exposes a single public function:

    detect(df, model, ollama_url) -> DetectionResult

where ``DetectionResult`` contains:
  - ``changepoints``  — list of changepoint dicts (index, type, direction, confidence, reason)
  - ``reasoning``     — human-readable reasoning narrative (Qwen think block or summary)
  - ``source``        — "qwen" | "cusum"
  - ``model``         — model name used

Call it before fitting Prophet; render ``reasoning`` in the UI before showing the forecast.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:4b"

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
    """Strip markdown fences and extract the first {...} block."""
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if "```" in text:
        text = text[: text.rfind("```")]
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1:
        return text[start: end + 1].strip()
    return text.strip()


def _qwen_result(df: pd.DataFrame, model: str, base_url: str) -> DetectionResult:
    sampled = df.iloc[::_STEP].copy()
    sampled["orig_idx"] = sampled.index
    pts = " ".join(f"({int(r.orig_idx)},{r.y:.1f})" for r in sampled.itertuples())

    schema = (
        '{"changepoints":[{"index":N,"type":"sudden|gradual|seasonal|recurring",'
        '"direction":"positive|negative","confidence":0.0-1.0,"reason":"brief explanation"}]}'
    )
    user_msg = (
        f"Analyse this time series for changepoints and drifts.\n"
        f"{len(sampled)} sample points (every {_STEP}th of {len(df)} daily observations):\n"
        f"{pts}\n\n"
        f"Identify up to 10 changepoints at their original indices. "
        f"Think carefully about the direction and magnitude of each change. "
        f"Return ONLY JSON (no markdown): {schema}"
    )

    think_text, answer_text = _call_ollama_stream(user_msg, model, base_url)
    cleaned = _extract_json(answer_text)
    parsed = json.loads(cleaned)
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
# Public entry point
# ---------------------------------------------------------------------------

def detect(
    df: pd.DataFrame,
    model: str = DEFAULT_MODEL,
    ollama_url: str = OLLAMA_BASE_URL,
) -> DetectionResult:
    """Run changepoint detection on ``df`` (must have ``ds``, ``y`` columns).

    Tries Qwen via Ollama first; falls back to CUSUM if Ollama is unavailable.
    Returns a :class:`DetectionResult` with ``changepoints``, ``reasoning``, and ``source``.
    """
    if _ollama_available(model, ollama_url):
        try:
            return _qwen_result(df, model, ollama_url)
        except Exception as exc:
            fallback_note = f"Qwen error ({exc}); using CUSUM fallback."
            result = _cusum_result(df)
            result.reasoning = fallback_note + "\n\n" + result.reasoning
            return result
    else:
        result = _cusum_result(df)
        result.reasoning = f"Ollama not reachable at {ollama_url}.\n\n" + result.reasoning
        return result
