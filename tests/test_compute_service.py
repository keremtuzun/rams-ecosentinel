"""Service failure fixtures, never satellite/model evidence."""

import importlib.util
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def service(monkeypatch):
    for key in ["ECOSENTINEL_INFERENCE_ENGINE", "ECOSENTINEL_ARTIFACTS"]:
        monkeypatch.setenv(key, "test-only")
    monkeypatch.setenv("ECOSENTINEL_BACKEND_TOKEN", "test-only")
    spec = importlib.util.spec_from_file_location("compute_service", Path("apps/backend/app.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("failure", ["timeout", "crash", "unexpected"])
def test_transient_service_failure_is_retryable_503(service, monkeypatch, failure):
    def compute_child(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("fixture", 235)
        if failure == "crash":
            return subprocess.CompletedProcess([], 1, "", "RuntimeError: fixture")
        return subprocess.CompletedProcess(
            [], 0, '{"ok":false,"detail":"Cloud processing failed","type":"ConnectionError"}', ""
        )

    monkeypatch.setattr(service.subprocess, "run", compute_child)
    with TestClient(service.app) as client:
        response = client.post(
            "/rpc", headers={"Authorization": "Bearer test-only"}, json={"action": "before"}
        )
    assert response.status_code == 503


def test_genuine_data_rejection_remains_terminal_422(service, monkeypatch):
    monkeypatch.setattr(
        service, "compute", lambda payload: {"ok": False, "detail": "No acceptable observation"}
    )
    with TestClient(service.app) as client:
        response = client.post(
            "/rpc", headers={"Authorization": "Bearer test-only"}, json={"action": "before"}
        )
    assert response.status_code == 422
