from datetime import datetime
from pathlib import Path

import numpy as np
from shapely.geometry import box, mapping, shape

from ecosentinel.common import (
    ARTIFACTS,
    PREPROCESSING,
    DataUnavailable,
    read_json,
    sha256,
    utcnow,
    write_json,
)
from ecosentinel.raster import acquire_scene, indices, make_grid, read_aligned, rgb_png, write_raster
from ecosentinel.sources import HANSEN_VERSION, hansen_url


def check_splits(regions):
    ids = [r["id"] for r in regions]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate region identifiers")
    if set(r["split"] for r in regions) != {"train", "validation", "test"}:
        raise ValueError("Explicit train, validation and test geography required")
    for i, a in enumerate(regions):
        for b in regions[i + 1 :]:
            if a["split"] != b["split"] and box(*a["bbox"]).buffer(0.05).intersects(box(*b["bbox"])):
                raise ValueError("Geographic overlap or inadequate split buffer")


def verify_manifest(directory):
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    check_splits(manifest["regions"])
    if manifest["preprocessing"] != PREPROCESSING:
        raise DataUnavailable("Dataset preprocessing differs from installed specification")
    for region in manifest["regions"]:
        if sha256(directory / region["sample"]) != region["sample_sha256"]:
            raise DataUnavailable("Dataset checksum mismatch")
        with np.load(directory / region["sample"], allow_pickle=False) as sample:
            if sample["before"].shape != sample["after"].shape or sample["before"].shape[0] != 6:
                raise DataUnavailable("Invalid band order or shape")
            if sample["label"].shape != sample["before"].shape[1:]:
                raise DataUnavailable("Label dimensions do not match observations")
            if not np.isfinite(sample["before"]).all() or not np.isfinite(sample["after"]).all():
                raise DataUnavailable("Nonfinite training input")
            if not np.isin(sample["label"], [0, 1]).all() or not sample["valid"].any():
                raise DataUnavailable("Invalid labels or empty supervision")
    return manifest


def acquire_dataset(regions_path, directory=None):
    directory = Path(directory or ARTIFACTS / "dataset")
    regions = read_json(regions_path)
    check_splits(regions)
    directory.mkdir(parents=True, exist_ok=True)
    samples = []
    for region in regions:
        print(f"Acquiring {region['id']} ({region['split']})", flush=True)
        geometry = mapping(box(*region["bbox"]))
        grid = make_grid(geometry)
        region_dir = directory / region["id"]
        before, bvalid, bmeta = acquire_scene(geometry, *region["before"], grid, region_dir / "before")
        after, avalid, ameta = acquire_scene(geometry, *region["after"], grid, region_dir / "after")
        year = region["loss_year"]
        bdate = datetime.fromisoformat(bmeta["acquired_at"].replace("Z", "+00:00"))
        adate = datetime.fromisoformat(ameta["acquired_at"].replace("Z", "+00:00"))
        if not bdate.year < year < adate.year:
            raise DataUnavailable("Annual label year must fall fully between observed acquisitions")
        lon, lat = shape(geometry).centroid.coords[0]
        urls = {key: hansen_url(key, lon, lat) for key in ["lossyear", "treecover2000", "datamask"]}
        label_cache = region_dir / "reference.npz"
        if label_cache.exists():
            reference_meta = read_json(region_dir / "reference.json")
            if reference_meta["urls"] != urls or reference_meta["grid"] != grid.metadata():
                raise DataUnavailable("Reference cache provenance mismatch")
            if sha256(label_cache) != reference_meta["sha256"]:
                raise DataUnavailable("Reference checksum mismatch")
            with np.load(label_cache) as values:
                reference = {key: values[key] for key in urls}
        else:
            reference = {key: read_aligned(url, grid, True) for key, url in urls.items()}
            np.savez_compressed(label_cache, **reference)
            write_json(
                region_dir / "reference.json",
                {
                    "urls": urls,
                    "grid": grid.metadata(),
                    "retrieved_at": utcnow(),
                    "sha256": sha256(label_cache),
                },
            )
        loss, canopy, land = reference["lossyear"], reference["treecover2000"], reference["datamask"]
        # Supervision restricted to year-2000 canopy >=30%, land, and stable pixels or target-year loss.
        # Other losses in/near interval excluded: annual labels cannot locate them within acquisition dates.
        valid = bvalid & avalid & (land == 1) & (canopy >= 30) & ((loss == 0) | (loss == year - 2000))
        label = (loss == year - 2000).astype(np.float32)
        if valid.sum() < 1000:
            raise DataUnavailable("Insufficient supervised forest pixels")
        sample_file = region_dir / "sample.npz"
        np.savez_compressed(
            sample_file,
            before=before,
            after=after,
            label=label,
            valid=valid,
            observation_valid=bvalid & avalid,
            canopy=canopy,
        )
        write_raster(region_dir / "label.tif", label[None], grid, nodata=-9999)
        write_raster(region_dir / "supervision_valid.tif", valid.astype(np.uint8)[None], grid, nodata=0)
        rgb_png(region_dir / "before.png", before, bvalid)
        rgb_png(region_dir / "after.png", after, avalid)
        bi, ai = indices(before), indices(after)
        record = {
            **region,
            "geometry": geometry,
            "grid": grid.metadata(),
            "before_scene": bmeta,
            "after_scene": ameta,
            "sample": sample_file.relative_to(directory).as_posix(),
            "sample_sha256": sha256(sample_file),
            "label_source": HANSEN_VERSION,
            "label_urls": urls,
            "valid_pixels": int(valid.sum()),
            "positive_pixels": int(label[valid].sum()),
            "negative_pixels": int((1 - label[valid]).sum()),
            "pair_clear_fraction": float((bvalid & avalid).mean()),
            "indicator_means_on_supervised_pixels": {
                key: {"before": float(bi[key][valid].mean()), "after": float(ai[key][valid].mean())}
                for key in bi
            },
        }
        write_json(region_dir / "sample.json", record)
        samples.append(record)
        print(
            f"  {grid.width}x{grid.height}, valid={record['valid_pixels']}, loss={record['positive_pixels']}",
            flush=True,
        )
    manifest = {
        "created_at": utcnow(),
        "preprocessing": PREPROCESSING,
        "regions": samples,
        "label_definition": "Hansen annual gross tree-cover loss in target calendar year, within year-2000 canopy >=30%",
        "label_limitations": "Algorithmic Landsat reference, not independent field truth. Stable means no mapped loss, not verified ecological intactness.",
        "split_policy": "Whole nonoverlapping regions with >=0.05 degree buffer; Izmir also uses an earlier loss year",
    }
    write_json(directory / "manifest.json", manifest)
    verify_manifest(directory)
    return manifest
