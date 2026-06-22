"""The ~100-case catalog: declarative recipes per (bucket × lever), each admitted by verify.py.

Design choice (matches the live level_shift→ramp finding): the gold expected_intervention_family
is the GATE-WINNING family, not the injected intent. We ALSO record the authored intent so the
divergence is auditable. A recipe is kept only if the gate admits it in its intended bucket;
otherwise we re-roll the knob across a small sweep, and skip if none lands (logged, not silent).

Buckets/levers (Topic-2 D8): competence / prompt / pipeline probes are synthetic_combined and must
be SOLVABLE-by-exactly-one-family; the tool lever is unsolvable (fallback). Real cases are added
separately by real.py (objective-only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from generator import base


@dataclass
class CaseSpec:
    scenario_id: str
    title: str
    length: int
    train_end: int
    n_cps: int
    lever: str                      # competence | prompt | pipeline | tool
    source_bucket: str              # synthetic_combined | unsolvable
    dev_or_test: str                # dev | test
    draft_family: str               # authored intent OR "fallback" (unsolvable)
    build: Callable[[Any], list[dict]]   # (df) -> gt_records ; mutates df['y']
    seed: int
    note: str = ""


# A "recipe" is a function taking (df, knob) -> gt_records, plus a sweep of knobs to try until the
# gate admits. Knobs let us re-roll magnitudes when a recipe doesn't trip its lever.

def _step(idx: int):
    def f(df, lift):
        return base.inject_step(df, [(idx, lift)])
    return f


def _ramp(start: int, end: int):
    def f(df, lift):
        return base.inject_ramp(df, start, end, lift)
    return f


def _events(blocks_no_lift: list[tuple[int, int]]):
    def f(df, lift):
        return base.inject_events(df, [(s, e, lift) for s, e in blocks_no_lift])
    return f


def _recurring_plus_kinks(month, d0, d1, years, kinks):
    def f(df, lift):
        base.inject_recurring(df, month, d0, d1, lift, years)
        return base.inject_kinks(df, kinks)
    return f


def _grow_amp():
    def f(df, rate):
        return base.inject_growing_seasonal_amplitude(df, rate)
    return f


def _mult():
    def f(df, strength):
        return base.inject_multiplicative_seasonality(df, strength)
    return f


def _nonlinear():
    def f(df, curv):
        return base.inject_nonlinear_trend(df, curv)
    return f


# Recipe registry: lever -> list of (recipe_fn, knob_sweep, draft_family, n_cps, length, train_end, note)
# Knobs are tried in order; the first the gate admits in-bucket is kept.
SHORT, SHORT_TE = base.SHORT_LEN, base.SHORT_TRAIN_END
LONG, LONG_TE = base.LONG_LEN, base.LONG_TRAIN_END

# Each entry yields ONE family of cases; we instantiate several with different seeds + index jitter.
RECIPE_FAMILIES: list[dict[str, Any]] = [
    # ---- competence (clean single-structure, solvable by exactly one tool) ----
    {"lever": "competence", "bucket": "synthetic_combined", "draft": "full_history_ramp_regressor",
     "make": lambda i: _ramp(300 + (i % 3) * 20, 520 + (i % 3) * 20), "knobs": [58.0, 70.0, 90.0],
     "n_cps": 2, "len": SHORT, "te": SHORT_TE, "note": "clean gradual drift"},
    {"lever": "competence", "bucket": "synthetic_combined", "draft": "full_history_clean_event",
     "make": lambda i: _events([(250 + i * 5, 268 + i * 5), (420, 444), (575, 600)]), "knobs": [40.0, 55.0, 70.0],
     "n_cps": 2, "len": SHORT, "te": SHORT_TE, "note": "clean temporary events"},
    {"lever": "competence", "bucket": "synthetic_combined", "draft": "full_history_step_regressor",
     "make": lambda i: _step(420 + i * 7), "knobs": [40.0, 60.0, 85.0],
     "n_cps": 2, "len": SHORT, "te": SHORT_TE, "note": "clean level shift (gate decides family)"},
    # ---- prompt probes (solvable; the weakness is the prompt) ----
    {"lever": "prompt", "bucket": "synthetic_combined", "draft": "full_history_ramp_regressor",
     "make": lambda i: _ramp(480 + i * 8, 620 + i * 8), "knobs": [42.0, 55.0, 70.0],
     "n_cps": 2, "len": SHORT, "te": SHORT_TE, "note": "P3 drift-looks-like-step"},
    {"lever": "prompt", "bucket": "synthetic_combined", "draft": "full_history_clean_event",
     "make": lambda i: _events([(300 + i * 6, 330 + i * 6)]), "knobs": [50.0, 65.0, 80.0],
     "n_cps": 2, "len": SHORT, "te": SHORT_TE, "note": "P4 dominant event + distractor"},
    # ---- pipeline probes (solvable-in-principle; harder structure but still beatable) ----
    {"lever": "pipeline", "bucket": "synthetic_combined", "draft": "full_history_clean_event",
     "make": lambda i: _events([(150 + i * 10, 230 + i * 10)]), "knobs": [60.0, 80.0, 100.0],
     "n_cps": 2, "len": SHORT, "te": SHORT_TE, "note": "T2 longer event"},
    {"lever": "pipeline", "bucket": "synthetic_combined", "draft": "full_history_ramp_regressor",
     "make": lambda i: _ramp(400 + i * 8, 460 + i * 8), "knobs": [40.0, 55.0, 70.0],
     "n_cps": 2, "len": SHORT, "te": SHORT_TE, "note": "T1 short drift"},
    # ---- tool lever (unsolvable: out-of-vocabulary; expected fallback) ----
    {"lever": "tool", "bucket": "unsolvable", "draft": "fallback",
     "make": lambda i: _grow_amp(), "knobs": [0.06, 0.09, 0.12, 0.16],
     "n_cps": 2, "len": LONG, "te": LONG_TE, "note": "growing seasonal amplitude (NOTES.md sinusoid)"},
    {"lever": "tool", "bucket": "unsolvable", "draft": "fallback",
     "make": lambda i: _mult(), "knobs": [0.6, 0.9, 1.2, 1.6],
     "n_cps": 2, "len": LONG, "te": LONG_TE, "note": "multiplicative seasonality"},
    {"lever": "tool", "bucket": "unsolvable", "draft": "fallback",
     "make": lambda i: _nonlinear(), "knobs": [40.0, 60.0, 90.0, 130.0],
     "n_cps": 2, "len": LONG, "te": LONG_TE, "note": "nonlinear (quadratic) trend"},
]
