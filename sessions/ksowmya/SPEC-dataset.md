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
2. Implement fast api in src/alif/pipelines/drift/pipeline.py to use the dataset generator, expose swagger ui for updating runtime sudden, gradual, recurring, incremental drifts, etc and recommended implementations and practices.
3. requirements.txt should have all the dependencies and versions pinned.
4. Add a README.md with instructions to run the project and details about the architecture and design decisions. Add a section about how to use the API endpoint to change the trend of the time series data during runtime.
5. Add tests for the time series generator and the API endpoint using pytest.
6. The DriftGenerator should be able to generate combination of two or more drifts in different types of series like sine, linear, binary, etc.
7. Drift is injected by modifying a shared component (trend + seasonal + noise), so multiple drifts can be stacked on the same series.
8. Use darts to implement the generators and ensure that the output is compatible with Prophet (i.e., a DataFrame with `ds` and `y` columns, plus optional covariates). The metadata dict should include the type of drift(s) injected, their parameters, and the exact timestamps of injection for evaluation purposes.

## Documentation
Create a mermaid diagram in sessions/ksowmya/architecture-phase1.md to visualize the architecture of the system and the flow of data. The diagram should include the time series generator, the API endpoint, and how they interact with each other. Use appropriate shapes and labels to make the diagram clear and easy to understand.


## 