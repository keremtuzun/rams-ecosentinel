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
Actual trained-model inference in these containers is now verified separately below;
the earlier Vercel real Sentinel-2/ONNX evidence remains separate. No scientific
threshold or model weight changed.

## Genuine Sentinel-2 / ONNX Docker run

Manual run [38778853803](https://github.com/keremtuzun/rams-ecosentinel/actions/runs/38778853803)
passed on source commit `ffaac89cd8459f5014c0f0250d2a6b2146cadcbd`.
This is a fresh acquisition and actual trained-model inference, not fixture evidence.
Chromium, web, API, PostGIS and the verifier run on the internal Docker network. Only
the worker has a second network for public Earth Search / Sentinel COG acquisition.
No Vercel API, queue, Blob or production database credentials enter these containers.
Exactly one job was submitted to the isolated stack; no production analysis was submitted.

The genuine serving model is mounted read-only outside the build context, transported
through temporary chunked GitHub secrets and pinned by its bundle SHA-256. Neither the
model nor the completed analysis is committed. Generated results are encrypted with
AES-256-GCM before artifact upload and decrypted only in ignored local artifacts.
The workflow always removes its containers, named volumes and runner model directory.
Temporary transfer secrets are removed after verification.

The first preflight, run `38777944445`, reproduced `ModuleNotFoundError: onnxruntime`
before any satellite download. The API/worker Docker image now installs the `onnx`
extra, pinned to the same `onnxruntime==1.24.3` used by the evaluated conversion.
The corrected image loads the provenance-validated model before accepting the job.
A separate failed browser probe (`38778276695`) used a host-published port on the
internal-only network. Moving Chromium into that network fixed the test setup without
opening the API or database to an external network; that probe submitted no job.

Measured result:

| Check | Actual evidence |
|---|---|
| Acquisition | `S2A_36TVK_20220620_0_L2A` and `S2B_36TVK_20240624_1_L2A`; fresh retrieval timestamps, STAC records, scaling, six aligned reflectance bands and source-index pixel counts verified. |
| Trained checkpoint | `c8463288bb16fba7a43d218004fba3851505b34025f33b72bf2b9db657a4b358`; ONNX file `c55049b746a265707b1d90690f739a95a9e8bf58ae4016f1ad561720e1a2d4c8`, matching the installed local artifact. |
| Completion | Job `cb0ada7b-e6ca-44c9-8652-2fd7c017babf`, one compute attempt, ONNX CPU runtime, committed owner and new generation timestamp. |
| Concave AOI | 145,976 selected pixels / 268,965 grid pixels. Joint clear fraction **0.9938688551542719**. The incorrect full-rectangle denominator would give **0.539404755265555**. Padding stays masked. |
| Output consistency | 24,557 eligible pixels, 429 candidate pixels / 38.61 ha / 13 polygons. Recomputed indices match raw reflectance, report and CSV. These are candidate patterns, not confirmed ecological loss. |
| All available exports | PDF (1,513,034 bytes; two pages rendered and visually reviewed), CSV, JSON, GeoJSON; score, mask and eight-band indices GeoTIFFs. The **5,764,360-byte** indices download matches the worker file SHA-256 through the real web proxy. PNG files also match and decode. |
| Point inspection | An eligible point returns `0.002178668975830078`, matching the score raster; polygon padding returns null; outside-grid coordinates return 422. |
| Browser | Real completed result, actual PDF/CSV downloads, refresh recovery, 390 px overflow and JavaScript error checks passed without mocked API responses. External basemap tiles are unavailable on the internal-only browser network; the genuine analysis overlay remains usable. |

The optional second-seed uncertainty GeoTIFF is **BLOCKED**: no compatible second
ONNX model is installed. The report explicitly says unavailable, the UI hides its
download and its file route returns 404. No uncertainty surface was fabricated.
Production signed Blob redirects and cloud queue delivery are **NOT_RUN in this
Docker exercise**; the separate prior cloud checks remain separate evidence.

Detailed exports, source rasters, verification JSON, screenshots and rendered PDF pages
are retained only under ignored `artifacts/deployment/real-container/run-38778853803/`.
The ordinary regression suite remains independent: 92 local Python cases passed,
15 PostgreSQL/container cases passed on the disposable runner; 42 local Playwright
cases passed and the packaged-evidence-only case skipped. TypeScript, Ruff and npm
audit passed. The real-data workflow is opt-in, never an automatic satellite job on push.

To repeat with Docker, combine `compose.yaml`, `docker/compose.verify.yaml` and
`docker/compose.real.yaml`, using a fresh Compose project and an absolute verified model
directory in `ECOSENTINEL_ISOLATED_MODEL`. The manual `real-analysis.yaml` workflow
performs the full browser/export run with temporary `TEMP_ECOSENTINEL_MODEL_0` through
`_7` base64 bundle chunks (40,000 characters each), its required SHA-256 input and a
random 32-byte base64 `TEMP_ECOSENTINEL_OUTPUT_KEY`. Provision these only for a trusted
commit, retrieve/decrypt the output, then delete the temporary secrets. Missing or
unverified model assets fail closed before acquisition.
