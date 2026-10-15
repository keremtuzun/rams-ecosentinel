"""Isolated container HTTP checks. No model, satellite data or cloud credentials."""

import os

import httpx
import pytest

from tests.test_geospatial import request

pytestmark = pytest.mark.skipif(
    not os.environ.get("ECOSENTINEL_TEST_WEB_URL"), reason="Isolated Docker stack only"
)


def test_web_proxies_to_container_api_and_reads_real_postgresql():
    with httpx.Client(base_url=os.environ["ECOSENTINEL_TEST_WEB_URL"], timeout=20) as client:
        health = client.get("/health")
        assert health.status_code == 200, health.text
        assert health.json()["mode"] == "research"
        assert client.get("/api/jobs").json() == []
        assert len(client.get("/api/regions").json()) == 4
        assert client.get("/brand/rams-7729.png").status_code == 200
        response = client.post("/api/jobs", json=request())
        assert response.status_code == 503
        assert "checkpoint" in response.json()["detail"]
        assert client.get("/api/jobs").json() == []
