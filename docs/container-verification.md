# Isolated Docker, PostgreSQL and worker verification

The baseline was `f35d974`; no user changes were present. This Windows host has neither
Docker nor WSL. Real Docker/PostGIS execution runs on disposable GitHub-hosted Ubuntu
runners through `.github/workflows/containers.yaml`, using the actual API/web Dockerfiles
and `compose.yaml` plus `docker/compose.verify.yaml`.

The override replaces host artifact/database mounts with new named volumes and gives
every run a unique Compose project. Runtime networking is internal, the database is
`ecosentinel_isolated`, and no cloud credentials, model, private report or satellite
dataset is uploaded. Cleanup removes only that run's containers/network/volumes.
The public deployment and its analysis quota are never used by these fault probes.

## Reproductions and fixes

| Reproduced failure | Root cause and correction |
|---|---|
| API/worker containers exited with `ImportError: libexpat.so.1`. | The slim base image lacked Rasterio's native dependency. Install Debian's `libexpat1` before installing Python dependencies. Baseline container run: `38771078694`. |
| A non-secret `.env.local` canary reached `/app/.env.local` in the web builder. | `.dockerignore` excluded only the root `.env`. Exclude nested environment files, `.vercel` and generated backend/private data directories. Canary checks cover both environment and Vercel metadata files without real credentials. |
| Container web had no usable server-side API connection. | Build browser requests as same-origin URLs and configure server-only `ECOSENTINEL_BACKEND_URL=http://api:8000`. Actual web → API → PostgreSQL checks now execute inside the stack. |
| Wrong-owner/completed delivery started inference, then failed repeatedly while trying to finish. | Check live ownership before compute. Treat lost ownership as an expected rejected transition. |
| A late expired attempt could overwrite the winning result's files. | Isolate output per owner; atomically commit `result_owner` with success. All report/export/inspection paths use that committed owner. Old imported results remain readable. |
| A temporary provider error failed permanently; an abnormal child exit after committing crashed the parent worker. | Retry infrastructure failures at most twice and preserve committed success. Genuine data rejection and the 900-second execution limit remain terminal. |
| A database disconnect or failure to launch the child terminated the daemon. | Reconnect the database with bounded delay and sanitized diagnostics; preserve the lease for unknown completion. Bound launch retries to the same two attempts. |

Five worker regressions initially failed on the original code. Additional disconnect and
launch-failure tests also failed before correction. The real subprocess timeout test
checks that Python killed/reaped its child and that unsuccessful jobs cannot export.
Its shorter injected test deadline does not change the production 900-second limit.

## Database and fault contracts

The opt-in `ECOSENTINEL_TEST_POSTGRES_URL` fixture rejects external hosts or any database
other than `ecosentinel_isolated`. Every case creates a unique schema and removes it
afterwards; it never falls back to a production `DATABASE_URL`.

Checks cover 24 concurrent submissions through independent queue instances (exactly ten
admitted), parallel claims (each job claimed once), `FOR UPDATE SKIP LOCKED`, lease expiry,
stale owners, bounded retries, committed result paths, additive migration of populated
old schemas, eight simultaneous migrations, and an actual PostgreSQL statement timeout
followed by successful connection-pool reuse. PostGIS presence is checked explicitly.

The stack also stops only its test database, checks web health fails closed with 503,
restarts the database, checks health returns 200 and confirms the existing worker can
claim a new diagnostic job. No model is installed: that job must fail explicitly before
acquisition and its PDF route must remain 409. This is software fault evidence, not a
satellite/model success claim.

The cloud coordination tests additionally use a real loopback HTTP server to accept and
then time out/reset RPC requests. Redelivery while leased cannot compute again; after
lease expiry exactly one retry advances the stage. Blob/queue ports remain isolated
test adapters, so Vercel messages and production quota are untouched.

## Running and evidence

```text
POSTGRES_PASSWORD=isolated-test-only docker compose --env-file /dev/null -f compose.yaml -f docker/compose.verify.yaml build
POSTGRES_PASSWORD=isolated-test-only docker compose --env-file /dev/null -f compose.yaml -f docker/compose.verify.yaml up -d --wait db api worker web
POSTGRES_PASSWORD=isolated-test-only docker compose --env-file /dev/null -f compose.yaml -f docker/compose.verify.yaml run --rm --no-deps verify
```

Use a unique `COMPOSE_PROJECT_NAME`, as CI does. The workflow also executes the database
restart and canary probes and always cleans up. A first corrected run, `38771701663`,
passed eleven actual container/database cases. Final exact-commit CI results and local
counts are recorded under ignored `artifacts/deployment/container-checks/`.

The legacy standalone `.env` path requires an explicitly chosen local PostgreSQL password;
bind-mounted artifacts must be writable by container UID 10001 on Linux. The isolated
verification uses fresh Docker-managed volumes and never changes host artifact permissions.
Actual trained-model inference in these containers is NOT_RUN; the earlier Vercel real
Sentinel-2/ONNX evidence remains separate. No scientific threshold or model weight changed.
