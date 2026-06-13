# Contract: On-Disk Eval Corpus Format

The persisted, reproducible corpus consumed by downstream drift tool tests, agent evals, and the
LLM judge (FR-010–FR-012). Plain, diffable, language-agnostic files.

## Layout

```text
data/synthetic/drift/            # corpus root (gitignored bulk dir)
├── corpus.json                  # manifest: enumerates every case
├── drift-trend_slope-0000/
│   ├── series.csv               # timestamp,value (univariate)
│   └── labels.json              # ground-truth label record
├── drift-mean_level-0000/
│   ├── series.csv
│   └── labels.json
├── ...
└── drift-combined-0009/
    ├── series.csv
    └── labels.json
```

## `series.csv`

Two columns, header row, one row per timestep. Univariate.

```csv
timestamp,value
2015-01-01,10.42
2015-01-02,10.55
...
```

## `labels.json`

```json
{
  "case_id": "drift-trend_slope-0000",
  "is_synthetic": true,
  "labeled": true,
  "labels": [
    {
      "flavor": "trend_slope",
      "affected_component": "trend",
      "onset_index": 182,
      "onset_time": "2015-07-02",
      "transition_width": 73,
      "magnitude": 0.5
    }
  ],
  "config": { "length": 365, "onset": 182, "transition_width": 73, "seed": 42, "...": "..." }
}
```

- Single-flavor cases: `labels` has length 1.
- Combined-flavor cases: `labels` has length ≥ 2 (one entry per injected flavor).
- Real demo series (if persisted): `labeled: false`, `labels: []`, `config: null`.

## `corpus.json` (manifest)

Enables O(1) enumeration without parsing every case (FR-012).

```json
{
  "base_seed": 42,
  "generated_with": "ailf.pipelines.drift.corpus@<build-config-version>",
  "cases": [
    { "case_id": "drift-trend_slope-0000", "flavors": ["trend_slope"], "labeled": true },
    { "case_id": "drift-combined-0009", "flavors": ["mean_level", "variance_inflation"], "labeled": true }
  ]
}
```

## Reproducibility contract

- `build_corpus(root, base_seed=42)` re-run with the same base seed + committed build config
  MUST reproduce byte-identical `series.csv` and `labels.json` for every case (FR-011, SC-003).
- The build config (seed + knob sweep defining the ≈100 single + ≈10 combined cases) lives in
  source (`ailf.pipelines.drift.corpus`), committed; the bulk output under `data/synthetic/drift/`
  is gitignored and treated as regenerable, not as a committed artifact.

## Consumption contract

- `load_corpus(root) -> Iterable[Case]` yields each case as an in-memory `Case` (series rehydrated
  from `series.csv`, labels from `labels.json`) so consumers never hand-parse files.
- Iterating the manifest yields case ids + flavors + `labeled` flag for filtering (e.g. exclude
  unlabeled from precision/recall).
