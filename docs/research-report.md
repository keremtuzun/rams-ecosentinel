# RAMS EcoSentinel technical research report

Generated from measured artifacts: 2026-10-14T17:20:40.832315+00:00.

## Outcome

The local research system retrieves real multispectral observations, trains and evaluates a temporal forest-loss-reference detector, and executes georeferenced inference through a web application. The full project definition of done is **not met**: prospective wildfire training, independent ecological validation, a reviewed pilot and container/PostgreSQL verification are incomplete.

## Data and reference labels

Sources: Copernicus Sentinel-2 L2A through Element 84 Earth Search; Hansen GFC-2025-v1.13 loss-year, year-2000 canopy and land mask. Six ordered calibrated bands, 30 m local UTM grid, bilinear spectral and nearest categorical sampling, buffered SCL masks. Target labels are annual gross tree-cover-loss reference pixels within baseline canopy >=30%; other annual losses are excluded.

| Region | Partition | Earlier acquisition | Later acquisition | Annual target | Eligible pixels | Positive reference pixels |
|---|---|---|---|---:|---:|---:|
| marmaris | train | 2020-06-28 | 2022-06-23 | 2021 | 70,961 | 88 |
| milas | train | 2020-06-28 | 2022-06-23 | 2021 | 54,179 | 2,212 |
| manavgat | validation | 2020-06-30 | 2022-06-30 | 2021 | 24,715 | 23,439 |
| izmir | test | 2018-06-12 | 2020-06-26 | 2019 | 62,667 | 9,913 |

Total eligible pixels: 212,522. Positive reference pixels: 35,652. Eight historical scenes. Whole-region partition buffers prevent adjacent/overlapping tiles from crossing partitions. İzmir uses an earlier loss year and unseen geography. Pixels are correlated; these counts are not independent statistical trials.

Visual QA inspected all four before/after pairs, masked annual labels and delta-NBR maps. Programmatic checks validated hashes, CRS, band order, finite reflectance, date ordering and dimensions. This is alignment/reference verification, not ecological field validation.

## Executed training

All neural runs use random initialization, actual task-specific gradient descent, AdamW, weighted BCE, deterministic seeds, regularization, clipping, scheduling, validation every epoch and checkpoint selection by validation loss. The predeclared threshold is 0.5. Serving uses seed 7729, selected before test evaluation. A second seed supplies disagreement rather than test-selected replacement.

| Experiment | Seed | Input | Epochs run / selected | Training tiles | Validation tiles | Parameter L1 change |
|---|---:|---|---:|---:|---:|---:|
| habitat-7729 | 7729 | multispectral, temporal | 42 / 30 | 65 | 15 | 356.65837 |
| habitat-7730 | 7730 | multispectral, temporal | 50 / 49 | 65 | 15 | 462.37760 |
| habitat-rgb | 7729 | rgb, temporal | 45 / 33 | 65 | 15 | 335.64496 |
| habitat-single-date | 7729 | multispectral, single-date | 50 / 50 | 65 | 15 | 382.77815 |

Total measured neural epochs: 187. Best and last checkpoints, optimizer/scheduler state, RNG state, model/dataset configurations, training curves and held-out metrics are saved. Habitat resume restores the original data-loader RNG and seed/configuration gates. The small number of independent regions and finite maximum epochs do not establish convergence or nationwide generalization.

## Held-out reference agreement

| Model | Test precision | Test recall | Test F1 | Test IoU | Test PR-AUC | Test Brier | Test ECE |
|---|---:|---:|---:|---:|---:|---:|---:|
| habitat-7729 | 0.96751 | 0.97337 | 0.97043 | 0.94256 | 0.98358 | 0.01215 | 0.05080 |
| habitat-7730 | 0.97411 | 0.97549 | 0.97480 | 0.95084 | 0.98782 | 0.00814 | 0.02113 |
| habitat-rgb | 0.96352 | 0.97518 | 0.96932 | 0.94046 | 0.98964 | 0.01205 | 0.04499 |
| habitat-single-date | 0.93846 | 0.96146 | 0.94982 | 0.90444 | 0.96422 | 0.01594 | 0.02904 |
| Logistic baseline: delta_nbr | 0.96029 | 0.98557 | 0.97277 | 0.94698 | 0.99618 | 0.00687 | 0.00609 |
| Logistic baseline: all | 0.94758 | 0.99193 | 0.96925 | 0.94033 | 0.99695 | 0.00825 | 0.01005 |

Primary model test confusion matrix [[TN, FP], [FN, TP]]: `[[52430, 324], [264, 9649]]`. Validation F1: 0.98368; IoU: 0.96788; false-positive rate among the relatively few negative reference pixels: 0.29781. Manavgat is overwhelmingly positive while the training cohort has rare positive labels, so aggregate accuracy alone is especially misleading.

The delta-NBR logistic baseline slightly outperformed the primary neural seed on held-out F1/IoU. The second seed did better than the first; two runs are insufficient to establish a deep-learning advantage. RGB was close to multispectral performance; the single-date ablation was weaker but still substantial. This selected cohort does not establish that multispectral or temporal modeling universally improves accuracy.

Brier/ECE are diagnostic reference-score metrics, not proof of calibrated ecological probabilities. No model probability calibration was fitted. Regions were selected before training based on accessible data; only one external test region is available. Annual reference labels are Landsat-derived algorithmic products, not independent manual/field truth. No confidence interval based on independent events or ecological plots is claimed.

## Executed inference and exports

Held-out historical inference was run on İzmir; it was loaded into the persistent queue as an explicitly completed offline result. Live job `a132c78a-8acc-43a8-875a-22b1f5028d48` independently retrieved a recent seasonal pair and completed through API submission, worker execution, checkpoint verification and spatial output generation.

- `S2A_35SNB_20250930_1_L2A` acquired `2025-09-30T09:10:12.477000Z`; locally clear nonwater fraction 0.82176.
- `S2C_35SNB_20260930_0_L2A` acquired `2026-09-30T09:00:02.026000Z`; locally clear nonwater fraction 0.80506.

Latest observation age at analysis: 14 days. Jointly clear grid fraction: 0.68283. The map contains 15 candidate polygons with 29.88 ha of mapped candidate extent. This is **not confirmed forest loss, habitat destruction or an unbiased area estimate**. One-year September inference is outside the two-year June evaluation domain.

Two-seed score disagreement over eligible pixels: mean 0.03812, p95 0.11693. This is a model-instability indicator, not an error bound. COG scores, candidate masks, indices, disagreement, GeoJSON polygons, source PNGs, CSV, JSON and a visually verified two-page PDF are present.

The actual browser rendered source imagery and georeferenced polygons after correcting MapLibre's worker deployment. Geometry drawing, study search, dates, actual queue states, source comparison, layer visibility/opacity, pixel inspection and downloads are implemented. The app's metrics page reads saved artifacts; no scientific result is embedded as a decorative UI value.

## Fire and auxiliary data

NASA's official public MODIS C6.1 rolling 24-hour NRT feed was retrieved, parsed, bounded, cached and hashed. The selected Milas AOI contained zero detections in that snapshot, which does not establish an absence of fire. Per-point timestamps, confidence, sensor and scan/track footprints are preserved. Authenticated VIIRS/MODIS historical adapters exist, but no MAP_KEY is configured. WorldCover 2021 context for Milas was also retrieved; it is not used as temporal ground truth.

The seven-day target, science-archive label builder, as-of/weather/event/geography/time gates, trainable fusion architecture and fire baselines exist. No real fire model training or wildfire forecasting validation has run. CDS weather credentials and publication-history evidence are absent. ERA5-Land retrieval is optional retrospective research, not prospective validation. Dynamic World and EFFIS are documented future inputs.

## Engineering verification and limits

See `docs/audit.md` and `docs/verification.json` for executed tests and exact remaining gates. The verified runtime is Windows CPU PyTorch, local Node, SQLite and a separate worker. Docker is not installed; Compose/PostgreSQL/PostGIS have not been exercised. CI configuration exists, but there is no remote or remote CI run. No public hosting, production authentication, field pilot or external partnerships were created.

## Artifact identities

- `artifacts/models/habitat-7729/best.pt`: SHA-256 `c8463288bb16fba7a43d218004fba3851505b34025f33b72bf2b9db657a4b358`.
- `artifacts/models/habitat-7730/best.pt`: SHA-256 `71df90e9ecdabc3f782e073bbf6a3f3940e0ea8ec524566219ba22dcc65a3fa1`.
- `artifacts/models/habitat-rgb/best.pt`: SHA-256 `fbdae18425eb7e8968e8cb6da74926a34463c345b100496d5e1b61a4a297573f`.
- `artifacts/models/habitat-single-date/best.pt`: SHA-256 `6122a6d37d5b398a8d33cb204b9655f7fc4eda766e0625ae9e4c741e156f855e`.

Dataset manifest SHA-256: `1095b2fb75cdfb9acd60460686155274c2e0cc4e253637f0079dc01d3b58cf70`. Full artifact registry: `artifacts/registry.json`. Artifacts are ignored by Git and require separate authorized storage/transfer. Fresh catalogue acquisition is a new dataset if source items change.

## Recommended next experiments

1. Obtain independent expert annotations and field/context review across additional Turkish ecologies, disturbance types and stable forests, including negative-heavy validation geography.
2. Add more seasons/years, cloud and misregistration challenges, and true event/geographic bootstrap uncertainty; freeze partitions before model selection.
3. Acquire authenticated historical FIRMS science records and genuinely as-of weather archives, audit event grouping and publication-time availability, then run the fire baselines before any forecast claims.
4. Evaluate regularized baselines against larger temporal models, calibration on separate validation data, region-level area errors and sample-based unbiased area estimation.
5. Exercise Docker/PostgreSQL, add production auth/quotas/artifact storage, and seek a reviewed local pilot with a real domain specialist. No external contact is authorized or fabricated.

Sources and legal references: [data-sources.md](data-sources.md). Architecture and target definitions: [architecture.md](architecture.md).
