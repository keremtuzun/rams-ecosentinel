"""Real PostgreSQL/PostGIS contracts, opt-in on a disposable local-only database."""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from ecosentinel.common import DataUnavailable
from ecosentinel.jobs import Job, Queue
from tests.test_geospatial import request
from tests import test_worker


@pytest.fixture
def queue():
    url = os.environ.get("ECOSENTINEL_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Requires opt-in isolated PostgreSQL; never uses DATABASE_URL")
    parsed = make_url(url)
    assert parsed.host in {"db", "localhost", "127.0.0.1"}
    assert parsed.database == "ecosentinel_isolated"
    admin = create_engine(url)
    schema = "isolation_" + uuid.uuid4().hex
    with admin.begin() as connection:
        assert connection.scalar(text("SELECT current_database()")) == "ecosentinel_isolated"
        assert connection.scalar(text("SELECT PostGIS_Version()"))
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = parsed.update_query_dict(
        {"options": f"-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=5000"}
    )
    result = Queue(scoped.render_as_string(hide_password=False))
    result.migrate()
    try:
        yield result
    finally:
        result.engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_parallel_admission_across_independent_api_instances_is_bounded(queue):
    def submit(_):
        other = Queue(queue.engine.url)
        try:
            return other.submit(request())
        except DataUnavailable:
            return None
        finally:
            other.engine.dispose()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(submit, range(24)))
    assert len({job for job in results if job}) == 10
    assert len(queue.list()) == 10


def test_parallel_claims_deliver_each_job_once(queue):
    jobs = {queue.submit(request()) for _ in range(10)}

    def claim(_):
        other = Queue(queue.engine.url)
        try:
            return other.claim()
        finally:
            other.engine.dispose()

    with ThreadPoolExecutor(max_workers=12) as pool:
        claims = [job for job in pool.map(claim, range(24)) if job]
    assert len(claims) == 10 and {job[0] for job in claims} == jobs
    for job_id, owner, _ in claims:
        queue.finish(job_id, owner, "failed")


def test_locked_oldest_job_is_skipped_without_waiting(queue):
    first, second = queue.submit(request()), queue.submit(request())
    with queue.session() as session:
        session.execute(text("SELECT id FROM jobs WHERE id=:id FOR UPDATE"), {"id": first})
        start = time.monotonic()
        assert queue.claim()[0] == second
        assert time.monotonic() - start < 3


def test_expired_lease_recovery_rejects_old_owner_and_stops_at_two(queue):
    job_id = queue.submit(request())
    _, old_owner, _ = queue.claim()
    with queue.session() as session:
        session.get(Job, job_id).lease_until = time.time() - 1
    _, new_owner, _ = queue.claim()
    with pytest.raises(ValueError, match="ownership"):
        queue.finish(job_id, old_owner, "succeeded")
    with queue.session() as session:
        session.get(Job, job_id).lease_until = time.time() - 1
    assert queue.claim() is None
    assert queue.get(job_id)["status"] == "failed"
    assert old_owner != new_owner


@pytest.mark.parametrize(
    "case",
    [
        test_worker.test_unowned_delivery_never_starts_compute,
        test_worker.test_completed_duplicate_never_recomputes,
        test_worker.test_expired_attempt_cannot_overwrite_winning_artifacts,
        test_worker.test_transient_compute_failure_retries_at_most_twice,
        test_worker.test_real_subprocess_timeout_kills_child_and_blocks_exports,
        test_worker.test_child_exit_after_commit_does_not_crash_worker_or_revert_success,
        test_worker.test_result_api_only_reads_committed_attempt,
        test_worker.test_additive_migration_preserves_old_rows,
    ],
)
def test_worker_fault_contracts_on_postgresql(case, queue, monkeypatch, tmp_path):
    case(queue, monkeypatch, tmp_path)


def test_simultaneous_migrations_on_fresh_schema_are_serialized(queue):
    with queue.engine.begin() as connection:
        connection.execute(text("DROP TABLE jobs"))

    def migrate(_):
        other = Queue(queue.engine.url)
        try:
            other.migrate()
        finally:
            other.engine.dispose()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(migrate, range(8)))
    assert queue.submit(request())


def test_statement_timeout_rolls_back_and_connection_pool_recovers(queue):
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError) as caught:
        with queue.engine.begin() as connection:
            connection.execute(text("SET LOCAL statement_timeout='100ms'"))
            connection.execute(text("SELECT pg_sleep(1)"))
    assert caught.value.orig.sqlstate == "57014"
    assert queue.submit(request())
