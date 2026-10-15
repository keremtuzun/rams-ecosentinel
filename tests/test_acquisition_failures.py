import json

import numpy as np
import pytest
from shapely.geometry import box, mapping

from ecosentinel.common import DataUnavailable, read_json, sha256, write_json
from ecosentinel.raster import acquire_scene, make_grid, write_raster


def test_catalogue_network_failure_is_retryable_without_exposing_upstream_details(monkeypatch):
    import httpx
    import ecosentinel.sources as sources
    from ecosentinel.common import TransientDataUnavailable

    def failure(*args, **kwargs):
        raise httpx.ConnectError("private upstream diagnostic")

    monkeypatch.setattr(sources.httpx, "request", failure)
    monkeypatch.setattr(sources.time, "sleep", lambda *args: None)
    with pytest.raises(TransientDataUnavailable, match="three bounded attempts") as caught:
        sources.request_json("POST", sources.EARTH_SEARCH + "/search", json={})
    assert "private upstream" not in str(caught.value)


def test_raster_network_failure_is_distinct_from_real_quality_rejection(tmp_path, monkeypatch):
    import ecosentinel.raster as raster
    from ecosentinel.common import TransientDataUnavailable
    from tests.test_large_areas import fixture_scene

    geometry = mapping(box(28.23, 37.02, 28.25, 37.04))
    scene = fixture_scene("network-fixture", box(28, 37, 29, 38), "2020-06-30T09:00:00Z")
    monkeypatch.setattr(raster, "covering_observations", lambda *args: [[scene]])

    def failure(*args, **kwargs):
        raise raster.rasterio.errors.RasterioIOError("network fixture")

    monkeypatch.setattr(raster, "read_aligned", failure)
    with pytest.raises(TransientDataUnavailable, match="could not be read"):
        acquire_scene(geometry, "2020-06-01", "2020-06-30", make_grid(geometry), tmp_path)
    assert not (tmp_path / "scene.json").exists()


def test_missing_observation_fails_with_record(tmp_path, monkeypatch):
    import ecosentinel.raster as raster

    geometry = mapping(box(28.23, 37.02, 28.25, 37.04))
    monkeypatch.setattr(raster, "covering_observations", lambda *args: [])
    with pytest.raises(DataUnavailable, match="No acceptable"):
        acquire_scene(geometry, "2020-06-01", "2020-06-30", make_grid(geometry), tmp_path)
    assert read_json(tmp_path / "failed_candidates.json") == []
    assert not (tmp_path / "scene.json").exists()


def test_cached_scene_integrity_and_geometry_normalization(tmp_path):
    geometry = mapping(box(28.23, 37.02, 28.25, 37.04))
    grid = make_grid(geometry)
    source = np.ones((6, grid.height, grid.width), np.float32) * 0.2
    valid = np.ones((1, grid.height, grid.width), np.uint8)
    write_raster(tmp_path / "reflectance.tif", source, grid)
    write_raster(tmp_path / "valid.tif", valid, grid, nodata=0)
    write_json(
        tmp_path / "scene.json",
        {
            "grid": grid.metadata(),
            "query": {
                "start": "2020-06-01",
                "end": "2020-06-30",
                "geometry": json.loads(json.dumps(geometry)),
            },
            "checksums": {name: sha256(tmp_path / name) for name in ["reflectance.tif", "valid.tif"]},
        },
    )
    cached, mask, _ = acquire_scene(geometry, "2020-06-01", "2020-06-30", grid, tmp_path)
    np.testing.assert_array_equal(source, cached)
    assert mask.all()
    with (tmp_path / "reflectance.tif").open("ab") as file:
        file.write(b"corruption")
    with pytest.raises(DataUnavailable, match="checksum"):
        acquire_scene(geometry, "2020-06-01", "2020-06-30", grid, tmp_path)


def test_public_firms_feed_preserves_empty_observation_result(tmp_path, monkeypatch):
    import ecosentinel.sources as sources
    from ecosentinel.common import utcnow

    monkeypatch.setattr(sources, "ARTIFACTS", tmp_path)
    directory = tmp_path / "sources" / "firms"
    directory.mkdir(parents=True)
    feed = directory / "MODIS_C6_1_Global_24h.csv"
    # Explicit parser fixture, not a retrieved scientific observation.
    feed.write_text(
        "latitude,longitude,acq_date,acq_time,confidence,instrument\n37.1,28.3,2026-10-14,930,85,MODIS\n"
    )
    write_json(directory / "public_feed.json", {"sha256": sha256(feed), "retrieved_at": utcnow()})
    result = sources.fetch_public_modis([30, 38, 30.1, 38.1])
    assert result["features"] == []
    assert result["window"] == "rolling 24 hours"
    assert "does not establish" in result["note"]
    feed.write_text(feed.read_text() + "unexpected change")
    with pytest.raises(DataUnavailable, match="checksum"):
        sources.fetch_public_modis([30, 38, 30.1, 38.1])
