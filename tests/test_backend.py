import time
import json

import pytest
from fastapi.testclient import TestClient

from ecosentinel.api import create_app
from ecosentinel.common import DataUnavailable
from ecosentinel.jobs import Queue
from tests.test_geospatial import request


@pytest.fixture
def queue(tmp_path):
    q = Queue(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    q.migrate()
    return q


def test_job_ownership_and_transitions(queue):
    job_id = queue.submit(request())
    assert queue.get(job_id)["status"] == "queued"
    claimed_id, owner, payload = queue.claim()
    assert claimed_id == job_id and payload == json.loads(json.dumps(request()))
    assert queue.claim() is None
    with pytest.raises(ValueError, match="ownership"):
        queue.finish(job_id, "wrong-owner", "succeeded")
    queue.finish(job_id, owner, "succeeded")
    assert queue.get(job_id)["status"] == "succeeded"
    with pytest.raises(ValueError):
        queue.finish(job_id, owner, "failed")


def test_queue_resource_limit(queue):
    for _ in range(10):
        queue.submit(request())
    with pytest.raises(DataUnavailable, match="full"):
        queue.submit(request())


def test_dead_worker_recovers_once(queue):
    from ecosentinel.jobs import Job

    job_id = queue.submit(request())
    queue.claim()
    with queue.session() as s:
        row = s.get(Job, job_id)
        row.lease_until = time.time() - 1
    claimed_id, owner, _ = queue.claim()
    assert claimed_id == job_id and queue.get(job_id)["attempts"] == 2
    with queue.session() as s:
        s.get(Job, job_id).lease_until = time.time() - 1
    assert queue.claim() is None
    assert queue.get(job_id)["status"] == "failed"


def test_api_validation_limits_and_missing_result(queue):
    with TestClient(create_app(queue)) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.post("/api/jobs", json={}).status_code == 422
        bad = {**request(), "geometry": {"type": "Point", "coordinates": [28, 37]}}
        assert client.post("/api/jobs", json=bad).status_code == 422
        assert client.post("/api/jobs", content="a" * 20000).status_code == 413
        assert client.get("/api/jobs/not-a-uuid").status_code == 404
        assert client.get("/api/jobs/../../.env/files/report.json").status_code == 404
        job_id = queue.submit(request())
        assert client.get(f"/api/jobs/{job_id}/export/pdf").status_code == 409
        assert client.get(f"/api/jobs/{job_id}/files/.env").status_code == 404


def test_firms_missing_credentials_and_redaction(queue, monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    with TestClient(create_app(queue)) as client:
        response = client.post("/api/fire-observations", json={"bbox": [28.23, 37.02, 28.25, 37.04]})
        assert response.status_code == 503
        assert "required" in response.json()["detail"]


def test_firms_upstream_error_does_not_leak_key(monkeypatch):
    import httpx
    from ecosentinel.sources import fetch_firms

    monkeypatch.setenv("FIRMS_MAP_KEY", "VERY_SECRET_MAP_KEY")

    def fail(url, **kwargs):
        raise httpx.ConnectError(url)

    monkeypatch.setattr(httpx, "get", fail)
    with pytest.raises(DataUnavailable) as exc:
        fetch_firms([28, 37, 28.1, 37.1])
    assert "VERY_SECRET_MAP_KEY" not in str(exc.value)


def test_rate_limit(queue):
    with TestClient(create_app(queue)) as client:
        for _ in range(5):
            assert client.post("/api/jobs", json={}).status_code == 422
        assert client.post("/api/jobs", json={}).status_code == 429
