"""ONE-TIME transform: build the self-contained schema-1.1 curated golden set for src/ailf.

Reads the POC curated records (pocs/llm_eval/golden_records/curated_golden.jsonl) and, for each
NON-CRASH record, INLINES the judge inputs (judged_iteration = {rationale, tool_argued_for, diag})
recovered from its agent_trace.json — using the SAME gated-iteration selection the POC judge uses —
then DROPS trace_path/metrics_path so the committed asset has no dependency on the gitignored
reports/ dir. Crash records (1.0-crash) are copied verbatim (already self-contained).

Writes:
  src/ailf/pipelines/changepoint/eval/data/curated_golden.jsonl  (schema 1.1)

Run once:  uv run python pocs/llm_eval/migrate_curated_to_src.py
"""

from __future__ import annotations

import json
from pathlib import Path

SRC_CURATED = Path("pocs/llm_eval/golden_records/curated_golden.jsonl")
REPORTS = Path("reports/changepoint")
DEST = Path("src/ailf/pipelines/changepoint/eval/data/curated_golden.jsonl")


def _judged_iteration_from_trace(scenario_id: str) -> dict | None:
    """Recover (rationale, tool_argued_for, diag) from the run's agent_trace.json, picking the
    gated full_history_prophet_tuned_holidays iteration if present, else iterations[0]."""
    tp = REPORTS / f"{scenario_id}-1729" / "agent_trace.json"
    if not tp.exists():
        return None
    t = json.loads(tp.read_text())
    its = t.get("iterations", [])
    if not its:
        return None
    gated = next((it for it in its
                  if it["proposal"].get("tool") == "full_history_prophet_tuned_holidays"), None)
    it = gated or its[0]
    d = t.get("diagnostics", {})
    return {
        "rationale": it["proposal"].get("rationale", ""),
        "tool_argued_for": it["proposal"].get("tool", ""),
        "diag": {
            "recurring_event_summary": d.get("recurring_event_summary"),
            "transient_event_score": d.get("transient_event_score"),
            "permanent_shift_magnitude": d.get("permanent_shift_magnitude"),
            "candidate_drift_intervals_count": len(d.get("candidate_drift_intervals", [])),
            "candidate_event_blocks_count": len(d.get("candidate_event_blocks", [])),
        },
    }


def main() -> None:
    out = []
    for line in SRC_CURATED.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        sid = rec["scenario_id"]
        if "crash_info" in rec:
            # already self-contained; just drop any disk paths
            rec.pop("trace_path", None)
            rec.pop("metrics_path", None)
            out.append(rec)
            continue
        ji = _judged_iteration_from_trace(sid)
        if ji is None:
            raise SystemExit(f"[migrate] missing agent_trace.json for non-crash case {sid}")
        rec["record_schema_version"] = "1.1"
        rec["judged_iteration"] = ji
        rec.pop("trace_path", None)
        rec.pop("metrics_path", None)
        out.append(rec)

    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text("\n".join(json.dumps(r) for r in out) + "\n")
    # safety: no committed string may reference reports/
    assert "reports/" not in DEST.read_text(), "committed asset still references reports/!"
    n_crash = sum(1 for r in out if "crash_info" in r)
    print(f"[migrate] wrote {len(out)} curated records ({len(out)-n_crash} schema-1.1 + {n_crash} crash) -> {DEST}")


if __name__ == "__main__":
    main()
