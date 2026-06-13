"""US2: build_corpus composition + reproducibility (T017)."""


from ailf.core.datasets.corpus import load_corpus
from ailf.pipelines.drift.corpus import build_corpus

EXPECTED_SINGLE_PER_FLAVOR = 25
EXPECTED_COMBINED = 10
EXPECTED_TOTAL = 110


def _read_bytes(root) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_corpus_composition(tmp_path) -> None:
    manifest = build_corpus(tmp_path, base_seed=42)
    rows = manifest["cases"]
    assert len(rows) == EXPECTED_TOTAL

    by_flavor: dict[str, int] = {}
    combined = 0
    for row in rows:
        if len(row["flavors"]) == 1:
            by_flavor[row["flavors"][0]] = by_flavor.get(row["flavors"][0], 0) + 1
        else:
            combined += 1

    assert combined == EXPECTED_COMBINED
    assert set(by_flavor) == {"trend_slope", "mean_level", "variance_inflation", "seasonal_amplitude"}
    assert all(count == EXPECTED_SINGLE_PER_FLAVOR for count in by_flavor.values())
    assert sum(by_flavor.values()) == 100


def test_corpus_is_enumerable_with_labels(tmp_path) -> None:
    build_corpus(tmp_path, base_seed=42)
    cases = list(load_corpus(tmp_path))
    assert len(cases) == EXPECTED_TOTAL
    assert all(c.labels for c in cases if c.labeled)


def test_corpus_rebuild_is_byte_identical(tmp_path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    build_corpus(root_a, base_seed=42)
    build_corpus(root_b, base_seed=42)

    files_a = {k: v for k, v in _bytes_relative(root_a).items()}
    files_b = {k: v for k, v in _bytes_relative(root_b).items()}
    assert files_a.keys() == files_b.keys()
    for key in files_a:
        assert files_a[key] == files_b[key], f"mismatch in {key}"


def _bytes_relative(root) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_overwrite_guard(tmp_path) -> None:
    build_corpus(tmp_path, base_seed=42)
    # Re-running with overwrite=True must succeed and stay identical.
    manifest = build_corpus(tmp_path, base_seed=42, overwrite=True)
    assert len(manifest["cases"]) == EXPECTED_TOTAL
