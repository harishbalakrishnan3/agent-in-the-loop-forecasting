"""Slope-change changepoint POC.

Self-contained proof-of-concept that generates synthetic time series whose
changepoints are changes in trend *slope* (continuous piecewise-linear trend,
no level jumps) and evaluates whether a naive (default-configuration) Prophet
model can detect and forecast them.

Mirrors the file structure of ``pocs/changepoint/level_shift`` but shares no
code with it (imports nothing from ``level_shift`` or ``src/ailf``).
"""
