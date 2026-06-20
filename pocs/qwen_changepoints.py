"""Qwen-3.5 (via Ollama) changepoint detection on generated drift series.

Uses the local Ollama server (http://localhost:11434) with the qwen3.5:4b
model to identify changepoints in each generated time-series graph.

Usage
-----
    # Default: use Qwen via Ollama
    python3 pocs/qwen_changepoints.py

    # Force CUSUM fallback (no LLM):
    python3 pocs/qwen_changepoints.py --no-llm

    # Use a different Ollama model:
    python3 pocs/qwen_changepoints.py --model qwen3:4b

Prerequisites
-------------
    ollama serve               # Ollama must be running
    ollama pull qwen3.5:4b    # model must be pulled (already done)

Outputs
-------
    pocs/qwen/changepoints.json   — detected changepoints per series
    pocs/qwen/changepoints.csv    — flat CSV of all changepoints
    pocs/qwen/<series>_qwen.png   — annotated plot per series
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── Project path bootstrap ────────────────────────────────────────────────
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from ailf.pipelines.drift.datasets import DriftGenerator  # noqa: E402

CONFIG = _PROJECT_ROOT / "src" / "config" / "config.yml"
OUT_DIR = pathlib.Path(__file__).parent / "qwen"
OUT_DIR.mkdir(exist_ok=True)

N_YEARS = 5
N_POINTS = N_YEARS * 365
START_DATE = "2020-01-01"
SEED = 7

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL   = "qwen3.5:4b"


# ── Generate the same 5-year series used in visualize_drift.py ───────────

def _build_series() -> dict[str, pd.DataFrame]:
    """Re-generate the SPEC §9 5-year series for changepoint analysis."""
    gen = DriftGenerator(config_path=CONFIG, trend="sine")
    start_ts = pd.Timestamp(START_DATE)
    QUARTER_DAYS = 91

    def _qspecs(seed_offset: int) -> list[dict]:
        rng_q = np.random.default_rng(SEED + seed_offset)
        specs = []
        for q in range(N_YEARS * 4):
            q_end = min((q + 1) * QUARTER_DAYS, N_POINTS) - 1
            burst_s = max(q_end - 9, q * QUARTER_DAYS)
            if burst_s >= N_POINTS:
                break
            sign = -1.0 if rng_q.random() < 0.30 else 1.0
            mag  = sign * rng_q.uniform(5.0, 10.0)
            specs.append({
                "type": "recurring", "period": N_POINTS + 1,
                "duration": 10, "magnitude": abs(mag),
                "_sign": sign, "_burst_start": burst_s,
            })
        return specs

    def _burst(y: np.ndarray, specs: list[dict]) -> None:
        for s in specs:
            bs = s["_burst_start"]
            y[bs:min(bs + 10, N_POINTS)] += s["magnitude"] * s["_sign"]

    def _base(seed_offset: int, extra: list[dict] | None = None) -> pd.DataFrame:
        qspecs = _qspecs(seed_offset)
        drift_specs = extra or [{"type": "sudden", "drift_point": 0, "magnitude": 0.0}]
        df, _ = gen.combined_drift(
            drift_specs=drift_specs, seed=SEED,
            n_points=N_POINTS, noise_std=0.5,
            start_date=START_DATE, freq="D",
        )
        y = df["y"].to_numpy().copy()
        _burst(y, qspecs)
        return pd.DataFrame({"ds": df["ds"], "y": y})

    # Graph i
    df_i = _base(1)
    yr2_q3_s = (pd.Timestamp("2021-07-01") - start_ts).days
    yr2_q3_e = (pd.Timestamp("2021-09-30") - start_ts).days
    y_i = df_i["y"].to_numpy().copy()
    for k in range(yr2_q3_s, min(yr2_q3_e, N_POINTS)):
        y_i[k] += -0.18 * (k - yr2_q3_s)
    df_i["y"] = y_i

    # Graph ii
    q4q1: list[dict] = []
    for yr_off in range(N_YEARS):
        year = pd.Timestamp(START_DATE).year + yr_off
        q4 = (pd.Timestamp(f"{year}-10-01") - start_ts).days
        q1 = (pd.Timestamp(f"{year}-01-01") - start_ts).days
        q2 = (pd.Timestamp(f"{year}-04-01") - start_ts).days
        q3e = (pd.Timestamp(f"{year}-09-30") - start_ts).days
        if 0 <= q4 < N_POINTS:
            q4q1.append({"type": "sudden", "drift_point": q4, "magnitude": 15.0})
        if 0 <= q1 < N_POINTS:
            q4q1.append({"type": "sudden", "drift_point": q1, "magnitude": -12.0})
        if 0 <= q2 < N_POINTS:
            q4q1.append({"type": "gradual", "drift_start": q2,
                          "drift_end": min(q3e, N_POINTS), "magnitude": 8.0})
    df_ii = _base(2, extra=q4q1)

    # Graph iii
    q2specs: list[dict] = []
    for yr_off in range(N_YEARS):
        year = pd.Timestamp(START_DATE).year + yr_off
        q2 = (pd.Timestamp(f"{year}-04-01") - start_ts).days
        if 0 <= q2 < N_POINTS:
            q2specs.append({"type": "sudden", "drift_point": q2, "magnitude": 20.0})
    df_iii = _base(3, extra=q2specs)
    y_iii = df_iii["y"].to_numpy().copy()
    y_iii += -0.05 * np.arange(N_POINTS, dtype=float)
    df_iii["y"] = y_iii

    return {
        "graph_i_neg_yr2q3":    df_i,
        "graph_ii_q4up_q1down": df_ii,
        "graph_iii_neg_q2up":   df_iii,
    }


# ── CUSUM changepoint detector ────────────────────────────────────────────

def _cusum_changepoints(y: np.ndarray, threshold_sigma: float = 4.0, min_gap: int = 14) -> list[int]:
    """CUSUM detector — returns indices of detected changepoints."""
    mu, sigma = np.mean(y), max(np.std(y), 1e-9)
    z = (y - mu) / sigma
    cp_pos = np.zeros(len(y))
    cp_neg = np.zeros(len(y))
    changepoints: list[int] = []
    last_cp = -min_gap

    for i in range(1, len(y)):
        cp_pos[i] = max(0, cp_pos[i - 1] + z[i] - 0.5)
        cp_neg[i] = max(0, cp_neg[i - 1] - z[i] - 0.5)
        if (cp_pos[i] > threshold_sigma or cp_neg[i] > threshold_sigma) \
                and (i - last_cp) >= min_gap:
            changepoints.append(i)
            cp_pos[i] = cp_neg[i] = 0
            last_cp = i

    return changepoints


# ── Qwen via Ollama ───────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a time-series expert. "
    "Output ONLY valid JSON — no markdown, no explanation outside the JSON."
)


def _call_ollama(prompt: str, model: str) -> str:
    """Call Ollama chat API via streaming, concatenate content chunks.

    qwen3.5 is a reasoning model: the final answer comes after a <think>
    block and only appears in streamed content chunks (not in the non-stream
    single response). We stream and join all content deltas.
    """
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "stream": True,
        "think": False,          # disable extended thinking for speed
        "options": {"temperature": 0.1, "num_predict": 512},
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode()

    # Each line is a JSON object; concatenate message.content across all chunks
    chunks: list[str] = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        obj = json.loads(line)
        content = obj.get("message", {}).get("content", "")
        if content:
            chunks.append(content)

    return "".join(chunks)


_STEP = 21   # downsample factor: 1825 pts → ~87 sample points per series


def _extract_json(content: str) -> str:
    """Strip thinking block and markdown fences from Qwen output."""
    if "<think>" in content:
        end = content.find("</think>")
        content = content[end + len("</think>"):].strip() if end != -1 else content
    if content.startswith("```"):
        content = "\n".join(content.split("\n")[1:])
    if "```" in content:
        content = content[: content.rfind("```")]
    # Extract first { … } block
    start = content.find("{")
    end   = content.rfind("}")
    if start != -1 and end != -1:
        content = content[start: end + 1]
    return content.strip()


def _qwen_changepoints(df: pd.DataFrame, series_name: str, model: str) -> list[dict]:
    """Ask Qwen (via Ollama, no extended thinking) to detect changepoints."""
    sampled = df.iloc[::_STEP].copy()
    sampled["orig_idx"] = sampled.index
    pts = " ".join(f"({int(r.orig_idx)},{r.y:.1f})" for r in sampled.itertuples())
    schema = (
        '{"changepoints":[{"index":N,"type":"sudden|gradual|seasonal|recurring",'
        '"direction":"positive|negative","confidence":0.9,"reason":"brief"}]}'
    )
    user_msg = (
        f"{len(sampled)} sample pts (every {_STEP}th of {len(df)} daily):\n"
        f"{pts}\n\n"
        f"Top 10 changepoints (original indices). JSON only: {schema}"
    )
    content = _call_ollama(user_msg, model)
    cleaned = _extract_json(content)
    if not cleaned:
        raise ValueError("Empty response from Qwen")
    parsed = json.loads(cleaned)
    return parsed.get("changepoints", [])


# ── Visualise changepoints ────────────────────────────────────────────────

_TYPE_COLORS = {
    "sudden":    "crimson",
    "gradual":   "darkorange",
    "seasonal":  "gold",
    "recurring": "mediumpurple",
    "unknown":   "gray",
}
_DIR_MARKERS = {"positive": "^", "negative": "v", "unknown": "D"}


def _plot_changepoints(
    df: pd.DataFrame, changepoints: list[dict], series_name: str, source: str
) -> None:
    dates = pd.DatetimeIndex(df["ds"])
    y = df["y"].to_numpy()

    fig, ax = plt.subplots(figsize=(18, 5))
    ax.plot(dates, y, lw=0.7, color="steelblue", alpha=0.9)

    plotted_types: set[str] = set()
    for cp in changepoints:
        idx = int(cp.get("index", -1))
        if idx < 0 or idx >= len(df):
            continue
        cp_type  = cp.get("type", "unknown")
        direction = cp.get("direction", "unknown")
        confidence = float(cp.get("confidence", 0.8))
        color  = _TYPE_COLORS.get(cp_type, "gray")
        marker = _DIR_MARKERS.get(direction, "o")

        ax.axvline(dates[idx], color=color, lw=1.0, alpha=min(confidence + 0.2, 1.0), ls="--")
        ax.plot(dates[idx], y[idx], marker=marker, color=color,
                markersize=7, zorder=6,
                label=cp_type if cp_type not in plotted_types else "")
        plotted_types.add(cp_type)

    legend_handles = [
        mpatches.Patch(color=c, alpha=0.75, label=t)
        for t, c in _TYPE_COLORS.items() if t in plotted_types
    ] + [
        plt.Line2D([0],[0], marker="^", color="black", ls="", markersize=6, label="positive"),
        plt.Line2D([0],[0], marker="v", color="black", ls="", markersize=6, label="negative"),
        plt.Line2D([0],[0], marker="D", color="black", ls="", markersize=5, label="unknown dir."),
    ]
    ax.legend(handles=legend_handles, loc="upper left", fontsize=7, ncol=5)
    ax.set_title(
        f"{series_name}  —  Changepoints via {source}  ({len(changepoints)} found)",
        fontsize=11,
    )
    ax.set_ylabel("y")
    ax.tick_params(axis="x", rotation=30, labelsize=8)
    fig.tight_layout()

    out = OUT_DIR / f"{series_name}_qwen.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {out.resolve()}")


# ── Main ─────────────────────────────────────────────────────────────────

def main(use_llm: bool = True, model: str = DEFAULT_MODEL) -> None:
    # Probe Ollama availability
    if use_llm:
        try:
            with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=5) as r:
                available = [m["name"] for m in json.loads(r.read()).get("models", [])]
            if model not in available:
                print(f"⚠  Model '{model}' not in Ollama ({available}). Falling back to CUSUM.")
                use_llm = False
            else:
                print(f"✓  Ollama running — using model: {model}")
        except Exception as exc:
            print(f"⚠  Ollama not reachable ({exc}). Falling back to CUSUM.")
            use_llm = False

    source = f"Qwen via Ollama ({model})" if use_llm else "CUSUM (fallback)"
    print(f"Changepoint source: {source}\n")

    print("Generating series…")
    series_map = _build_series()

    all_results: dict[str, list[dict]] = {}

    for name, df in series_map.items():
        print(f"\n[{name}]")
        if use_llm:
            try:
                cps = _qwen_changepoints(df, name, model)
                print(f"  Qwen found {len(cps)} changepoints")
                # Attach timestamps
                dates = pd.DatetimeIndex(df["ds"])
                for cp in cps:
                    idx = int(cp.get("index", -1))
                    if 0 <= idx < len(df):
                        cp["timestamp"] = str(dates[idx].date())
                    cp["series"] = name
            except Exception as exc:
                print(f"  ⚠ Qwen error: {exc}  →  falling back to CUSUM")
                idxs = _cusum_changepoints(df["y"].to_numpy())
                dates = pd.DatetimeIndex(df["ds"])
                cps = [{"index": i, "type": "sudden", "direction": "unknown",
                         "confidence": 0.7, "reason": "CUSUM fallback",
                         "timestamp": str(dates[i].date()), "series": name}
                        for i in idxs]
        else:
            idxs = _cusum_changepoints(df["y"].to_numpy())
            dates = pd.DatetimeIndex(df["ds"])
            cps = [{"index": i, "type": "sudden", "direction": "unknown",
                     "confidence": 0.7, "reason": "CUSUM detector",
                     "timestamp": str(dates[i].date()), "series": name}
                    for i in idxs]
            print(f"  CUSUM found {len(cps)} changepoints")

        all_results[name] = cps
        _plot_changepoints(df, cps, name, source)

    # Save JSON
    json_out = OUT_DIR / "changepoints.json"
    with json_out.open("w") as fh:
        json.dump(all_results, fh, indent=2)
    print(f"\nSaved JSON → {json_out.resolve()}")

    # Save CSV
    rows = [cp for cps in all_results.values() for cp in cps]
    if rows:
        csv_out = OUT_DIR / "changepoints.csv"
        pd.DataFrame(rows).to_csv(csv_out, index=False)
        print(f"Saved CSV  → {csv_out.resolve()}")

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qwen-3.5 (Ollama) changepoint detector")
    parser.add_argument("--no-llm",  action="store_true", help="Use CUSUM fallback, skip Ollama")
    parser.add_argument("--model",   default=DEFAULT_MODEL, help=f"Ollama model name (default: {DEFAULT_MODEL})")
    args = parser.parse_args()
    main(use_llm=not args.no_llm, model=args.model)
