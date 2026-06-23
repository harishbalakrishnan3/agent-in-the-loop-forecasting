"""Streamlit shell for the streamlined agent UI (feature 006).

Thin presentation layer: a left control pane (dataset, models, diagnostics, tools, visual toggle)
and a right main area (run metadata → live event stream → verdict + interactive graph). All
non-trivial logic lives in the pure helpers (config_builder, run_controller, event_view, verdict,
chart, models); this module only wires Streamlit widgets to them and is validated via the manual
quickstart, not unit tests.

Run with:  uv run streamlit run src/ailf/ui/app.py

Covers tasks T020 (shell), T021 (live stream loop), T022 (verdict + graph), T027 (custom CSV),
T029/T030/T031 (instrument toggles).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from ailf.core.config.resolve import ConfigError
from ailf.core.config.schema import ConfigOverride, RunCredentials
from ailf.pipelines.changepoint.datasets import load_metadata
from ailf.ui import chart as chart_mod
from ailf.ui import config_builder as cb
from ailf.ui import event_view, models, run_controller, verdict as verdict_mod

_PAGE_TITLE = "Agent-in-the-Loop Forecasting"
_CSV_HELP = (
    "Upload a CSV with EXACTLY two columns: a time column named `ds` and a numeric value column "
    "named `y`. Rows must be in chronological order with no duplicate timestamps and no missing "
    "values. Train / validation / test fractions must sum to 1."
)


# --- control pane ------------------------------------------------------------------------------


def _group_heading(label: str) -> None:
    """A slightly-larger umbrella heading for a group of checkboxes."""
    st.markdown(
        f"<div style='font-size:1.05rem;font-weight:700;margin:0.5rem 0 0.15rem 0'>{label}</div>",
        unsafe_allow_html=True,
    )


def _indented_checkbox(label: str, *, key: str, help: str, value: bool = True, disabled: bool = False) -> bool:
    """Render a checkbox with a small left tab-space so items sit under their group heading."""
    spacer, body = st.columns([0.08, 0.92])
    with body:
        return st.checkbox(label, value=value, key=key, help=help, disabled=disabled)


def _render_control_pane() -> dict[str, Any]:
    """Render the left control pane and return the collected selections."""
    sel: dict[str, Any] = {}
    with st.sidebar:
        st.header("Agent-in-the-Loop Forecasting")
        start = st.button("▶ Start run", type="primary", use_container_width=True)

        st.subheader("1 · Dataset")
        mode = st.radio(
            "Data source", ["Built-in scenario", "Custom CSV"], horizontal=True,
            label_visibility="collapsed",
        )
        if mode == "Built-in scenario":
            sel["dataset_mode"] = "scenario"
            scenarios = load_metadata()["scenarios"]
            id_to_title = {s["scenario_id"]: s.get("title", s["scenario_id"]) for s in scenarios}
            sel["scenario_id"] = st.selectbox(
                "Scenario", list(id_to_title), format_func=lambda i: id_to_title[i],
            )
        else:
            sel["dataset_mode"] = "custom_csv"
            upload = st.file_uploader("CSV file (ds, y)", type=["csv"], help=_CSV_HELP)
            st.caption("Required columns: **`ds`** (time) and **`y`** (value).")
            sel["custom_df"] = pd.read_csv(upload) if upload is not None else None
            c1, c2, c3 = st.columns(3)
            sel["train_ratio"] = c1.number_input("train", 0.0, 1.0, 0.8, 0.05)
            sel["val_ratio"] = c2.number_input("val", 0.0, 1.0, 0.1, 0.05)
            sel["test_ratio"] = c3.number_input("test", 0.0, 1.0, 0.1, 0.05)
            st.caption("Fractions must sum to 1 (e.g. 0.8 / 0.1 / 0.1).")
            with st.expander("Advanced detection settings"):
                sel["seasonal_period"] = st.number_input("Seasonal period", 1, 100_000, 365)
                sel["n_changepoints_to_detect"] = st.number_input("Changepoints to detect", 1, 50, 3)

        st.subheader("2 · Models")
        sel["visual_analysis_enabled"] = st.toggle("Visual analysis", value=True)
        sel["visual_model_id"] = models.model_id_for_label(
            st.selectbox(
                "Visual model",
                models.labels(),
                index=models.labels().index(models.label_for_model_id(models.DEFAULT_VISUAL_MODEL_ID)),
                disabled=not sel["visual_analysis_enabled"],
            )
        )
        sel["decision_model_id"] = models.model_id_for_label(
            st.selectbox(
                "Reasoning agent model",
                models.labels(),
                index=models.labels().index(models.label_for_model_id(models.DEFAULT_REASONING_MODEL_ID)),
            )
        )

        st.subheader("3 · Diagnostic bundle")
        st.caption("What the agent is allowed to *see* about the series before it decides.")
        diags: dict[str, bool] = {}
        for group_label, keys in cb.DIAGNOSTIC_GROUPS:
            _group_heading(group_label)
            for key in keys:
                meta = cb.DIAGNOSTIC_META[key]
                diags[key] = _indented_checkbox(meta.label, key=f"diag_{key}", help=meta.help)
        sel["diagnostics_enabled"] = diags

        st.subheader("4 · Agent tools")
        st.caption("What the agent is allowed to *do* to fix the forecast.")
        tools: dict[str, bool] = {}
        for group_label, keys in cb.TOOL_GROUPS:
            _group_heading(group_label)
            for key in keys:
                meta = cb.TOOL_META[key]
                if key == cb.FALLBACK_TOOL_KEY:
                    # Always-on fallback: shown locked so the audience sees it can't be disabled.
                    _indented_checkbox(meta.label, key="tool_fallback", help=meta.help, disabled=True)
                else:
                    tools[key] = _indented_checkbox(meta.label, key=f"tool_{key}", help=meta.help)
        sel["tools_enabled"] = tools

    sel["start"] = start
    return sel


# --- credentials panel (main area) -------------------------------------------------------------


def _render_credentials_panel() -> RunCredentials:
    """Render the main-area Credentials panel and return a RunCredentials.

    Lives in the main area (not the sidebar). The panel makes it unmistakable that nothing is
    stored — credentials are used only for the current run, in memory, on this session.
    """
    # ``expanded`` MUST be a stable constant. Deriving it from session_state that changes within the
    # same render makes Streamlit re-apply the value on every rerun and snap the box shut whenever a
    # widget inside it changes. We start expanded and let the user collapse it.
    with st.expander("🔑 Credentials", expanded=True):
        st.info(
            "**Your credentials are never stored.** They are kept only in memory for the current "
            "session and used solely to make this run's model calls — not written to disk, not "
            "logged, not shared. Reloading the page clears them.",
            icon="🔒",
        )
        provider = st.radio(
            "Provider", ["Anthropic API", "AWS Bedrock"], horizontal=True,
            help="Bring your own credentials for whichever provider you use.",
        )

        anthropic_key = aws_id = aws_secret = aws_region = ""
        if provider == "Anthropic API":
            anthropic_key = st.text_input(
                "Anthropic API key", type="password", placeholder="sk-ant-…",
                help="Get one at console.anthropic.com. Used only for this session.",
            ).strip()
        else:
            st.warning(
                "⚠️ **Heads up:** AWS access keys are often broadly scoped. Prefer a key restricted "
                "to Bedrock, and never reuse a production key on a shared/hosted app. As above, "
                "nothing you enter here is stored.",
                icon="⚠️",
            )
            c1, c2 = st.columns(2)
            aws_id = c1.text_input("AWS access key ID", type="password", placeholder="AKIA…").strip()
            aws_secret = c2.text_input("AWS secret access key", type="password").strip()
            aws_region = st.text_input("AWS region", value="us-west-2").strip()

        # Optional LangSmith tracing. A plain toggle-gated section — NOT a nested expander, which
        # Streamlit does not reliably support inside another expander.
        st.markdown("---")
        ls_on = st.toggle("Enable LangSmith tracing", value=False, help="Trace this run to LangSmith.")
        ls_key = ""
        ls_project = "agent-in-the-loop-forecasting"
        if ls_on:
            ls_key = st.text_input(
                "LangSmith API key", type="password", placeholder="lsv2_…",
            ).strip()
            ls_project = st.text_input(
                "LangSmith project", value="agent-in-the-loop-forecasting",
            ).strip() or "agent-in-the-loop-forecasting"

    return RunCredentials(
        anthropic_api_key=anthropic_key or None,
        aws_access_key_id=aws_id or None,
        aws_secret_access_key=aws_secret or None,
        aws_region=aws_region or None,
        langsmith_tracing=bool(ls_on),
        langsmith_api_key=ls_key or None,
        langsmith_project=ls_project,
    )


# --- pre-run validation ------------------------------------------------------------------------


def _validate(sel: dict[str, Any]) -> cb.ValidationResult:
    if sel["dataset_mode"] == "scenario":
        if not sel.get("scenario_id"):
            return cb.ValidationResult(ok=False, errors=["Select a scenario."])
        return cb.ValidationResult(ok=True)
    return cb.validate_custom_series(
        sel.get("custom_df"),
        train=sel["train_ratio"], val=sel["val_ratio"], test=sel["test_ratio"],
    )


# --- run + live stream + results ---------------------------------------------------------------


def _command_metadata(sel: dict[str, Any]) -> str:
    if sel["dataset_mode"] == "scenario":
        return (
            "uv run python -m ailf.pipelines.changepoint.pipeline "
            f"--scenario {sel['scenario_id']}"
        )
    return (
        "run_scenario(series_df=<uploaded CSV>, "
        f"train_ratio={sel['train_ratio']}, val_ratio={sel['val_ratio']}, "
        f"test_ratio={sel['test_ratio']}, seasonal_period={sel['seasonal_period']}, "
        f"n_changepoints_to_detect={sel['n_changepoints_to_detect']})"
    )


def _run_and_stream(sel: dict[str, Any], credentials: RunCredentials) -> None:
    override = ConfigOverride.from_dict(
        cb.to_override_dict(
            visual_model_id=sel["visual_model_id"],
            decision_model_id=sel["decision_model_id"],
            visual_analysis_enabled=sel["visual_analysis_enabled"],
            diagnostics_enabled=sel["diagnostics_enabled"],
            tools_enabled=sel["tools_enabled"],
        )
    )

    st.subheader("What's running")
    st.code(_command_metadata(sel), language="bash")

    kwargs: dict[str, Any] = {"override": override, "credentials": credentials}
    if sel["dataset_mode"] == "scenario":
        scenario_id = sel["scenario_id"]
    else:
        scenario_id = "custom"
        kwargs.update(
            series_df=sel["custom_df"],
            train_ratio=sel["train_ratio"], val_ratio=sel["val_ratio"], test_ratio=sel["test_ratio"],
            seasonal_period=int(sel["seasonal_period"]),
            n_changepoints_to_detect=int(sel["n_changepoints_to_detect"]),
        )

    try:
        handle = run_controller.start_run(scenario_id=scenario_id, **kwargs)
    except ConfigError as exc:
        st.error(f"Cannot start: {exc}")
        return

    st.subheader("Live event stream")
    stream_area = st.container()
    progress = st.empty()
    rendered = 0
    errored = False

    # Drain the queue on the main thread until run_complete, an error, or the worker dies.
    # Each stage emits a `start` then a `complete` (or `error`); render only the terminal event so
    # every stage shows up exactly once, when it finishes (still live and in order).
    while True:
        events = run_controller.drain(handle, timeout=0.25)
        for raw in events:
            if raw.get("status") == "start":
                continue
            vm = event_view.from_event(raw)
            icon = "🛑" if vm.is_error else "•"
            # Use a contiguous render counter (1,2,3…) — the raw emitter seq skips numbers because
            # each stage emits a hidden `start` event before its `complete`.
            step = rendered + 1
            # When a stage has a summary, show "… — summary"; otherwise append a ✓ (a dangling dash
            # with nothing after it reads as broken) — errors keep the 🛑 icon and no tick.
            if vm.summary:
                label = f"{icon} [{step}] {vm.title} — {vm.summary}"
            elif vm.is_error:
                label = f"{icon} [{step}] {vm.title}"
            else:
                label = f"{icon} [{step}] {vm.title}  ✓"
            with stream_area.expander(label, expanded=vm.is_error):
                if vm.payload_ref:
                    st.caption(f"(large payload offloaded to {vm.payload_ref})")
                st.json(vm.payload)
            rendered += 1
            if vm.is_error:
                errored = True
            if vm.stage == "run_complete":
                # The run_complete EVENT is emitted just before run_scenario RETURNS, so
                # handle.result may not be populated yet — join the worker first to avoid a race.
                progress.info("⏳ Finalizing results…")
                if handle.thread is not None:
                    handle.thread.join()
                progress.empty()
                _render_results(handle)
                return
        if errored:
            progress.error("Run stopped due to an error (see the highlighted event above).")
            return
        if handle.done and handle.events.empty():
            break
        progress.info(f"⏳ Agent working… {rendered} events so far.")
        time.sleep(0.05)

    # Worker finished without a run_complete event → surface any captured exception, else render.
    if handle.thread is not None:
        handle.thread.join()
    if handle.error is not None:
        progress.error(f"Run failed: {type(handle.error).__name__}: {handle.error}")
        return
    progress.empty()
    _render_results(handle)


def _render_results(handle: run_controller.RunHandle) -> None:
    result = handle.result
    if not result:
        if handle.error is not None:
            st.error(f"Run failed: {type(handle.error).__name__}: {handle.error}")
        else:
            st.warning("Run finished but no results were returned.")
        return

    fe = result.get("final_eval")
    if fe:
        v = verdict_mod.derive(fe)
        (st.success if v.winner == "agent" else st.info)(f"🏆 {v.headline}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Agent MAE", f"{v.agent_mae:.3f}")
        c2.metric("Full-history MAE", f"{v.full_history_mae:.3f}")
        c3.metric("Naive MAE", f"{v.naive_mae:.3f}")

    csv_path = result.get("csv_path")
    if csv_path and Path(csv_path).exists():
        df = pd.read_csv(csv_path)
        changepoints = _changepoints_from_events(handle)
        data = chart_mod.build_frame(df, changepoints=changepoints)
        st.plotly_chart(chart_mod.build_figure(data), use_container_width=True)
    else:
        st.warning("No comparison chart available for this run.")


def _changepoints_from_events(handle: run_controller.RunHandle) -> list[dict[str, Any]]:
    """Best-effort: recover the detected-changepoints payload from the run_dir events.jsonl."""
    run_dir = (handle.result or {}).get("run_dir")
    if not run_dir:
        return []
    path = Path(run_dir) / "events.jsonl"
    if not path.exists():
        return []
    import json

    for line in path.read_text().splitlines():
        e = json.loads(line)
        if e.get("stage") == "changepoint_detection" and e.get("status") == "complete":
            payload = e.get("payload", {})
            if isinstance(payload, dict):
                return payload.get("detected", [])
    return []


def main() -> None:  # pragma: no cover - exercised via the manual quickstart
    st.set_page_config(page_title=_PAGE_TITLE, layout="wide")
    sel = _render_control_pane()
    st.title("Agent-in-the-Loop Forecasting")

    credentials = _render_credentials_panel()

    if not sel["start"]:
        st.info("Configure the run in the left pane, add your credentials above, then click **Start run**.")
        return

    # Guard: a real run needs a provider. Block with a friendly prompt rather than failing mid-run.
    if credentials.is_empty:
        st.warning(
            "Please enter your credentials in the **🔑 Credentials** panel above (an Anthropic API "
            "key, or AWS Bedrock keys) before starting a run.",
            icon="🔑",
        )
        return

    result = _validate(sel)
    if not result.ok:
        for err in result.errors:
            st.error(err)
        return

    _run_and_stream(sel, credentials)


if __name__ == "__main__":  # pragma: no cover
    main()
