# POCs

Throwaway, fail-fast exploration — one folder per use-case. This area is **exempt from
the test and quality gates** (constitution: POC exemption) so you can move fast and prove
(or disprove) that an issue reproduces and is detectable.

Notebooks and scratch scripts are fine here. They may `import ailf`, but POC code is not
held to the core standards until it is **promoted** into `src/ailf/pipelines/<usecase>/`
or `src/ailf/core/`, at which point the full gates apply.

Goal of the POC phase (milestone M1): each track demonstrates its issue reproduces under
Prophet / Seasonal Naive and that its diagnostic signal is detectable on known data.
