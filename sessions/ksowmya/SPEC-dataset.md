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

## Documentation
Create a mermaid diagram in sessions/ksowmya/architecture-phase1.md to visualize the architecture of the system and the flow of data. The diagram should include the time series generator, the API endpoint, and how they interact with each other. Use appropriate shapes and labels to make the diagram clear and easy to understand.


## 