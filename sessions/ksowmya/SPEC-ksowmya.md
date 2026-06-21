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
    ii. Build an interactive UI with Streamlit which can help in visualizing the predicted forecast for an input csv file trend by learned Prophet model vs actual output.
   iii. The UI must have: Historical vs. Predicted Data: Display historical data with a solid line and forecast data with a dashed line. Confidence Intervals: Use a shaded area (e.g., Plotly's fill='tonexty') to represent upper and lower bounds of uncertainty.Interactive Controls: Add UI components so users can adjust the Prediction Length or filter specific data parameters on the fly.
2. Save the generated graphs in csv to experiment in UI with prophet model. The csv should be split till fourth year before feeding to prophet and prophet's predicted output should be compared with the actual graph in the UI interactively. Both the http://127.0.0.1:8000/forecast/ui and streamlist UI should also have output display to show what the qwen agent is thinking while detecting the changepoints and drifts before invoking the prophet with input.
3. Save the predicted output vs actual for all the generated graphs from 9 to 12 in prophet/ dir.
4. In addition to the ollama models, convert it to a drop down to allow selecting langsmith or claude sonnet and claude opus in which case use the api key from the .env file for langsmith for changepoint detection.
5. When langsmith or claude is selected, the agen reasoning tab in streamlit ui should show the streamed reasoning from the models for visualizing what agent thinks while detecting changepoints like sudden, gradual, recurring , etc.

## Forecasting
1. Write a tool to use Qwen-3.5 with reasoning (which is already installed with ollama) to find the changepoints from the generated graphs and save them in json or csv format. To visualize the changepoints found by Qwen, mark them and visualize in graphs under qwen folder.
2. Use prophet model to forecast fifth year with the first four year's data from the generated csvs from above and compare with the actual data of fifth year and display on UI.

## Documentation
Create a mermaid diagram in sessions/ksowmya/architecture-phase1.md to visualize the architecture of the system and the flow of data. The diagram should include the time series generator, the API endpoint, and how they interact with each other. Use appropriate shapes and labels to make the diagram clear and easy to understand.


## 