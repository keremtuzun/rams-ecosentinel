# RAMS EcoSentinel

Live application: [rams-ecosentinel.vercel.app](https://rams-ecosentinel.vercel.app/).

Pushes to the `main` branch automatically deploy both connected Vercel projects: `apps/web` serves the
website and `apps/backend` serves the analysis API. The API build bundles the current
`ecosentinel/` source from this repository. Build-time model weights and completed
public studies are restored from immutable, SHA-256-pinned bundles in private Blob
storage; credentials and large generated artifacts stay outside Git. Both projects
require `ECOSENTINEL_BUILD_ASSET_PATH` and `ECOSENTINEL_BUILD_ASSET_SHA256` in Vercel.
To deliberately update those artifact versions, run `python -m scripts.package_build_assets`
on a machine with the verified artifacts, upload the generated bundles to the existing
private store, and update those references. Normal source edits need only a push to `main`.

Environmental research software developed by **FRC Team 7729 RAMs**, **FIRST BIOCORE 2027**.
This release contains genuine Sentinel-2 acquisition, task-specific PyTorch training,
held-out reference evaluation, on-demand inference, and a map-first Next.js application.
It is **not an operational wildfire warning or independently validated habitat assessment system**.

## What ran

Four Turkish study regions, eight historical Sentinel-2 L2A observations, Hansen GFC-2025-v1.13
reference labels, four neural experiments, two logistic baselines, held-out İzmir inference,
and a live Milas analysis using 30 September 2025 / 30 September 2026 observations.
The complete measured record is in [docs/research-report.md](docs/research-report.md).

## Start locally (Windows / PowerShell)

Python 3.11+ and Node 22+ are required. CUDA is optional. This machine used Python 3.13,
CPU PyTorch, SQLite, and Node. A local `.venv` has already been prepared here.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
# For the recorded Windows package versions, use requirements-lock.txt instead.
.\.venv\Scripts\python.exe -m ecosentinel.cli migrate
.\.venv\Scripts\python.exe -m uvicorn ecosentinel.api:app --host 127.0.0.1 --port 8000
```

Open a second terminal at the repository root:

```powershell
.\.venv\Scripts\python.exe -m ecosentinel.cli worker
```

Open a third terminal:

```powershell
cd apps/web
npm ci
npm run build
npm run start
```

Open **http://localhost:3000**. API docs are at **http://localhost:8000/docs**.
Both servers bind to loopback. Jobs remain queued until the worker is running.
`npm run dev` provides the frontend development server instead of the build/start sequence.
Stop a running production frontend before rebuilding, particularly on Windows where its
standalone bundle directory can remain locked. Use the development server while editing.
For Linux/macOS use `.venv/bin/python` and normal forward-slash paths.

## Acquire and train real data

No Copernicus account is needed for the public Earth Search COG mirror used here.
CDSE STAC discovery was also tested successfully. Use the explicit source versions and
preprocessing recorded in the manifests; do not substitute screenshots or visual LLM output.

```powershell
.\.venv\Scripts\python.exe -m ecosentinel.cli doctor
.\.venv\Scripts\python.exe -m ecosentinel.cli acquire
.\.venv\Scripts\python.exe -m ecosentinel.cli train-habitat --epochs 50 --patience 12
.\.venv\Scripts\python.exe -m ecosentinel.cli train-habitat --output artifacts/models/habitat-7730 --seed 7730 --epochs 50 --patience 12 --skip-baselines
.\.venv\Scripts\python.exe -m ecosentinel.cli train-habitat --output artifacts/models/habitat-rgb --bands rgb --epochs 50 --patience 12 --skip-baselines
.\.venv\Scripts\python.exe -m ecosentinel.cli train-habitat --output artifacts/models/habitat-single-date --single-date --epochs 50 --patience 12 --skip-baselines
.\.venv\Scripts\python.exe -m ecosentinel.cli infer-offline artifacts/dataset/izmir --output artifacts/results/izmir-heldout
.\.venv\Scripts\python.exe -m ecosentinel.cli import-result artifacts/results/izmir-heldout
.\.venv\Scripts\python.exe -m ecosentinel.cli worldcover-context artifacts/dataset/milas
.\.venv\Scripts\python.exe scripts/visual_qa.py
.\.venv\Scripts\python.exe -m ecosentinel.cli registry
```

Completed experiments are protected from accidental overwrite. To reproduce a run, use a
new output directory. To resume interrupted habitat training, supply the original output
and `--resume artifacts/models/<run>/last.pt`; configuration and dataset hashes must match.
Seed, optimizer, scheduler, data-loader RNG, initial weights, and history are restored.
GPU mixed precision is not implemented; CPU and GPU use deterministic full precision.
Numerical and binary identity across hardware/library versions is not promised.

Each experiment contains `best.pt`, `last.pt`, `config.json`, `dataset_manifest.json`,
`history.json`, `training.png`, and `metrics.json`. The primary seed also contains safe
numeric logistic baseline coefficients in `baselines.json`. Its checkpoint is the
predeclared serving model; the second seed supplies a disagreement raster rather than
being selected by test performance.

`artifacts/registry.json` records checksums and source manifests; binaries and raw data are
ignored by Git. Preserve the complete artifact directory for exact-input reruns. Fresh
catalogue acquisition can select a different reprocessed item; it is a new dataset and
must not be described as the original experiment. Cloud analyses use private Vercel Blob
storage; the original training artifacts remain local.

## Live analysis

Search a study location or draw a polygon/rectangle. Choose nonoverlapping, seasonally
comparable windows of at most 62 days each. The worker uses the newest acceptable
covering scene among at most five candidates per window; scene-wide cloud metadata is
followed by local QA. No acceptable data means a failed job, with no synthetic replacement.

Every successful job contains exact source metadata and checksums, source PNGs, calibrated
index COGs, a classifier-score COG, a masked candidate COG, GeoJSON polygons, and JSON/PDF/CSV
exports. With two compatible seeds, `uncertainty.tif` holds absolute classifier-score
disagreement. That measures model instability, not calibrated ecological uncertainty.
Only valid, earlier NDVI >=0.45 pixels are displayed as the approximate forest-like domain.
The map is an approximate preview of projected rasters; use CRS-preserving GeoTIFF/GeoJSON
exports for quantitative GIS work. Pixel counts are mapped extent, not unbiased area estimates.

The live Milas result is a one-year September pair; training/evaluation used two-year June
pairs. It demonstrates functioning acquisition and inference, **not validated recent-change accuracy**.

## Thermal observations and wildfire research

The public rolling 24-hour **MODIS C6.1 NRT** CSV is available without credentials. It is
bounded to 10 MB, cached for one hour, checked for stale acquisition timestamps, persisted
with provenance, and filtered to the AOI. Zero detections do not prove no fire. A FIRMS
`FIRMS_MAP_KEY` enables the authenticated VIIRS/MODIS adapters and historical requests.

```powershell
$env:FIRMS_MAP_KEY='your-key' # never commit or place in NEXT_PUBLIC_* variables
```

The seven-day, 1 km wildfire target and trainable image/weather fusion architecture are
implemented. Fire-label generation and training require curated records proving feature
availability at T, science-quality archive coverage, event groups, geographic separation,
and purged chronological holdouts. The necessary historical data are not installed.

```powershell
ecosentinel build-fire-labels features.json firms-science.csv coverage.json --output fire-manifest.json
ecosentinel train-fire fire-manifest.json --output artifacts/models/fire-study --epochs 60
```

See [docs/fire-data-contract.md](docs/fire-data-contract.md). These fire commands **were not
run on real data**. Fire forecasting stays blocked in the application. Optional ERA5-Land
retrieval requires `pip install -e '.[cds]'`, `CDSAPI_KEY`, accepted dataset terms, and use of
`ecosentinel.sources.retrieve_era5_land`. It is retrospective reanalysis; the adapter does
not establish prospective feature availability. Dynamic World is researched but not ingested.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check ecosentinel tests
cd apps/web
npm run build
npm run typecheck
npx playwright install chromium
npm test
npm audit --audit-level=high
```

Real-artifact integration tests skip explicitly in clean CI when ignored data/checkpoints
are absent. UI contract tests use clearly labeled test-only API fixtures. Actual map and
live-data checks are recorded separately. GitHub Actions runs the checked-in workflow on
pushes and pull requests. See [docs/debug-verification.md](docs/debug-verification.md)
for the current debugging evidence and remaining verification limits.

## Containers

Copy `.env.example` to `.env` and set a local `POSTGRES_PASSWORD` (URI-safe characters or
appropriate URL encoding). Then run `docker compose up --build`. The composition includes
PostgreSQL/PostGIS, API, separate bounded worker and frontend, and binds exposed ports to
loopback. Only the job queue uses PostgreSQL in this release; PostGIS spatial indexing is
future work. The initial migration is in `database/migrations/001_jobs.sql`.

Docker/API/web builds and PostgreSQL queue behavior are verified on an isolated Ubuntu
CI runner; see [docs/container-verification.md](docs/container-verification.md). Local
Windows Docker/WSL remains uninstalled. Local inference uses Python/Node and SQLite; the
cloud path below uses a separate stateless Python service, durable storage and Queues.
Cloud results belong to a signed anonymous browser session, not a named user account.
No public administrative mutation endpoints or file uploads are exposed.

## Vercel

Published application: https://rams-ecosentinel.vercel.app

The Next.js web app deploys from `apps/web`; FastAPI deploys separately from `apps/backend`.
Cloud mode accepts a Turkish place search or a drawn area and two comparison dates. Each
simple date selects up to 30 preceding days. For close dates, the later window starts
after the earlier endpoint so that no observation day is counted twice. Exact windows are available in the
collapsed advanced controls. Analyses cover Türkiye, with 0.1–2,500 km² areas up to 50 km
per bounding dimension on a bounded 1670×1670 grid at the original 30 m resolution.
Comparison endpoints must be at least two calendar years apart, use past dates from
2017 onward and comparable seasons. Existing shorter-interval reports remain readable.
Large areas combine real tiles spanning at most five calendar days, recording each source
and pixel-to-source assignment in GeoTIFFs. Source QA may reject a window;
the service does not substitute invented imagery. Wildfire forecasting remains unavailable.

Three durable queued stages acquire the earlier observation, acquire the later observation
and perform inference. Each stage executes a bounded Python subprocess on Vercel; the
laptop's API and worker are not required. Private Blob stores immutable artifacts and
versioned job state. Strong ETags and conditional writes guard ownership across retries.
New job admission is bounded to three analyses per browser per UTC hour and eight globally.
Anonymous result access lasts with the signed browser cookie (30 days); clearing it loses
access to that browser's private history. Existing public study results remain available.

The serving model is an ONNX conversion of the original trained primary checkpoint. Its
scores were checked against PyTorch on all four real study regions (maximum absolute
error 0.00001848; zero threshold-mask disagreements). The secondary conversion exceeded
the declared numerical tolerance and is excluded; new cloud jobs have no two-seed
disagreement layer. This is an experimental tree-cover change score, not a calibrated
probability or confirmed ecological diagnosis.

Prepare authentic evidence and the verified cloud model before uploading:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_vercel_evidence.py
.\.venv\Scripts\python.exe scripts/export_cloud_models.py --model primary
.\.venv\Scripts\python.exe scripts/prepare_cloud_backend.py
cd apps/backend
npx vercel@64.0.2 deploy --prod --scope keremtuzuns-projects
cd ../web
npx vercel@64.0.2 deploy --prod --skip-domain --scope keremtuzuns-projects
```

Generated evidence is ignored by Git but included in CLI deployments. Do not exclude
`public/evidence` from the upload. Inspect and test the staged deployment before promotion.
The web project requires server-only `ECOSENTINEL_CLOUD_ANALYSIS=1`,
`ECOSENTINEL_BACKEND_URL`, the shared `ECOSENTINEL_BACKEND_TOKEN`, and an OIDC-linked private
Blob store (`BLOB_STORE_ID`). The backend requires the same shared token and its own
server-only `BLOB_READ_WRITE_TOKEN` for that store. Never put credentials in `NEXT_PUBLIC_*`
variables. Queue triggers are declared in `apps/web/vercel.json`. The backend build compiles
pinned, checksum-verified Expat source for Rasterio's Linux runtime dependency.

Without cloud configuration, Vercel serves only the checksum-verified public evidence.
Local production defaults to the Python API on port 8000; `ECOSENTINEL_HOSTED_MODE=evidence`
exercises the viewer locally. See [docs/cloud-verification.md](docs/cloud-verification.md)
for the actual cloud run and its limitations.

Read [docs/architecture.md](docs/architecture.md), [docs/data-sources.md](docs/data-sources.md),
and [docs/audit.md](docs/audit.md) before external demonstrations or a pilot.
