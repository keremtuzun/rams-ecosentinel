"""Generate the technical research record exclusively from saved real artifacts."""

import importlib.metadata
import os
import torch

from ecosentinel.common import ARTIFACTS, ROOT, read_json, sha256, utcnow, write_json

manifest = read_json(ARTIFACTS / "dataset" / "manifest.json")
runs = []
for directory in sorted((ARTIFACTS / "models").glob("habitat-*")):
    if (directory / "metrics.json").exists():
        runs.append((directory, read_json(directory / "config.json"), read_json(directory / "metrics.json")))
primary = next(r for r in runs if r[0].name == "habitat-7729")
baselines = read_json(primary[0] / "baselines.json")
job_id = "a132c78a-8acc-43a8-875a-22b1f5028d48"
live = read_json(ARTIFACTS / "jobs" / job_id / "report.json")
lines = [
    "# RAMS EcoSentinel technical research report",
    "",
    f"Generated from measured artifacts: {utcnow()}.",
    "",
    "## Outcome",
    "",
    "The local research system retrieves real multispectral observations, trains and evaluates a temporal forest-loss-reference detector, and executes georeferenced inference through a web application. The full project definition of done is **not met**: prospective wildfire training, independent ecological validation, a reviewed pilot and container/PostgreSQL verification are incomplete.",
    "",
    "## Data and reference labels",
    "",
    "Sources: Copernicus Sentinel-2 L2A through Element 84 Earth Search; Hansen GFC-2025-v1.13 loss-year, year-2000 canopy and land mask. Six ordered calibrated bands, 30 m local UTM grid, bilinear spectral and nearest categorical sampling, buffered SCL masks. Target labels are annual gross tree-cover-loss reference pixels within baseline canopy >=30%; other annual losses are excluded.",
    "",
    "| Region | Partition | Earlier acquisition | Later acquisition | Annual target | Eligible pixels | Positive reference pixels |",
    "|---|---|---|---|---:|---:|---:|",
]
for region in manifest["regions"]:
    lines.append(
        f"| {region['id']} | {region['split']} | {region['before_scene']['acquired_at'][:10]} | {region['after_scene']['acquired_at'][:10]} | {region['loss_year']} | {region['valid_pixels']:,} | {region['positive_pixels']:,} |"
    )
lines += [
    "",
    f"Total eligible pixels: {sum(r['valid_pixels'] for r in manifest['regions']):,}. Positive reference pixels: {sum(r['positive_pixels'] for r in manifest['regions']):,}. Eight historical scenes. Whole-region partition buffers prevent adjacent/overlapping tiles from crossing partitions. İzmir uses an earlier loss year and unseen geography. Pixels are correlated; these counts are not independent statistical trials.",
    "",
    "Visual QA inspected all four before/after pairs, masked annual labels and delta-NBR maps. Programmatic checks validated hashes, CRS, band order, finite reflectance, date ordering and dimensions. This is alignment/reference verification, not ecological field validation.",
    "",
    "## Executed training",
    "",
    "All neural runs use random initialization, actual task-specific gradient descent, AdamW, weighted BCE, deterministic seeds, regularization, clipping, scheduling, validation every epoch and checkpoint selection by validation loss. The predeclared threshold is 0.5. Serving uses seed 7729, selected before test evaluation. A second seed supplies disagreement rather than test-selected replacement.",
    "",
    "| Experiment | Seed | Input | Epochs run / selected | Training tiles | Validation tiles | Parameter L1 change |",
    "|---|---:|---|---:|---:|---:|---:|",
]
for directory, config, metrics in runs:
    mode = f"{config['bands']}, {'temporal' if config['temporal'] else 'single-date'}"
    lines.append(
        f"| {directory.name} | {config['seed']} | {mode} | {metrics['epochs_run']} / {metrics['best_epoch']} | {config['training_tiles']} | {config['validation_tiles']} | {metrics['parameter_l1_change']:.5f} |"
    )
lines += [
    "",
    f"Total measured neural epochs: {sum(m['epochs_run'] for _, _, m in runs)}. Best and last checkpoints, optimizer/scheduler state, RNG state, model/dataset configurations, training curves and held-out metrics are saved. Habitat resume restores the original data-loader RNG and seed/configuration gates. The small number of independent regions and finite maximum epochs do not establish convergence or nationwide generalization.",
    "",
    "## Held-out reference agreement",
    "",
    "| Model | Test precision | Test recall | Test F1 | Test IoU | Test PR-AUC | Test Brier | Test ECE |",
    "|---|---:|---:|---:|---:|---:|---:|---:|",
]


def metric_row(name, m):
    return f"| {name} | {m['precision']:.5f} | {m['recall']:.5f} | {m['f1']:.5f} | {m['iou']:.5f} | {m['pr_auc']:.5f} | {m['brier_score']:.5f} | {m['ece_10_bins']:.5f} |"


for directory, _, metrics in runs:
    lines.append(metric_row(directory.name, metrics["test"]["aggregate"]))
for name, value in baselines.items():
    lines.append(metric_row("Logistic baseline: " + name, value["metrics"]["test"]["aggregate"]))
test = primary[2]["test"]["aggregate"]
validation = primary[2]["validation"]["aggregate"]
lines += [
    "",
    f"Primary model test confusion matrix [[TN, FP], [FN, TP]]: `{test['confusion_matrix']}`. Validation F1: {validation['f1']:.5f}; IoU: {validation['iou']:.5f}; false-positive rate among the relatively few negative reference pixels: {validation['false_positive_rate']:.5f}. Manavgat is overwhelmingly positive while the training cohort has rare positive labels, so aggregate accuracy alone is especially misleading.",
    "",
    "The delta-NBR logistic baseline slightly outperformed the primary neural seed on held-out F1/IoU. The second seed did better than the first; two runs are insufficient to establish a deep-learning advantage. RGB was close to multispectral performance; the single-date ablation was weaker but still substantial. This selected cohort does not establish that multispectral or temporal modeling universally improves accuracy.",
    "",
    "Brier/ECE are diagnostic reference-score metrics, not proof of calibrated ecological probabilities. No model probability calibration was fitted. Regions were selected before training based on accessible data; only one external test region is available. Annual reference labels are Landsat-derived algorithmic products, not independent manual/field truth. No confidence interval based on independent events or ecological plots is claimed.",
    "",
    "## Executed inference and exports",
    "",
    f"Held-out historical inference was run on İzmir; it was loaded into the persistent queue as an explicitly completed offline result. Live job `{job_id}` independently retrieved a recent seasonal pair and completed through API submission, worker execution, checkpoint verification and spatial output generation.",
    "",
]
for source in live["source_observations"]:
    lines.append(
        f"- `{source['scene_id']}` acquired `{source['acquired_at']}`; locally clear nonwater fraction {source['clear_fraction']:.5f}."
    )
lines += [
    "",
    f"Latest observation age at analysis: {live['latest_observation_age_days']} days. Jointly clear grid fraction: {live['clear_fraction']:.5f}. The map contains {live['candidate_polygons']} candidate polygons with {live['mapped_candidate_area_ha']:.2f} ha of mapped candidate extent. This is **not confirmed forest loss, habitat destruction or an unbiased area estimate**. One-year September inference is outside the two-year June evaluation domain.",
    "",
    f"Two-seed score disagreement over eligible pixels: mean {live['uncertainty']['mean_disagreement_on_eligible_pixels']:.5f}, p95 {live['uncertainty']['p95_disagreement_on_eligible_pixels']:.5f}. This is a model-instability indicator, not an error bound. COG scores, candidate masks, indices, disagreement, GeoJSON polygons, source PNGs, CSV, JSON and a visually verified two-page PDF are present.",
    "",
    "The actual browser rendered source imagery and georeferenced polygons after correcting MapLibre's worker deployment. Geometry drawing, study search, dates, actual queue states, source comparison, layer visibility/opacity, pixel inspection and downloads are implemented. The app's metrics page reads saved artifacts; no scientific result is embedded as a decorative UI value.",
    "",
    "## Fire and auxiliary data",
    "",
    "NASA's official public MODIS C6.1 rolling 24-hour NRT feed was retrieved, parsed, bounded, cached and hashed. The selected Milas AOI contained zero detections in that snapshot, which does not establish an absence of fire. Per-point timestamps, confidence, sensor and scan/track footprints are preserved. Authenticated VIIRS/MODIS historical adapters exist, but no MAP_KEY is configured. WorldCover 2021 context for Milas was also retrieved; it is not used as temporal ground truth.",
    "",
    "The seven-day target, science-archive label builder, as-of/weather/event/geography/time gates, trainable fusion architecture and fire baselines exist. No real fire model training or wildfire forecasting validation has run. CDS weather credentials and publication-history evidence are absent. ERA5-Land retrieval is optional retrospective research, not prospective validation. Dynamic World and EFFIS are documented future inputs.",
    "",
    "## Engineering verification and limits",
    "",
    "See `docs/audit.md` and `docs/verification.json` for executed tests and exact remaining gates. The verified runtime is Windows CPU PyTorch, local Node, SQLite and a separate worker. Docker is not installed; Compose/PostgreSQL/PostGIS have not been exercised. CI configuration exists, but there is no remote or remote CI run. No public hosting, production authentication, field pilot or external partnerships were created.",
    "",
    "## Artifact identities",
    "",
]
for directory, _, metrics in runs:
    lines += [
        f"- `{directory.relative_to(ROOT).as_posix()}/best.pt`: SHA-256 `{metrics['checkpoint_sha256']}`."
    ]
lines += [
    "",
    f"Dataset manifest SHA-256: `{sha256(ARTIFACTS / 'dataset' / 'manifest.json')}`. Full artifact registry: `artifacts/registry.json`. Artifacts are ignored by Git and require separate authorized storage/transfer. Fresh catalogue acquisition is a new dataset if source items change.",
    "",
    "## Recommended next experiments",
    "",
    "1. Obtain independent expert annotations and field/context review across additional Turkish ecologies, disturbance types and stable forests, including negative-heavy validation geography.",
    "2. Add more seasons/years, cloud and misregistration challenges, and true event/geographic bootstrap uncertainty; freeze partitions before model selection.",
    "3. Acquire authenticated historical FIRMS science records and genuinely as-of weather archives, audit event grouping and publication-time availability, then run the fire baselines before any forecast claims.",
    "4. Evaluate regularized baselines against larger temporal models, calibration on separate validation data, region-level area errors and sample-based unbiased area estimation.",
    "5. Exercise Docker/PostgreSQL, add production auth/quotas/artifact storage, and seek a reviewed local pilot with a real domain specialist. No external contact is authorized or fabricated.",
    "",
    "Sources and legal references: [data-sources.md](data-sources.md). Architecture and target definitions: [architecture.md](architecture.md).",
]
(ROOT / "docs" / "research-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

# Capture only this project's declared runtime packages, not unrelated global package metadata.
packages = [
    "torch",
    "numpy",
    "rasterio",
    "shapely",
    "pyproj",
    "fastapi",
    "uvicorn",
    "pydantic",
    "sqlalchemy",
    "psycopg",
    "scikit-learn",
    "httpx",
    "pillow",
    "reportlab",
    "matplotlib",
    "pytest",
    "ruff",
]
write_json(
    ROOT / "docs" / "runtime.json",
    {
        "captured_at": utcnow(),
        "packages": {p: importlib.metadata.version(p) for p in packages},
        "compute": {"cuda": torch.cuda.is_available(), "logical_cpus": os.cpu_count()},
    },
)
