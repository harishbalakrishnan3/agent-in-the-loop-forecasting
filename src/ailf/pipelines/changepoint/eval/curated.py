"""The CURATED regression set — the *proper* golden dataset for monitoring fixes.

The full 90-case set (poc_golden.jsonl) was for DISCOVERY (find the failure modes). For ongoing
regression monitoring after each pipeline change, 90 is too many to eyeball; this hand-picked
10-case set is the minimal high-signal panel: every github_issues.txt fix should move at least one
case here, and the CONTROLS must never regress.

Selection (each maps to a github_issues.txt issue or is a control):
  controls (clean_success — must NOT regress):
    competence_clean_0_0   (ramp)         competence_clean_1_0  (clean_event)   prompt_p4_4_7 (clean_event)
  ISSUE 2 — crashed_indexerror (fix: clamp ramp interval bounds):
    tool_nonlinear_9_0     tool_growing_7_3
  ISSUE 1 — loop on blocked tool -> crash at final eval (fix: feed rejection reason / fallback rule):
    tool_growing_7_1       tool_multiplicative_8_3
  ISSUE 3 — never picks the explicit fallback on unsolvable cases (fix: fallback prompt rule):
    tool_growing_7_0       pipeline_t2_5_9
  extra behavioral coverage (no_proposal_beat_naive):
    competence_clean_0_4
"""

from __future__ import annotations

CURATED_IDS: list[str] = [
    # controls (must not regress)
    "competence_clean_0_0",
    "competence_clean_1_0",
    "prompt_p4_4_7",
    # ISSUE 2 — crashed_indexerror
    "tool_nonlinear_9_0",
    "tool_growing_7_3",
    # ISSUE 1 — looped_on_blocked_tool / crashed_at_final_eval
    "tool_growing_7_1",
    "tool_multiplicative_8_3",
    # ISSUE 3 — unsolvable, agent never picks fallback
    "tool_growing_7_0",
    "pipeline_t2_5_9",
    # behavioral coverage
    "competence_clean_0_4",
]

# What each case is FOR — surfaced as LangSmith example metadata so the regression panel is legible.
CURATED_ROLE: dict[str, str] = {
    "competence_clean_0_0": "control",
    "competence_clean_1_0": "control",
    "prompt_p4_4_7": "control",
    "tool_nonlinear_9_0": "issue2_crashed_indexerror",
    "tool_growing_7_3": "issue2_crashed_indexerror",
    "tool_growing_7_1": "issue1_loop_then_crash",
    "tool_multiplicative_8_3": "issue1_loop_then_crash",
    "tool_growing_7_0": "issue3_no_fallback",
    "pipeline_t2_5_9": "issue3_no_fallback",
    "competence_clean_0_4": "behavioral_no_proposal_beat_naive",
}
