import json
import os
import time
import uuid
import threading
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Column, Float, Integer, String, Text, create_engine, select, update
from sqlalchemy.orm import declarative_base, sessionmaker

from ecosentinel.common import ARTIFACTS, DataUnavailable, utcnow

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String(36), primary_key=True)
    status = Column(String(16), nullable=False, index=True)
    request = Column(Text, nullable=False)
    created_at = Column(String(40), nullable=False)
    updated_at = Column(String(40), nullable=False)
    error = Column(Text)
    attempts = Column(Integer, nullable=False, default=0)
    lease_until = Column(Float, nullable=False, default=0)
    lease_owner = Column(String(36))


class Queue:
    def __init__(self, url=None):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        url = url or os.environ.get("DATABASE_URL", f"sqlite:///{(ARTIFACTS / 'jobs.db').as_posix()}")
        options = {"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=options, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine)
        self.admission_lock = threading.Lock()

    def migrate(self):
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self):
        with self.sessions.begin() as session:
            yield session

    def submit(self, request):
        with self.admission_lock, self.session() as s:
            # Single-worker queue is bounded. Database admission lock serializes PostgreSQL API instances.
            if self.engine.dialect.name == "postgresql":
                s.execute(__import__("sqlalchemy").text("SELECT pg_advisory_xact_lock(7729001)"))
            active = s.scalars(select(Job).where(Job.status.in_(["queued", "running"]))).all()
            if len(active) >= 10:
                raise DataUnavailable("Analysis queue is full (maximum ten pending jobs)")
            job_id = str(uuid.uuid4())
            s.add(
                Job(
                    id=job_id,
                    status="queued",
                    request=json.dumps(request),
                    created_at=utcnow(),
                    updated_at=utcnow(),
                    attempts=0,
                    lease_until=0,
                )
            )
        return job_id

    def get(self, job_id):
        with self.session() as s:
            row = s.get(Job, job_id)
            return self.public(row) if row else None

    def list(self, limit=30):
        with self.session() as s:
            return [
                self.public(row)
                for row in s.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit))
            ]

    @staticmethod
    def public(row):
        return {
            "id": row.id,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "request": json.loads(row.request),
            "error": row.error,
            "attempts": row.attempts,
        }

    def claim(self):
        now, owner = time.time(), str(uuid.uuid4())
        with self.session() as s:
            expired_query = select(Job).where(Job.status == "running", Job.lease_until < now)
            if self.engine.dialect.name == "postgresql":
                expired_query = expired_query.with_for_update(skip_locked=True)
            expired = s.scalars(expired_query).all()
            for row in expired:
                row.status = "queued" if row.attempts < 2 else "failed"
                row.error = "Worker lease expired; interrupted analysis did not complete"
                row.updated_at, row.lease_owner = utcnow(), None
            s.flush()
            query = select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1)
            if self.engine.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = s.scalars(query).first()
            if not row:
                return None
            result = s.execute(
                update(Job)
                .where(Job.id == row.id, Job.status == "queued")
                .values(
                    status="running",
                    attempts=Job.attempts + 1,
                    lease_until=now + 1200,
                    lease_owner=owner,
                    updated_at=utcnow(),
                    error=None,
                )
            )
            if result.rowcount != 1:
                return None
            return row.id, owner, json.loads(row.request)

    def finish(self, job_id, owner, status, error=None):
        if status not in {"succeeded", "failed"}:
            raise ValueError("Invalid terminal state")
        with self.session() as s:
            result = s.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == "running",
                    Job.lease_owner == owner,
                    Job.lease_until >= time.time(),
                )
                .values(status=status, error=error, lease_owner=None, lease_until=0, updated_at=utcnow())
            )
            if result.rowcount != 1:
                raise ValueError("Job ownership/state transition rejected")

    def import_result(self, request, report_dir):
        """CLI-only import of a completed local inference artifact; never a public endpoint."""
        import shutil
        from ecosentinel.common import read_json

        report = read_json(Path(report_dir) / "report.json")
        if report["module"] != "habitat":
            raise ValueError("Unsupported imported result")
        from ecosentinel.common import sha256

        for name, digest in report["checksums"].items():
            if Path(name).name != name or sha256(Path(report_dir) / name) != digest:
                raise ValueError("Imported result checksum/path mismatch")
        job_id = self.submit(request)
        destination = ARTIFACTS / "jobs" / job_id
        shutil.copytree(report_dir, destination)
        with self.session() as s:
            row = s.get(Job, job_id)
            row.status, row.updated_at = "succeeded", utcnow()
        return job_id
