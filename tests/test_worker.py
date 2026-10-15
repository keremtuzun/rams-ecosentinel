"""Fault fixtures only: no satellite or model output is fabricated as evidence."""

import json
import subprocess
import sys
import time

import pytest

from ecosentinel.common import TransientDataUnavailable
from ecosentinel.jobs import Job, Queue
from tests.test_geospatial import request


@pytest.fixture
def queue(tmp_path):
    result = Queue(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    result.migrate()
    return result


def configure(queue, monkeypatch, tmp_path):
    import ecosentinel.worker as worker

    monkeypatch.setattr(worker, "Queue", lambda: queue)
    monkeypatch.setattr(worker, "ARTIFACTS", tmp_path)
    return worker


def test_unowned_delivery_never_starts_compute(queue, monkeypatch, tmp_path):
    worker = configure(queue, monkeypatch, tmp_path)
    job_id = queue.submit(request())
    _, owner, _ = queue.claim()
    calls = []
    monkeypatch.setattr(worker, "analyze", lambda *args: calls.append(args))
    worker.process_one(job_id, "wrong-owner")
    assert calls == []
    assert queue.get(job_id)["status"] == "running"
    queue.finish(job_id, owner, "failed")


def test_completed_duplicate_never_recomputes(queue, monkeypatch, tmp_path):
    worker = configure(queue, monkeypatch, tmp_path)
    job_id = queue.submit(request())
    _, owner, _ = queue.claim()
    calls = []
    monkeypatch.setattr(worker, "analyze", lambda *args: calls.append(args))
    queue.finish(job_id, owner, "succeeded")
    worker.process_one(job_id, owner)
    assert calls == []
    assert queue.get(job_id)["status"] == "succeeded"


def test_expired_attempt_cannot_overwrite_winning_artifacts(queue, monkeypatch, tmp_path):
    worker = configure(queue, monkeypatch, tmp_path)
    job_id = queue.submit(request())
    _, first_owner, _ = queue.claim()
    attempts = []

    def fixture_compute(payload, output):
        output.mkdir(parents=True, exist_ok=True)
        attempts.append(output)
        if len(attempts) == 1:
            with queue.session() as session:
                session.get(Job, job_id).lease_until = time.time() - 1
            _, second_owner, _ = queue.claim()
            worker.process_one(job_id, second_owner)
            (output / "diagnostic.txt").write_text("late owner - test fixture")
        else:
            (output / "diagnostic.txt").write_text("winning owner - test fixture")

    monkeypatch.setattr(worker, "analyze", fixture_compute)
    worker.process_one(job_id, first_owner)
    assert len(attempts) == 2 and attempts[0] != attempts[1]
    assert (attempts[1] / "diagnostic.txt").read_text() == "winning owner - test fixture"
    record = queue.get(job_id)
    assert record["status"] == "succeeded" and record["attempts"] == 2
    assert record["result_owner"] == attempts[1].name


def test_transient_compute_failure_retries_at_most_twice(queue, monkeypatch, tmp_path):
    worker = configure(queue, monkeypatch, tmp_path)
    job_id = queue.submit(request())

    def outage(*args):
        raise TransientDataUnavailable("bounded test outage")

    monkeypatch.setattr(worker, "analyze", outage)
    for expected_status in ["queued", "failed"]:
        _, owner, _ = queue.claim()
        worker.process_one(job_id, owner)
        assert queue.get(job_id)["status"] == expected_status
    assert queue.claim() is None
    assert queue.get(job_id)["attempts"] == 2


def test_real_subprocess_timeout_kills_child_and_blocks_exports(queue, monkeypatch, tmp_path):
    worker = configure(queue, monkeypatch, tmp_path)
    job_id = queue.submit(request())
    real_run = subprocess.run
    marker = tmp_path / "child.json"

    def short_lived_fixture(command, *, timeout, check):
        assert timeout == 900  # The serving wall limit is unchanged.
        script = (
            "import os,time,json; from pathlib import Path; Path("
            + repr(str(marker))
            + ").write_text(json.dumps({'pid':os.getpid()})); time.sleep(60)"
        )
        return real_run([sys.executable, "-c", script], timeout=0.8, check=check)

    monkeypatch.setattr(worker.subprocess, "run", short_lived_fixture)
    worker.run_worker(once=True)
    assert marker.exists() and json.loads(marker.read_text())["pid"] > 0
    record = queue.get(job_id)
    assert record["status"] == "failed" and record["attempts"] == 1
    assert "15 minute" in record["error"]
    assert queue.claim() is None
    from fastapi.testclient import TestClient
    from ecosentinel.api import create_app

    with TestClient(create_app(queue)) as client:
        assert client.get(f"/api/jobs/{job_id}/export/pdf").status_code == 409


def test_child_exit_after_commit_does_not_crash_worker_or_revert_success(queue, monkeypatch, tmp_path):
    worker = configure(queue, monkeypatch, tmp_path)
    job_id = queue.submit(request())

    def committed_then_exited(command, **kwargs):
        queue.finish(command[-2], command[-1], "succeeded")
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(worker.subprocess, "run", committed_then_exited)
    worker.run_worker(once=True)
    assert queue.get(job_id)["status"] == "succeeded"
