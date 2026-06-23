"""Domain-agnostic boundary-matching primitives + JSONL io for the eval harness (promoted from the
``pocs/llm_eval`` POC).

Pure functions over plain serializable dicts/lists (Principle I): no use-case (changepoint) types or
tool/family names appear here. ``match_intervals`` (IoU, greedy 1:1) scores interval recall/precision;
``match_points`` (±tolerance, greedy 1:1) scores point recall — labelled ``measures="detector"``
because, for the changepoint use-case, point matching reflects the detector grid, not the agent
(the caller decides what to do with that). The "found nothing ⇒ precision is None (not 1.0)" rule
is enforced so a no-detection case never inflates precision.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_IOU_THRESHOLD = 0.5
DEFAULT_POINT_TOLERANCE = 25


def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    """IoU of two half-open intervals ``[start, end)``."""
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = (a["end"] - a["start"]) + (b["end"] - b["start"]) - inter
    return inter / union if union > 0 else 0.0


def match_intervals(gt: list[dict[str, Any]], pred: list[dict[str, Any]],
                    iou_threshold: float = DEFAULT_IOU_THRESHOLD) -> dict[str, Any]:
    """Greedy 1:1 interval match by descending IoU. Returns tp/fp/fn + precision/recall.

    ``precision`` is None when there are no predictions (tp+fp==0) — "found nothing" must not score
    1.0. ``recall`` is None when there is no ground truth (tp+fn==0)."""
    pairs = []
    for gi, g in enumerate(gt):
        for pi, p in enumerate(pred):
            v = _iou(g, p)
            if v >= iou_threshold:
                pairs.append((v, gi, pi))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))  # desc IoU, deterministic tie-break
    used_g, used_p, matches = set(), set(), []
    for v, gi, pi in pairs:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        matches.append({"gt": gt[gi], "pred": pred[pi], "iou": round(v, 4)})
    tp = len(matches)
    fp = len(pred) - tp
    fn = len(gt) - tp
    precision = None if (tp + fp) == 0 else tp / (tp + fp)
    recall = None if (tp + fn) == 0 else tp / (tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "matches": matches, "missed": [gt[i] for i in range(len(gt)) if i not in used_g],
            "iou_threshold": iou_threshold}


def match_points(gt: list[dict[str, Any]], detected: list[int],
                 tolerance: int = DEFAULT_POINT_TOLERANCE) -> dict[str, Any]:
    """Greedy 1:1 point match within ±tolerance. ``measures="detector"`` flags that point recall
    reflects the upstream detector, not the agent (caller's interpretation)."""
    g_idx = [g["index"] for g in gt]
    pairs = []
    for gi, g in enumerate(g_idx):
        for di, d in enumerate(detected):
            if abs(d - g) <= tolerance:
                pairs.append((abs(d - g), gi, di))
    pairs.sort(key=lambda t: (t[0], t[1], t[2]))  # asc distance, deterministic tie-break
    used_g, used_d = set(), set()
    for dist, gi, di in pairs:
        if gi in used_g or di in used_d:
            continue
        used_g.add(gi)
        used_d.add(di)
    tp = len(used_g)
    fp = len(detected) - len(used_d)
    fn = len(g_idx) - tp
    precision = None if (tp + fp) == 0 else tp / (tp + fp)
    recall = None if (tp + fn) == 0 else tp / (tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "tolerance": tolerance, "measures": "detector"}


# --- generic JSONL / JSON io -------------------------------------------------------------------

def write_jsonl(records: list[dict[str, Any]], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())
