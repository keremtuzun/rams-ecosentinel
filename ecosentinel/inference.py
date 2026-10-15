from datetime import datetime, timezone
import os
from pathlib import Path

import numpy as np
from PIL import Image
from rasterio.features import shapes
from shapely.geometry import mapping, shape
from shapely.ops import transform as transform_geometry
from pyproj import Transformer
from scipy.ndimage import binary_opening, label as connected_labels

from ecosentinel.common import (
    ARTIFACTS,
    PREPROCESSING,
    DataUnavailable,
    read_json,
    sha256,
    utcnow,
    write_json,
)
from ecosentinel.raster import (
    Grid,
    acquire_scene,
    aoi_mask,
    indices,
    joint_valid_mask,
    make_grid,
    rgb_png,
    write_raster,
)


def load_model(model_dir=None):
    model_dir = Path(model_dir or ARTIFACTS / "models" / "habitat-7729")
    if os.environ.get("ECOSENTINEL_INFERENCE_ENGINE") == "onnx":
        from ecosentinel.onnx_runtime import load_onnx

        return load_onnx(model_dir)
    import torch
    from ecosentinel.models import SiameseUNet

    if not (model_dir / "metrics.json").exists():
        raise DataUnavailable("No evaluated task-trained habitat checkpoint is installed")
    metrics, config = read_json(model_dir / "metrics.json"), read_json(model_dir / "config.json")
    if not metrics["weights_changed"] or metrics["parameter_l1_change"] <= 0:
        raise DataUnavailable("Model lacks evidence of gradient training")
    if metrics["checkpoint_sha256"] != sha256(model_dir / "best.pt"):
        raise DataUnavailable("Model artifact checksum mismatch")
    if config["preprocessing"] != PREPROCESSING:
        raise DataUnavailable("Training/inference preprocessing mismatch")
    checkpoint = torch.load(model_dir / "best.pt", map_location="cpu", weights_only=True)
    if checkpoint["config"] != config:
        raise DataUnavailable("Checkpoint configuration mismatch")
    model = SiameseUNet(bands=3 if config["bands"] == "rgb" else 6, width=config["width"])
    model.load_state_dict(checkpoint["model"], strict=True)
    model.eval()
    return model, config, metrics


def tiled_scores(model, before, after, valid, bands="multispectral", temporal=True):
    if os.environ.get("ECOSENTINEL_INFERENCE_ENGINE") == "onnx":
        from ecosentinel.onnx_runtime import tiled_onnx_scores

        return tiled_onnx_scores(model, before, after, valid, bands=bands, temporal=temporal)
    import torch
    from ecosentinel.training import tiled_scores as torch_scores

    torch.set_num_threads(6)
    return torch_scores(model, before, after, valid, bands=bands, temporal=temporal)


def polygons(score, valid, grid, threshold=0.5, min_pixels=9):
    candidates = binary_opening((score >= threshold) & valid)
    labels, _ = connected_labels(candidates)
    counts = np.bincount(labels.ravel())
    candidates &= counts[labels] >= min_pixels
    projector = Transformer.from_crs(grid.crs, 4326, always_xy=True).transform
    features = []
    for geom, value in shapes(candidates.astype(np.uint8), mask=candidates, transform=grid.transform):
        if not value:
            continue
        polygon = shape(geom)
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(transform_geometry(projector, polygon)),
                "properties": {
                    "mapped_area_ha": round(polygon.area / 1e4, 3),
                    "meaning": "candidate forest-loss pattern requiring investigation",
                    "minimum_mapping_unit_m2": min_pixels * 900,
                    "score_threshold": threshold,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}, candidates


def infer_pair(before, after, valid, grid, before_meta, after_meta, output, model_dir=None, geometry=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    model, config, metrics = load_model(model_dir)
    if before.shape != after.shape or before.shape != (6, grid.height, grid.width):
        raise DataUnavailable("Inference inputs do not match the recorded grid and band contract")
    if before_meta["preprocessing"] != PREPROCESSING or after_meta["preprocessing"] != PREPROCESSING:
        raise DataUnavailable("Source preprocessing mismatch")
    if before_meta["grid"] != grid.metadata() or after_meta["grid"] != grid.metadata():
        raise DataUnavailable("Source georeferencing mismatch")
    if not np.isfinite(before).all() or not np.isfinite(after).all() or not valid.any():
        raise DataUnavailable("Inference contains invalid or empty observations")
    score = tiled_scores(model, before, after, valid, bands=config["bands"], temporal=config["temporal"])
    # Scope to baseline forest-like vegetation, because supervised labels only cover forest canopy.
    # NDVI is a domain screen, not a current land-cover assertion or degradation label.
    eligible = valid & (indices(before)["ndvi"] >= 0.45)
    uncertainty = {"status": "unavailable", "reason": "A compatible second-seed checkpoint is not installed"}
    secondary_path = ARTIFACTS / "models" / "habitat-7730"
    if (
        (secondary_path / "metrics.json").exists()
        and config["bands"] == "multispectral"
        and config["temporal"]
    ):
        secondary, secondary_config, secondary_metrics = load_model(secondary_path)
        if secondary_config["dataset_sha256"] != config["dataset_sha256"]:
            raise DataUnavailable("Uncertainty models were trained on incompatible datasets")
        secondary_score = tiled_scores(secondary, before, after, valid)
        disagreement = np.abs(score - secondary_score)
        write_raster(
            output / "uncertainty.tif",
            np.where(eligible, disagreement, -9999).astype(np.float32)[None],
            grid,
            descriptions=["absolute_two_seed_score_disagreement"],
        )
        uncertainty = {
            "status": "available",
            "method": "Absolute score disagreement between two trained random seeds",
            "mean_disagreement_on_eligible_pixels": float(disagreement[eligible].mean())
            if eligible.any()
            else None,
            "p95_disagreement_on_eligible_pixels": float(np.percentile(disagreement[eligible], 95))
            if eligible.any()
            else None,
            "comparison_checkpoint_sha256": secondary_metrics["checkpoint_sha256"],
            "meaning": "Model instability indicator, not a calibrated error bound or ecological probability",
        }
    features, mask = polygons(score, eligible, grid, config["threshold"])
    score_out = np.where(eligible, score, -9999).astype(np.float32)
    write_raster(
        output / "score.tif", score_out[None], grid, descriptions=["uncalibrated_loss_reference_score"]
    )
    write_raster(output / "mask.tif", np.where(eligible, mask, 255).astype(np.uint8)[None], grid, nodata=255)
    write_json(output / "change.geojson", features)
    rgba = np.zeros((grid.height, grid.width, 4), np.uint8)
    rgba[mask] = [205, 104, 42, 200]
    Image.fromarray(rgba).save(output / "overlay.png")
    rgb_png(output / "before.png", before, valid)
    rgb_png(output / "after.png", after, valid)
    with Image.open(output / "after.png") as source_image:
        base = source_image.convert("RGBA")
        Image.alpha_composite(base, Image.fromarray(rgba)).save(output / "map.png")
    bi, ai = indices(before), indices(after)
    write_raster(
        output / "indices.tif",
        np.stack(
            [
                np.where(valid, arr, -9999)
                for arr in [
                    bi["ndvi"],
                    ai["ndvi"],
                    ai["ndvi"] - bi["ndvi"],
                    bi["ndmi"],
                    ai["ndmi"],
                    bi["nbr"],
                    ai["nbr"],
                    ai["nbr"] - bi["nbr"],
                ]
            ]
        ).astype(np.float32),
        grid,
        descriptions=[
            "before_ndvi",
            "after_ndvi",
            "delta_ndvi",
            "before_ndmi",
            "after_ndmi",
            "before_nbr",
            "after_nbr",
            "delta_nbr",
        ],
    )
    acquired = datetime.fromisoformat(after_meta["acquired_at"].replace("Z", "+00:00"))
    project = Transformer.from_crs(grid.crs, 4326, always_xy=True).transform
    corners = [
        list(project(*(grid.transform * p)))
        for p in [(0, 0), (grid.width, 0), (grid.width, grid.height), (0, grid.height)]
    ]
    report = {
        "generated_at": utcnow(),
        "organization": "FRC Team 7729 RAMs · FIRST BIOCORE 2027",
        "module": "habitat",
        "status": "experimental",
        "grid": grid.metadata(),
        "bounds": grid.wgs84_bounds(),
        "geometry": geometry,
        "corners": corners,
        "source_observations": [before_meta, after_meta],
        "latest_observation_age_days": (datetime.now(timezone.utc) - acquired).days,
        "model_version": metrics["checkpoint_sha256"][:16],
        "model_checkpoint_sha256": metrics["checkpoint_sha256"],
        "inference_runtime": os.environ.get("ECOSENTINEL_INFERENCE_ENGINE", "pytorch"),
        "clear_fraction": float(valid[aoi_mask(geometry, grid)].mean()) if geometry else float(valid.mean()),
        "clear_fraction_denominator": (
            "Requested AOI pixels, including water; excludes grid padding outside the boundary"
            if geometry
            else "Full analysis grid"
        ),
        "eligible_pixels": int(eligible.sum()),
        "candidate_pixels": int(mask.sum()),
        "mapped_candidate_area_ha": float(mask.sum() * 900 / 1e4),
        "candidate_polygons": len(features["features"]),
        "uncertainty": uncertainty,
        "indices": {
            key: {
                "before_mean": float(bi[key][valid].mean()),
                "after_mean": float(ai[key][valid].mean()),
                "delta_mean": float((ai[key] - bi[key])[valid].mean()),
            }
            for key in bi
        },
        "interpretation": "The trained model identified candidate patterns resembling annual tree-cover loss. These are hypotheses for inspection, not confirmed habitat degradation.",
        "limitations": [
            "Research-only model; no independent field validation or calibrated ecological probability.",
            "Annual Hansen reference is algorithmic and does not establish cause or permanent deforestation.",
            "30 m common grid; seasonal matching and SCL masking do not eliminate all atmospheric, phenological or registration error.",
            "Pixel totals are mapped candidate extent, not an unbiased forest-loss area estimate.",
            "Model trained on a small Turkish cohort; vegetation screen NDVI >=0.45 is approximate.",
            "Training uses two-year June pairs. Different seasons and comparison durations, including one-year September pairs, are outside the tested domain.",
            "Tile boundaries, residual clouds, agriculture and recovery can cause errors.",
            "Large areas can combine multiple real scenes spanning up to five calendar days; source-index rasters identify the acquisition used at each pixel.",
        ],
        "checksums": {
            name: sha256(output / name) for name in ["score.tif", "mask.tif", "indices.tif", "change.geojson"]
        },
    }
    if uncertainty["status"] == "available":
        report["checksums"]["uncertainty.tif"] = sha256(output / "uncertainty.tif")
    write_json(output / "report.json", report)
    return report


def analyze(request, output, model_dir=None):
    if request.module != "habitat":
        raise DataUnavailable(
            "Wildfire forecasting is blocked: authenticated historical labels and as-of covariates are not installed"
        )
    load_model(model_dir)  # Fail before satellite download if no evaluated checkpoint.
    grid = make_grid(request.geometry)
    before, bvalid, bmeta = acquire_scene(
        request.geometry, request.before_start, request.before_end, grid, Path(output) / "source_before"
    )
    after, avalid, ameta = acquire_scene(
        request.geometry, request.after_start, request.after_end, grid, Path(output) / "source_after"
    )
    valid = joint_valid_mask(bvalid, avalid, request.geometry, grid)
    return infer_pair(before, after, valid, grid, bmeta, ameta, output, model_dir, request.geometry)


def infer_offline(region_dir, output, model_dir=None):
    region_dir = Path(region_dir)
    meta = read_json(region_dir / "sample.json")
    if sha256(region_dir / "sample.npz") != meta["sample_sha256"]:
        raise DataUnavailable("Offline sample checksum mismatch")
    with np.load(region_dir / "sample.npz") as sample:
        return infer_pair(
            sample["before"],
            sample["after"],
            sample["observation_valid"],
            Grid.from_metadata(meta["grid"]),
            meta["before_scene"],
            meta["after_scene"],
            output,
            model_dir,
            meta["geometry"],
        )
