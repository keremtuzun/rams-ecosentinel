import json
import logging
import subprocess
import sys
import time
from sqlalchemy.exc import SQLAlchemyError

from ecosentinel.common import ARTIFACTS, DataUnavailable, TransientDataUnavailable
from ecosentinel.geometry import AnalysisRequest
from ecosentinel.inference import analyze
from ecosentinel.jobs import OwnershipLost, Queue

logger = logging.getLogger("ecosentinel.worker")


def process_one(job_id, owner):
    queue = Queue()
    try:
        record = queue.owned(job_id, owner)
        if record is None:
            return
        try:
            # Fenced paths keep a late process from overwriting the winning attempt.
            analyze(AnalysisRequest.model_validate(record["request"]), ARTIFACTS / "jobs" / job_id / owner)
        except TransientDataUnavailable as exc:
            queue.retry(job_id, owner, str(exc))
        except DataUnavailable as exc:
            queue.finish(job_id, owner, "failed", str(exc))
        except Exception:
            logger.error(
                json.dumps({"event": "job_failed", "job_id": job_id, "reason": "internal_processing_error"})
            )
            queue.finish(job_id, owner, "failed", "Processing failed; inspect local worker diagnostics")
        else:
            queue.finish(job_id, owner, "succeeded")
    except OwnershipLost:
        logger.info(json.dumps({"event": "job_owner_superseded", "job_id": job_id}))


def run_worker(once=False):
    queue = Queue()
    queue.migrate()
    while True:
        try:
            claimed = queue.claim()
        except SQLAlchemyError:
            logger.warning(json.dumps({"event": "job_database_unavailable"}))
            if once:
                raise DataUnavailable("Job database is unavailable") from None
            time.sleep(2)
            continue
        if not claimed:
            if once:
                return
            time.sleep(2)
            continue
        job_id, owner, _ = claimed
        logger.info(json.dumps({"event": "job_started", "job_id": job_id}))
        try:
            try:
                completed = subprocess.run(
                    [sys.executable, "-m", "ecosentinel.cli", "process-job", job_id, owner],
                    timeout=900,
                    check=False,
                )
                if completed.returncode:
                    queue.retry(job_id, owner, "Worker process exited before completion")
            except subprocess.TimeoutExpired:
                queue.finish(job_id, owner, "failed", "Analysis exceeded the 15 minute execution limit")
            except OSError:
                queue.retry(job_id, owner, "Worker process could not start")
        except OwnershipLost:
            pass  # Completion may have been committed before the child exited.
        except SQLAlchemyError:
            # Do not acknowledge unknown completion or disclose driver diagnostics.
            # The existing lease/retry bound will recover the job after reconnect.
            logger.warning(json.dumps({"event": "job_database_unavailable", "job_id": job_id}))
            if once:
                raise DataUnavailable("Job database is unavailable") from None
        if once:
            return
