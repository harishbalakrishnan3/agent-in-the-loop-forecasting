## Dataset
Create a time series generator which uses the 'trend' parameter from src/config by looking upon config.yml during initialization.
#Feature:
Use src/
1. Add a runtime variable exposed via api endpoint which can be altered to change the trend of the time series data during runtime.
2. Use SiD2ReGenerator PyPI for prophet forecasting model's data. Use the below different kind of method for DriftGenerator.
class DriftGenerator:
    def sudden_drift(self):
        ...

    def gradual_drift(self):
        ...

    def incremental_drift(self):
        ...

    def seasonal_drift(self):
        ...

    def recurring_drift(self):
        ...

    def covariate_drift(self):
        ...

    def concept_drift(self):
        ...
2. requirements.txt should have all the dependencies and versions pinned.
4. Add a README.md with instructions to run the project and details about the architecture and design decisions. Add a section about how to use the API endpoint to change the trend of the time series data during runtime.
5. Add tests for the time series generator and the API endpoint using pytest.
6. The DriftGenerator should be able to generate combination of two or more drifts in different types of series like sine, linear, binary, etc.
7. Drift is injected by modifying a shared component (trend + seasonal + noise), so multiple drifts can be stacked on the same series.
8. Use darts to implement the generators and ensure that the output is compatible with Prophet (i.e., a DataFrame with `ds` and `y` columns, plus optional covariates). The metadata dict should include the type of drift(s) injected, their parameters, and the exact timestamps of injection for evaluation purposes.
9. Use the combined drift generators to generate below a sinusoidal time series of 5 years with atleast 10 sudden drifts each year in both positive and negative directions pertaining to one - two day holidays; recurrent drifts during every quarter end; seasonal drifts increase during the year end and summer and drops (negative severely) during winter in alternate years. Make it with less frequency or less noise so it is easy to differentiate changepoints with naked eye.
   i. First graph should be in negative trend for the second year third quarter.
    ii. Second graph which goes up 
         -  last 5 days of last quarter in first year, last 10 days of last quarter in second year, last 15 days of last quarter in third year, last 20 days of last quarter in fourth year and last 25 days of last quarter in fifth year.
      - goes down in the first quarter of next year every year before gradually rising again.
      iii. Third graph should be negative trend and upwards only during the second quarter of every year.
10. New graph which is a sine wave which has seasonal drift in ampltide only during the third year second and third quarter out of 5 years and recurring drifts during quarter end for a period of 10 days every year.
11. Update the config.yaml to generate different variety of drift trends and capture atleast 3 mutually exclusive. Task: Generate 3 new graphs with different configs. Goal: Choose the configs such that it is difficult-to-predict drift trends by any naive/prophet model. Capture the config.yaml params in their graphs.
12. New sinusoidal graph which has covariate drift during the seasonal drift with high amplitude during second year second, third  quarter and covariate shift backs to old in the end of third year, seasonal drifts every december of 5 years and recurrent amplitude drifts every month end for 5 days. Sudden covariate drifts once in first, third year, twice in second, fourth year and fifth year has three sudden drifts.


## Visualization
1. Implement fast api in src/alif/pipelines/drift/pipeline.py to use the dataset generator, expose swagger ui for updating runtime sudden, gradual, recurring, incremental drifts, etc and recommended implementations and practices.
   i. The api should have a post endpoint which accepts a csv file and forecast the output.
    ii. Build an interactive UI with Streamlit which can help in visualizing the predicted forecast for an input csv file trend by a plain Prophet model vs model-taught-prophet vs actual output.
   iii. The UI must have: Historical vs. Predicted Data: Display historical data with a solid line and forecast data with a dashed line. Confidence Intervals: Use a shaded area (e.g., Plotly's fill='tonexty') to represent upper and lower bounds of uncertainty.Interactive Controls: Add UI components so users can adjust the Prediction Length or filter specific data parameters on the fly.
2. Save the generated graphs in csv to experiment in UI with prophet model. Forecast Parameters in Controls should have 'Split Dataset Ratio' option in addition to the prediction length. The csv should be split till 'Split Dataset Ratio' before feeding to prophet and prophet's predicted output should be compared with the actual graph in the UI interactively. Both the http://127.0.0.1:8000/forecast/ui and streamlist UI should also have output display to show what the qwen agent/claude/LangSmith Tracing is thinking while detecting the changepoints and drifts before invoking the prophet with input.
3. Save the predicted output vs actual for all the generated graphs from 9 to 12 in prophet/ dir.
4. In addition to the ollama models, convert it to a drop down to allow selecting langsmith or claude sonnet and claude opus in which case use the api key from the .env file for langsmith for changepoint detection.
5. When langsmith or claude is selected, the agen reasoning tab in streamlit ui should show the streamed reasoning from the models for visualizing what agent thinks while detecting changepoints like sudden, gradual, recurring , etc.
6. src/ailf/ directory has lang graph and integrations for langsmith and bedrock. Integrate them in streamlit ui to visualize.
7. User should be able to use the free tier https://apac.smith.langchain.com/ with client = Client(api_key=api_key, api_url=_langsmith_api_url()) apart from the bedrock from .env configs.
8. In addition to Bedrock, add langsmith option in 'Detect with' section to use the LANGSMITH_API_KEY to get the changepoints and visualize the forecast.
9. Without changing the skeleton of the UI, need to add few more controls to playaround with the configs.
10. Rename Series to Data Scenario. Data Scenario should have these options under Data Source: 
level_shift_loses_seasonality
gradual_drift_loses_seasonality
temporary_event_not_regime_change
many_temporary_events_long_history
prophet_prior_tuning_recurring_event 


Model Settings

Expose editable text fields:

visual_model_id (move 'Detect with' dropdown section to here in Controls)
decision_model_id
aws_region
These are non-secret operational settings. Do not collect AWS credentials or API keys in the UI.
Note: if it isn't Bedrock option: then visual_model_id, decision_model_id and aws_region should be greyed out
Agent Settings

Expose:

visual_analysis_enabled toggle
seed numeric input
When visual analysis is off, the UI should indicate that no agent_context.png will be produced.

Diagnostic Toggles

Render checkboxes for all diagnostics:

detected_changepoints
latest_changepoint
primary_changepoint
post_changepoint_history_len
post_changepoint_shorter_than_season
seasonal_period
segment_stats
candidate_event_blocks
recurring_event_summary
local_boundary_jumps
candidate_drift_intervals
transient_event_score
permanent_shift_magnitude
Unchecked diagnostics are still computed by the backend but hidden from the agent. The UI should show hidden diagnostics after config_resolved.


11. Tool Toggles

Render checkboxes for:

recent_window
full_history_step_regressor
full_history_ramp_regressor
full_history_clean_event
full_history_clean_event
full_history_prophet_tuned_holidays
full_history_default
full_history_default is the fallback and must remain enabled. Display it as checked and disabled.

Add help icon for all the Tool Toggles and Diagnostic toggles with description under 10 words. LangSmith Tracing is enabled by default.

12. Build fastapi endpoints to call the src/ailf/core/ for the UI to make calls for each forecast. The below command should be invoked from the Streamlit UI to api and capture the results and show instead of the 'Changepoint Pipeline — Run & Artifacts'.
uv run python -m ailf.pipelines.changepoint.pipeline --scenario prophet_prior_tuning_recurring_event --override '{"models": {"visual_model_id": "us.anthropic.claude-opus-4-8", "decision_model_id": "us.anthropic.claude-sonnet-4-6", "aws_region": "us-west-2"}, "visual_analysis_enabled": true, "seed": 1729, "diagnostics": {"detected_changepoints": true, "latest_changepoint": true, "primary_changepoint": true, "post_changepoint_history_len": true, "post_changepoint_shorter_than_season": true, "seasonal_period": true, "segment_stats": true, "candidate_event_blocks": true, "recurring_event_summary": true, "local_boundary_jumps": true, "candidate_drift_intervals": true, "transient_event_score": true, "permanent_shift_magnitude": true}, "agent_tools": {"recent_window": true, "full_history_step_regressor": true, "full_history_ramp_regressor": true, "full_history_clean_event": true, "full_history_prophet_tuned_holidays": true, "full_history_default": true}}'

13. Move the 'Run Changepoint Pipeline' under Controls making it a toggle button before 'Detect and Forecast' button. Rename it to Bedrock Changepoint Pipeline. 
14. Add yet another forecast output in the Forecast section from calling 'run_scenario' in src/ailf/core/pipelines/changepoint/pipeline in dotted light purple and name it as 'agent-in-the-loop forecast' and the old orange dotted line as 'naive forecast'.
'run_scenario': 
    i. for registered scenario fixtures, update the code to accept pocs/data/ folder for dataset-scenario.
    ii. Use Split Dataset Ratio and other diagnostic options in Controls for passing the split ratio and options to run_scenario.

A completed run writes:

effective_config.json
events.jsonl
metrics.json
agent_trace.json
report.md
forecast_comparison.png
agent_context.png   # only when visual_analysis_enabled=true
event_payloads/     # sidecar JSON for large event payloads

When 'Bedrock Changepoint Pipeline' toggle is on, then use the below api contract for the visualization with Streamlit UI for visualization.

uv run python -m ailf.pipelines.changepoint.pipeline --scenario <scenario_id> --override '<json>'


Events follow this envelope:


{
  "run_id": "level_shift_loses_seasonality-1729",
  "seq": 1,
  "ts": "2026-06-20T...",
  "stage": "diagnostics_computed",
  "status": "start|complete|error",
  "concurrency_group": null,
  "payload": {},
  "error": null
}

15. Graceful fallback if any of the steps is interrupted and exception is thrown.

## Forecasting
1. Write a tool to use Qwen-3.5/langsmith/claude with reasoning to find the changepoints from the generated graphs and save them in json or csv format. To visualize the changepoints found by Qwen, mark them and visualize in graphs under qwen folder.
2. Use prophet model to forecast from the split ratio in Controls of generated csvs from above and compare with the actual data of and display on UI.
3. When 'Bedrock Changepoint Pipeline' toggle is off, the run_scenario pipeline needs to be newly written in a new fallback.py for the claude and anthropic client to perform the tool call and prophet's hyperparameters, since run_scenario only passes changepoints from a png to the hyperparameters of prophet.

## Documentation
Create a mermaid diagram in sessions/ksowmya/architecture-phase1.md to visualize the architecture of the system and the flow of data. The diagram should include the time series generator, the API endpoint, and how they interact with each other. Use appropriate shapes and labels to make the diagram clear and easy to understand.


## 