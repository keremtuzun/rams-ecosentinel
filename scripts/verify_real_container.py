"""Validate one genuine Docker analysis through the web proxy; never targets production."""

import csv
from datetime import datetime
import io
import json
import os
from pathlib import Path
import shutil
import time
from urllib.parse import urlparse

import httpx
import numpy as np
from PIL import Image
from pyproj import Transformer
import rasterio
from shapely.geometry import shape

from ecosentinel.common import ARTIFACTS, PREPROCESSING, read_json, sha256, write_json
from ecosentinel.onnx_runtime import load_onnx
from ecosentinel.raster import Grid, aoi_mask, indices


def main():
    origin = os.environ.get("ECOSENTINEL_TEST_WEB_URL", "http://web:3000")
    if urlparse(origin).hostname not in {"web", "localhost", "127.0.0.1"}:
        raise ValueError("Real-data verifier only supports the isolated Docker stack")
    job_id = os.environ["ECOSENTINEL_REAL_JOB_ID"]
    output = ARTIFACTS / "real-verification"
    output.mkdir(exist_ok=False)
    model_path = ARTIFACTS / "models/habitat-7729"
    _, config, metrics = load_onnx(model_path)
    started = time.monotonic()
    with httpx.Client(base_url=origin, timeout=120) as client:
        while time.monotonic() - started < 930:
            response = client.get(f"/api/jobs/{job_id}")
            response.raise_for_status()
            job = response.json()
            if job["status"] in {"succeeded", "failed"}:
                break
            time.sleep(3)
        assert job["status"] == "succeeded", job
        assert job["attempts"] == 1 and job["result_owner"]
        directory = ARTIFACTS / "jobs" / job_id / job["result_owner"]
        report = job["report"]
        assert report["inference_runtime"] == "onnx"
        assert report["model_checkpoint_sha256"] == metrics["checkpoint_sha256"]
        assert datetime.fromisoformat(report["generated_at"]) >= datetime.fromisoformat(job["created_at"])
        assert report["geometry"] == job["request"]["geometry"]
        exports = {}
        for extension in ["pdf", "csv", "json", "geojson"]:
            response = client.get(f"/api/jobs/{job_id}/export/{extension}")
            response.raise_for_status()
            assert "attachment" in response.headers["content-disposition"]
            target = output / f"assessment.{extension}"
            target.write_bytes(response.content)
            exports[target.name] = {"bytes": target.stat().st_size, "sha256": sha256(target)}
        assert read_json(output / "assessment.json") == report
        assert read_json(output / "assessment.geojson") == read_json(directory / "change.geojson")
        for name in [
            "score.tif",
            "mask.tif",
            "indices.tif",
            "before.png",
            "after.png",
            "overlay.png",
            "map.png",
        ]:
            response = client.get(f"/api/jobs/{job_id}/files/{name}")
            response.raise_for_status()
            target = output / name
            target.write_bytes(response.content)
            assert sha256(target) == sha256(directory / name)
            if name in report["checksums"]:
                assert sha256(target) == report["checksums"][name]
            exports[name] = {"bytes": target.stat().st_size, "sha256": sha256(target)}
        grid = Grid.from_metadata(report["grid"])
        area = aoi_mask(report["geometry"], grid)
        assert area.sum() < area.size * 0.65, "Use a concave AOI that exercises padding"
        sources = []
        data = []
        valid_masks = []
        for phase, source in zip(["before", "after"], report["source_observations"]):
            source_dir = directory / f"source_{phase}"
            assert source == read_json(source_dir / "scene.json")
            assert source["preprocessing"] == PREPROCESSING and source["clear_fraction"] >= 0.8
            assert datetime.fromisoformat(source["retrieved_at"]) >= datetime.fromisoformat(job["created_at"])
            for name, checksum in source["checksums"].items():
                assert sha256(source_dir / name) == checksum
            with rasterio.open(source_dir / "reflectance.tif") as raster:
                assert raster.count == 6 and raster.crs.to_string() == grid.crs
                data.append(raster.read())
            with rasterio.open(source_dir / "valid.tif") as raster:
                valid = raster.read(1).astype(bool)
                assert not valid[~area].any()
                valid_masks.append(valid)
            with rasterio.open(source_dir / "source_index.tif") as raster:
                source_index = raster.read(1)
                assert np.array_equal(source_index > 0, valid)
            stac = read_json(source_dir / "stac.json")
            stac = stac if isinstance(stac, list) else [stac]
            for index, observation in enumerate(source["observations"], 1):
                assert observation["scene_id"] in {item["id"] for item in stac}
                assert int((source_index == index).sum()) == observation["used_pixels"]
                for band in observation["scaling"].values():
                    assert urlparse(band["href"]).hostname == "sentinel-cogs.s3.us-west-2.amazonaws.com"
            sources.append(
                {"phase": phase, "scene_id": source["scene_id"], "retrieved_at": source["retrieved_at"]}
            )
            shutil.copytree(source_dir, output / f"source_{phase}")
        valid = valid_masks[0] & valid_masks[1] & area
        fraction = float(valid[area].mean())
        assert fraction >= 0.65 and abs(fraction - report["clear_fraction"]) < 1e-12
        expected_indices = [indices(values) for values in data]
        with rasterio.open(output / "indices.tif") as raster:
            assert raster.count == 8 and raster.transform == grid.transform
            bands = raster.read(masked=True)
            assert np.array_equal(~np.ma.getmaskarray(bands[0]), valid)
            for name, b, a in [("ndvi", 0, 1), ("ndmi", 3, 4), ("nbr", 5, 6)]:
                for i, band in enumerate([b, a]):
                    assert np.allclose(bands[band][valid], expected_indices[i][name][valid], atol=1e-7)
                values = [bands[b][valid].mean(), bands[a][valid].mean(), (bands[a] - bands[b])[valid].mean()]
                for label, value in zip(["before_mean", "after_mean", "delta_mean"], values):
                    assert abs(float(value) - report["indices"][name][label]) < 1e-6
        eligible = valid & (expected_indices[0]["ndvi"] >= 0.45)
        with rasterio.open(output / "score.tif") as raster:
            assert raster.transform == grid.transform and raster.crs.to_string() == grid.crs
            scores = raster.read(1, masked=True)
            assert np.array_equal(~np.ma.getmaskarray(scores), eligible)
            assert eligible.sum() == report["eligible_pixels"] and eligible.any()
            assert np.all((scores[eligible] >= 0) & (scores[eligible] <= 1))
        with rasterio.open(output / "mask.tif") as raster:
            mask = raster.read(1)
            assert np.all(mask[~eligible] == 255)
            assert int((mask == 1).sum()) == report["candidate_pixels"]
        assert report["mapped_candidate_area_ha"] == report["candidate_pixels"] * 900 / 1e4
        geojson = read_json(output / "assessment.geojson")
        assert len(geojson["features"]) == report["candidate_polygons"]
        for feature in geojson["features"]:
            assert shape(feature["geometry"]).is_valid
            assert feature["properties"]["score_threshold"] == config["threshold"]
        rows = list(csv.reader(io.StringIO((output / "assessment.csv").read_text())))
        for row in rows[1:4]:
            assert [float(v) for v in row[1:]] == list(report["indices"][row[0]].values())
        assert ["model_version", report["model_version"]] in rows
        transform = Transformer.from_crs(grid.crs, 4326, always_xy=True)
        inspected = []
        for selection, expected in [(eligible, "score"), (~area, None)]:
            points = np.argwhere(selection)
            row, col = points[len(points) // 2]
            lon, lat = transform.transform(*(grid.transform * (float(col) + 0.5, float(row) + 0.5)))
            response = client.get(f"/api/jobs/{job_id}/inspect", params={"longitude": lon, "latitude": lat})
            response.raise_for_status()
            actual = response.json()["score"]
            assert actual is None if expected is None else abs(actual - float(scores[row, col])) < 1e-7
            inspected.append(actual)
        assert client.get(f"/api/jobs/{job_id}/inspect?longitude=0&latitude=0").status_code == 422
        assert report["uncertainty"]["status"] == "unavailable"
        assert client.get(f"/api/jobs/{job_id}/files/uncertainty.tif").status_code == 404
        for name in ["before.png", "after.png", "map.png", "overlay.png"]:
            with Image.open(output / name) as image:
                assert image.size == (grid.width, grid.height)
                image.verify()
    from pypdf import PdfReader

    reader = PdfReader(output / "assessment.pdf")
    assert len(reader.pages) == 2
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert report["model_version"] in text and "Limitations" in text
    assert f"{report['mapped_candidate_area_ha']:.2f}" in text
    proof = {
        "status": "PASS",
        "job_id": job_id,
        "compute_attempts": job["attempts"],
        "runtime": report["inference_runtime"],
        "trained_checkpoint_sha256": report["model_checkpoint_sha256"],
        "onnx_sha256": sha256(model_path / "model.onnx"),
        "grid_pixels": int(area.size),
        "aoi_pixels": int(area.sum()),
        "clear_fraction": fraction,
        "rectangle_clear_fraction": float(valid.mean()),
        "eligible_pixels": report["eligible_pixels"],
        "candidate_pixels": report["candidate_pixels"],
        "sources": sources,
        "exports": exports,
        "inspection_scores": inspected,
        "pdf_pages": len(reader.pages),
        "uncertainty": "UNAVAILABLE: compatible second seed absent",
        "production_analysis_requests": 0,
    }
    write_json(output / "verification.json", proof)
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
