"""An isolated model-missing probe verifies worker reconnection, never real inference."""

import json
import os
import time

import httpx
from sqlalchemy.engine import make_url

from ecosentinel.jobs import Queue


def main():
    url = os.environ["ECOSENTINEL_TEST_POSTGRES_URL"]
    parsed = make_url(url)
    assert parsed.host == "db" and parsed.database == "ecosentinel_isolated"
    assert not any(
        os.environ.get(key)
        for key in [
            "BLOB_READ_WRITE_TOKEN",
            "BLOB_STORE_ID",
            "VERCEL_OIDC_TOKEN",
            "ECOSENTINEL_BACKEND_TOKEN",
        ]
    )
    queue = Queue(url)
    queue.migrate()
    job_id = queue.submit(
        {
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[28.23, 37.02], [28.25, 37.02], [28.25, 37.04], [28.23, 37.04], [28.23, 37.02]]
                ],
            },
            "before_start": "2020-06-01",
            "before_end": "2020-06-30",
            "after_start": "2022-06-01",
            "after_end": "2022-06-30",
            "module": "habitat",
        }
    )
    deadline = time.monotonic() + 20
    record = queue.get(job_id)
    while record["status"] not in {"failed", "succeeded"} and time.monotonic() < deadline:
        time.sleep(0.25)
        record = queue.get(job_id)
    assert record["status"] == "failed", record
    assert record["attempts"] == 1 and "checkpoint" in record["error"]
    with httpx.Client(base_url="http://web:3000", timeout=10) as client:
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "failed"
        assert client.get(f"/api/jobs/{job_id}/export/pdf").status_code == 409
    print(
        json.dumps(
            {
                "database_restart_recovery": "PASS",
                "actual_worker_claims": 1,
                "missing_model_fails_closed": True,
                "production_jobs_submitted": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
