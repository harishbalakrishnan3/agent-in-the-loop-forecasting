# Drift Pipeline

The drift path is for series whose behavior changes gradually rather than abruptly. The changepoint
pipeline already includes a gradual-drift stress scenario, but a dedicated drift pipeline should
eventually own drift-specific diagnostics and tools.

## Current motivation

The report's gradual-drift scenario is a useful partial success. The agent chose the intended ramp
regressor and improved MAE from `7.32` to `4.56`, but the forecast was still visibly imperfect.

That result says the agent selected the best available family, not that the family was expressive
enough.

## What drift needs

A mature drift pipeline should improve:

- transition-shape diagnostics,
- seasonal coverage checks after the transition,
- piecewise or saturating drift tools,
- stronger prompts for comparing ramp versus step repairs,
- evaluation cases with multiple drift shapes.

## Why this matters

Gradual drift is a common production failure mode. The repair is rarely "drop all history" or
"blindly trust the latest window." The hard part is preserving useful seasonal history while
representing the transition honestly.
