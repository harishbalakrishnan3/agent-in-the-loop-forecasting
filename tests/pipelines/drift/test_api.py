"""Tests for the Drift API (FastAPI app).

Written BEFORE the implementation (Principle II — Test-First).
Uses httpx + FastAPI's TestClient for deterministic, no-network testing.

Covers:
  - GET  /drift/config        — read current config
  - PATCH /drift/config/trend — update trend at runtime
  - POST /drift/generate/{drift_type} — generate a dataset
  - Swagger UI reachable at /docs
  - Invalid drift_type → 422
  - Invalid trend → 422
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ailf.pipelines.drift.pipeline import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/drift/config")
        assert resp.status_code == 200

    def test_response_has_trend(self, client: TestClient) -> None:
        body = client.get("/drift/config").json()
        assert "trend" in body

    def test_trend_is_valid(self, client: TestClient) -> None:
        body = client.get("/drift/config").json()
        assert body["trend"] in {"flat", "linear", "exponential"}


class TestPatchTrend:
    def test_update_trend_to_flat(self, client: TestClient) -> None:
        resp = client.patch("/drift/config/trend", json={"trend": "flat"})
        assert resp.status_code == 200
        assert resp.json()["trend"] == "flat"

    def test_update_trend_to_exponential(self, client: TestClient) -> None:
        resp = client.patch("/drift/config/trend", json={"trend": "exponential"})
        assert resp.status_code == 200
        assert resp.json()["trend"] == "exponential"

    def test_invalid_trend_returns_422(self, client: TestClient) -> None:
        resp = client.patch("/drift/config/trend", json={"trend": "quadratic"})
        assert resp.status_code == 422

    def test_config_reflects_update(self, client: TestClient) -> None:
        client.patch("/drift/config/trend", json={"trend": "linear"})
        body = client.get("/drift/config").json()
        assert body["trend"] == "linear"


# ---------------------------------------------------------------------------
# Generate endpoints
# ---------------------------------------------------------------------------

DRIFT_TYPES = [
    "sudden",
    "gradual",
    "incremental",
    "seasonal",
    "recurring",
    "covariate",
    "concept",
]


class TestGenerateDrift:
    @pytest.mark.parametrize("drift_type", DRIFT_TYPES)
    def test_generate_returns_200(self, client: TestClient, drift_type: str) -> None:
        resp = client.post(f"/drift/generate/{drift_type}", json={"seed": 0, "n_points": 100})
        assert resp.status_code == 200

    @pytest.mark.parametrize("drift_type", DRIFT_TYPES)
    def test_response_has_data_and_meta(self, client: TestClient, drift_type: str) -> None:
        resp = client.post(f"/drift/generate/{drift_type}", json={"seed": 0, "n_points": 100})
        body = resp.json()
        assert "data" in body and "meta" in body

    @pytest.mark.parametrize("drift_type", DRIFT_TYPES)
    def test_data_is_list_of_records(self, client: TestClient, drift_type: str) -> None:
        resp = client.post(f"/drift/generate/{drift_type}", json={"seed": 0, "n_points": 50})
        records = resp.json()["data"]
        assert isinstance(records, list)
        assert len(records) == 50
        assert "ds" in records[0] and "y" in records[0]

    def test_invalid_drift_type_returns_404(self, client: TestClient) -> None:
        resp = client.post("/drift/generate/unknown_type", json={"seed": 0})
        assert resp.status_code == 404

    def test_sudden_drift_point_in_meta(self, client: TestClient) -> None:
        resp = client.post(
            "/drift/generate/sudden",
            json={"seed": 0, "n_points": 200, "drift_point": 80},
        )
        meta = resp.json()["meta"]
        assert meta["drift_point"] == 80

    def test_reproducibility_via_api(self, client: TestClient) -> None:
        payload = {"seed": 42, "n_points": 100}
        r1 = client.post("/drift/generate/sudden", json=payload).json()["data"]
        r2 = client.post("/drift/generate/sudden", json=payload).json()["data"]
        assert r1 == r2

    def test_trend_affects_output(self, client: TestClient) -> None:
        """Changing trend should produce different y values."""
        payload = {"seed": 0, "n_points": 100}
        client.patch("/drift/config/trend", json={"trend": "flat"})
        flat_data = client.post("/drift/generate/sudden", json=payload).json()["data"]

        client.patch("/drift/config/trend", json={"trend": "exponential"})
        exp_data = client.post("/drift/generate/sudden", json=payload).json()["data"]

        flat_y = [r["y"] for r in flat_data]
        exp_y = [r["y"] for r in exp_data]
        assert flat_y != exp_y


# ---------------------------------------------------------------------------
# Swagger UI
# ---------------------------------------------------------------------------


class TestSwaggerUI:
    def test_docs_reachable(self, client: TestClient) -> None:
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json_reachable(self, client: TestClient) -> None:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        # Verify our routes appear in the schema
        paths = schema.get("paths", {})
        assert any("/drift/generate/" in p or "/drift/generate/{drift_type}" in p for p in paths)
