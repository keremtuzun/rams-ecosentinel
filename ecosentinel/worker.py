import json
import logging
import subprocess
import sys
import time

from ecosentinel.common import ARTIFACTS, DataUnavailable
from ecosentinel.geometry import AnalysisRequest
from ecosentinel.inference import analyze
from ecosentinel.jobs import Queue

logger = logging.getLogger("ecosentinel.worker")


def process_one(job_id, owner):
    queue = Queue()
    record = queue.get(job_id)
    try:
        analyze(AnalysisRequest.model_validate(record["request"]), ARTIFACTS / "jobs" / job_id)
        queue.finish(job_id, owner, "succeeded")
    except DataUnavailable as exc:
        queue.finish(job_id, owner, "failed", str(exc))
    except Exception:
        # No raw upstream URL, traceback, credential or local filesystem path in API-visible errors.
        logger.error(
            json.dumps({"event": "job_failed", "job_id": job_id, "reason": "internal_processing_error"})
        )
        queue.finish(job_id, owner, "failed", "Processing failed; inspect local worker diagnostics")


def run_worker(once=False):
    queue = Queue()
    queue.migrate()
    while True:
        claimed = queue.claim()
        if not claimed:
            if once:
                return
            time.sleep(2)
            continue
        job_id, owner, _ = claimed
        logger.info(json.dumps({"event": "job_started", "job_id": job_id}))
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "ecosentinel.cli", "process-job", job_id, owner],
                timeout=900,
                check=False,
            )
            if completed.returncode:
                queue.finish(job_id, owner, "failed", "Worker process exited before completion")
        except subprocess.TimeoutExpired:
            queue.finish(job_id, owner, "failed", "Analysis exceeded the 15 minute execution limit")
        if once:
            return
