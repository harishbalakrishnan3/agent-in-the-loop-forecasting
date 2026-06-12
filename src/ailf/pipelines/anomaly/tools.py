"""Outlier-flagging diagnostic tool.

A pure, typed function the agent can call. Must distinguish isolated outliers from
structural changes. Test-first against synthetic series with KNOWN injected outliers
(precision / recall / FPR) before integrating with the agent.
"""
