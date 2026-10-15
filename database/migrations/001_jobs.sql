-- PostgreSQL schema equivalent to Queue.migrate(). Not required for SQLite local research mode.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS jobs (
    id varchar(36) PRIMARY KEY,
    status varchar(16) NOT NULL,
    request text NOT NULL,
    created_at varchar(40) NOT NULL,
    updated_at varchar(40) NOT NULL,
    error text,
    attempts integer NOT NULL DEFAULT 0,
    lease_until double precision NOT NULL DEFAULT 0,
    lease_owner varchar(36),
    CONSTRAINT job_status CHECK (status IN ('queued','running','succeeded','failed'))
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs (status);
-- Spatial analysis is currently performed on CRS-preserving files. PostGIS is provisioned
-- for later spatial indexing; this release does not claim DB-backed spatial queries.
