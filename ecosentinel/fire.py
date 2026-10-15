"""Prospective fire experiment with explicit feature availability and event grouping gates.

No packaged fire checkpoint exists until authenticated, science-quality labels and
as-of covariates pass these gates. Reanalysis without publication timestamps fails closed.
"""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import torch
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from ecosentinel.common import PREPROCESSING, read_json, sha256, utcnow, write_json
from ecosentinel.metrics import binary_metrics
from ecosentinel.models import FireFusion
from ecosentinel.training import network_input, plot_history, set_seed

WEATHER_FIELDS = [
    "temperature_c",
    "relative_humidity_pct",
    "wind_speed_ms",
    "precipitation_7d_mm",
    "soil_moisture",
    "elevation_m",
]


def timestamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Feature and target timestamps must include timezone")
    return stamp


def build_fire_labels(features_path, observations_path, coverage_path, output):
    """Construct seven-day observed-anomaly targets from a documented historical science archive.

    Coverage metadata must identify the actual archive source and date/geographic extent.
    It cannot establish absence of ignition: target zero only means no mapped observation.
    """
    from shapely.geometry import Point, shape
    from ecosentinel.sources import parse_firms

    features_path, observations_path, coverage_path, output = map(
        Path, [features_path, observations_path, coverage_path, output]
    )
    if output.parent.resolve() != features_path.parent.resolve():
        raise ValueError(
            "Write the generated fire manifest beside its feature manifest to preserve image paths"
        )
    features, coverage = read_json(features_path), read_json(coverage_path)
    if coverage["quality"] != "science" or not coverage["coverage_verified"]:
        raise ValueError("Verified science-quality archive coverage required")
    if sha256(observations_path) != coverage["archive_sha256"] or not coverage["source_url"].startswith(
        "https://firms.modaps.eosdis.nasa.gov/"
    ):
        raise ValueError("Historical FIRMS archive checksum or source invalid")
    observations = parse_firms(observations_path.read_text(encoding="utf-8"), source=coverage["product"])[
        "features"
    ]
    start, end = timestamp(coverage["start"]), timestamp(coverage["end"])
    region = shape(coverage["geometry"])
    rows = []
    for feature in features["records"]:
        t, aoi = timestamp(feature["prediction_at"]), shape(feature["geometry"])
        window_end = t + timedelta(days=7)
        if not start <= t < window_end <= end or not region.covers(aoi):
            raise ValueError("Target window or AOI outside verified archive coverage")
        observed = [
            o
            for o in observations
            if t < timestamp(o["properties"]["acquired_at"]) <= window_end
            and aoi.covers(Point(o["geometry"]["coordinates"]))
        ]
        rows.append(
            {
                **feature,
                "target": int(bool(observed)),
                "label_window_end": window_end.isoformat(),
                "label_source_quality": "science",
                "label_coverage_verified": True,
                "label_source": coverage["source_url"],
                "label_sha256": coverage["archive_sha256"],
                "target_observations": observed,
            }
        )
    validate_fire_records(rows)
    write_json(
        output,
        {
            "records": rows,
            "created_at": utcnow(),
            "coverage": coverage,
            "coverage_sha256": sha256(coverage_path),
            "features_sha256": sha256(features_path),
            "target_definition": "A science-quality FIRMS thermal observation within (T,T+7d] and the 1 km target cell; not ignition probability",
        },
    )


def validate_fire_records(records):
    from shapely.geometry import shape

    if not records or set(r["split"] for r in records) != {"train", "validation", "test"}:
        raise ValueError("Fire dataset requires three explicit partitions")
    groups, scenes = {}, {}
    for row in records:
        t = timestamp(row["prediction_at"])
        if timestamp(row["label_window_end"]) != t + timedelta(days=7):
            raise ValueError("Fire target must use exactly seven days after prediction timestamp")
        if row["label_source_quality"] != "science" or not row["label_coverage_verified"]:
            raise ValueError("Science-quality label coverage required, including negatives")
        if row["target"] not in [0, 1]:
            raise ValueError("Fire target must be binary")
        for field in WEATHER_FIELDS:
            entry = row["weather"][field]
            if not np.isfinite(float(entry["value"])) or not entry.get("source"):
                raise ValueError("Covariates must be finite and sourced")
            if timestamp(entry["observed_at"]) > t or timestamp(entry["available_at"]) > t:
                raise ValueError("Future or not-yet-published covariate detected")
        if timestamp(row["scene_acquired_at"]) > t or timestamp(row["scene_available_at"]) > t:
            raise ValueError("Satellite feature was unavailable at prediction time")
        if not row.get("label_source") or not row.get("label_sha256") or not row.get("scene_id"):
            raise ValueError("Fire labels and satellite features require provenance")
        for key in ["region_id", "event_group"]:
            previous = groups.setdefault((key, row[key]), row["split"])
            if previous != row["split"]:
                raise ValueError("Fire event or geography leaked across partitions")
        previous = scenes.setdefault(row["scene_id"], row["split"])
        if previous != row["split"]:
            raise ValueError("Satellite scene leaked across partitions")
        if row["grid_resolution_m"] != 30 or row["spatial_target_km"] != 1:
            raise ValueError("Fire experiment contract uses 30 m imagery over a 1 km target cell")
        if row["preprocessing"] != PREPROCESSING:
            raise ValueError("Fire preprocessing contract mismatch")
    # Regional event keys alone cannot prove disjointness. Check actual AOIs and purge target windows.
    for i, a in enumerate(records):
        for b in records[i + 1 :]:
            if a["split"] != b["split"] and shape(a["geometry"]).buffer(0.02).intersects(
                shape(b["geometry"])
            ):
                raise ValueError("Fire partitions are geographically adjacent or overlapping")
    latest_train = max(timestamp(r["label_window_end"]) for r in records if r["split"] == "train")
    earliest_val = min(timestamp(r["prediction_at"]) for r in records if r["split"] == "validation")
    latest_val = max(timestamp(r["label_window_end"]) for r in records if r["split"] == "validation")
    earliest_test = min(timestamp(r["prediction_at"]) for r in records if r["split"] == "test")
    if not latest_train < earliest_val or not latest_val < earliest_test:
        raise ValueError("Chronological holdout must purge overlapping seven-day target windows")
    for split in ["train", "validation", "test"]:
        if set(r["target"] for r in records if r["split"] == split) != {0, 1}:
            raise ValueError(f"Both classes required in {split}")


def train_fire(manifest_path, output, epochs=60, patience=10, seed=7729):
    """Train baselines and image/weather fusion on validated, genuinely sourced records."""
    source = Path(manifest_path)
    dataset = read_json(source)
    rows = dataset["records"]
    validate_fire_records(rows)
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a new experiment output directory")
    output.mkdir(parents=True)
    set_seed(seed)
    images, weather, labels = [], [], []
    for row in rows:
        path = (source.parent / row["image_path"]).resolve()
        if not path.is_relative_to(source.parent.resolve()) or sha256(path) != row["image_sha256"]:
            raise ValueError("Fire input path or checksum invalid")
        with np.load(path, allow_pickle=False) as image:
            bands, valid = image["reflectance"], image["valid"].astype(bool)
            if bands.shape != (6, 32, 32) or valid.shape != (32, 32) or valid.mean() < 0.8:
                raise ValueError("Fire images must be clear 6-band 32 x 32 tiles")
            if not np.isfinite(bands).all():
                raise ValueError("Fire imagery contains invalid values")
            images.append(network_input(bands, valid))
        weather.append([row["weather"][key]["value"] for key in WEATHER_FIELDS])
        labels.append(row["target"])
    images, weather, labels = np.stack(images), np.array(weather, np.float32), np.array(labels, np.float32)
    masks = {
        split: np.array([r["split"] == split for r in rows]) for split in ["train", "validation", "test"]
    }
    mean, std = weather[masks["train"]].mean(0), weather[masks["train"]].std(0).clip(1e-6)
    normalized = (weather - mean) / std
    # Only train-partition statistics and before-T image summaries enter the interpretable baselines.
    features = np.concatenate([images.mean((2, 3)), normalized], 1)
    baselines = {}
    for name, estimator in {
        "logistic": make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=500, class_weight="balanced", random_state=seed)
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=200, min_samples_leaf=5, class_weight="balanced", random_state=seed
        ),
    }.items():
        estimator.fit(features[masks["train"]], labels[masks["train"]])
        baselines[name] = {
            split: binary_metrics(labels[mask], estimator.predict_proba(features[mask])[:, 1])
            for split, mask in masks.items()
            if split != "train"
        }
    write_json(output / "baselines.json", baselines)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = FireFusion().to(device)
    initial = {key: value.clone() for key, value in model.state_dict().items()}
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.001)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=3, factor=0.5)
    train_mask = masks["train"]
    loader = DataLoader(
        TensorDataset(
            torch.from_numpy(images[train_mask]),
            torch.from_numpy(normalized[train_mask]),
            torch.from_numpy(labels[train_mask]),
        ),
        batch_size=16,
        shuffle=True,
    )
    val_mask = masks["validation"]
    vy = torch.from_numpy(labels[val_mask]).to(device)
    pos_weight = float((1 - labels[train_mask]).sum() / labels[train_mask].sum())
    criterion = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_weight, device=device))
    config = {
        "seed": seed,
        "preprocessing": PREPROCESSING,
        "manifest_sha256": sha256(source),
        "weather_mean": mean.tolist(),
        "weather_std": std.tolist(),
        "weather_fields": WEATHER_FIELDS,
        "target": "satellite-observed thermal anomaly in next seven days in a 1 km cell",
        "architecture": "FireFusion",
        "initialization": "random",
        "threshold": 0.5,
        "status": "experimental uncalibrated susceptibility score",
        "created_at": utcnow(),
    }
    write_json(output / "config.json", config)
    write_json(output / "dataset_manifest.json", dataset)
    history, best, stalled = [], float("inf"), 0
    for epoch in range(epochs):
        model.train()
        loss_sum = 0.0
        for im, we, y in loader:
            im, we, y = im.to(device), we.to(device), y.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(im, we), y)
            loss.backward()
            optimizer.step()
            loss_sum += float(loss.detach()) * len(y)
        model.eval()
        with torch.inference_mode():
            val_loss = float(
                criterion(
                    model(
                        torch.from_numpy(images[val_mask]).to(device),
                        torch.from_numpy(normalized[val_mask]).to(device),
                    ),
                    vy,
                )
            )
        scheduler.step(val_loss)
        history.append(
            {"epoch": epoch + 1, "train_loss": loss_sum / train_mask.sum(), "validation_loss": val_loss}
        )
        checkpoint = {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "config": config,
            "epoch": epoch + 1,
            "history": history,
            "rng": torch.get_rng_state(),
        }
        torch.save(checkpoint, output / "last.pt")
        if val_loss < best:
            best, stalled = val_loss, 0
            torch.save(checkpoint, output / "best.pt")
        else:
            stalled += 1
        write_json(output / "history.json", history)
        if stalled >= patience:
            break
    checkpoint = torch.load(output / "best.pt", weights_only=True, map_location=device)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    with torch.inference_mode():
        score = (
            model(torch.from_numpy(images).to(device), torch.from_numpy(normalized).to(device))
            .sigmoid()
            .cpu()
            .numpy()
        )
    metrics = {
        split: binary_metrics(labels[mask], score[mask]) for split, mask in masks.items() if split != "train"
    }
    metrics["parameter_l1_change"] = sum(
        float((value.cpu() - initial[key].cpu()).abs().sum()) for key, value in model.state_dict().items()
    )
    metrics["checkpoint_sha256"] = sha256(output / "best.pt")
    metrics["epochs_run"] = len(history)
    metrics["deployment_status"] = (
        "blocked pending independent validation and as-of data acquisition integration"
    )
    write_json(output / "metrics.json", metrics)
    plot_history(history, output / "training.png")
    return metrics
