# Architecture decisions

## Research scope

Module B is a supervised **annual tree-cover-loss reference detection experiment**, not
validated habitat degradation diagnosis. The common grid is 30 m in the AOI's local UTM
zone. Six ordered, calibrated Sentinel-2 bands from two dates enter a compact Siamese U-Net.
This architecture was selected for temporal features, spatial output, limited CPU compute,
and maintainability. No unchanged pretrained inference or external vision LLM is used.
Random initialization is explicitly recorded. RGB and single-date ablations are actual runs.

Module A1's specified target is an observed thermal anomaly within (T,T+7 days] in a 1 km
cell. Absence of a detection is not absence of ignition. No historical fire model is served
until source coverage and as-of feature provenance can be established. Module A2 supplies
independent NASA thermal observations and never describes them as AI forecasts.

## Data flow

```
provider STAC → bounded COG windows → calibrated, aligned surface reflectance
             → local SCL QA + cloud/shadow buffer → CRS-preserving cache + hashes
Hansen annual loss + baseline canopy → eligible binary reference + exclusion mask
whole-region partitions → train/validate/checkpoint → full-region held-out evaluation
user geometry + date windows → persistent job → worker subprocess → verified checkpoint
                             → score + disagreement + mask + GeoJSON + provenance report
                             → Next.js / MapLibre → GIS / CSV / PDF exports
```

Earth Search was chosen as the **explicit public COG mirror** to avoid credentials and full
SAFE downloads. CDSE discovery is supported and verified, but its authenticated JP2/SAFE
download flow is not implemented. No fallback is presented as the original provider.

Provider assets are HTTPS and hostname allowlisted. Scene objects cannot be submitted by
users. Scaling is recorded per band. Already-applied Earth Search BOA offsets are not
subtracted again; ambiguous modern false-offset metadata fails closed.

## Quality, splits and labels

SCL classes 4/5 are valid land. Water is excluded. Invalid/dark/shadow/cloud/cirrus/snow
classes and nodata receive a two-pixel contamination buffer. A candidate needs at least 80%
clear nonwater AOI pixels; clouds and nodata remain in that denominator. Bilinear spectral
resampling and nearest categorical resampling share the exact grid. No automatic registration
correction is claimed; subpixel registration errors remain a research limitation.

Supervision uses year-2000 canopy >=30%, Hansen land mask, stable no-mapped-loss pixels or
the target annual loss code. All other loss-year codes are excluded. The target year lies
fully between acquisition years. Thus annual labels are not used to invent event dates.

Marmaris/Milas train, Manavgat validates, İzmir tests with an earlier loss year. Whole AOIs
have a >=0.05-degree partition buffer. No overlapping tile random split is permitted.
Training uses nonoverlapping 64x64 tiles with >=15% eligible supervision; border remainder
tiles are excluded from training loss. Held-out evaluation uses the full eligible raster.
Label pixels are correlated; they are not independent trial counts.

## Training and inference

AdamW, weighted BCE, clipping, deterministic seeds, validation each epoch, a plateau
scheduler, early stopping, best/last checkpoints, RNG-preserving habitat resume, and
measured weight changes are implemented. Threshold 0.5 is predeclared. No test threshold
tuning or choosing the serving seed by test performance occurred. Mean absolute disagreement
between two trained seeds is an experimental instability indicator, not calibration.

Inference verifies trained-weight evidence, checkpoint hashes, embedded configuration,
source grid and preprocessing. The U-Net output is an uncalibrated reference classifier
score. A before-NDVI >=0.45 display screen is approximate; a spatial opening and nine-pixel
minimum mapping unit reduce fragments. Raw and postprocessed outputs have distinct meanings.
Map image-corner reprojection is a preview; authoritative grids and vector CRS metadata
remain in COG/GeoJSON outputs. Effective independent spatial resolution is not claimed as
10 m after combining 10/20 m bands with a roughly 30 m annual reference.

## Application and deployment boundary

Next.js/React/TypeScript and MapLibre provide the map, drawing, source comparison, inspection,
actual job status, layer controls, metrics and exports. CSS uses a restrained laboratory
layout. External basemap imagery is context and never enters the models. Scientific numbers
originate from saved experiment artifacts.

FastAPI validates polygon geometry, dates, seasons, country bounds, vertex count, area and
grid limits. SQLAlchemy persists jobs in SQLite locally or PostgreSQL in the composition.
A separate worker claims ownership leases and runs each analysis in a subprocess with a
15-minute wall limit. Expired worker leases can be requeued once; a stale worker cannot
complete another owner's job. Provider requests have bounded attempts; raw upstream errors
and credential-bearing FIRMS URLs are not returned or logged at INFO.

The local API allows five expensive requests per IP/minute, 16 KB POST bodies and ten
pending jobs. SQLite is single API/worker research mode. PostgreSQL claims use row locking
and an admission advisory lock, but that path has not been executed locally. Multi-instance
rate limits and spatial DB indexing in that database path remain incomplete.

The public Vercel application has a separate deployment path: Next.js coordinates three
Vercel Queue stages, each invoking an authenticated stateless FastAPI compute service.
Private Blob stores job state, source observations and final artifacts; `/tmp` is scratch
space only. Atomic conditional writes compare the strong ETag of the exact JSON read with
`Accept-Encoding: identity`, preventing stale owners from publishing a result. Completed
progress is committed before dispatching the next stage, so duplicate deliveries repair
dispatch without recomputing committed work. Compute attempts are bounded per stage.

A signed HttpOnly browser cookie scopes new result access. Distributed hourly admission
limits use conditional Blob writes (three jobs per browser, eight globally). This is
anonymous session isolation, not named-account authentication; clearing the cookie loses
private history. The Python service checks a shared server-only bearer token and never
accepts user-supplied artifact URLs. Source metadata and checksums are preserved across
durable stages. Hosted inference uses a verified ONNX conversion of the primary checkpoint;
the secondary conversion failed its declared parity tolerance and is excluded.
